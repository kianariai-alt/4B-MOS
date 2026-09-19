"use strict";

const API_BASE = "/api/v1";
const REFRESH_INTERVAL_MS = 30_000;

const roleLabels = Object.freeze({
  admin: "مدیر سامانه",
  physician: "پزشک",
  nurse: "پرستار",
  operator: "پذیرش",
  viewer: "مشاهده‌گر",
});

const priorityLabels = Object.freeze({
  normal: "عادی",
  attention: "نیازمند توجه",
  urgent: "فوری",
});

const actionLabels = Object.freeze({
  check_in: "پذیرش بیمار",
  mark_ready: "آمادهٔ درمان",
  start_treatment: "شروع درمان",
  complete: "تکمیل درمان",
  discharge: "ترخیص",
  cancel: "لغو جلسه",
});

const columns = Object.freeze([
  { key: "scheduled", label: "برنامه‌ریزی‌شده" },
  { key: "checked_in", label: "پذیرش‌شده" },
  { key: "ready", label: "آماده" },
  { key: "in_treatment", label: "در حال درمان" },
  { key: "awaiting_discharge", label: "در انتظار ترخیص" },
]);

const elements = {
  loginView: document.querySelector("#login-view"),
  consoleView: document.querySelector("#console-view"),
  loginForm: document.querySelector("#login-form"),
  username: document.querySelector("#username"),
  password: document.querySelector("#password"),
  loginButton: document.querySelector("#login-button"),
  loginMessage: document.querySelector("#login-message"),
  identityArea: document.querySelector("#identity-area"),
  userDisplayName: document.querySelector("#user-display-name"),
  userRole: document.querySelector("#user-role"),
  logoutButton: document.querySelector("#logout-button"),
  refreshButton: document.querySelector("#refresh-button"),
  generatedAt: document.querySelector("#generated-at"),
  connectionState: document.querySelector("#connection-state"),
  consoleMessage: document.querySelector("#console-message"),
  flowBoard: document.querySelector("#flow-board"),
  metricActive: document.querySelector("#metric-active"),
  metricCheckedIn: document.querySelector("#metric-checked-in"),
  metricReady: document.querySelector("#metric-ready"),
  metricTreatment: document.querySelector("#metric-treatment"),
  metricAttention: document.querySelector("#metric-attention"),
  actionDialog: document.querySelector("#action-dialog"),
  dialogCopy: document.querySelector("#dialog-copy"),
  dialogConfirm: document.querySelector("#dialog-confirm"),
};

let accessToken = null;
let currentUser = null;
let currentFlow = null;
let refreshTimer = null;
let requestInProgress = false;
let actionInProgress = false;

class ApiError extends Error {
  constructor(status, detail) {
    super(detail || "درخواست با خطا روبه‌رو شد.");
    this.name = "ApiError";
    this.status = status;
  }
}

async function apiRequest(path, options = {}) {
  const headers = new Headers(options.headers || {});
  headers.set("Accept", "application/json");

  if (accessToken) {
    headers.set("Authorization", `Bearer ${accessToken}`);
  }

  if (options.body) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
    cache: "no-store",
    credentials: "omit",
  });

  let payload = null;
  const contentType = response.headers.get("content-type") || "";

  if (contentType.includes("application/json")) {
    payload = await response.json();
  }

  if (!response.ok) {
    throw new ApiError(response.status, payload && payload.detail);
  }

  return payload;
}

function toPersianNumber(value) {
  return Number(value || 0).toLocaleString("fa-IR");
}

function formatDateTime(value) {
  if (!value) {
    return "—";
  }

  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return "—";
  }

  return new Intl.DateTimeFormat("fa-IR", {
    dateStyle: "short",
    timeStyle: "short",
  }).format(date);
}

function formatMinutes(value) {
  if (value === null || value === undefined) {
    return "—";
  }

  return `${toPersianNumber(value)} دقیقه`;
}

function setConnectionState(connected) {
  elements.connectionState.textContent = connected ? "متصل" : "ارتباط قطع است";
  elements.connectionState.classList.toggle("is-offline", !connected);
}

function showConsoleMessage(message, isError = false) {
  elements.consoleMessage.textContent = message;
  elements.consoleMessage.classList.toggle("is-error", isError);
  elements.consoleMessage.hidden = !message;
}

function setLoginBusy(isBusy) {
  elements.loginButton.disabled = isBusy;
  elements.username.disabled = isBusy;
  elements.password.disabled = isBusy;
  elements.loginButton.textContent = isBusy ? "در حال بررسی…" : "ورود به کنسول";
}

function setRefreshBusy(isBusy) {
  requestInProgress = isBusy;
  elements.refreshButton.disabled = isBusy;
  elements.refreshButton.textContent = isBusy ? "در حال دریافت…" : "تازه‌سازی";
}

function showLogin() {
  stopAutoRefresh();
  accessToken = null;
  currentUser = null;
  currentFlow = null;
  elements.consoleView.hidden = true;
  elements.identityArea.hidden = true;
  elements.loginView.hidden = false;
  elements.loginForm.reset();
  elements.loginMessage.textContent = "";
  elements.username.focus();
}

function showConsole() {
  elements.loginView.hidden = true;
  elements.consoleView.hidden = false;
  elements.identityArea.hidden = false;
  elements.userDisplayName.textContent = currentUser.display_name;
  elements.userRole.textContent = roleLabels[currentUser.role] || currentUser.role;
  startAutoRefresh();
}

function createTextElement(tagName, className, text) {
  const element = document.createElement(tagName);
  element.className = className;
  element.textContent = text;
  return element;
}

function createMeta(label, value) {
  const wrapper = document.createElement("div");
  const term = createTextElement("dt", "", label);
  const description = createTextElement("dd", "", value || "—");
  wrapper.append(term, description);
  return wrapper;
}

function createSessionCard(item) {
  const card = document.createElement("article");
  card.className = "session-card";
  card.dataset.priority = item.priority_level;

  const top = document.createElement("div");
  top.className = "session-card-top";

  const identity = document.createElement("div");
  identity.append(
    createTextElement("h3", "patient-name", item.patient_name),
    createTextElement("span", "patient-code", item.patient_code),
  );

  const priority = createTextElement(
    "span",
    "priority-badge",
    priorityLabels[item.priority_level] || item.priority_level,
  );
  priority.dataset.priority = item.priority_level;
  top.append(identity, priority);

  const metadata = document.createElement("dl");
  metadata.className = "session-meta";
  metadata.append(
    createMeta("درمان", item.treatment_type),
    createMeta("جلسه", toPersianNumber(item.session_number)),
    createMeta("زمان برنامه", formatDateTime(item.scheduled_at)),
    createMeta("زمان انتظار", formatMinutes(
      item.waiting_minutes ?? item.ready_wait_minutes ?? item.discharge_wait_minutes,
    )),
  );

  card.append(top, metadata);

  if (item.alerts.length) {
    const alertList = document.createElement("ul");
    alertList.className = "alert-list";

    for (const alert of item.alerts) {
      const alertItem = createTextElement("li", "", alert.message);
      alertItem.dataset.severity = alert.severity;
      alertList.append(alertItem);
    }

    card.append(alertList);
  }

  if (item.allowed_actions.length) {
    const actions = document.createElement("div");
    actions.className = "session-actions";

    for (const action of item.allowed_actions) {
      const button = createTextElement(
        "button",
        action.is_primary ? "button button-primary" : "button button-quiet",
        actionLabels[action.code] || action.label,
      );
      button.type = "button";
      button.dataset.sessionId = item.session_id;
      button.dataset.actionCode = action.code;
      button.dataset.targetStatus = action.target_status;
      actions.append(button);
    }

    card.append(actions);
  }

  return card;
}

function renderFlow(flow) {
  currentFlow = flow;
  elements.metricActive.textContent = toPersianNumber(flow.active_count);
  elements.metricCheckedIn.textContent = toPersianNumber(flow.checked_in_count);
  elements.metricReady.textContent = toPersianNumber(flow.ready_count);
  elements.metricTreatment.textContent = toPersianNumber(flow.in_treatment_count);
  elements.metricAttention.textContent = toPersianNumber(
    flow.attention_count + flow.urgent_count,
  );

  elements.generatedAt.textContent = (
    `آخرین به‌روزرسانی: ${formatDateTime(flow.generated_at)} · ${flow.clinic_timezone}`
  );

  const board = document.createDocumentFragment();

  for (const column of columns) {
    const items = flow[column.key] || [];
    const section = document.createElement("section");
    section.className = "flow-column";

    const header = document.createElement("div");
    header.className = "flow-column-header";
    header.append(
      createTextElement("h2", "", column.label),
      createTextElement("span", "count-pill", toPersianNumber(items.length)),
    );

    const list = document.createElement("div");
    list.className = "flow-list";

    if (items.length) {
      for (const item of items) {
        list.append(createSessionCard(item));
      }
    } else {
      list.append(createTextElement("p", "empty-state", "موردی در این مرحله نیست."));
    }

    section.append(header, list);
    board.append(section);
  }

  elements.flowBoard.replaceChildren(board);
}

function allFlowItems() {
  if (!currentFlow) {
    return [];
  }

  return columns.flatMap((column) => currentFlow[column.key] || []);
}

async function loadFlow({ quiet = false } = {}) {
  if (!accessToken || requestInProgress || document.hidden) {
    return;
  }

  setRefreshBusy(true);

  if (!quiet) {
    showConsoleMessage("");
  }

  try {
    const flow = await apiRequest("/dashboard/live-flow");
    renderFlow(flow);
    setConnectionState(true);
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      showLogin();
      elements.loginMessage.textContent = "نشست شما پایان یافته است؛ دوباره وارد شوید.";
      return;
    }

    if (error instanceof ApiError && error.status === 403) {
      showConsoleMessage(
        "نقش کاربری شما اجازهٔ مشاهدهٔ جریان عملیاتی کلینیک را ندارد.",
        true,
      );
    } else {
      showConsoleMessage("دریافت جریان کلینیک ممکن نشد؛ دوباره تلاش کنید.", true);
    }

    setConnectionState(false);
  } finally {
    setRefreshBusy(false);
  }
}

function requestActionConfirmation(item, action) {
  return new Promise((resolve) => {
    const actionLabel = actionLabels[action.code] || action.label;
    elements.dialogCopy.textContent = (
      `آیا «${actionLabel}» برای ${item.patient_name} ثبت شود؟ `
      + "این اقدام در backend بررسی و ثبت خواهد شد."
    );
    elements.actionDialog.returnValue = "";
    elements.actionDialog.addEventListener(
      "close",
      () => resolve(elements.actionDialog.returnValue === "confirm"),
      { once: true },
    );
    elements.actionDialog.showModal();
  });
}

async function performAction(item, action) {
  const confirmed = await requestActionConfirmation(item, action);

  if (!confirmed) {
    return;
  }

  actionInProgress = true;
  elements.flowBoard.setAttribute("aria-busy", "true");
  elements.dialogConfirm.disabled = true;
  showConsoleMessage("در حال ثبت اقدام…");

  try {
    await apiRequest(`/treatment-sessions/${encodeURIComponent(item.session_id)}/workflow`, {
      method: "PATCH",
      body: JSON.stringify({ operational_status: action.target_status }),
    });
    showConsoleMessage("اقدام با موفقیت ثبت شد.");
    await loadFlow({ quiet: true });
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      showLogin();
      elements.loginMessage.textContent = "نشست شما پایان یافته است؛ دوباره وارد شوید.";
      return;
    }

    const detail = error instanceof ApiError && error.message
      ? error.message
      : "ثبت اقدام ممکن نشد.";
    showConsoleMessage(detail, true);
  } finally {
    actionInProgress = false;
    elements.flowBoard.removeAttribute("aria-busy");
    elements.dialogConfirm.disabled = false;
  }
}

async function handleLogin(event) {
  event.preventDefault();
  elements.loginMessage.textContent = "";

  if (!elements.loginForm.reportValidity()) {
    return;
  }

  setLoginBusy(true);

  try {
    const tokenResponse = await apiRequest("/auth/login", {
      method: "POST",
      body: JSON.stringify({
        username: elements.username.value.trim(),
        password: elements.password.value,
      }),
    });

    accessToken = tokenResponse.access_token;
    elements.password.value = "";
    currentUser = await apiRequest("/auth/me");
    showConsole();
    await loadFlow();
  } catch (error) {
    accessToken = null;
    currentUser = null;

    if (error instanceof ApiError && error.status === 503) {
      elements.loginMessage.textContent = (
        "ورود موقتاً در دسترس نیست؛ چند لحظه دیگر دوباره تلاش کنید."
      );
    } else {
      elements.loginMessage.textContent = "نام کاربری یا گذرواژه صحیح نیست.";
    }
  } finally {
    setLoginBusy(false);
  }
}

function startAutoRefresh() {
  stopAutoRefresh();
  refreshTimer = window.setInterval(() => loadFlow({ quiet: true }), REFRESH_INTERVAL_MS);
}

function stopAutoRefresh() {
  if (refreshTimer !== null) {
    window.clearInterval(refreshTimer);
    refreshTimer = null;
  }
}

elements.loginForm.addEventListener("submit", handleLogin);
elements.logoutButton.addEventListener("click", showLogin);
elements.refreshButton.addEventListener("click", () => loadFlow());

elements.flowBoard.addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-session-id]");

  if (!button || requestInProgress || actionInProgress) {
    return;
  }

  const item = allFlowItems().find(
    (candidate) => candidate.session_id === button.dataset.sessionId,
  );

  if (!item) {
    showConsoleMessage("این جلسه دیگر در نمای فعلی وجود ندارد؛ صفحه را تازه کنید.", true);
    return;
  }

  const action = item.allowed_actions.find(
    (candidate) => (
      candidate.code === button.dataset.actionCode
      && candidate.target_status === button.dataset.targetStatus
    ),
  );

  if (!action) {
    showConsoleMessage("این اقدام دیگر مجاز نیست؛ صفحه را تازه کنید.", true);
    return;
  }

  await performAction(item, action);
});

document.addEventListener("visibilitychange", () => {
  if (!document.hidden && accessToken) {
    loadFlow({ quiet: true });
  }
});

window.addEventListener("online", () => {
  setConnectionState(true);
  loadFlow({ quiet: true });
});

window.addEventListener("offline", () => setConnectionState(false));

elements.username.focus();
