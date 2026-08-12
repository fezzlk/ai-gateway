# ai-gateway

Unified mobile-friendly gateway for routing work between Claude and Codex
across execution environments (Web/Routines, Mac via Tailscale, GCP VM
fallback).

## Execution environment priority

1. Claude Web/Routines or Codex Cloud (no PC required, MCP limited to
   connectors)
2. Mac over Tailscale (full local MCP setup, requires the Mac to be
   reachable)
3. GCP VM fallback (used only when the Mac isn't reachable)

## GCP VM fallback: ephemeral by design

The fallback environment is **not** a persistent, always-on VM. Keeping an
idle instance around costs money even when stopped (the boot disk alone is
billed 24/7), so instead each fallback session:

1. Creates a brand-new VM (`infra/spin-up-fallback-vm.sh`)
2. Installs tools and clones only the repo needed for that task
   (`infra/startup-tools.sh`, run automatically as the instance's
   startup-script)
3. Gets used over SSH (via GCP IAP, no external IP)
4. Gets deleted (`infra/teardown-fallback-vm.sh`) as soon as the task is done

No custom image or standing disk is kept between sessions. This trades a
few minutes of tool-install time per session for effectively zero cost
when the fallback isn't in use.

### One-time project setup

Requires a GCP project with billing enabled, the Compute Engine API
enabled, and a firewall rule allowing SSH only from the IAP range
(`35.235.240.0/20`, tcp:22) — no other inbound access, no external IP on
the instances.

### Usage

```bash
export PROJECT_ID=your-project-id
export TASK_REPO_URL=https://github.com/you/your-repo.git  # optional

./infra/spin-up-fallback-vm.sh
# ... wait a few minutes for startup-script to finish, then:
gcloud compute ssh <instance-name> --project=$PROJECT_ID --zone=asia-northeast1-a --tunnel-through-iap

# On first login, authenticate interactively — credentials are never baked
# into the image or instance metadata:
gh auth login
claude  # follow login prompt
codex   # follow login prompt

# When done:
INSTANCE_NAME=<instance-name> ./infra/teardown-fallback-vm.sh
```

### Why no credentials in the startup-script

Instance metadata (including startup-script contents) can be read in
plaintext by anyone with `describe` access to the instance
(`gcloud compute instances describe`). Auth tokens and API keys are
therefore never embedded there — they're entered interactively after SSH,
each session.
