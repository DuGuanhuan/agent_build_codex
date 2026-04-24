const messagesEl = document.querySelector("#messages");
const form = document.querySelector("#chatForm");
const input = document.querySelector("#input");
const sendButton = document.querySelector("#sendButton");

const history = [];

function addMessage(role, content, steps = []) {
  const message = document.createElement("article");
  message.className = `message ${role}`;
  message.textContent = content;

  if (steps.length) {
    const stepBox = document.createElement("div");
    stepBox.className = "steps";
    stepBox.innerHTML = steps
      .map((step) => {
        const result = JSON.stringify(step.result);
        return `调用 <code>${escapeHtml(step.tool)}</code> -> <code>${escapeHtml(result)}</code>`;
      })
      .join("<br />");
    message.appendChild(stepBox);
  }

  messagesEl.appendChild(message);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

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
  input.style.height = `${input.scrollHeight}px`;
}

async function sendMessage(text) {
  history.push({ role: "user", content: text });
  addMessage("user", text);
  addMessage("system", "Agent 思考中...");
  sendButton.disabled = true;

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages: history }),
    });
    const data = await response.json();
    messagesEl.lastElementChild.remove();

    if (!response.ok || data.error) {
      throw new Error(data.error || "请求失败");
    }

    history.push({ role: "assistant", content: data.answer });
    addMessage("agent", data.answer, data.steps || []);
  } catch (error) {
    messagesEl.lastElementChild?.classList.contains("system") && messagesEl.lastElementChild.remove();
    addMessage("agent", `出错了：${error.message}`);
  } finally {
    sendButton.disabled = false;
    input.focus();
  }
}

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

addMessage("agent", "你好，我是这个项目里的手写 Agent。可以直接聊天，也可以让我调用时间和计算工具。");
