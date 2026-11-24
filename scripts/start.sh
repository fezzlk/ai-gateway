#!/bin/sh
# Container ENTRYPOINT: join the tailnet in userspace-networking mode (no
# /dev/net/tun available on Cloud Run), then start the app.
set -e

# Join the tailnet with TAILSCALE_AUTHKEY, which may hold either:
#   - a regular auth key ("tskey-auth-..."), which expires (90 days at most), or
#   - an OAuth client secret ("tskey-client-..."), which Tailscale turns into a
#     short-lived auth key on every start, so there is nothing to renew.
# An OAuth client secret needs the tags the client was created with
# (TAILSCALE_TAGS, default "tag:ai-gateway") and is registered as an
# ephemeral, pre-authorized node. See README ("Tailscale authentication").
tailscale_up() {
  ts_bin="${TAILSCALE_BIN:-/usr/local/bin/tailscale}"
  case "${TAILSCALE_AUTHKEY}" in
    tskey-client-*)
      "${ts_bin}" up \
        --auth-key="${TAILSCALE_AUTHKEY}?ephemeral=true&preauthorized=true" \
        --advertise-tags="${TAILSCALE_TAGS:-tag:ai-gateway}" \
        --hostname="${TAILSCALE_HOSTNAME:-ai-gateway-cloudrun}" \
        --ssh=false
      ;;
    *)
      "${ts_bin}" up \
        --auth-key="${TAILSCALE_AUTHKEY}" \
        --hostname="${TAILSCALE_HOSTNAME:-ai-gateway-cloudrun}" \
        --ssh=false
      ;;
  esac
}

# Tests source this file to exercise tailscale_up without starting anything.
if [ -n "${START_SH_FUNCTIONS_ONLY:-}" ]; then
  return 0
fi

/usr/local/bin/tailscaled --tun=userspace-networking --state=mem: --socks5-server=localhost:1055 &

tailscale_up

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
