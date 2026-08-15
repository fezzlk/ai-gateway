if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/service-worker.js");
}

const TOKEN_KEY = "ai_gateway_token";
const REPO_KEY = "ai_gateway_repo";

function getToken() {
  let token = localStorage.getItem(TOKEN_KEY);
  if (!token) {
    token = window.prompt("Enter the ai-gateway access token:") || "";
    if (token) localStorage.setItem(TOKEN_KEY, token);
  }
  return token;
}

const form = document.getElementById("run-form");
const repoEl = document.getElementById("repo");
const promptEl = document.getElementById("prompt");
const submitBtn = document.getElementById("submit-btn");
const output = document.getElementById("output");

let lastSessionId = null;

repoEl.value = localStorage.getItem(REPO_KEY) || "";

form.addEventListener("submit", async (event) => {
  event.preventDefault();

  const prompt = promptEl.value.trim();
  if (!prompt) return;

  const repo = repoEl.value.trim();
  localStorage.setItem(REPO_KEY, repo);

  submitBtn.disabled = true;
  output.textContent = "";

  try {
    await runTask(prompt, repo);
  } catch (err) {
    output.textContent += `\n[error] ${err.message}`;
  } finally {
    submitBtn.disabled = false;
  }
});

async function runTask(prompt, repo) {
  const response = await fetch("/api/run", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${getToken()}`,
    },
    body: JSON.stringify({ prompt, resume_session_id: lastSessionId, repo: repo || null }),
  });

  if (response.status === 401) {
    localStorage.removeItem(TOKEN_KEY);
    throw new Error("unauthorized — reload and re-enter the token");
  }

  if (!response.ok || !response.body) {
    throw new Error(`request failed (${response.status})`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });

    let frameEnd;
    while ((frameEnd = buffer.indexOf("\n\n")) !== -1) {
      const frame = buffer.slice(0, frameEnd);
      buffer = buffer.slice(frameEnd + 2);
      handleFrame(frame);
    }
  }
}

function handleFrame(frame) {
  const dataLine = frame.split("\n").find((line) => line.startsWith("data: "));
  if (!dataLine) return;

  let event;
  try {
    event = JSON.parse(dataLine.slice("data: ".length));
  } catch {
    return;
  }

  if (event.type === "text_delta" && event.delta) {
    output.textContent += event.delta;
  } else if (event.type === "result") {
    if (event.session_id) lastSessionId = event.session_id;
    if (event.result) output.textContent += `\n\n${event.result}`;
  } else if (event.type === "gateway_error" || event.type === "log") {
    output.textContent += `\n[${event.type}] ${event.message || event.line || ""}`;
  }

  output.scrollTop = output.scrollHeight;
}
