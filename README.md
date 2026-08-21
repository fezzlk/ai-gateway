# ai-gateway

Unified mobile-friendly gateway for routing work between Claude and Codex
across execution environments (Web/Routines, Mac via Tailscale, GCP VM
fallback).

## Web chat and conversation storage

The root page is a responsive chat client with server-side conversation
history, Markdown/code rendering, code copy, run cancellation, retry, title
editing, repository selection, and conversation switching/deletion. Claude's
session ID is stored with each conversation, so switching back to a thread
continues the corresponding Claude session.

Conversation data is stored in the project's Firestore Standard default
database. Cloud Run's local filesystem is intentionally not used because it
is ephemeral. One-time setup (Tokyo region) is:

```bash
gcloud services enable firestore.googleapis.com --project="$PROJECT_ID"
gcloud firestore databases create \
  --database='(default)' \
  --location=asia-northeast1 \
  --type=firestore-native \
  --project="$PROJECT_ID"
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:ai-gateway-run@$PROJECT_ID.iam.gserviceaccount.com" \
  --role=roles/datastore.user
```

Do not run the database creation command if a `(default)` database already
exists. Check first with:

```bash
gcloud firestore databases describe --database='(default)' --project="$PROJECT_ID"
```

Firestore's Standard free quota includes 1 GiB stored data, 50,000 document
reads/day, and 20,000 writes/day. A personal gateway should normally remain
within that quota, but billing remains usage-based beyond it. The shared
gateway bearer token protects all conversation endpoints; this is a single-
user data model, not per-user tenancy.

### Web authentication modes

Authentication and execution backends are controlled by environment
variables. `AUTH_MODE=shared_token` preserves the original bearer-token flow.
`AUTH_MODE=oauth` enables Google and/or LINE Login; a provider is shown only
when both its ID and secret are configured. OAuth conversations are stored
under a one-way hash of the provider's stable subject ID, so users cannot read
or modify each other's conversations.

| Variable | Values / purpose |
| --- | --- |
| `AUTH_MODE` | `shared_token` or `oauth` |
| `ACCESS_MODE` | `private` (allowlist) or `authenticated` (any signed-in account) |
| `AUTHORIZED_GOOGLE_EMAILS` | Comma-separated verified emails for private mode |
| `AUTHORIZED_LINE_USER_IDS` | Comma-separated LINE Login user IDs for private mode |
| `EXECUTION_ENABLED` | Global execution kill switch |
| `CLAUDE_ENABLED` | Enable the currently implemented Claude executor |
| `CODEX_ENABLED` | Advertise Codex availability (executor not yet implemented) |
| `GCP_VM_ENABLED` | Advertise GCP VM availability |

OAuth secrets belong in Secret Manager (`SESSION_SECRET`,
`GOOGLE_OAUTH_CLIENT_SECRET`, and `LINE_LOGIN_CHANNEL_SECRET`). IDs and access
policy are Cloud Build trigger substitutions. Configure these callback URLs:

- Google: `https://<service-host>/auth/callback/google`
- LINE Login: `https://<service-host>/auth/callback/line`

Google uses the OpenID Connect authorization-code flow with a verified email.
LINE Login uses OpenID Connect with server-side ID-token verification. Both
flows validate `state` and `nonce`; the resulting application session is kept
in a Secure, HttpOnly, SameSite=Lax signed cookie for 30 days.

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
- `VM履歴` / `VMログ` / `vm history`: fallback VMの作成・削除の成功・失敗を直近10件表示

リッチメニューを設定すると、上記のうち`board`、`判断待ち`、`kobito状況`を常時ボタンから開ける。画像生成と設定は次の通り。

```bash
rsvg-convert -w 2500 -h 843 assets/line-rich-menu.svg -o assets/line-rich-menu.png
LINE_CHANNEL_ACCESS_TOKEN=... python3 scripts/setup_line_rich_menu.py assets/line-rich-menu.png
```

問い合わせはLINE署名検証と`LINE_AUTHORIZED_USER_ID`照合を通過したユーザーだけが実行できる。タスク・優先度・正式な完了状態の正本はLinearであり、返信内容はkobitoが更新するリアルタイム状態のスナップショットとして扱う。

### kobito実行監視

`/api/run`がkobitoの固定プロンプトまたは`source: "kobito"`を受け取ると、Mac上のhuman-agent-boardへ実行開始、60秒heartbeat、正常・異常終了を自動記録する。gateway/SSHエラーでは同一障害を重複させず、ユーザー対応依頼をBoardとLINEへ送る。正常終了時にその障害項目を自動解消する。

`POST /api/kobito-health`は、heartbeatが15分以上停止した実行、4時間以上起動が確認できない状態、連続失敗を検査する。別のCloud Scheduler等から15分間隔で呼び出すことで、通常のkobitoトリガー自体が止まった場合も検知できる。認証は他の`/api/*`と同じBearer tokenを使う。

監視ジョブを追加する場合も既存の`ai-gateway`・単一リージョンを利用し、Cloud Runのmin instancesやCPU設定は変更しない。

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

両スクリプトの実行結果は、隣接する`human-agent-board`リポジトリの`board/vm/events.jsonl`へ自動記録される。LINE BotのBoard画面にある「VM履歴」ボタン、または`VM履歴`メッセージから確認できる。`BOARD_CLI`を指定すれば別の`board.py`を利用できる。記録処理の失敗はVM操作自体の終了コードを変更しない。GCP Consoleや直接実行した`gcloud`は記録対象外。

### Why no credentials in the startup-script

Instance metadata (including startup-script contents) can be read in
plaintext by anyone with `describe` access to the instance
(`gcloud compute instances describe`). Auth tokens and API keys are
therefore never embedded there — they're entered interactively after SSH,
each session.
