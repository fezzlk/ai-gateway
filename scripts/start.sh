#!/bin/sh
# Container ENTRYPOINT: join the tailnet in userspace-networking mode (no
# /dev/net/tun available on Cloud Run), then start the app.
set -e

/usr/local/bin/tailscaled --tun=userspace-networking --state=mem: --socks5-server=localhost:1055 &

/usr/local/bin/tailscale up \
  --auth-key="${TAILSCALE_AUTHKEY}" \
  --hostname="${TAILSCALE_HOSTNAME:-ai-gateway-cloudrun}" \
  --ssh=false

# Secret Manager volume mounts are read-only (~0444); ssh refuses keys that
# aren't 0600, so copy to a private tmpfs path before use. `install`/`cp`
# stat the source before and after copying and abort with "replaced while
# being copied" against Cloud Run's secret volume mount (its FUSE layer
# doesn't present a stable inode across the copy) — `cat` just streams
# bytes and doesn't hit that check.
if [ -f "${MAC_SSH_KEY_SECRET_PATH:-/secrets/mac_ssh_key}" ]; then
  cat "${MAC_SSH_KEY_SECRET_PATH:-/secrets/mac_ssh_key}" > /tmp/mac_ssh_key
  chmod 600 /tmp/mac_ssh_key
fi

mkdir -p /root/.ssh
if [ -n "${MAC_SSH_KNOWN_HOST_LINE}" ]; then
  echo "${MAC_SSH_KNOWN_HOST_LINE}" > /root/.ssh/known_hosts
fi

export MAC_SSH_KEY_PATH=/tmp/mac_ssh_key

exec gunicorn src.server:app \
  --bind "0.0.0.0:${PORT:-8080}" \
  --worker-class=gthread \
  --workers=2 \
  --threads=4 \
  --timeout=0 \
  --log-file=-
