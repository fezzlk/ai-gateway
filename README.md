# ai-gateway

Headless execution gateway that lets kobito and other automation clients run
Claude on the Mac over Tailscale SSH, with run monitoring and usage reporting.

## kobito実行の中継

人間向けのWebチャットと会話の保存は2026-11-01に撤去した（FEZ-266）。人間はClaude/Codexそれぞれの公式アプリを使う。Macのローカル環境をスマホから使う場合はClaude Remote Controlを使う。

### Project別kobitoの実行（opt-in）

`POST /api/run`は`project_id`・`repo`・`execution_mode`（`conversation`または`work`）を受け取れる。指定したProjectとrepoの対応、稼働設定はMacのkobito側`project_slack.py exec`が私有設定で検証し、異なるrepoへの実行を拒否する。

Slackの即時会話は`source: "kobito-slack"`で、Project・repo・`conversation`モードの指定を必須とする。Claudeには`--restricted`、Read/Glob/Grepだけのツール、空のstrict MCP設定、hooks無効、plan permission modeを適用する。会話により編集権限を増やさず、Schedulerの稼働記録にも混ぜない。

`KOBITO_PROJECT_DISPATCH_ENABLED`（既定false）がtrueの場合、従来のkobito定期実行で登録Projectを順番に選ぶ。`KOBITO_PROJECT_RUNNER`はMac側のrunnerパス（既定`~/repos/kobito/scripts/project_slack.py`）。選択に失敗したり稼働Projectがない場合は、従来の全Project横断実行へ戻らず終了する。新しいSchedulerやクラウドサービスを追加しない。秘密情報とProject・channel対応表はMac側で管理し、コンテナイメージへ含めない。

この機能はhuman-agent-boardのProject対応とkobitoのSlack受付実装を先に反映してから有効にする。導入・本人照合・置き手紙・承認の検証はkobitoの`SLACK_SETUP.md`を参照する。
既存の`cloudbuild.yaml`も`_KOBITO_PROJECT_DISPATCH_ENABLED: "false"`を既定とする。稼働を切り替える際は既存トリガーの同名substitutionで指定し、別のトリガーやSchedulerを作らない。

### Web authentication configuration

Authentication and execution backends are controlled by environment
variables. `AUTH_MODE=shared_token` preserves the original bearer-token flow.
`AUTH_MODE=oauth` enables Google and/or LINE Login; a provider is shown only
when both its ID and secret are configured.

| Variable | Values / purpose |
| --- | --- |
| `AUTH_MODE` | `shared_token` or `oauth` |
| `ACCESS_MODE` | `private` (allowlist) or `authenticated` (any signed-in account) |
| `AUTHORIZED_GOOGLE_EMAILS` | Comma-separated verified emails for private mode |
| `AUTHORIZED_LINE_USER_IDS` | Comma-separated LINE Login user IDs for private mode |
| `LIFF_ID` | LIFF app ID used by `/usage.html`; empty disables LIFF |
| `EXECUTION_ENABLED` | Global execution kill switch |
| `CLAUDE_ENABLED` | Enable the currently implemented Claude executor |
| `CODEX_ENABLED` | Advertise Codex availability (executor not yet implemented) |
| `USAGE_PRIVATE_ONLY` | Keep `/api/usage` restricted to allowlisted identities |

OAuth secrets belong in Secret Manager (`SESSION_SECRET`,
`GOOGLE_OAUTH_CLIENT_SECRET`, and `LINE_LOGIN_CHANNEL_SECRET`). IDs and access
policy are Cloud Build trigger substitutions. Configure these callback URLs:

- Google: `https://<service-host>/auth/callback/google`
- LINE Login: `https://<service-host>/auth/callback/line`

The usage dashboard can reuse that same LINE Login channel through a LIFF app.
Set its Endpoint URL to `https://<service-host>/usage.html`, request only
`openid` and `profile`, and put its public LIFF ID in `LIFF_ID`. The browser
sends the LIFF ID token to `/auth/liff`; the server verifies it directly with
LINE before creating the same application session used by ordinary LINE Login.

Google uses the OpenID Connect authorization-code flow with a verified email.
LINE Login uses OpenID Connect with server-side ID-token verification. Both
flows validate `state` and `nonce`; the resulting application session is kept
in a Secure, HttpOnly, SameSite=Lax signed cookie for 30 days.

## Execution environment

kobitoの実行はMac（Tailscale経由のSSH）だけで行う。Macが止まっている間の代わりの実行環境（GCP VMフォールバック）は、2026-11-01に不要と判断して撤去した（FEZ-266）。

## Board通知

Board・kobitoの通知と承認はSlackに一本化した。LINE Messaging APIのwebhook（`/line/webhook`）、リッチメニュー、「kobito状況」の問い合わせは2026-11に撤去した（FEZ-273）。LINE Login（usage画面のログイン）は引き続き使う。

### kobito実行監視

`/api/run`がkobitoの固定プロンプトまたは`source: "kobito"`を受け取ると、Mac上のhuman-agent-boardへ実行開始、60秒heartbeat、正常・異常終了を自動記録する。gateway/SSHエラーでは同一障害を重複させず、ユーザー対応依頼をBoard（通知はSlack）へ送る。正常終了時にその障害項目を自動解消する。

`POST /api/kobito-health`は、heartbeatが15分以上停止した実行、4時間以上起動が確認できない状態、連続失敗を検査する。別のCloud Scheduler等から15分間隔で呼び出すことで、通常のkobitoトリガー自体が止まった場合も検知できる。認証は他の`/api/*`と同じBearer tokenを使う。

監視ジョブを追加する場合も既存の`ai-gateway`・単一リージョンを利用し、Cloud Runのmin instancesやCPU設定は変更しない。
