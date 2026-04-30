const messagesEl = document.querySelector("#messages");
const form = document.querySelector("#chatForm");
const input = document.querySelector("#input");
const sendButton = document.querySelector("#sendButton");
const welcome = document.querySelector("#welcome");
const modelPicker = document.querySelector("#modelPicker");
const modelButton = document.querySelector("#modelButton");
const modelButtonLabel = document.querySelector("#modelButtonLabel");
const modelProviderLabel = document.querySelector("#modelProviderLabel");
const modelMenu = document.querySelector("#modelMenu");

const history = [];
let selectedModelId = "";
let modelOptions = [];

/* ===== Helpers ===== */
function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function resizeInput() {
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight, 200)}px`;
}

function scrollToBottom() {
  const chatMain = document.querySelector(".chat-main");
  chatMain.scrollTop = chatMain.scrollHeight;
}

function renderMarkdown(value) {
  const text = String(value || "").replace(/\r\n?/g, "\n");
  if (!window.marked || !window.DOMPurify) {
    return `<p>${escapeHtml(text).replaceAll("\n", "<br>")}</p>`;
  }

  const dirtyHtml = window.marked.parse(text, {
    async: false,
    breaks: true,
    gfm: true,
  });

  return window.DOMPurify.sanitize(dirtyHtml, {
    ADD_ATTR: ["class"],
    USE_PROFILES: { html: true },
  });
}

function decorateRenderedMarkdown(root) {
  root.querySelectorAll(".agent-text a[href]").forEach((link) => {
    link.target = "_blank";
    link.rel = "noreferrer";
  });
}

function selectedModel() {
  return modelOptions.find((model) => model.id === selectedModelId);
}

function providerName(provider) {
  const names = {
    zhipu: "智谱",
    deepseek: "DeepSeek",
  };
  return names[provider] || provider || "模型";
}

function updateModelTrigger() {
  const model = selectedModel();
  if (!modelButtonLabel || !modelProviderLabel) return;

  modelButtonLabel.textContent = model?.label || "选择模型";
  modelProviderLabel.textContent = model ? providerName(model.provider) : "模型";
}

function modelCardHTML(model) {
  const selected = model.id === selectedModelId;
  const unavailable = !model.available;
  const modeLabel = model.thinking === "enabled" ? "Thinking" : "Chat";
  const disabledText = unavailable ? " · 未配置 key" : "";

  return `
    <button
      class="model-card${selected ? " selected" : ""}"
      type="button"
      role="option"
      aria-selected="${selected ? "true" : "false"}"
      data-model-id="${escapeHtml(model.id)}"
      ${unavailable ? "disabled" : ""}
    >
      <span class="model-card-main">
        <span class="model-card-title">${escapeHtml(model.label)}</span>
        <span class="model-card-meta">
          <span>${escapeHtml(providerName(model.provider))}</span>
          <span>${escapeHtml(modeLabel + disabledText)}</span>
        </span>
      </span>
      <span class="model-card-desc">${escapeHtml(model.description || "")}</span>
    </button>`;
}

function renderModelMenu() {
  if (!modelMenu) return;

  modelMenu.innerHTML = `
    <div class="model-menu-header">
      <span>选择本次对话模型</span>
      <small>${modelOptions.filter((model) => model.available).length}/${modelOptions.length} 可用</small>
    </div>
    <div class="model-card-list">
      ${modelOptions.map(modelCardHTML).join("")}
    </div>`;
}

function setModelMenuOpen(open) {
  if (!modelMenu || !modelButton) return;
  modelMenu.hidden = !open;
  modelButton.setAttribute("aria-expanded", open ? "true" : "false");
}

function setSelectedModel(modelId) {
  const nextModel = modelOptions.find((model) => model.id === modelId && model.available);
  if (!nextModel) return;

  selectedModelId = nextModel.id;
  localStorage.setItem("agent:model", selectedModelId);
  updateModelTrigger();
  renderModelMenu();
  setModelMenuOpen(false);
}

function setModelOptions(models, defaultModelId) {
  if (!modelButton || !modelMenu) return;

  const savedModelId = localStorage.getItem("agent:model");
  const availableModels = models.filter((model) => model.available);
  modelOptions = models;
  selectedModelId = (
    availableModels.find((model) => model.id === savedModelId)?.id
    || availableModels.find((model) => model.id === defaultModelId)?.id
    || availableModels[0]?.id
    || defaultModelId
    || models[0]?.id
    || ""
  );

  updateModelTrigger();
  renderModelMenu();
}

async function loadModels() {
  if (!modelButton || !modelMenu) return;

  try {
    const response = await fetch("/api/models");
    const data = await response.json();
    if (!response.ok || !Array.isArray(data.models)) {
      throw new Error(data.error || "模型列表加载失败");
    }
    setModelOptions(data.models, data.default);
  } catch (error) {
    modelButtonLabel.textContent = "模型加载失败";
    modelButton.disabled = true;
    console.warn(error);
  }
}

/* ===== Avatar SVG ===== */
function agentAvatarHTML() {
  return `<div class="agent-avatar">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <path d="M12 2L2 7l10 5 10-5-10-5z"/>
      <path d="M2 17l10 5 10-5"/>
      <path d="M2 12l10 5 10-5"/>
    </svg>
  </div>`;
}

/* ===== Build Step Detail ===== */
function buildStepsHTML(steps) {
  if (!steps.length) return "";

  const id = `steps-${Date.now()}`;
  const lines = steps
    .map((step) => {
      const result = JSON.stringify(step.result);
      return `调用 <code>${escapeHtml(step.tool)}</code> → <code>${escapeHtml(result)}</code>`;
    })
    .join("<br/>");

  return `<div class="steps">
    <button class="steps-toggle" onclick="toggleSteps('${id}', this)">
      <svg viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 4.5l3 3 3-3"/></svg>
      ${steps.length} 个工具调用
    </button>
    <div class="steps-detail" id="${id}">${lines}</div>
  </div>`;
}

/* Toggle steps collapse */
window.toggleSteps = function (id, btn) {
  const detail = document.getElementById(id);
  detail.classList.toggle("open");
  btn.classList.toggle("open");
};

/* ===== Add Message ===== */
function hideWelcome() {
  if (welcome) {
    welcome.style.display = "none";
  }
}

function addMessage(role, content, steps = []) {
  hideWelcome();

  const el = document.createElement("article");
  el.className = `message ${role}`;

  if (role === "user") {
    el.textContent = content;
  } else if (role === "agent") {
    el.innerHTML = `
      ${agentAvatarHTML()}
      <div class="agent-body">
        <div class="agent-text">${renderMarkdown(content)}</div>
        ${buildStepsHTML(steps)}
      </div>`;
  } else if (role === "thinking") {
    el.innerHTML = `
      ${agentAvatarHTML()}
      <div class="agent-body">
        <div class="thinking-dots">
          <span></span><span></span><span></span>
        </div>
      </div>`;
  }

  messagesEl.appendChild(el);
  if (role === "agent") {
    decorateRenderedMarkdown(el);
  }
  requestAnimationFrame(scrollToBottom);
}

/* ===== Remove Thinking Indicator ===== */
function removeThinking() {
  const dots = messagesEl.querySelectorAll(".message.thinking");
  dots.forEach((el) => el.remove());
}

/* ===== Send Message ===== */
async function sendMessage(text) {
  history.push({ role: "user", content: text });
  addMessage("user", text);
  addMessage("thinking");
  sendButton.disabled = true;

  // 60-second timeout to prevent infinite hanging
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 60000);

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages: history, model: selectedModelId }),
      signal: controller.signal,
    });

    let data;
    try {
      data = await response.json();
    } catch {
      throw new Error(`服务器返回了无效响应 (HTTP ${response.status})`);
    }

    removeThinking();

    if (!response.ok || data.error) {
      throw new Error(data.error || `请求失败 (HTTP ${response.status})`);
    }

    history.push({ role: "assistant", content: data.answer });
    addMessage("agent", data.answer, data.steps || []);
  } catch (error) {
    removeThinking();
    const msg = error.name === "AbortError"
      ? "请求超时，请稍后重试"
      : error.message;
    addMessage("agent", `出错了：${msg}`);
  } finally {
    clearTimeout(timeout);
    sendButton.disabled = false;
    input.focus();
  }
}

/* ===== Events ===== */
form.addEventListener("submit", (event) => {
  event.preventDefault();
  const text = input.value.trim();
  if (!text || sendButton.disabled) return;
  input.value = "";
  resizeInput();
  sendMessage(text);
});

input.addEventListener("input", resizeInput);
input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    form.requestSubmit();
  }
});

/* ===== Suggestion Buttons ===== */
document.querySelectorAll(".suggestion-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    const prompt = btn.dataset.prompt;
    if (prompt && !sendButton.disabled) {
      input.value = "";
      resizeInput();
      sendMessage(prompt);
    }
  });
});

modelButton?.addEventListener("click", () => {
  setModelMenuOpen(modelMenu.hidden);
});

modelMenu?.addEventListener("click", (event) => {
  const card = event.target.closest("[data-model-id]");
  if (!card) return;
  setSelectedModel(card.dataset.modelId);
});

document.addEventListener("click", (event) => {
  if (!modelPicker || modelPicker.contains(event.target)) return;
  setModelMenuOpen(false);
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    setModelMenuOpen(false);
  }
});

loadModels();
