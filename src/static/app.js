if ("serviceWorker" in navigator) navigator.serviceWorker.register("/service-worker.js");

const TOKEN_KEY = "ai_gateway_token";
const REPO_KEY = "ai_gateway_repo";
const ACTIVE_KEY = "ai_gateway_active_conversation";

const el = Object.fromEntries([
  "run-form", "repo", "prompt", "submit-btn", "messages", "empty-state",
  "conversation-list", "conversation-title", "conversation-status", "new-chat",
  "delete-chat", "run-notice", "run-notice-text", "stop-btn", "sidebar",
  "sidebar-backdrop", "menu-button", "close-sidebar",
].map((id) => [id, document.getElementById(id)]));

const state = {
  conversations: [], active: null, running: false, controller: null,
  currentAssistant: null, lastPrompt: "",
};

function getToken() {
  let token = localStorage.getItem(TOKEN_KEY);
  if (!token) {
    token = window.prompt("ai-gateway access token") || "";
    if (token) localStorage.setItem(TOKEN_KEY, token);
  }
  return token;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${getToken()}`,
      ...(options.headers || {}),
    },
  });
  if (response.status === 401) {
    localStorage.removeItem(TOKEN_KEY);
    throw new Error("認証に失敗しました。再読み込みしてトークンを入力してください。");
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.error || `リクエストに失敗しました (${response.status})`);
  }
  return response.status === 204 ? null : response.json();
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;",
  })[char]);
}

function renderMarkdown(source) {
  const blocks = [];
  let text = String(source || "").replace(/```([\w.+-]*)\n?([\s\S]*?)```/g, (_, language, code) => {
    const index = blocks.push({ language: language || "text", code: code.replace(/\n$/, "") }) - 1;
    return `\n@@CODE${index}@@\n`;
  });
  text = escapeHtml(text)
    .replace(/`([^`\n]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\n{2,}/g, "</p><p>")
    .replace(/\n/g, "<br>");
  text = `<p>${text}</p>`;
  blocks.forEach((block, index) => {
    const codeBlock = `<div class="code-block"><div class="code-toolbar"><span>${escapeHtml(block.language)}</span><button class="copy-code" type="button">コピー</button></div><pre><code>${escapeHtml(block.code)}</code></pre></div>`;
    text = text.replace(`<p>@@CODE${index}@@</p>`, codeBlock).replace(`@@CODE${index}@@`, codeBlock);
  });
  return text.replace(/<p>\s*<\/p>/g, "");
}

function formatTime(value = new Date()) {
  const date = value instanceof Date ? value : new Date(value);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleTimeString("ja-JP", { hour: "2-digit", minute: "2-digit" });
}

function addMessage(message, { streaming = false } = {}) {
  el["empty-state"].classList.add("hidden");
  const article = document.createElement("article");
  article.className = `message ${message.role}`;
  article.dataset.messageId = message.id || "";
  const names = { user: "あなた", assistant: "Claude", system: "システム" };
  const avatars = { user: "YOU", assistant: "AI", system: "!" };
  article.innerHTML = `
    <div class="avatar">${avatars[message.role] || "?"}</div>
    <div>
      <div class="message-head"><strong>${names[message.role] || message.role}</strong><span>${formatTime(message.created_at)}</span></div>
      <div class="message-content"></div>
      ${message.role === "assistant" && !streaming ? '<div class="message-actions"><button class="retry-button" type="button">↻ 再実行</button></div>' : ""}
    </div>`;
  article.querySelector(".message-content").innerHTML = renderMarkdown(message.content);
  el.messages.appendChild(article);
  bindMessageActions(article);
  scrollToBottom();
  return article;
}

function bindMessageActions(container) {
  container.querySelectorAll(".copy-code").forEach((button) => button.addEventListener("click", async () => {
    await navigator.clipboard.writeText(button.closest(".code-block").querySelector("code").textContent);
    button.textContent = "コピー済み";
    setTimeout(() => { button.textContent = "コピー"; }, 1400);
  }));
  container.querySelectorAll(".retry-button").forEach((button) => button.addEventListener("click", () => retryLastPrompt()));
}

function updateStreamingMessage(content) {
  if (!state.currentAssistant) {
    state.currentAssistant = addMessage({ role: "assistant", content: "", created_at: new Date() }, { streaming: true });
  }
  state.currentAssistant.querySelector(".message-content").innerHTML = renderMarkdown(content || "▍");
  bindMessageActions(state.currentAssistant);
  scrollToBottom();
}

function scrollToBottom() {
  requestAnimationFrame(() => { el.messages.scrollTop = el.messages.scrollHeight; });
}

function renderConversationList() {
  el["conversation-list"].replaceChildren();
  state.conversations.forEach((conversation) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `conversation-item${state.active?.id === conversation.id ? " active" : ""}`;
    button.innerHTML = `<span>${escapeHtml(conversation.title)}</span>`;
    button.addEventListener("click", () => openConversation(conversation.id));
    el["conversation-list"].appendChild(button);
  });
}

async function refreshConversations() {
  const data = await api("/api/conversations");
  state.conversations = data.conversations;
  renderConversationList();
}

async function openConversation(id) {
  if (state.running) return;
  const conversation = await api(`/api/conversations/${id}`);
  state.active = conversation;
  localStorage.setItem(ACTIVE_KEY, id);
  el["conversation-title"].value = conversation.title;
  el.repo.value = conversation.repo || "";
  localStorage.setItem(REPO_KEY, conversation.repo || "");
  el.messages.replaceChildren();
  if (!conversation.messages.length) el.messages.appendChild(el["empty-state"]);
  conversation.messages.forEach((message) => addMessage(message));
  state.lastPrompt = [...conversation.messages].reverse().find((message) => message.role === "user")?.content || "";
  setStatus("準備完了");
  renderConversationList();
  closeSidebar();
}

async function createConversation() {
  if (state.running) return state.active;
  const conversation = await api("/api/conversations", {
    method: "POST",
    body: JSON.stringify({ title: "新しい会話", repo: el.repo.value.trim() || null }),
  });
  state.conversations.unshift(conversation);
  await openConversation(conversation.id);
  el.prompt.focus();
  return conversation;
}

async function ensureConversation(prompt) {
  if (!state.active) await createConversation();
  if (state.active.title === "新しい会話") {
    const title = prompt.replace(/\s+/g, " ").slice(0, 48);
    state.active = await api(`/api/conversations/${state.active.id}`, {
      method: "PATCH", body: JSON.stringify({ title }),
    });
    el["conversation-title"].value = title;
  }
  return state.active;
}

function setRunning(running) {
  state.running = running;
  el["submit-btn"].disabled = running;
  el.prompt.disabled = running;
  el["run-notice"].classList.toggle("hidden", !running);
  el["delete-chat"].disabled = running;
}

function setStatus(text) { el["conversation-status"].textContent = text; }

async function saveMessage(role, content, kind = "message") {
  return api(`/api/conversations/${state.active.id}/messages`, {
    method: "POST", body: JSON.stringify({ role, content, kind }),
  });
}

async function runTask(prompt) {
  await ensureConversation(prompt);
  const repo = el.repo.value.trim();
  localStorage.setItem(REPO_KEY, repo);
  if (repo !== (state.active.repo || "")) {
    state.active = await api(`/api/conversations/${state.active.id}`, {
      method: "PATCH", body: JSON.stringify({ repo: repo || null }),
    });
  }
  const userMessage = await saveMessage("user", prompt);
  addMessage(userMessage);
  state.lastPrompt = prompt;
  state.currentAssistant = null;
  let assistantText = "";
  let runDetail = "";
  setRunning(true);
  setStatus("実行中");
  el["run-notice-text"].textContent = "Claudeが作業中です…";
  state.controller = new AbortController();

  try {
    const response = await fetch("/api/run", {
      method: "POST",
      signal: state.controller.signal,
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${getToken()}` },
      body: JSON.stringify({ prompt, resume_session_id: state.active.session_id, repo: repo || null }),
    });
    if (!response.ok || !response.body) throw new Error(`実行リクエストに失敗しました (${response.status})`);
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
        const event = parseFrame(frame);
        if (!event) continue;
        if (event.type === "text_delta" && event.delta) {
          assistantText += event.delta;
          updateStreamingMessage(assistantText);
        } else if (event.type === "result") {
          if (!assistantText && event.result) assistantText = event.result;
          if (event.session_id) {
            state.active.session_id = event.session_id;
            await api(`/api/conversations/${state.active.id}`, { method: "PATCH", body: JSON.stringify({ session_id: event.session_id }) });
          }
        } else if (event.type === "connectivity_preflight") {
          runDetail = `接続確認: ${event.overall}`;
          el["run-notice-text"].textContent = runDetail;
        } else if (event.type === "gateway_error") {
          throw new Error(event.message || "Gateway error");
        }
      }
    }
    if (!assistantText) assistantText = "応答本文がありませんでした。";
    updateStreamingMessage(assistantText);
    await saveMessage("assistant", assistantText);
    finishAssistantMessage();
    setStatus("完了");
  } catch (error) {
    if (error.name === "AbortError") {
      const partial = assistantText ? `${assistantText}\n\n_（ユーザーが実行を停止しました）_` : "実行を停止しました。";
      updateStreamingMessage(partial);
      await saveMessage("assistant", partial, "log").catch(() => {});
      finishAssistantMessage();
      setStatus("停止済み");
    } else {
      const message = `[エラー] ${error.message}`;
      addMessage({ role: "system", content: message, created_at: new Date() });
      await saveMessage("system", message, "error").catch(() => {});
      setStatus("エラー");
    }
  } finally {
    setRunning(false);
    state.controller = null;
    await refreshConversations().catch(() => {});
    el.prompt.focus();
  }
}

function finishAssistantMessage() {
  if (!state.currentAssistant) return;
  const actions = document.createElement("div");
  actions.className = "message-actions";
  actions.innerHTML = '<button class="retry-button" type="button">↻ 再実行</button>';
  state.currentAssistant.querySelector(":scope > div:last-child").appendChild(actions);
  bindMessageActions(state.currentAssistant);
  state.currentAssistant = null;
}

function parseFrame(frame) {
  const line = frame.split("\n").find((part) => part.startsWith("data: "));
  if (!line) return null;
  try { return JSON.parse(line.slice(6)); } catch { return null; }
}

async function retryLastPrompt() {
  if (!state.running && state.lastPrompt) await runTask(state.lastPrompt);
}

function autoSizePrompt() {
  el.prompt.style.height = "auto";
  el.prompt.style.height = `${Math.min(el.prompt.scrollHeight, 180)}px`;
}

function openSidebar() { el.sidebar.classList.add("open"); el["sidebar-backdrop"].classList.add("open"); }
function closeSidebar() { el.sidebar.classList.remove("open"); el["sidebar-backdrop"].classList.remove("open"); }

el["run-form"].addEventListener("submit", async (event) => {
  event.preventDefault();
  const prompt = el.prompt.value.trim();
  if (!prompt || state.running) return;
  el.prompt.value = "";
  autoSizePrompt();
  await runTask(prompt);
});
el.prompt.addEventListener("input", autoSizePrompt);
el.prompt.addEventListener("keydown", (event) => {
  if ((event.metaKey || event.ctrlKey) && event.key === "Enter") el["run-form"].requestSubmit();
});
el["stop-btn"].addEventListener("click", () => state.controller?.abort());
el["new-chat"].addEventListener("click", createConversation);
el["delete-chat"].addEventListener("click", async () => {
  if (!state.active || state.running || !window.confirm(`「${state.active.title}」を削除しますか？`)) return;
  await api(`/api/conversations/${state.active.id}`, { method: "DELETE" });
  state.active = null;
  localStorage.removeItem(ACTIVE_KEY);
  await refreshConversations();
  if (state.conversations.length) await openConversation(state.conversations[0].id); else await createConversation();
});
el["conversation-title"].addEventListener("change", async () => {
  if (!state.active) return;
  const title = el["conversation-title"].value.trim() || "新しい会話";
  state.active = await api(`/api/conversations/${state.active.id}`, { method: "PATCH", body: JSON.stringify({ title }) });
  await refreshConversations();
});
el["menu-button"].addEventListener("click", openSidebar);
el["close-sidebar"].addEventListener("click", closeSidebar);
el["sidebar-backdrop"].addEventListener("click", closeSidebar);

async function initialize() {
  el.repo.value = localStorage.getItem(REPO_KEY) || "";
  try {
    await refreshConversations();
    const preferred = localStorage.getItem(ACTIVE_KEY);
    const target = state.conversations.find((item) => item.id === preferred) || state.conversations[0];
    if (target) await openConversation(target.id); else await createConversation();
  } catch (error) {
    setStatus("接続エラー");
    addMessage({ role: "system", content: error.message, created_at: new Date() });
  }
}

initialize();
