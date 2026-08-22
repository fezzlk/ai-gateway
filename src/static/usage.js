const TOKEN_KEY = "ai_gateway_token";
let selectedHours = 168;
let authConfig = null;

function token() { return localStorage.getItem(TOKEN_KEY) || ""; }

function line(points, provider, start, span) {
  const values = points.filter((point) => point.provider === provider);
  if (!values.length) return "";
  return values.map((point, index) => {
    const time = Date.parse(point.recorded_at);
    const x = 50 + ((time - start) / span) * 720;
    const y = 280 - Number(point.primary_used) * 2.4;
    return `${index ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
}

function render(data) {
  document.querySelector("#updated").textContent = `更新 ${data.generated_at}`;
  document.querySelector("#cards").innerHTML = ["claude", "codex"].map((provider) => {
    const item = data.latest[provider];
    if (!item) return `<article class="card"><span>${provider}</span><strong>取得待ち</strong><span class="muted">利用開始後に反映</span></article>`;
    return `<article class="card"><span>${provider}</span><strong>${(100 - item.primary_used).toFixed(0)}% 残</strong><span>5時間枠</span><p class="muted">最終取得 ${item.recorded_at}</p></article>`;
  }).join("");
  const end = Date.now();
  const start = end - selectedHours * 3600000;
  const span = Math.max(1, end - start);
  const grid = [0, 25, 50, 75, 100].map((value) => `<path class="grid" d="M50 ${280 - value * 2.4}H770"/><text x="8" y="${285 - value * 2.4}" fill="#8fa2b8">${value}%</text>`).join("");
  document.querySelector("#chart").innerHTML = `${grid}<path class="series claude" d="${line(data.snapshots, "claude", start, span)}"/><path class="series codex" d="${line(data.snapshots, "codex", start, span)}"/>`;
  document.querySelector("#tasks").innerHTML = data.tasks.length ? data.tasks.map((task) => `<div class="task"><span>${task.work_id} · ${task.provider}</span><strong>${task.primary_used_delta == null ? "計測中" : `${task.primary_used_delta.toFixed(1)}pt`}</strong></div>`).join("") : '<p class="muted">issue紐付けデータを蓄積中です。</p>';
  document.querySelector("#savings").textContent = data.savings.message;
}

async function load() {
  const headers = {};
  if (authConfig.mode === "shared_token") {
    if (!token()) {
      showAuth("認証してください", "legacy");
      return;
    }
    headers.Authorization = `Bearer ${token()}`;
  }
  const response = await fetch(`/api/usage?hours=${selectedHours}`, { headers });
  if (response.status === 401) {
    if (authConfig.mode === "shared_token") localStorage.removeItem(TOKEN_KEY);
    showAuth("認証が必要です", authConfig.mode === "oauth" ? "line" : "legacy");
    return;
  }
  if (response.status === 403) throw new Error("このアカウントには利用量を表示する権限がありません");
  if (!response.ok) throw new Error(`取得失敗 (${response.status})`);
  document.querySelector("#auth").classList.remove("visible");
  render(await response.json());
}

function showAuth(message, kind) {
  document.querySelector("#auth").classList.add("visible");
  document.querySelector("#legacy-auth").hidden = kind !== "legacy";
  document.querySelector("#line-auth").hidden = kind !== "line";
  document.querySelector("#updated").textContent = message;
}

async function authenticateWithLiff() {
  if (!authConfig.liff_id || !window.liff) {
    window.location.assign("/auth/login/line");
    return;
  }
  await window.liff.init({ liffId: authConfig.liff_id });
  if (!window.liff.isLoggedIn()) {
    window.liff.login({ redirectUri: window.location.href.split("?")[0] });
    return;
  }
  const idToken = window.liff.getIDToken();
  if (!idToken) throw new Error("LINE IDトークンを取得できませんでした");
  const response = await fetch("/auth/liff", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id_token: idToken }),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.error || "LINE認証に失敗しました");
  }
  authConfig.authenticated = true;
  await load();
}

document.querySelectorAll("nav button").forEach((button) => {
  button.onclick = () => {
    document.querySelector("nav button.active").classList.remove("active");
    button.classList.add("active");
    selectedHours = Number(button.dataset.hours);
    load().catch(showError);
  };
});
document.querySelector("#legacy-auth").onsubmit = (event) => {
  event.preventDefault();
  const value = document.querySelector("#token").value.trim();
  if (value) localStorage.setItem(TOKEN_KEY, value);
  load().catch(showError);
};
document.querySelector("#line-login").onclick = () => authenticateWithLiff().catch(showError);

function showError(error) { document.querySelector("#updated").textContent = error.message; }

async function initialize() {
  const response = await fetch("/auth/session");
  if (!response.ok) throw new Error("認証設定を取得できませんでした");
  authConfig = await response.json();
  if (authConfig.mode === "oauth" && !authConfig.authenticated) {
    showAuth("LINE認証が必要です", "line");
    if (authConfig.liff_id && window.liff) await authenticateWithLiff();
    return;
  }
  await load();
}

initialize().catch(showError);
