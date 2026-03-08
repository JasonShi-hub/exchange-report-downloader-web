const API_BASE = "https://api.shijason.com";
const TOKEN_KEY = "exchange-report-downloader-token";
const TOKEN_EXP_KEY = "exchange-report-downloader-token-exp";

const state = {
  token: localStorage.getItem(TOKEN_KEY) || "",
  tokenExpiresAt: localStorage.getItem(TOKEN_EXP_KEY) || "",
  market: "ashare",
  meta: null,
  currentJobId: "",
  currentJob: null,
  streamAbortController: null,
  selectedDirectoryHandle: null,
};

const elements = {};

document.addEventListener("DOMContentLoaded", () => {
  cacheElements();
  bindEvents();
  setDefaultDates();
  configureFolderModeSupport();
  restoreSession();
});

function cacheElements() {
  const ids = [
    "authPanel", "appShell", "passwordInput", "loginButton", "authStatus",
    "logoutButton", "sessionChip", "stocksInput", "stockLabel", "startDateInput",
    "endDateInput", "categoryGrid", "languageStrip", "langChinese", "langEnglish",
    "ashareActions", "hkexActions", "startButton", "cancelButton", "downloadButton",
    "jobStatus", "queuePosition", "jobIdLabel", "progressLabel", "progressFill",
    "statTotal", "statDownloaded", "statSkipped", "statFailed", "logBox", "logHint",
    "limitStocks", "limitDays", "marketNote", "folderModeCard"
  ];
  ids.forEach((id) => {
    elements[id] = document.getElementById(id);
  });
  elements.marketButtons = Array.from(document.querySelectorAll(".market-button"));
  elements.deliveryOptions = Array.from(document.querySelectorAll(".mode-option"));
  elements.deliveryInputs = Array.from(document.querySelectorAll("input[name='deliveryMode']"));
}

function bindEvents() {
  elements.loginButton.addEventListener("click", handleLogin);
  elements.logoutButton.addEventListener("click", logout);
  elements.startButton.addEventListener("click", startJob);
  elements.cancelButton.addEventListener("click", cancelJob);
  elements.downloadButton.addEventListener("click", () => {
    if (state.currentJobId) {
      void downloadArtifact(state.currentJobId, "zip");
    }
  });

  elements.marketButtons.forEach((button) => {
    button.addEventListener("click", () => switchMarket(button.dataset.market));
  });

  elements.deliveryOptions.forEach((option) => {
    option.addEventListener("click", () => {
      const radio = option.querySelector("input");
      if (!radio || option.classList.contains("hidden")) {
        return;
      }
      radio.checked = true;
      syncDeliveryCards();
    });
  });

  elements.ashareActions.querySelectorAll(".text-action").forEach((button) => {
    button.addEventListener("click", () => handleCategoryAction(button.dataset.action));
  });
  elements.hkexActions.querySelectorAll(".text-action").forEach((button) => {
    button.addEventListener("click", () => handleCategoryAction(button.dataset.action));
  });
}

function setDefaultDates() {
  const today = new Date();
  const start = new Date(today);
  start.setFullYear(start.getFullYear() - 1);
  elements.endDateInput.value = toDateInputValue(today);
  elements.startDateInput.value = toDateInputValue(start);
}

function restoreSession() {
  if (!state.token) {
    showAuth();
    return;
  }
  void bootstrapAuthenticatedApp();
}

function configureFolderModeSupport() {
  const supported = window.isSecureContext && typeof window.showDirectoryPicker === "function";
  elements.folderModeCard.classList.toggle("hidden", !supported);
  if (!supported) {
    elements.deliveryInputs.forEach((input) => {
      if (input.value === "folder") {
        input.checked = false;
      }
    });
  }
  syncDeliveryCards();
}

function syncDeliveryCards() {
  elements.deliveryOptions.forEach((option) => {
    const input = option.querySelector("input");
    option.classList.toggle("active", Boolean(input && input.checked));
  });
}

async function handleLogin() {
  const password = elements.passwordInput.value.trim();
  if (!password) {
    setAuthStatus("请输入访问密码", true);
    return;
  }

  setAuthStatus("正在验证...", false);
  elements.loginButton.disabled = true;

  try {
    const response = await fetch(`${API_BASE}/api/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password }),
    });
    const payload = await parseJsonResponse(response);
    state.token = payload.token;
    state.tokenExpiresAt = payload.expiresAt;
    localStorage.setItem(TOKEN_KEY, state.token);
    localStorage.setItem(TOKEN_EXP_KEY, state.tokenExpiresAt || "");
    elements.passwordInput.value = "";
    await bootstrapAuthenticatedApp();
  } catch (error) {
    setAuthStatus(error.message || "登录失败", true);
  } finally {
    elements.loginButton.disabled = false;
  }
}

async function bootstrapAuthenticatedApp() {
  try {
    const response = await authedFetch("/api/meta");
    state.meta = await parseJsonResponse(response);
    hydrateMeta();
    setAuthStatus("", false);
    showApp();
  } catch (error) {
    logout();
    setAuthStatus(error.message || "登录状态无效，请重新输入密码", true);
  }
}

function hydrateMeta() {
  elements.limitStocks.textContent = state.meta.limits.maxStocksPerJob;
  elements.limitDays.textContent = state.meta.limits.maxDateRangeDays;
  switchMarket(state.meta.defaults.market || "ashare");
  elements.sessionChip.textContent = `令牌有效至 ${formatDateTime(state.tokenExpiresAt)}`;
}

function showAuth() {
  elements.authPanel.classList.remove("hidden");
  elements.appShell.classList.add("hidden");
}

function showApp() {
  elements.authPanel.classList.add("hidden");
  elements.appShell.classList.remove("hidden");
}

function setAuthStatus(message, isError) {
  elements.authStatus.textContent = message;
  elements.authStatus.style.color = isError ? "var(--crimson)" : "var(--muted)";
}

function logout() {
  state.token = "";
  state.tokenExpiresAt = "";
  state.meta = null;
  state.selectedDirectoryHandle = null;
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(TOKEN_EXP_KEY);
  stopStreaming();
  resetJobUi();
  showAuth();
}

function switchMarket(market) {
  state.market = market;
  elements.marketButtons.forEach((button) => {
    button.classList.toggle("active", button.dataset.market === market);
  });

  const isHKEX = market === "hkex";
  elements.stockLabel.textContent = isHKEX
    ? "股票代码（4位港股代码，多个用空格或逗号分隔）"
    : "股票代码（多个用空格或逗号分隔）";
  elements.stocksInput.placeholder = isHKEX ? "例如: 0700 0005" : "例如: 000001 600036";
  elements.languageStrip.classList.toggle("hidden", !isHKEX);
  elements.ashareActions.classList.toggle("hidden", isHKEX);
  elements.hkexActions.classList.toggle("hidden", !isHKEX);
  elements.marketNote.textContent = isHKEX
    ? state.meta.notes.hkexEmptyCategories
    : state.meta.notes.ashareEmptyCategories;
  renderCategoryGrid();
}

function renderCategoryGrid() {
  const categories = state.market === "hkex"
    ? state.meta.categories.hkex
    : state.meta.categories.ashare;

  elements.categoryGrid.innerHTML = "";
  categories.forEach((category) => {
    const label = document.createElement("label");
    label.className = "category-chip";
    label.innerHTML = `<input type="checkbox" value="${escapeHtml(category)}"><span>${escapeHtml(category)}</span>`;
    const input = label.querySelector("input");
    input.addEventListener("change", () => {
      label.classList.toggle("checked", input.checked);
    });
    elements.categoryGrid.appendChild(label);
  });
}

function handleCategoryAction(action) {
  const inputs = Array.from(elements.categoryGrid.querySelectorAll("input"));
  const checkedSet = new Set();
  const presets = state.market === "hkex"
    ? state.meta.presets.hkexResultsOnly
    : state.meta.presets.asharePeriodic;

  if (action === "all") {
    inputs.forEach((input) => checkedSet.add(input.value));
  } else if (action === "periodic" || action === "results") {
    presets.forEach((name) => checkedSet.add(name));
  }

  inputs.forEach((input) => {
    input.checked = checkedSet.has(input.value);
    input.closest(".category-chip").classList.toggle("checked", input.checked);
  });
}

async function startJob() {
  if (!state.meta) {
    return;
  }

  const stocks = elements.stocksInput.value
    .replace(/[,，;；\s]+/g, " ")
    .trim()
    .split(" ")
    .filter(Boolean);

  const startDate = elements.startDateInput.value;
  const endDate = elements.endDateInput.value;
  const categories = Array.from(elements.categoryGrid.querySelectorAll("input:checked")).map((input) => input.value);
  const languages = state.market === "hkex"
    ? [
        elements.langChinese.checked ? "中文" : null,
        elements.langEnglish.checked ? "英文" : null,
      ].filter(Boolean)
    : [];
  const deliveryMode = getSelectedDeliveryMode();

  if (!stocks.length) {
    appendLog("请输入股票代码");
    return;
  }
  if (!startDate || !endDate) {
    appendLog("请选择起止日期");
    return;
  }
  if (state.market === "hkex" && languages.length === 0) {
    appendLog("港股任务至少选择一种语言");
    return;
  }

  state.selectedDirectoryHandle = null;
  if (deliveryMode === "folder") {
    try {
      state.selectedDirectoryHandle = await window.showDirectoryPicker({ mode: "readwrite" });
    } catch (error) {
      appendLog("未选择本地文件夹，任务未启动");
      return;
    }
  }

  resetJobUi();
  elements.startButton.disabled = true;
  elements.cancelButton.disabled = false;
  elements.logHint.textContent = "正在创建任务";
  appendLog(`正在创建任务 [${state.market === "hkex" ? "港股" : "A股"}]...`);

  try {
    const response = await authedFetch("/api/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        market: state.market,
        stocks,
        startDate,
        endDate,
        categories,
        languages,
        deliveryMode,
      }),
    });
    const payload = await parseJsonResponse(response);
    state.currentJobId = payload.job.jobId;
    state.currentJob = payload.job;
    updateJobSnapshot(payload.job);
    await streamJobEvents(payload.job.jobId);
  } catch (error) {
    appendLog(error.message || "创建任务失败");
    elements.startButton.disabled = false;
    elements.cancelButton.disabled = true;
    elements.logHint.textContent = "任务未启动";
  }
}

async function cancelJob() {
  if (!state.currentJobId) {
    return;
  }
  try {
    const response = await authedFetch(`/api/jobs/${state.currentJobId}/cancel`, {
      method: "POST",
    });
    const payload = await parseJsonResponse(response);
    updateJobSnapshot(payload.job);
    appendLog("已发送取消请求");
  } catch (error) {
    appendLog(error.message || "取消任务失败");
  }
}

async function streamJobEvents(jobId) {
  stopStreaming();
  const controller = new AbortController();
  state.streamAbortController = controller;

  const response = await authedFetch(`/api/jobs/${jobId}/events`, {
    signal: controller.signal,
  });

  if (!response.body) {
    throw new Error("浏览器不支持流式响应");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) {
      break;
    }
    buffer += decoder.decode(value, { stream: true });

    let boundary = buffer.indexOf("\n\n");
    while (boundary !== -1) {
      const rawEvent = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      const dataLines = rawEvent
        .split("\n")
        .filter((line) => line.startsWith("data:"))
        .map((line) => line.slice(5).trimStart());
      if (dataLines.length) {
        handleJobEvent(JSON.parse(dataLines.join("\n")));
      }
      boundary = buffer.indexOf("\n\n");
    }
  }
}

function handleJobEvent(event) {
  if (event.type === "snapshot") {
    updateJobSnapshot(event.job);
    elements.logBox.textContent = "";
    (event.logs || []).forEach((line) => appendLog(line));
    return;
  }

  if (event.type === "log") {
    appendLog(event.text);
    return;
  }

  if (event.type === "progress") {
    updateProgress(event.current, event.total);
    return;
  }

  if (event.type === "stats") {
    updateStats(event.stats);
    return;
  }

  if (event.type === "state") {
    updateJobSnapshot(event.job);
    return;
  }

  if (event.type === "done") {
    updateJobSnapshot(event.job);
    elements.startButton.disabled = false;
    elements.cancelButton.disabled = true;
    elements.logHint.textContent = event.job.status === "completed" ? "任务已完成" : "任务已结束";
    stopStreaming();
    if (event.job.status === "completed") {
      elements.downloadButton.disabled = false;
      void finalizeCompletedJob(event.job);
    }
  }
}

async function finalizeCompletedJob(job) {
  const mode = getSelectedDeliveryMode();
  if (mode === "folder" && state.selectedDirectoryHandle) {
    try {
      await downloadArtifact(job.jobId, "folder");
      appendLog("已将文件写入你选择的本地文件夹");
    } catch (error) {
      appendLog(`本地文件夹写入失败，已保留 ZIP 下载按钮: ${error.message}`);
    }
  } else {
    appendLog("任务已完成，可点击“下载结果 ZIP”获取文件");
  }
}

function updateJobSnapshot(job) {
  state.currentJob = job;
  state.currentJobId = job.jobId;
  elements.jobStatus.textContent = translateStatus(job.status);
  elements.queuePosition.textContent = job.queuePosition || "-";
  elements.jobIdLabel.textContent = job.jobId || "-";
  updateProgress(job.progress.current, job.progress.total);
  updateStats(job.stats);
  elements.downloadButton.disabled = !job.artifactReady;
}

function updateProgress(current, total) {
  const safeCurrent = Number(current || 0);
  const safeTotal = Number(total || 0);
  elements.progressLabel.textContent = `${safeCurrent} / ${safeTotal}`;
  const ratio = safeTotal > 0 ? Math.min(100, Math.round((safeCurrent / safeTotal) * 100)) : 0;
  elements.progressFill.style.width = `${ratio}%`;
}

function updateStats(stats) {
  const safe = stats || {};
  elements.statTotal.textContent = safe.total || 0;
  elements.statDownloaded.textContent = safe.downloaded || 0;
  elements.statSkipped.textContent = safe.skipped || 0;
  elements.statFailed.textContent = safe.failed || 0;
}

async function downloadArtifact(jobId, mode) {
  const response = await authedFetch(`/api/jobs/${jobId}/artifact`);
  const blob = await response.blob();

  if (mode === "folder" && state.selectedDirectoryHandle) {
    await extractZipToDirectory(blob, state.selectedDirectoryHandle);
    return;
  }

  triggerBlobDownload(blob, `exchange-report-${jobId}.zip`);
}

async function extractZipToDirectory(blob, directoryHandle) {
  if (!window.JSZip) {
    throw new Error("JSZip 未加载");
  }

  const zip = await window.JSZip.loadAsync(blob);
  const entries = Object.values(zip.files);
  for (const entry of entries) {
    const parts = entry.name.split("/").filter(Boolean);
    if (!parts.length) {
      continue;
    }
    if (entry.dir) {
      await ensureDirectory(directoryHandle, parts);
      continue;
    }
    const filename = parts.pop();
    const parent = await ensureDirectory(directoryHandle, parts);
    const fileHandle = await parent.getFileHandle(filename, { create: true });
    const writable = await fileHandle.createWritable();
    const content = await entry.async("uint8array");
    await writable.write(content);
    await writable.close();
  }
}

async function ensureDirectory(rootHandle, parts) {
  let current = rootHandle;
  for (const part of parts) {
    current = await current.getDirectoryHandle(part, { create: true });
  }
  return current;
}

function triggerBlobDownload(blob, filename) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

function appendLog(message) {
  elements.logBox.textContent += `${message}\n`;
  elements.logBox.scrollTop = elements.logBox.scrollHeight;
}

function resetJobUi() {
  state.currentJob = null;
  state.currentJobId = "";
  updateProgress(0, 0);
  updateStats({ total: 0, downloaded: 0, skipped: 0, failed: 0 });
  elements.jobStatus.textContent = "空闲";
  elements.queuePosition.textContent = "-";
  elements.jobIdLabel.textContent = "-";
  elements.downloadButton.disabled = true;
  elements.logBox.textContent = "";
  elements.logHint.textContent = "等待任务";
}

function stopStreaming() {
  if (state.streamAbortController) {
    state.streamAbortController.abort();
    state.streamAbortController = null;
  }
}

async function authedFetch(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (state.token) {
    headers.set("Authorization", `Bearer ${state.token}`);
  }
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
  });
  if (response.status === 401) {
    logout();
    throw new Error("登录状态已失效，请重新输入密码");
  }
  return response;
}

async function parseJsonResponse(response) {
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.error || "请求失败");
  }
  return payload;
}

function getSelectedDeliveryMode() {
  const selected = elements.deliveryInputs.find((input) => input.checked);
  return selected ? selected.value : "zip";
}

function toDateInputValue(date) {
  return date.toISOString().split("T")[0];
}

function formatDateTime(isoString) {
  if (!isoString) {
    return "-";
  }
  const date = new Date(isoString);
  if (Number.isNaN(date.getTime())) {
    return isoString;
  }
  return date.toLocaleString("zh-CN", { hour12: false });
}

function translateStatus(status) {
  const map = {
    queued: "排队中",
    running: "执行中",
    completed: "已完成",
    failed: "失败",
    cancelled: "已取消",
    expired: "已过期",
  };
  return map[status] || status || "空闲";
}

function escapeHtml(value) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

