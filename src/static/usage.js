const TOKEN_KEY = "ai_gateway_token";
let selectedHours = 168;

function token() {
  return localStorage.getItem(TOKEN_KEY) || "";
}

function line(points, provider, start, span) {
  const values = points.filter(p => p.provider === provider);
  if (!values.length) return "";
  return values.map((p, index) => {
    const time = Date.parse(p.recorded_at);
    const x = 50 + ((time - start) / span) * 720;
    const y = 280 - Number(p.primary_used) * 2.4;
    return `${index ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
}

function render(data) {
  document.querySelector("#updated").textContent = `更新 ${data.generated_at}`;
  document.querySelector("#cards").innerHTML = ["claude", "codex"].map(provider => {
    const item = data.latest[provider];
    if (!item) return `<article class="card"><span>${provider}</span><strong>取得待ち</strong><span class="muted">利用開始後に反映</span></article>`;
    return `<article class="card"><span>${provider}</span><strong>${(100-item.primary_used).toFixed(0)}% 残</strong><span>5時間枠</span><p class="muted">最終取得 ${item.recorded_at}</p></article>`;
  }).join("");
  const end = Date.now(), start = end - selectedHours * 3600000, span = Math.max(1, end - start);
  const grid = [0,25,50,75,100].map(v => `<path class="grid" d="M50 ${280-v*2.4}H770"/><text x="8" y="${285-v*2.4}" fill="#8fa2b8">${v}%</text>`).join("");
  document.querySelector("#chart").innerHTML = `${grid}<path class="series claude" d="${line(data.snapshots,"claude",start,span)}"/><path class="series codex" d="${line(data.snapshots,"codex",start,span)}"/>`;
  document.querySelector("#tasks").innerHTML = data.tasks.length ? data.tasks.map(t => `<div class="task"><span>${t.work_id} · ${t.provider}</span><strong>${t.primary_used_delta == null ? "計測中" : t.primary_used_delta.toFixed(1)+"pt"}</strong></div>`).join("") : '<p class="muted">issue紐付けデータを蓄積中です。</p>';
  document.querySelector("#savings").textContent = data.savings.message;
}

async function load() {
  if (!token()) { document.querySelector("#auth").classList.add("visible"); document.querySelector("#updated").textContent = "認証してください"; return; }
  document.querySelector("#auth").classList.remove("visible");
  const response = await fetch(`/api/usage?hours=${selectedHours}`, {headers:{Authorization:`Bearer ${token()}`}});
  if (response.status === 401) { localStorage.removeItem(TOKEN_KEY); document.querySelector("#auth").classList.add("visible"); document.querySelector("#updated").textContent = "トークンが違います"; return; }
  if (!response.ok) throw new Error(`取得失敗 (${response.status})`);
  render(await response.json());
}
document.querySelectorAll("nav button").forEach(button => button.onclick = () => { document.querySelector("nav button.active").classList.remove("active"); button.classList.add("active"); selectedHours=Number(button.dataset.hours); load(); });
document.querySelector("#auth").onsubmit = event => { event.preventDefault(); const value=document.querySelector("#token").value.trim(); if (value) localStorage.setItem(TOKEN_KEY,value); load(); };
load().catch(error => document.querySelector("#updated").textContent = error.message);
