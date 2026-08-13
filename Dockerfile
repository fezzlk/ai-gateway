FROM docker.io/tailscale/tailscale:stable AS tailscale

FROM python:3.11-slim
WORKDIR /app

# openssh-client provides the `ssh` binary; tailscale binaries are copied
# from the official image (Cloud Run has no /dev/net/tun, so tailscaled
# must run in userspace-networking mode — see scripts/start.sh).
RUN apt-get update \
    && apt-get install -y --no-install-recommends openssh-client \
    && rm -rf /var/lib/apt/lists/*
COPY --from=tailscale /usr/local/bin/tailscaled /usr/local/bin/tailscaled
COPY --from=tailscale /usr/local/bin/tailscale /usr/local/bin/tailscale

COPY requirements.txt /app/requirements.txt
RUN python -m pip install --upgrade pip \
    && pip install --no-cache-dir -r /app/requirements.txt

COPY src /app/src
COPY scripts/start.sh /app/scripts/start.sh
RUN chmod +x /app/scripts/start.sh

EXPOSE 8080
CMD ["/app/scripts/start.sh"]
