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

## LINEでBoardを確認・管理する

human-agent-boardとkobitoを設定済みの環境では、認可済みユーザーがLINE BotからBoard全体をFlex Messageで確認・管理できる。

- `board` / `ボード`: 判断待ち、依頼・通知、kobito進行状況の件数と概要
- `判断待ち` / `decisions`: 判断材料リンクを開き、その場で承認・却下
- `依頼` / `requests`: 依頼・通知を確認し、処理済みに変更
- `kobito状況` / `kobito status`: 進行中と直近の完了・失敗、次の作業、関連リンク

リッチメニューを設定すると、上記のうち`board`、`判断待ち`、`kobito状況`を常時ボタンから開ける。画像生成と設定は次の通り。

```bash
rsvg-convert -w 2500 -h 843 assets/line-rich-menu.svg -o assets/line-rich-menu.png
LINE_CHANNEL_ACCESS_TOKEN=... python3 scripts/setup_line_rich_menu.py assets/line-rich-menu.png
```

問い合わせはLINE署名検証と`LINE_AUTHORIZED_USER_ID`照合を通過したユーザーだけが実行できる。タスク・優先度・正式な完了状態の正本はLinearであり、返信内容はkobitoが更新するリアルタイム状態のスナップショットとして扱う。

## GCP VM fallback: ephemeral by design

The fallback environment is **not** a persistent, always-on VM. Keeping an
idle instance around costs money even when stopped (the boot disk alone is
billed 24/7), so instead each fallback session:

1. Creates a brand-new VM (`infra/spin-up-fallback-vm.sh`)
2. Installs tools and clones only the repo needed for that task
   (`infra/startup-tools.sh`, run automatically as the instance's
   startup-script)
3. Gets used over SSH (via GCP IAP; the instance does have a normal
   ephemeral external IP so the startup-script can reach the public
   internet for tool installation — see note below)
4. Gets deleted (`infra/teardown-fallback-vm.sh`) as soon as the task is done

No custom image or standing disk is kept between sessions. This trades a
few minutes of tool-install time per session for effectively zero cost
when the fallback isn't in use.

### One-time project setup

Requires a GCP project with billing enabled, the Compute Engine API
enabled, and a firewall rule allowing SSH only from the IAP range
(`35.235.240.0/20`, tcp:22) — no other inbound access, regardless of the
instance having a public IP.

**Important — delete the auto-created default firewall rules.** Every new
GCP project's `default` VPC comes with `default-allow-ssh` (tcp:22 from
`0.0.0.0/0`, i.e. the whole internet) and `default-allow-rdp` already
present. These are *additional* ALLOW rules, not overridden by a
narrower one — so leaving them in place means the instance is reachable
from the entire internet on port 22 regardless of the IAP-only rule
above (found by actually checking `gcloud compute firewall-rules list`
after standing this up — it looked IAP-only until this was checked).
Delete both once per project:
```bash
gcloud compute firewall-rules delete default-allow-ssh default-allow-rdp --project=$PROJECT_ID
```

**Why the instance has an external IP:** with no external IP and no NAT
gateway, the instance has zero route to the public internet, so the
startup-script's apt/GitHub/npm installs fail outright (confirmed by
testing). Adding a Cloud NAT gateway would fix that, but Cloud NAT bills
a flat ~$32/month for the gateway itself regardless of usage — the
opposite of what an ephemeral, pay-only-when-used VM is for. A normal
*ephemeral* (not reserved/static) external IP is free while the instance
is running, so that's what's used instead. This doesn't reopen the
instance to inbound traffic: the firewall rule still only allows SSH from
the IAP range, on any IP the instance happens to have.

### Usage

```bash
export PROJECT_ID=your-project-id

./infra/spin-up-fallback-vm.sh
# ... wait a few minutes for startup-script to finish, then:
gcloud compute ssh <instance-name> --project=$PROJECT_ID --zone=asia-northeast1-a --tunnel-through-iap

# On first login, authenticate and clone what you need interactively —
# credentials are never baked into the image or instance metadata, and
# repos aren't cloned automatically since they're private:
gh auth login
git clone https://github.com/you/your-repo.git /opt/work/your-repo
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
