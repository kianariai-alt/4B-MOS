"use strict";

const API_BASE = "/api/v1";
const REFRESH_INTERVAL_MS = 30_000;
const MAX_SELECTED_FACTS = 20;
const COPILOT_READ_ROLES = new Set(["admin", "physician"]);
const EVIDENCE_READ_ROLES = new Set(["admin", "physician", "nurse"]);
const SAFETY_READ_ROLES = new Set(["admin", "physician", "nurse"]);
const SAFETY_EVALUATE_ROLES = new Set(["admin", "physician"]);

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

const evidenceGradeLabels = Object.freeze({
  high: "بالا",
  moderate: "متوسط",
  low: "پایین",
  very_low: "بسیار پایین",
  consensus: "اجماع",
  ungraded: "درجه‌بندی‌نشده",
});

const lateralityLabels = Object.freeze({
  left: "چپ",
  right: "راست",
  bilateral: "دوطرفه",
  midline: "خط میانی",
  not_applicable: "نامرتبط",
  unknown: "نامشخص",
});

const interpretationLabels = Object.freeze({
  normal: "طبیعی",
  low: "پایین",
  high: "بالا",
  critical_low: "بحرانی پایین",
  critical_high: "بحرانی بالا",
  abnormal: "غیرطبیعی",
  indeterminate: "نامعین",
});

const safetySeverityLabels = Object.freeze({
  info: "اطلاعاتی",
  warning: "هشدار",
  high: "بالا",
  critical: "بحرانی",
});

const safetyRequiredActionLabels = Object.freeze({
  document: "ثبت و مستندسازی",
  review_before_proceeding: "مرور پیش از ادامه",
  urgent_clinical_review: "مرور فوری بالینی",
});

const safetyOutcomeLabels = Object.freeze({
  alerts_present: "یافته ثبت شده است",
  no_alerts: "یافته‌ای ثبت نشده است (مجوز بالینی نیست)",
  no_active_rules: "قاعدهٔ فعال وجود ندارد (مجوز بالینی نیست)",
});

const roadmapStatusLabels = Object.freeze({
  options_available: "گزینه‌های قابل بررسی موجود است",
  insufficient_local_data: "دادهٔ محلی کافی نیست",
  blocked_pending_safety_evaluation: "در انتظار ارزیابی ایمنی فعلی",
  blocked_stale_safety_evaluation: "ارزیابی ایمنی با زمینهٔ فعلی منطبق نیست",
  blocked_pending_safety_review: "در انتظار تکمیل مرور یافته‌های ایمنی",
});

const roadmapSafetyLabels = Object.freeze({
  current: "فعلی",
  missing: "ثبت نشده",
  stale: "قدیمی / نامنطبق",
  pending_review: "نیازمند مرور",
});

const roadmapWindowLabels = Object.freeze({
  early_28_to_70_days: "پیگیری زودهنگام، ۲۸ تا ۷۰ روز",
  intermediate_71_to_180_days: "پیگیری میان‌مدت، ۷۱ تا ۱۸۰ روز",
  long_term_181_to_365_days: "پیگیری بلندمدت، ۱۸۱ تا ۳۶۵ روز",
});

const roadmapVolumeLabels = Object.freeze({
  insufficient: "ناکافی",
  very_limited: "بسیار محدود",
  limited: "محدود",
  moderate: "متوسط",
  substantial: "حجم بالا",
});

const safetyReviewStatusLabels = Object.freeze({
  unreviewed: "مرور نشده",
  acknowledged: "مشاهده و ثبت شد",
  escalated: "ارجاع شد",
  assessed: "ارزیابی پزشک ثبت شد",
});

const safetyReviewActionLabels = Object.freeze({
  acknowledged: "ثبت مشاهده",
  escalated: "ارجاع برای بررسی",
  assessed: "ثبت ارزیابی پزشک",
});

const safetyDispositionLabels = Object.freeze({
  requires_action: "نیازمند اقدام بالینی",
  not_applicable: "نامرتبط با زمینهٔ فعلی",
  action_documented: "اقدام جداگانه مستند شده",
  monitoring: "پایش مستند",
});

const safetyReasonLabels = Object.freeze({
  clinical_context: "زمینهٔ بالینی",
  measurement_quality: "کیفیت اندازه‌گیری",
  rule_scope: "دامنهٔ قاعده",
  patient_specific_factor: "عامل مختص بیمار",
  action_taken: "اقدام انجام‌شده",
  other: "سایر",
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
  flowTab: document.querySelector("#flow-tab"),
  copilotTab: document.querySelector("#copilot-tab"),
  evidenceTab: document.querySelector("#evidence-tab"),
  safetyTab: document.querySelector("#safety-tab"),
  flowWorkspace: document.querySelector("#flow-workspace"),
  copilotWorkspace: document.querySelector("#copilot-workspace"),
  evidenceWorkspace: document.querySelector("#evidence-workspace"),
  safetyWorkspace: document.querySelector("#safety-workspace"),
  flowBoard: document.querySelector("#flow-board"),
  metricActive: document.querySelector("#metric-active"),
  metricCheckedIn: document.querySelector("#metric-checked-in"),
  metricReady: document.querySelector("#metric-ready"),
  metricTreatment: document.querySelector("#metric-treatment"),
  metricAttention: document.querySelector("#metric-attention"),
  copilotVisitForm: document.querySelector("#copilot-visit-form"),
  copilotVisitId: document.querySelector("#copilot-visit-id"),
  loadCopilotButton: document.querySelector("#load-copilot-button"),
  copilotMessage: document.querySelector("#copilot-message"),
  copilotContent: document.querySelector("#copilot-content"),
  copilotSummary: document.querySelector("#copilot-summary"),
  copilotEscalations: document.querySelector("#copilot-escalations"),
  copilotRoadmap: document.querySelector("#copilot-roadmap"),
  copilotOutcomes: document.querySelector("#copilot-outcomes"),
  copilotEvidence: document.querySelector("#copilot-evidence"),
  evidenceVisitForm: document.querySelector("#evidence-visit-form"),
  evidenceVisitId: document.querySelector("#evidence-visit-id"),
  activeVisits: document.querySelector("#active-visits"),
  loadEvidenceButton: document.querySelector("#load-evidence-button"),
  evidenceMessage: document.querySelector("#evidence-message"),
  evidenceContent: document.querySelector("#evidence-content"),
  contextHash: document.querySelector("#context-hash"),
  clinicalContext: document.querySelector("#clinical-context"),
  evidenceComposer: document.querySelector("#evidence-composer"),
  knowledgeSearchForm: document.querySelector("#knowledge-search-form"),
  knowledgeSearch: document.querySelector("#knowledge-search"),
  knowledgeSearchButton: document.querySelector("#knowledge-search-button"),
  knowledgeResetButton: document.querySelector("#knowledge-reset-button"),
  knowledgeFacts: document.querySelector("#knowledge-facts"),
  selectedFactCount: document.querySelector("#selected-fact-count"),
  selectedFacts: document.querySelector("#selected-facts"),
  evidenceBriefForm: document.querySelector("#evidence-brief-form"),
  clinicalQuestion: document.querySelector("#clinical-question"),
  evidenceAcknowledgement: document.querySelector("#evidence-acknowledgement"),
  createBriefButton: document.querySelector("#create-brief-button"),
  evidenceBriefs: document.querySelector("#evidence-briefs"),
  safetyVisitForm: document.querySelector("#safety-visit-form"),
  safetyVisitId: document.querySelector("#safety-visit-id"),
  loadSafetyButton: document.querySelector("#load-safety-button"),
  safetyMessage: document.querySelector("#safety-message"),
  safetyContent: document.querySelector("#safety-content"),
  safetyContextHash: document.querySelector("#safety-context-hash"),
  safetySummary: document.querySelector("#safety-summary"),
  runSafetyEvaluationButton: document.querySelector("#run-safety-evaluation-button"),
  safetyFindings: document.querySelector("#safety-findings"),
  loadSafetyEscalationsButton: document.querySelector(
    "#load-safety-escalations-button",
  ),
  safetyEscalationsMessage: document.querySelector(
    "#safety-escalations-message",
  ),
  safetyEscalations: document.querySelector("#safety-escalations"),
  actionDialog: document.querySelector("#action-dialog"),
  dialogKicker: document.querySelector("#dialog-kicker"),
  dialogTitle: document.querySelector("#dialog-title"),
  dialogCopy: document.querySelector("#dialog-copy"),
  dialogConfirm: document.querySelector("#dialog-confirm"),
};

let accessToken = null;
let currentUser = null;
let currentFlow = null;
let refreshTimer = null;
let requestInProgress = false;
let actionInProgress = false;
let copilotRequestInProgress = false;
let evidenceRequestInProgress = false;
let safetyRequestInProgress = false;
let safetyEscalationRequestInProgress = false;
let activeWorkspace = "flow";
let currentCopilotVisitId = null;
let currentCopilotSnapshot = null;
let currentTreatmentRoadmap = null;
let currentEvidenceVisitId = null;
let currentClinicalContext = null;
let currentKnowledgeFacts = [];
let currentEvidenceBriefs = [];
let currentSafetyVisitId = null;
let currentSafetyInbox = null;
let currentSafetyEscalations = null;
let sessionGeneration = 0;
const selectedFacts = new Map();

class ApiError extends Error {
  constructor(status, detail) {
    super(typeof detail === "string" ? detail : "درخواست با خطا روبه‌رو شد.");
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

function displayValue(value) {
  if (value === null || value === undefined || value === "") {
    return "—";
  }

  if (Array.isArray(value)) {
    return value.length ? value.join("، ") : "—";
  }

  return String(value);
}

function canReadCopilot() {
  return Boolean(currentUser && COPILOT_READ_ROLES.has(currentUser.role));
}

function canReadEvidence() {
  return Boolean(currentUser && EVIDENCE_READ_ROLES.has(currentUser.role));
}

function canCreateEvidence() {
  return Boolean(currentUser && currentUser.role === "physician");
}

function canReadSafety() {
  return Boolean(currentUser && SAFETY_READ_ROLES.has(currentUser.role));
}

function canRunSafetyEvaluation() {
  return Boolean(currentUser && SAFETY_EVALUATE_ROLES.has(currentUser.role));
}

function canRecordSafetyReview() {
  return Boolean(currentUser && ["physician", "nurse"].includes(currentUser.role));
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

function showCopilotMessage(message, isError = false) {
  elements.copilotMessage.textContent = message;
  elements.copilotMessage.classList.toggle("is-error", isError);
  elements.copilotMessage.hidden = !message;
}

function showEvidenceMessage(message, isError = false) {
  elements.evidenceMessage.textContent = message;
  elements.evidenceMessage.classList.toggle("is-error", isError);
  elements.evidenceMessage.hidden = !message;
}

function showSafetyMessage(message, isError = false) {
  elements.safetyMessage.textContent = message;
  elements.safetyMessage.classList.toggle("is-error", isError);
  elements.safetyMessage.hidden = !message;
}

function showSafetyEscalationsMessage(message, isError = false) {
  elements.safetyEscalationsMessage.textContent = message;
  elements.safetyEscalationsMessage.classList.toggle("is-error", isError);
  elements.safetyEscalationsMessage.hidden = !message;
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

function setCopilotBusy(isBusy) {
  copilotRequestInProgress = isBusy;
  elements.loadCopilotButton.disabled = isBusy;
  elements.loadCopilotButton.textContent = isBusy
    ? "در حال دریافت…"
    : "بارگذاری snapshot پزشک‌یار";
}

function setEvidenceBusy(isBusy, label = "در حال بارگذاری…") {
  evidenceRequestInProgress = isBusy;
  elements.loadEvidenceButton.disabled = isBusy;
  elements.knowledgeSearchButton.disabled = isBusy;
  elements.knowledgeResetButton.disabled = isBusy;
  elements.createBriefButton.disabled = isBusy;
  elements.loadEvidenceButton.textContent = isBusy
    ? label
    : "بارگذاری زمینه و خلاصه‌ها";
}

function setSafetyBusy(isBusy, label = "در حال بارگذاری…") {
  safetyRequestInProgress = isBusy;
  elements.loadSafetyButton.disabled = isBusy;
  elements.runSafetyEvaluationButton.disabled = isBusy;
  elements.loadSafetyButton.textContent = isBusy
    ? label
    : "بارگذاری صندوق ایمنی";
  for (const field of elements.safetyFindings.querySelectorAll(
    "button, select, textarea, input",
  )) {
    field.disabled = isBusy;
  }
}

function setSafetyEscalationsBusy(isBusy) {
  safetyEscalationRequestInProgress = isBusy;
  elements.loadSafetyEscalationsButton.disabled = isBusy;
  elements.loadSafetyEscalationsButton.textContent = isBusy
    ? "در حال دریافت…"
    : "تازه‌سازی صف";
}

function resetCopilotState() {
  currentCopilotVisitId = null;
  currentCopilotSnapshot = null;
  currentTreatmentRoadmap = null;
  elements.copilotVisitForm.reset();
  elements.copilotContent.hidden = true;
  elements.copilotSummary.replaceChildren();
  elements.copilotEscalations.replaceChildren();
  elements.copilotRoadmap.replaceChildren();
  elements.copilotOutcomes.replaceChildren();
  elements.copilotEvidence.replaceChildren();
  showCopilotMessage("");
}

function resetEvidenceState() {
  currentEvidenceVisitId = null;
  currentClinicalContext = null;
  currentKnowledgeFacts = [];
  currentEvidenceBriefs = [];
  selectedFacts.clear();
  elements.evidenceVisitForm.reset();
  elements.knowledgeSearchForm.reset();
  elements.evidenceBriefForm.reset();
  elements.evidenceContent.hidden = true;
  elements.contextHash.textContent = "";
  elements.clinicalContext.replaceChildren();
  elements.knowledgeFacts.replaceChildren();
  elements.selectedFacts.replaceChildren();
  elements.evidenceBriefs.replaceChildren();
  showEvidenceMessage("");
  updateSelectedFacts();
}

function resetSafetyState() {
  currentSafetyVisitId = null;
  currentSafetyInbox = null;
  currentSafetyEscalations = null;
  elements.safetyVisitForm.reset();
  elements.safetyContent.hidden = true;
  elements.safetyContextHash.textContent = "";
  elements.safetySummary.replaceChildren();
  elements.safetyFindings.replaceChildren();
  elements.safetyEscalations.replaceChildren();
  elements.runSafetyEvaluationButton.hidden = true;
  showSafetyMessage("");
  showSafetyEscalationsMessage("");
}

function resetOperationalState() {
  currentFlow = null;
  elements.flowBoard.replaceChildren();
  elements.activeVisits.replaceChildren();
  elements.generatedAt.textContent = "";
  elements.metricActive.textContent = "۰";
  elements.metricCheckedIn.textContent = "۰";
  elements.metricReady.textContent = "۰";
  elements.metricTreatment.textContent = "۰";
  elements.metricAttention.textContent = "۰";
  showConsoleMessage("");
}

function setWorkspace(workspace) {
  if (workspace === "copilot" && !canReadCopilot()) {
    return;
  }
  if (workspace === "evidence" && !canReadEvidence()) {
    return;
  }
  if (workspace === "safety" && !canReadSafety()) {
    return;
  }

  activeWorkspace = workspace;
  const isFlow = workspace === "flow";
  const isCopilot = workspace === "copilot";
  const isEvidence = workspace === "evidence";
  const isSafety = workspace === "safety";
  elements.flowWorkspace.hidden = !isFlow;
  elements.copilotWorkspace.hidden = !isCopilot;
  elements.evidenceWorkspace.hidden = !isEvidence;
  elements.safetyWorkspace.hidden = !isSafety;
  elements.flowTab.setAttribute("aria-selected", String(isFlow));
  elements.copilotTab.setAttribute("aria-selected", String(isCopilot));
  elements.evidenceTab.setAttribute("aria-selected", String(isEvidence));
  elements.safetyTab.setAttribute("aria-selected", String(isSafety));
  elements.flowTab.tabIndex = isFlow ? 0 : -1;
  elements.copilotTab.tabIndex = isCopilot ? 0 : -1;
  elements.evidenceTab.tabIndex = isEvidence ? 0 : -1;
  elements.safetyTab.tabIndex = isSafety ? 0 : -1;

  if (isFlow) {
    startAutoRefresh();
    if (accessToken && currentFlow) {
      loadFlow({ quiet: true });
    }
  } else {
    stopAutoRefresh();
  }
  if (
    isSafety
    && accessToken
    && currentSafetyEscalations === null
    && !safetyEscalationRequestInProgress
  ) {
    loadSafetyEscalations({ quiet: true });
  }
}

function showLogin() {
  stopAutoRefresh();
  sessionGeneration += 1;
  accessToken = null;
  currentUser = null;
  requestInProgress = false;
  copilotRequestInProgress = false;
  evidenceRequestInProgress = false;
  safetyRequestInProgress = false;
  safetyEscalationRequestInProgress = false;
  actionInProgress = false;
  elements.refreshButton.disabled = false;
  elements.refreshButton.textContent = "تازه‌سازی";
  elements.loadCopilotButton.disabled = false;
  elements.loadCopilotButton.textContent = "بارگذاری snapshot پزشک‌یار";
  elements.loadEvidenceButton.disabled = false;
  elements.loadEvidenceButton.textContent = "بارگذاری زمینه و خلاصه‌ها";
  elements.knowledgeSearchButton.disabled = false;
  elements.knowledgeResetButton.disabled = false;
  elements.loadSafetyButton.disabled = false;
  elements.loadSafetyButton.textContent = "بارگذاری صندوق ایمنی";
  elements.runSafetyEvaluationButton.disabled = false;
  elements.loadSafetyEscalationsButton.disabled = false;
  elements.loadSafetyEscalationsButton.textContent = "تازه‌سازی صف";
  elements.dialogConfirm.disabled = false;
  resetOperationalState();
  resetCopilotState();
  resetEvidenceState();
  resetSafetyState();
  activeWorkspace = "flow";
  elements.flowWorkspace.hidden = false;
  elements.copilotWorkspace.hidden = true;
  elements.evidenceWorkspace.hidden = true;
  elements.safetyWorkspace.hidden = true;
  elements.flowTab.setAttribute("aria-selected", "true");
  elements.copilotTab.setAttribute("aria-selected", "false");
  elements.evidenceTab.setAttribute("aria-selected", "false");
  elements.safetyTab.setAttribute("aria-selected", "false");
  elements.flowTab.tabIndex = 0;
  elements.copilotTab.tabIndex = -1;
  elements.evidenceTab.tabIndex = -1;
  elements.safetyTab.tabIndex = -1;
  elements.copilotTab.hidden = true;
  elements.evidenceTab.hidden = true;
  elements.safetyTab.hidden = true;
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
  elements.copilotTab.hidden = !canReadCopilot();
  elements.evidenceTab.hidden = !canReadEvidence();
  elements.safetyTab.hidden = !canReadSafety();
  elements.evidenceComposer.hidden = !canCreateEvidence();
  elements.runSafetyEvaluationButton.hidden = !canRunSafetyEvaluation();
  setWorkspace("flow");
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
  const description = createTextElement("dd", "", displayValue(value));
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

  if (canReadCopilot()) {
    const copilotButton = createTextElement(
      "button",
      "button button-secondary",
      "پزشک‌یار",
    );
    copilotButton.type = "button";
    copilotButton.dataset.copilotVisitId = item.visit_id;
    copilotButton.setAttribute(
      "aria-label",
      `پزشک‌یار برای ویزیت ${item.patient_name}`,
    );
    card.append(copilotButton);
  }

  if (canReadEvidence()) {
    const evidenceButton = createTextElement(
      "button",
      "button button-evidence",
      "مرور شواهد",
    );
    evidenceButton.type = "button";
    evidenceButton.dataset.evidenceVisitId = item.visit_id;
    evidenceButton.setAttribute(
      "aria-label",
      `مرور شواهد برای ویزیت ${item.patient_name}`,
    );
    card.append(evidenceButton);
  }

  if (canReadSafety()) {
    const safetyButton = createTextElement(
      "button",
      "button button-safety",
      "صندوق ایمنی",
    );
    safetyButton.type = "button";
    safetyButton.dataset.safetyVisitId = item.visit_id;
    safetyButton.setAttribute(
      "aria-label",
      `صندوق ایمنی برای ویزیت ${item.patient_name}`,
    );
    card.append(safetyButton);
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

  const visits = new Map();
  for (const item of allFlowItems()) {
    if (!visits.has(item.visit_id)) {
      visits.set(item.visit_id, item);
    }
  }
  const visitOptions = document.createDocumentFragment();
  for (const item of visits.values()) {
    const option = document.createElement("option");
    option.value = item.visit_id;
    option.label = `${item.patient_name} · ${item.patient_code}`;
    visitOptions.append(option);
  }
  elements.activeVisits.replaceChildren(visitOptions);

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
  if (
    !accessToken
    || requestInProgress
    || document.hidden
    || activeWorkspace !== "flow"
  ) {
    return;
  }

  const requestGeneration = sessionGeneration;
  setRefreshBusy(true);

  if (!quiet) {
    showConsoleMessage("");
  }

  try {
    const flow = await apiRequest("/dashboard/live-flow");
    if (!accessToken || requestGeneration !== sessionGeneration) {
      return;
    }
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
    if (requestGeneration === sessionGeneration) {
      setRefreshBusy(false);
    }
  }
}

function createDefinitionGrid(entries, className = "context-grid") {
  const grid = document.createElement("dl");
  grid.className = className;
  for (const [label, value] of entries) {
    grid.append(createMeta(label, displayValue(value)));
  }
  return grid;
}

function observationValue(observation) {
  switch (observation.value_type) {
    case "quantity":
      return [
        observation.quantity_value,
        observation.unit_display || observation.unit_code,
      ].filter(Boolean).join(" ");
    case "string":
      return observation.string_value;
    case "boolean":
      return observation.boolean_value ? "بله" : "خیر";
    case "integer":
      return observation.integer_value;
    case "coded":
      return observation.coded_display || observation.coded_value;
    case "datetime":
      return formatDateTime(observation.datetime_value);
    case "absent":
      return `ثبت‌نشده: ${displayValue(observation.absent_reason)}`;
    default:
      return "—";
  }
}

function renderClinicalContext(context) {
  elements.contextHash.textContent = context.clinical_context_sha256;
  elements.contextHash.title = "هش دقیق زمینهٔ بالینی فعلی";

  const fragment = document.createDocumentFragment();
  if (!context.intake) {
    fragment.append(createTextElement(
      "p",
      "context-warning",
      "برای این ویزیت شرح حال نهایی فعالی وجود ندارد؛ ساخت خلاصهٔ شواهد مجاز نیست.",
    ));
    elements.clinicalContext.replaceChildren(fragment);
    return;
  }

  const intake = context.intake;
  const intakeCard = document.createElement("article");
  intakeCard.className = "context-card context-intake";
  intakeCard.append(
    createTextElement("h4", "", `شرح حال نهایی · نسخه ${toPersianNumber(intake.version)}`),
    createDefinitionGrid([
      ["شکایت اصلی", intake.chief_complaint],
      ["شرح بیماری فعلی", intake.history_present_illness],
      ["ناحیه", intake.body_region],
      ["سمت", lateralityLabels[intake.laterality] || intake.laterality],
      ["شروع علائم", intake.symptom_onset_date],
      ["امتیاز درد", intake.pain_score === null ? null : toPersianNumber(intake.pain_score)],
      ["محدودیت عملکردی", intake.functional_limitations],
      ["سابقهٔ مرتبط", intake.relevant_history],
      ["داروهای فعلی", intake.current_medications],
      ["حساسیت‌ها", intake.allergies],
      ["یافته‌های معاینه", intake.exam_findings],
      ["پرچم‌های قرمز", intake.red_flags],
      ["برداشت بالینی", intake.clinical_impression],
      ["هدف مراقبت", intake.care_goal],
    ]),
    createTextElement(
      "p",
      "record-meta",
      `نهایی‌شده در ${formatDateTime(intake.finalized_at)} · SHA-256: ${intake.content_sha256}`,
    ),
  );
  fragment.append(intakeCard);

  const reportsHeading = createTextElement(
    "h4",
    "context-subheading",
    `گزارش‌های پاراکلینیکی نهایی (${toPersianNumber(context.reports.length)})`,
  );
  fragment.append(reportsHeading);

  if (!context.reports.length) {
    fragment.append(createTextElement(
      "p",
      "empty-state",
      "گزارش پاراکلینیکی نهایی فعالی ثبت نشده است.",
    ));
  }

  for (const report of context.reports) {
    const reportCard = document.createElement("article");
    reportCard.className = "context-card context-report";
    reportCard.append(
      createTextElement("h4", "", `${report.title} · نسخه ${toPersianNumber(report.version)}`),
      createDefinitionGrid([
        ["دسته", report.category],
        ["شناسهٔ بیرونی", report.external_identifier],
        ["زمان انجام", formatDateTime(report.performed_at)],
        ["زمان صدور", formatDateTime(report.issued_at)],
        ["انجام‌دهنده", report.performer],
        ["نتیجه‌گیری", report.conclusion],
        ["مرجع منبع", report.source_reference],
      ]),
    );

    if (report.observations.length) {
      const observations = document.createElement("div");
      observations.className = "observation-list";
      for (const observation of report.observations) {
        const observationCard = document.createElement("div");
        observationCard.className = "observation-card";
        observationCard.append(
          createTextElement("strong", "", observation.display_name),
          createTextElement("span", "observation-value", displayValue(observationValue(observation))),
          createTextElement(
            "span",
            "observation-interpretation",
            interpretationLabels[observation.interpretation]
              || displayValue(observation.interpretation),
          ),
          createTextElement(
            "small",
            "",
            `کد ${observation.code_system}: ${observation.code}`,
          ),
        );
        observations.append(observationCard);
      }
      reportCard.append(observations);
    }

    reportCard.append(createTextElement(
      "p",
      "record-meta",
      `نهایی‌شده در ${formatDateTime(report.finalized_at)} · SHA-256: ${report.content_sha256}`,
    ));
    fragment.append(reportCard);
  }

  elements.clinicalContext.replaceChildren(fragment);
}

function createSourceList(sources) {
  const list = document.createElement("ul");
  list.className = "source-list";
  for (const source of sources) {
    const item = document.createElement("li");
    item.append(
      createTextElement("strong", "", source.title),
      createTextElement("span", "", source.citation),
    );
    if (source.publisher || source.publication_date) {
      item.append(createTextElement(
        "small",
        "",
        [source.publisher, source.publication_date].filter(Boolean).join(" · "),
      ));
    }
    if (source.url || source.doi) {
      item.append(createTextElement(
        "small",
        "source-reference",
        [source.doi ? `DOI: ${source.doi}` : null, source.url].filter(Boolean).join(" · "),
      ));
    }
    list.append(item);
  }
  return list;
}

function updateCreateButton() {
  const valid = (
    canCreateEvidence()
    && currentClinicalContext
    && currentClinicalContext.intake
    && selectedFacts.size > 0
    && elements.clinicalQuestion.value.trim().length >= 5
    && elements.evidenceAcknowledgement.checked
  );
  elements.createBriefButton.disabled = evidenceRequestInProgress || !valid;
}

function updateSelectedFacts() {
  elements.selectedFactCount.textContent = (
    `${toPersianNumber(selectedFacts.size)} از ${toPersianNumber(MAX_SELECTED_FACTS)}`
  );
  const fragment = document.createDocumentFragment();
  if (!selectedFacts.size) {
    fragment.append(createTextElement(
      "p",
      "empty-selection",
      "هنوز منبعی انتخاب نشده است.",
    ));
  } else {
    fragment.append(createTextElement("h4", "", "منابع انتخاب‌شده توسط پزشک"));
    const list = document.createElement("ul");
    for (const fact of selectedFacts.values()) {
      list.append(createTextElement(
        "li",
        "",
        `${fact.fact_key} · نسخه ${toPersianNumber(fact.version)} · ${fact.title}`,
      ));
    }
    fragment.append(list);
  }
  elements.selectedFacts.replaceChildren(fragment);

  for (const checkbox of elements.knowledgeFacts.querySelectorAll("input[type='checkbox']")) {
    const isSelected = selectedFacts.has(checkbox.dataset.factId);
    checkbox.checked = isSelected;
    checkbox.disabled = !isSelected && selectedFacts.size >= MAX_SELECTED_FACTS;
  }
  updateCreateButton();
}

function renderKnowledgeFacts(facts) {
  const fragment = document.createDocumentFragment();
  if (!facts.length) {
    fragment.append(createTextElement(
      "p",
      "empty-state",
      "منبع تأییدشده‌ای با این عبارت پیدا نشد.",
    ));
  }

  for (const fact of facts) {
    const card = document.createElement("article");
    card.className = "knowledge-card";

    const selector = document.createElement("label");
    selector.className = "fact-selector";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.dataset.factId = fact.id;
    checkbox.checked = selectedFacts.has(fact.id);
    checkbox.disabled = !checkbox.checked && selectedFacts.size >= MAX_SELECTED_FACTS;
    selector.append(
      checkbox,
      createTextElement("span", "", "انتخاب دستی این منبع"),
    );

    const titleRow = document.createElement("div");
    titleRow.className = "knowledge-title-row";
    titleRow.append(
      createTextElement("h4", "", fact.title),
      createTextElement(
        "span",
        "evidence-grade",
        `سطح شواهد: ${evidenceGradeLabels[fact.evidence_grade] || fact.evidence_grade}`,
      ),
    );

    card.append(
      selector,
      titleRow,
      createTextElement(
        "p",
        "knowledge-key",
        `${fact.fact_key} · نسخه ${toPersianNumber(fact.version)} · ${fact.clinical_domain}`,
      ),
      createTextElement("p", "knowledge-statement", fact.statement),
      createDefinitionGrid([
        ["جمعیت", fact.population],
        ["اندیکاسیون", fact.indication],
        ["موارد منع", fact.contraindications],
        ["نوع درمان", fact.therapy_type],
        ["بازهٔ اعتبار", [fact.valid_from, fact.valid_to].filter(Boolean).join(" تا ")],
      ], "fact-meta"),
      createTextElement("h5", "", "منابع ثبت‌شده"),
      createSourceList(fact.sources),
      createTextElement("p", "record-meta", `SHA-256: ${fact.content_sha256}`),
    );
    fragment.append(card);
  }
  elements.knowledgeFacts.replaceChildren(fragment);
  updateSelectedFacts();
}

function createSafetyFlags() {
  const list = document.createElement("ul");
  list.className = "safety-flags";
  for (const label of [
    "توصیهٔ درمانی نیست",
    "درمان‌ها را رتبه‌بندی نمی‌کند",
    "نمرهٔ خطر یا مجوز بالینی نیست",
    "برای تصمیم زمان‌حساس نیست",
    "بازبینی مستقل پزشک الزامی است",
  ]) {
    list.append(createTextElement("li", "", label));
  }
  return list;
}

function renderEvidenceBriefs(briefs) {
  const fragment = document.createDocumentFragment();
  if (!briefs.length) {
    fragment.append(createTextElement(
      "p",
      "empty-state",
      "برای این ویزیت هنوز خلاصهٔ شواهدی ثبت نشده است.",
    ));
  }

  for (const brief of briefs) {
    const details = document.createElement("details");
    details.className = "brief-card";
    const summary = document.createElement("summary");
    summary.append(
      createTextElement("strong", "", formatDateTime(brief.created_at)),
      createTextElement(
        "span",
        "",
        `${brief.payload.actor.actor_display_name} · ${toPersianNumber(brief.payload.facts.length)} منبع`,
      ),
    );
    details.append(
      summary,
      createTextElement("h4", "", "پرسش بالینی ثبت‌شده"),
      createTextElement("p", "brief-question", brief.payload.clinical_question),
      createSafetyFlags(),
    );

    const factList = document.createElement("div");
    factList.className = "brief-facts";
    for (const fact of brief.payload.facts) {
      const factCard = document.createElement("article");
      factCard.append(
        createTextElement(
          "h5",
          "",
          `${fact.fact_key} · نسخه ${toPersianNumber(fact.version)} · ${fact.title}`,
        ),
        createTextElement("p", "", fact.statement),
        createSourceList(fact.sources),
      );
      factList.append(factCard);
    }
    details.append(
      factList,
      createTextElement("h4", "", "محدودیت‌های ثبت‌شده"),
    );
    const limitations = document.createElement("ul");
    limitations.className = "limitations-list";
    for (const limitation of brief.payload.known_limitations) {
      limitations.append(createTextElement("li", "", limitation));
    }
    details.append(
      limitations,
      createDefinitionGrid([
        ["شناسهٔ خلاصه", brief.id],
        ["تاریخ دانش", brief.knowledge_as_of],
        ["هش زمینه", brief.clinical_context_sha256],
        ["هش مجموعهٔ دانش", brief.knowledge_set_sha256],
        ["هش خلاصه", brief.sha256],
      ], "brief-hashes"),
    );
    fragment.append(details);
  }
  elements.evidenceBriefs.replaceChildren(fragment);
}

async function loadApprovedFacts(search = "") {
  if (!canCreateEvidence() || !currentEvidenceVisitId) {
    return;
  }

  const normalizedSearch = search.trim();
  if (normalizedSearch && normalizedSearch.length < 2) {
    showEvidenceMessage("عبارت جست‌وجو باید دست‌کم دو نویسه باشد.", true);
    return;
  }

  const requestGeneration = sessionGeneration;
  const query = new URLSearchParams({ limit: "100" });
  if (normalizedSearch) {
    query.set("search", normalizedSearch);
  }

  setEvidenceBusy(true, "در حال دریافت منابع…");
  try {
    const facts = await apiRequest(`/knowledge/facts/approved?${query}`);
    if (!accessToken || requestGeneration !== sessionGeneration) {
      return;
    }
    currentKnowledgeFacts = facts;
    currentKnowledgeFacts.sort((left, right) => (
      left.fact_key.localeCompare(right.fact_key, "en") || left.version - right.version
    ));
    renderKnowledgeFacts(currentKnowledgeFacts);
    showEvidenceMessage("");
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      showLogin();
      elements.loginMessage.textContent = "نشست شما پایان یافته است؛ دوباره وارد شوید.";
      return;
    }
    showEvidenceMessage("دریافت منابع تأییدشده ممکن نشد؛ دوباره تلاش کنید.", true);
  } finally {
    if (requestGeneration === sessionGeneration) {
      setEvidenceBusy(false);
      updateCreateButton();
    }
  }
}

async function loadEvidenceWorkspace(visitId) {
  const normalizedVisitId = visitId.trim();
  if (!canReadEvidence() || !normalizedVisitId || evidenceRequestInProgress) {
    return;
  }

  const requestGeneration = sessionGeneration;
  currentEvidenceVisitId = normalizedVisitId;
  currentClinicalContext = null;
  currentKnowledgeFacts = [];
  currentEvidenceBriefs = [];
  selectedFacts.clear();
  elements.evidenceVisitId.value = normalizedVisitId;
  elements.evidenceBriefForm.reset();
  elements.knowledgeSearchForm.reset();
  elements.evidenceContent.hidden = true;
  updateSelectedFacts();
  showEvidenceMessage("در حال دریافت زمینهٔ بالینی و سابقهٔ شواهد…");
  setEvidenceBusy(true);

  try {
    const requests = [
      apiRequest(`/visits/${encodeURIComponent(normalizedVisitId)}/clinical-context`),
      apiRequest(`/visits/${encodeURIComponent(normalizedVisitId)}/evidence-briefs`),
    ];
    if (canCreateEvidence()) {
      requests.push(apiRequest("/knowledge/facts/approved?limit=100"));
    }
    const [context, briefs, facts = []] = await Promise.all(requests);
    if (!accessToken || requestGeneration !== sessionGeneration) {
      return;
    }
    currentClinicalContext = context;
    currentEvidenceBriefs = briefs;
    currentKnowledgeFacts = facts;
    currentKnowledgeFacts.sort((left, right) => (
      left.fact_key.localeCompare(right.fact_key, "en") || left.version - right.version
    ));

    renderClinicalContext(context);
    renderEvidenceBriefs(briefs);
    elements.evidenceComposer.hidden = !canCreateEvidence() || !context.intake;
    if (canCreateEvidence() && context.intake) {
      renderKnowledgeFacts(currentKnowledgeFacts);
    }
    elements.evidenceContent.hidden = false;

    if (!context.intake) {
      showEvidenceMessage(
        "شرح حال نهایی فعال وجود ندارد؛ پیش از انتخاب شواهد، زمینهٔ بالینی باید نهایی شود.",
        true,
      );
    } else if (!canCreateEvidence()) {
      showEvidenceMessage("نمای فقط‌خواندنی است؛ ایجاد خلاصه فقط برای پزشک فعال مجاز است.");
    } else {
      showEvidenceMessage("زمینه و منابع فعلی بارگذاری شد؛ انتخاب منابع کاملاً دستی است.");
    }
    setConnectionState(true);
  } catch (error) {
    elements.evidenceContent.hidden = true;
    if (error instanceof ApiError && error.status === 401) {
      showLogin();
      elements.loginMessage.textContent = "نشست شما پایان یافته است؛ دوباره وارد شوید.";
      return;
    }
    if (error instanceof ApiError && error.status === 404) {
      showEvidenceMessage("ویزیت موردنظر پیدا نشد.", true);
    } else if (error instanceof ApiError && error.status === 403) {
      showEvidenceMessage("نقش کاربری شما اجازهٔ مرور این شواهد را ندارد.", true);
    } else {
      showEvidenceMessage("دریافت فضای شواهد ممکن نشد؛ دوباره تلاش کنید.", true);
    }
    setConnectionState(false);
  } finally {
    if (requestGeneration === sessionGeneration) {
      setEvidenceBusy(false);
      updateCreateButton();
    }
  }
}


function formatRoadmapNumber(value, digits = 1) {
  if (value === null || value === undefined) {
    return "—";
  }
  return Number(value).toLocaleString("fa-IR", {
    maximumFractionDigits: digits,
    minimumFractionDigits: 0,
  });
}

function formatRoadmapPercent(value) {
  if (value === null || value === undefined) {
    return "—";
  }
  return `${formatRoadmapNumber(value * 100, 1)}٪`;
}

function roadmapMetricText(metric, formatter = formatRoadmapNumber) {
  if (!metric || metric.value === null) {
    const denominator = metric ? toPersianNumber(metric.denominator) : "۰";
    const minimum = metric ? toPersianNumber(metric.minimum_denominator) : "۵";
    return `گزارش نمی‌شود؛ n=${denominator}، حداقل ${minimum}`;
  }
  return `${formatter(metric.value)} · n=${toPersianNumber(metric.denominator)}`;
}

function renderTreatmentRoadmap(roadmap) {
  currentTreatmentRoadmap = roadmap;
  const fragment = document.createDocumentFragment();

  const summary = document.createElement("article");
  summary.className = "context-card context-intake";
  summary.append(
    createTextElement("h4", "", "خلاصهٔ نقشه‌راه"),
    createDefinitionGrid([
      ["وضعیت", roadmapStatusLabels[roadmap.roadmap_status] || roadmap.roadmap_status],
      ["ایمنی", roadmapSafetyLabels[roadmap.safety_evaluation_status] || roadmap.safety_evaluation_status],
      ["ناحیه", roadmap.target_profile.body_region],
      [
        "سن در زمان ویزیت",
        roadmap.target_profile.age_years === null
          ? null
          : toPersianNumber(roadmap.target_profile.age_years),
      ],
      [
        "درد پایه",
        roadmap.target_profile.baseline_pain_score === null
          ? null
          : `${toPersianNumber(roadmap.target_profile.baseline_pain_score)} از ۱۰`,
      ],
      ["بیماران مشابه منحصربه‌فرد", roadmap.matched_unique_patient_count_display],
      ["حداقل cohort قابل گزارش", toPersianNumber(roadmap.cohort_definition.minimum_reportable_unique_patients)],
      ["SHA-256 نقشه‌راه", roadmap.roadmap_sha256],
      ["رتبه‌بندی درمان", "ندارد"],
      ["مجوز بالینی", "خیر"],
    ], "safety-summary-grid"),
  );
  fragment.append(summary);

  if (roadmap.roadmap_status !== "options_available") {
    fragment.append(createTextElement(
      "p",
      "context-warning",
      roadmapStatusLabels[roadmap.roadmap_status] || roadmap.roadmap_status,
    ));
  }

  if (!roadmap.options.length) {
    fragment.append(createTextElement(
      "p",
      "empty-state",
      "گزینهٔ قابل گزارش وجود ندارد. نبود گزینه به معنی نامناسب بودن یا مناسب بودن هیچ درمانی نیست.",
    ));
  }

  for (const option of roadmap.options) {
    const card = document.createElement("article");
    card.className = "evidence-brief-card";
    card.append(
      createTextElement(
        "h4",
        "",
        `${option.protocol.name} · ${option.protocol_code} · نسخه ${option.protocol_version}`,
      ),
      createDefinitionGrid([
        ["نوع درمان", option.treatment_type],
        ["ناحیه", option.body_region],
        ["بازه‌های دارای داده کافی", toPersianNumber(option.reportable_window_count)],
        ["ترتیب درمانی", "ندارد؛ ترتیب فقط بر اساس کد پروتکل است"],
      ]),
      createTextElement(
        "p",
        "ordering-note",
        "این کارت یک گزینهٔ قابل بررسی است، نه انتخاب نهایی، نسخه یا ادعای برتری درمان.",
      ),
    );

    for (const window of option.windows) {
      const windowCard = document.createElement("div");
      windowCard.className = "context-card context-report";
      const improvement = window.observed_improvement_proportion;
      let improvementText = roadmapMetricText(
        improvement,
        formatRoadmapPercent,
      );
      if (
        window.observed_improvement_wilson_95_low !== null
        && window.observed_improvement_wilson_95_high !== null
      ) {
        improvementText += (
          ` · بازه ۹۵٪ ${formatRoadmapPercent(window.observed_improvement_wilson_95_low)} تا `
          + formatRoadmapPercent(window.observed_improvement_wilson_95_high)
        );
      }
      windowCard.append(
        createTextElement(
          "h5",
          "context-subheading",
          roadmapWindowLabels[window.window] || window.window,
        ),
        createDefinitionGrid([
          ["تعداد بیمار", toPersianNumber(window.unique_patient_count || 0)],
          ["حجم دادهٔ محلی", roadmapVolumeLabels[window.local_data_volume] || window.local_data_volume],
          ["میانه روز پیگیری", window.median_follow_up_day === null ? null : formatRoadmapNumber(window.median_follow_up_day)],
          ["بهبود مشاهده‌شده", improvementText],
          ["میانه امتیاز بیمار", roadmapMetricText(window.median_patient_rating)],
          ["میانه امتیاز پزشک", roadmapMetricText(window.median_physician_rating)],
          ["میانه کاهش درد (مثبت=کاهش)", roadmapMetricText(window.median_pain_change)],
          ["میانه عملکرد", roadmapMetricText(window.median_function_score)],
          ["عارضه مستندشده", roadmapMetricText(window.documented_adverse_event_proportion, formatRoadmapPercent)],
        ], "safety-summary-grid"),
      );
      card.append(windowCard);
    }
    fragment.append(card);
  }

  fragment.append(createTextElement(
    "p",
    "ordering-note",
    "این تحلیل فقط دادهٔ مشاهده‌ای محلی را خلاصه می‌کند. شواهد علمی بیرونی، منع مصرف‌ها و شرایط اختصاصی بیمار باید مستقل توسط پزشک بررسی شوند.",
  ));
  elements.copilotRoadmap.replaceChildren(fragment);
}

function renderCopilotSnapshot(snapshot) {
  currentCopilotSnapshot = snapshot;
  const context = snapshot.clinical_context;
  const safety = snapshot.safety_inbox;

  const summaryCard = document.createElement("article");
  summaryCard.className = "context-card context-intake";
  summaryCard.append(
    createTextElement("h4", "", "Snapshot یکپارچهٔ پزشک‌یار"),
    createDefinitionGrid([
      ["زمان تولید", formatDateTime(snapshot.generated_at)],
      ["SHA-256 snapshot", snapshot.snapshot_sha256],
      ["SHA-256 زمینهٔ بالینی", context.clinical_context_sha256],
      ["شرح حال نهایی فعال", context.intake ? "بله" : "خیر"],
      ["گزارش‌های پاراکلینیک", toPersianNumber(context.reports.length)],
      ["ارزیابی ایمنی", safety.evaluation ? "ثبت شده" : "ثبت نشده"],
      [
        "انطباق ارزیابی با زمینهٔ فعلی",
        safety.evaluation_matches_current_context === null
          ? "ارزیابی وجود ندارد"
          : (safety.evaluation_matches_current_context ? "بله" : "خیر"),
      ],
      ["یافته‌های آخرین ارزیابی", toPersianNumber(safety.findings.length)],
      ["ارجاع باز در آخرین ارزیابی", toPersianNumber(snapshot.open_escalations.length)],
      [
        "خلاصهٔ شواهد منطبق با زمینهٔ فعلی",
        toPersianNumber(snapshot.current_context_evidence_briefs.length),
      ],
      ["کل خلاصه‌های شواهد ویزیت", toPersianNumber(snapshot.evidence_briefs.length)],
      ["ثبت‌های outcome", toPersianNumber(snapshot.treatment_outcomes.length)],
      ["مجوز بالینی", "خیر"],
    ], "safety-summary-grid"),
  );

  const summaryFragment = document.createDocumentFragment();
  if (safety.evaluation_matches_current_context === false) {
    summaryFragment.append(createTextElement(
      "p",
      "context-warning",
      "ارزیابی ایمنی موجود به زمینهٔ بالینی فعلی متصل نیست؛ پیش از اتکا، ارزیابی فعلی باید مستقل بررسی شود.",
    ));
  }
  summaryFragment.append(summaryCard);
  elements.copilotSummary.replaceChildren(summaryFragment);

  const escalationFragment = document.createDocumentFragment();
  if (!snapshot.open_escalations.length) {
    escalationFragment.append(createTextElement(
      "p",
      "empty-state",
      "در آخرین ارزیابی ایمنی این ویزیت ارجاع بازی وجود ندارد. این وضعیت مجوز بالینی نیست.",
    ));
  }
  for (const item of snapshot.open_escalations) {
    const card = document.createElement("article");
    card.className = "safety-finding-card";
    card.dataset.severity = item.finding.severity;
    card.append(
      createTextElement("h4", "", item.finding.title),
      createDefinitionGrid([
        ["شدت ثبت‌شده", safetySeverityLabels[item.finding.severity] || item.finding.severity],
        [
          "اقدام مقرر در قاعده",
          safetyRequiredActionLabels[item.finding.action] || item.finding.action,
        ],
        ["وضعیت پیگیری", safetyReviewStatusLabels[item.timeline.review_status] || item.timeline.review_status],
        [
          "آخرین ثبت پیگیری",
          item.timeline.reviews.length
            ? formatDateTime(item.timeline.reviews[item.timeline.reviews.length - 1].created_at)
            : "—",
        ],
      ], "safety-summary-grid"),
    );
    escalationFragment.append(card);
  }
  elements.copilotEscalations.replaceChildren(escalationFragment);

  const outcomeFragment = document.createDocumentFragment();
  if (!snapshot.treatment_outcomes.length) {
    outcomeFragment.append(createTextElement(
      "p",
      "empty-state",
      "برای درمان‌های این ویزیت هنوز outcome ساختاریافته‌ای ثبت نشده است.",
    ));
  }
  for (const outcome of snapshot.treatment_outcomes) {
    const card = document.createElement("article");
    card.className = "evidence-brief-card";
    card.append(
      createTextElement(
        "h4",
        "",
        `${outcome.protocol_code || outcome.treatment_type} · روز پیگیری ${toPersianNumber(outcome.follow_up_day)}`,
      ),
      createDefinitionGrid([
        ["وضعیت کلی", outcome.outcome_status],
        ["امتیاز بیمار", outcome.patient_rating === null ? null : `${toPersianNumber(outcome.patient_rating)} از ۵`],
        ["امتیاز پزشک", outcome.physician_rating === null ? null : `${toPersianNumber(outcome.physician_rating)} از ۵`],
        ["امتیاز درد", outcome.pain_score === null ? null : `${toPersianNumber(outcome.pain_score)} از ۱۰`],
        ["عملکرد", outcome.function_score === null ? null : `${toPersianNumber(outcome.function_score)} از ۱۰۰`],
        ["زمان ثبت", formatDateTime(outcome.recorded_at)],
        ["SHA-256 outcome", outcome.sha256],
      ]),
      createTextElement(
        "p",
        "ordering-note",
        "دادهٔ مشاهده‌ای است؛ برای نتیجه‌گیری علّی یا رتبه‌بندی درمان کافی نیست.",
      ),
    );
    outcomeFragment.append(card);
  }
  elements.copilotOutcomes.replaceChildren(outcomeFragment);

  const evidenceFragment = document.createDocumentFragment();
  if (!snapshot.evidence_briefs.length) {
    evidenceFragment.append(createTextElement(
      "p",
      "empty-state",
      "برای این ویزیت هنوز خلاصهٔ شواهد ثبت‌شده‌ای وجود ندارد.",
    ));
  }
  for (const brief of snapshot.evidence_briefs) {
    const isCurrent = brief.clinical_context_sha256 === context.clinical_context_sha256;
    const card = document.createElement("article");
    card.className = "evidence-brief-card";
    card.append(
      createTextElement("h4", "", brief.payload.clinical_question),
      createTextElement(
        "p",
        isCurrent ? "queue-current" : "context-warning",
        isCurrent
          ? "این خلاصه به زمینهٔ بالینی فعلی متصل است."
          : "این خلاصه تاریخی است و به snapshot قبلی زمینهٔ بالینی متصل می‌ماند.",
      ),
      createDefinitionGrid([
        ["زمان ثبت", formatDateTime(brief.created_at)],
        ["تعداد منابع انتخاب‌شده", toPersianNumber(brief.knowledge_fact_ids.length)],
        ["SHA-256 خلاصه", brief.sha256],
        ["روش انتخاب", "انتخاب دستی پزشک"],
      ]),
    );
    evidenceFragment.append(card);
  }
  elements.copilotEvidence.replaceChildren(evidenceFragment);
  elements.copilotContent.hidden = false;
}

async function loadCopilotWorkspace(visitId) {
  const normalizedVisitId = visitId.trim();
  if (!canReadCopilot() || !normalizedVisitId || copilotRequestInProgress) {
    return;
  }

  const requestGeneration = sessionGeneration;
  currentCopilotVisitId = normalizedVisitId;
  currentCopilotSnapshot = null;
  currentTreatmentRoadmap = null;
  elements.copilotVisitId.value = normalizedVisitId;
  elements.copilotContent.hidden = true;
  elements.copilotSummary.replaceChildren();
  elements.copilotEscalations.replaceChildren();
  elements.copilotRoadmap.replaceChildren();
  elements.copilotOutcomes.replaceChildren();
  elements.copilotEvidence.replaceChildren();
  showCopilotMessage("در حال دریافت snapshot یکپارچهٔ ویزیت…");
  setCopilotBusy(true);

  try {
    const snapshot = await apiRequest(
      `/visits/${encodeURIComponent(normalizedVisitId)}/physician-copilot`,
    );
    if (!accessToken || requestGeneration !== sessionGeneration) {
      return;
    }
    renderCopilotSnapshot(snapshot);
    try {
      const roadmap = await apiRequest(
        `/visits/${encodeURIComponent(normalizedVisitId)}/treatment-options-roadmap`,
      );
      if (!accessToken || requestGeneration !== sessionGeneration) {
        return;
      }
      renderTreatmentRoadmap(roadmap);
      showCopilotMessage(
        roadmap.roadmap_status === "options_available"
          ? "Snapshot و گزینه‌های چندگانهٔ قابل بررسی بارگذاری شد؛ هیچ گزینه‌ای رتبه‌بندی یا انتخاب نشده است."
          : "Snapshot بارگذاری شد؛ وضعیت نقشه‌راه در بخش گزینه‌های درمانی نمایش داده شده است.",
      );
    } catch (roadmapError) {
      if (roadmapError instanceof ApiError && roadmapError.status === 401) {
        showLogin();
        elements.loginMessage.textContent = "نشست شما پایان یافته است؛ دوباره وارد شوید.";
        return;
      }
      currentTreatmentRoadmap = null;
      elements.copilotRoadmap.replaceChildren(createTextElement(
        "p",
        "context-warning",
        roadmapError instanceof ApiError && roadmapError.status === 409
          ? "نقشه‌راه به‌دلیل ناسازگاری یا ناکافی بودن زمینهٔ ساختاریافته تولید نشد."
          : "دریافت نقشه‌راه گزینه‌های درمانی ممکن نشد.",
      ));
      showCopilotMessage(
        "Snapshot بارگذاری شد، اما نقشه‌راه درمانی در دسترس نیست.",
        true,
      );
    }
    setConnectionState(true);
  } catch (error) {
    elements.copilotContent.hidden = true;
    if (error instanceof ApiError && error.status === 401) {
      showLogin();
      elements.loginMessage.textContent = "نشست شما پایان یافته است؛ دوباره وارد شوید.";
      return;
    }
    if (error instanceof ApiError && error.status === 404) {
      showCopilotMessage("ویزیت موردنظر پیدا نشد.", true);
    } else if (error instanceof ApiError && error.status === 403) {
      showCopilotMessage("نقش کاربری شما اجازهٔ مشاهدهٔ پزشک‌یار را ندارد.", true);
    } else {
      showCopilotMessage("دریافت snapshot پزشک‌یار ممکن نشد؛ دوباره تلاش کنید.", true);
    }
    setConnectionState(false);
  } finally {
    if (requestGeneration === sessionGeneration) {
      setCopilotBusy(false);
    }
  }
}

function createSafetyStatus(value, labels, className = "safety-status") {
  const status = createTextElement("span", className, labels[value] || value);
  status.dataset.value = value;
  return status;
}

function renderSafetyEscalations(queue) {
  currentSafetyEscalations = queue;
  const fragment = document.createDocumentFragment();
  if (!queue.items.length) {
    fragment.append(createTextElement(
      "p",
      "empty-state",
      "در حال حاضر ارجاع بازی با آخرین وضعیت معتبر «ارجاع‌شده» وجود ندارد. این نتیجه مجوز بالینی یا تأیید نبود خطر نیست.",
    ));
  }

  for (const item of queue.items) {
    const card = document.createElement("article");
    card.className = "safety-escalation-card";
    card.dataset.severity = item.severity;

    const heading = document.createElement("div");
    heading.className = "safety-finding-heading";
    heading.append(
      createTextElement("h4", "", item.title),
      createSafetyStatus(
        item.severity,
        safetySeverityLabels,
        "safety-severity",
      ),
      createSafetyStatus(
        item.review_status,
        safetyReviewStatusLabels,
        "safety-review-status",
      ),
    );

    const freshness = createTextElement(
      "p",
      item.evaluation_matches_current_context ? "queue-current" : "context-warning",
      item.evaluation_matches_current_context
        ? "snapshot با زمینهٔ بالینی فعلی منطبق است."
        : "زمینهٔ بالینی تغییر کرده است؛ این ارجاع به snapshot قبلی متصل می‌ماند.",
    );
    const openButton = createTextElement(
      "button",
      "button button-secondary",
      "باز کردن جزئیات ارجاع",
    );
    openButton.type = "button";
    openButton.dataset.escalationVisitId = item.visit_id;

    card.append(
      heading,
      freshness,
      createDefinitionGrid([
        ["شناسهٔ ویزیت", item.visit_id],
        ["زمان ثبت ارجاع", formatDateTime(item.escalated_at)],
        ["کلید و نسخهٔ قاعده", `${item.rule_key} · ${item.rule_version}`],
        ["اقدام مقرر در قاعده", safetyRequiredActionLabels[item.required_action] || item.required_action],
        ["ترتیب بالینی", "ندارد"],
        ["مجوز بالینی", "خیر"],
      ], "safety-summary-grid"),
      openButton,
    );
    fragment.append(card);
  }
  elements.safetyEscalations.replaceChildren(fragment);
}

async function loadSafetyEscalations({ quiet = false } = {}) {
  if (!canReadSafety() || safetyEscalationRequestInProgress) {
    return;
  }

  const requestGeneration = sessionGeneration;
  setSafetyEscalationsBusy(true);
  if (!quiet) {
    showSafetyEscalationsMessage("در حال اعتبارسنجی زنجیره‌ها و دریافت ارجاع‌های باز…");
  }
  try {
    const queue = await apiRequest("/safety/escalations?limit=50");
    if (!accessToken || requestGeneration !== sessionGeneration) {
      return;
    }
    if (
      queue.is_clinical_priority_order !== false
      || queue.is_clinical_clearance !== false
      || queue.items.some(
        (item) => (
          item.is_clinical_priority !== false
          || item.is_clinical_clearance !== false
          || item.review_status !== "escalated"
        ),
      )
    ) {
      throw new ApiError(409, "Unexpected safety escalation queue contract.");
    }
    renderSafetyEscalations(queue);
    showSafetyEscalationsMessage(
      queue.total
        ? `${toPersianNumber(queue.total)} ارجاع باز با ترتیب زمانی، بدون اولویت‌بندی پزشکی، بارگذاری شد.`
        : "ارجاع بازی ثبت نشده است؛ این وضعیت مجوز بالینی یا تأیید نبود خطر نیست.",
    );
    setConnectionState(true);
  } catch (error) {
    currentSafetyEscalations = null;
    elements.safetyEscalations.replaceChildren();
    if (error instanceof ApiError && error.status === 401) {
      showLogin();
      elements.loginMessage.textContent = "نشست شما پایان یافته است؛ دوباره وارد شوید.";
      return;
    }
    if (error instanceof ApiError && error.status === 403) {
      showSafetyEscalationsMessage("نقش شما اجازهٔ مشاهدهٔ صف ارجاع‌ها را ندارد.", true);
    } else if (error instanceof ApiError && error.status === 409) {
      showSafetyEscalationsMessage("اعتبار یکی از زنجیره‌های پیگیری تأیید نشد.", true);
    } else {
      showSafetyEscalationsMessage("دریافت صف ارجاع‌ها ممکن نشد؛ دوباره تلاش کنید.", true);
    }
    setConnectionState(false);
  } finally {
    if (requestGeneration === sessionGeneration) {
      setSafetyEscalationsBusy(false);
    }
  }
}

function renderSafetySummary(inbox) {
  elements.safetyContextHash.textContent = inbox.current_clinical_context_sha256;
  elements.safetyContextHash.title = "هش دقیق زمینهٔ بالینی فعلی";
  elements.runSafetyEvaluationButton.hidden = !canRunSafetyEvaluation();

  const fragment = document.createDocumentFragment();
  if (!inbox.evaluation) {
    fragment.append(
      createTextElement(
        "p",
        "empty-state",
        "برای این ویزیت هنوز snapshot ارزیابی ایمنی ثبت نشده است. این وضعیت به‌معنای نبود خطر یا مجوز بالینی نیست.",
      ),
    );
    elements.safetySummary.replaceChildren(fragment);
    return;
  }

  const evaluation = inbox.evaluation;
  const freshness = createTextElement(
    "p",
    inbox.evaluation_matches_current_context ? "safety-fresh" : "context-warning",
    inbox.evaluation_matches_current_context
      ? "این ارزیابی با زمینهٔ بالینی فعلی منطبق است."
      : "زمینهٔ بالینی پس از این ارزیابی تغییر کرده است؛ یافته‌ها snapshot قبلی‌اند و باید پیش از اتکا، ارزیابی تازه اجرا شود.",
  );
  const summaryCard = document.createElement("article");
  summaryCard.className = "safety-summary-card";
  summaryCard.append(
    createSafetyStatus(evaluation.outcome, safetyOutcomeLabels, "safety-outcome"),
    createDefinitionGrid([
      ["زمان ارزیابی", formatDateTime(evaluation.created_at)],
      ["قواعد ارزیابی‌شده", toPersianNumber(evaluation.evaluated_rule_count)],
      ["تعداد یافته‌ها", toPersianNumber(evaluation.triggered_count)],
      [
        "بالاترین شدت",
        evaluation.highest_severity
          ? safetySeverityLabels[evaluation.highest_severity] || evaluation.highest_severity
          : "—",
      ],
      ["نسخهٔ موتور", evaluation.engine_version],
      ["مجوز بالینی", "خیر"],
    ], "safety-summary-grid"),
    createDefinitionGrid([
      ["هش زمینهٔ snapshot", evaluation.clinical_context_sha256],
      ["هش مجموعهٔ قواعد", evaluation.rule_set_sha256],
      ["هش نتیجه", evaluation.result_sha256],
    ], "brief-hashes"),
  );
  fragment.append(freshness, summaryCard);
  elements.safetySummary.replaceChildren(fragment);
}

function createSafetyTrace(trace) {
  const item = document.createElement("li");
  item.className = "safety-trace";
  item.dataset.matched = String(trace.matched);
  const source = trace.source === "intake" ? "شرح حال" : "مشاهدهٔ پاراکلینیکی";
  const code = [trace.code_system, trace.code].filter(Boolean).join(": ");
  item.append(
    createTextElement(
      "strong",
      "",
      `${source} · ${trace.field} · ${trace.operator}`,
    ),
    createTextElement(
      "span",
      "",
      trace.matched ? "شرط منطبق شد" : "شرط منطبق نشد",
    ),
  );
  if (code) {
    item.append(createTextElement("small", "", `کد: ${code}`));
  }
  if (trace.matched_record_ids.length) {
    item.append(createTextElement(
      "small",
      "record-meta",
      `شناسهٔ رکوردهای منطبق: ${trace.matched_record_ids.join("، ")}`,
    ));
  }
  return item;
}

function createSafetyTimeline(timeline) {
  const section = document.createElement("section");
  section.className = "safety-timeline";
  section.append(createTextElement("h4", "", "زنجیرهٔ پیگیری تغییرناپذیر"));
  if (!timeline.reviews.length) {
    section.append(createTextElement(
      "p",
      "empty-state",
      "هنوز رویداد پیگیری برای این یافته ثبت نشده است.",
    ));
    return section;
  }

  const list = document.createElement("ol");
  for (const review of timeline.reviews) {
    const item = document.createElement("li");
    item.className = "safety-review-event";
    item.append(
      createTextElement(
        "strong",
        "",
        `${toPersianNumber(review.sequence)}. ${safetyReviewActionLabels[review.action] || review.action}`,
      ),
      createTextElement(
        "span",
        "",
        `${review.payload.actor.actor_display_name} · ${roleLabels[review.payload.actor.actor_role] || review.payload.actor.actor_role} · ${formatDateTime(review.created_at)}`,
      ),
    );
    if (review.disposition) {
      item.append(createTextElement(
        "span",
        "",
        `وضعیت ثبت‌شده: ${safetyDispositionLabels[review.disposition] || review.disposition}`,
      ));
    }
    if (review.payload.reason_code) {
      item.append(createTextElement(
        "span",
        "",
        `دلیل: ${safetyReasonLabels[review.payload.reason_code] || review.payload.reason_code}`,
      ));
    }
    if (review.payload.note) {
      item.append(createTextElement("p", "safety-review-note", review.payload.note));
    }
    item.append(createTextElement("code", "record-meta", `SHA-256: ${review.sha256}`));
    list.append(item);
  }
  section.append(list);
  return section;
}

function allowedSafetyReviewActions(status) {
  if (!canRecordSafetyReview() || status === "assessed") {
    return [];
  }
  const actions = [];
  if (status === "unreviewed") {
    actions.push("acknowledged");
  }
  if (["unreviewed", "acknowledged"].includes(status)) {
    actions.push("escalated");
  }
  if (currentUser.role === "physician") {
    actions.push("assessed");
  }
  return actions;
}

function createLabeledSelect(labelText, name, labels, values) {
  const label = document.createElement("label");
  label.append(createTextElement("span", "", labelText));
  const select = document.createElement("select");
  select.name = name;
  const prompt = document.createElement("option");
  prompt.value = "";
  prompt.textContent = "انتخاب کنید";
  select.append(prompt);
  for (const value of values) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = labels[value] || value;
    select.append(option);
  }
  label.append(select);
  return { label, select };
}

function syncSafetyReviewForm(form) {
  const action = form.elements.action.value;
  const isAssessment = action === "assessed";
  const noteRequired = action === "escalated" || isAssessment;
  const assessmentFields = form.querySelector(".safety-assessment-fields");
  assessmentFields.hidden = !isAssessment;
  form.elements.disposition.required = isAssessment;
  form.elements.reason_code.required = isAssessment;
  form.elements.note.required = noteRequired;
  if (!isAssessment) {
    form.elements.disposition.value = "";
    form.elements.reason_code.value = "";
  }
}

function createSafetyReviewForm(timeline) {
  const actions = allowedSafetyReviewActions(timeline.review_status);
  if (!actions.length) {
    return null;
  }

  const form = document.createElement("form");
  form.className = "safety-review-form";
  form.dataset.findingId = timeline.finding_id;
  form.dataset.evaluationHash = timeline.evaluation_result_sha256;

  const action = createLabeledSelect(
    "رویداد جدید",
    "action",
    safetyReviewActionLabels,
    actions,
  );
  action.select.required = true;
  action.select.className = "safety-review-action";

  const assessmentFields = document.createElement("div");
  assessmentFields.className = "safety-assessment-fields";
  assessmentFields.hidden = true;
  const disposition = createLabeledSelect(
    "وضعیت ثبت‌شده توسط پزشک",
    "disposition",
    safetyDispositionLabels,
    Object.keys(safetyDispositionLabels),
  );
  const reason = createLabeledSelect(
    "دلیل ثبت‌شده",
    "reason_code",
    safetyReasonLabels,
    Object.keys(safetyReasonLabels),
  );
  assessmentFields.append(disposition.label, reason.label);

  const noteLabel = document.createElement("label");
  noteLabel.append(createTextElement("span", "", "یادداشت پیگیری"));
  const note = document.createElement("textarea");
  note.name = "note";
  note.maxLength = 5000;
  note.rows = 4;
  noteLabel.append(note);

  const acknowledgement = document.createElement("label");
  acknowledgement.className = "acknowledgement";
  const checkbox = document.createElement("input");
  checkbox.type = "checkbox";
  checkbox.name = "acknowledgement";
  checkbox.required = true;
  acknowledgement.append(
    checkbox,
    createTextElement(
      "span",
      "",
      "می‌دانم این رویداد فقط مستندسازی پیگیری است، نتیجهٔ ارزیابی را تغییر نمی‌دهد و مجوز بالینی ایجاد نمی‌کند.",
    ),
  );

  const submit = createTextElement("button", "button button-primary", "ثبت رویداد");
  submit.type = "submit";
  form.append(action.label, assessmentFields, noteLabel, acknowledgement, submit);
  return form;
}

function renderSafetyFindings(inbox) {
  const fragment = document.createDocumentFragment();
  if (!inbox.evaluation) {
    fragment.append(createTextElement(
      "p",
      "empty-state",
      "تا پیش از ثبت یک ارزیابی، یافته‌ای برای نمایش وجود ندارد.",
    ));
  } else if (!inbox.findings.length) {
    fragment.append(createTextElement(
      "p",
      "empty-state",
      "در این snapshot یافته‌ای ثبت نشده است؛ این نتیجه مجوز بالینی یا تأیید نبود خطر نیست.",
    ));
  }

  for (const entry of inbox.findings) {
    const { finding, timeline } = entry;
    const card = document.createElement("article");
    card.className = "safety-finding-card";
    card.dataset.severity = finding.severity;

    const heading = document.createElement("div");
    heading.className = "safety-finding-heading";
    heading.append(
      createTextElement("h4", "", finding.title),
      createSafetyStatus(finding.severity, safetySeverityLabels, "safety-severity"),
      createSafetyStatus(
        timeline.review_status,
        safetyReviewStatusLabels,
        "safety-review-status",
      ),
    );
    const traces = document.createElement("ul");
    traces.className = "safety-traces";
    for (const trace of finding.condition_trace) {
      traces.append(createSafetyTrace(trace));
    }

    card.append(
      heading,
      createTextElement("p", "safety-finding-message", finding.message),
      createDefinitionGrid([
        ["اقدام مقرر در قاعده", safetyRequiredActionLabels[finding.action] || finding.action],
        ["کلید و نسخهٔ قاعده", `${finding.rule_key} · ${finding.rule_version}`],
        ["منابع دانشی", finding.knowledge_fact_ids],
        ["مجوز بالینی", "خیر"],
      ], "fact-meta"),
      createTextElement("h5", "", "ردیابی شرایط بدون نمایش مقدار بیمار"),
      traces,
      createSafetyTimeline(timeline),
    );
    const reviewForm = createSafetyReviewForm(timeline);
    if (reviewForm) {
      card.append(reviewForm);
    }
    fragment.append(card);
  }
  elements.safetyFindings.replaceChildren(fragment);
}

function renderSafetyInbox(inbox) {
  currentSafetyInbox = inbox;
  renderSafetySummary(inbox);
  renderSafetyFindings(inbox);
  elements.safetyContent.hidden = false;
}

async function loadSafetyWorkspace(visitId) {
  const normalizedVisitId = visitId.trim();
  if (!canReadSafety() || !normalizedVisitId || safetyRequestInProgress) {
    return;
  }

  const requestGeneration = sessionGeneration;
  currentSafetyVisitId = normalizedVisitId;
  currentSafetyInbox = null;
  elements.safetyVisitId.value = normalizedVisitId;
  elements.safetyContent.hidden = true;
  elements.safetySummary.replaceChildren();
  elements.safetyFindings.replaceChildren();
  showSafetyMessage("در حال دریافت آخرین snapshot و زنجیره‌های پیگیری…");
  setSafetyBusy(true);

  try {
    const inbox = await apiRequest(
      `/visits/${encodeURIComponent(normalizedVisitId)}/safety-inbox`,
    );
    if (!accessToken || requestGeneration !== sessionGeneration) {
      return;
    }
    renderSafetyInbox(inbox);
    if (!inbox.evaluation) {
      showSafetyMessage(
        canRunSafetyEvaluation()
          ? "ارزیابی ثبت نشده است؛ اجرای ارزیابی فقط snapshot قواعد و زمینهٔ فعلی را ثبت می‌کند."
          : "ارزیابی ثبت نشده است؛ برای اجرا با مدیر یا پزشک هماهنگ کنید.",
      );
    } else if (!inbox.evaluation_matches_current_context) {
      showSafetyMessage(
        "این ارزیابی قدیمی است چون زمینهٔ بالینی تغییر کرده؛ snapshot تازه لازم است.",
        true,
      );
    } else {
      showSafetyMessage("آخرین snapshot و تمام رویدادهای پیگیریِ قابل‌اعتبار بارگذاری شد.");
    }
    setConnectionState(true);
  } catch (error) {
    elements.safetyContent.hidden = true;
    if (error instanceof ApiError && error.status === 401) {
      showLogin();
      elements.loginMessage.textContent = "نشست شما پایان یافته است؛ دوباره وارد شوید.";
      return;
    }
    if (error instanceof ApiError && error.status === 404) {
      showSafetyMessage("ویزیت موردنظر پیدا نشد.", true);
    } else if (error instanceof ApiError && error.status === 403) {
      showSafetyMessage("نقش کاربری شما اجازهٔ مشاهدهٔ صندوق ایمنی را ندارد.", true);
    } else if (error instanceof ApiError && error.status === 409) {
      showSafetyMessage("اعتبار یکی از رکوردهای ذخیره‌شده تأیید نشد.", true);
    } else {
      showSafetyMessage("دریافت صندوق ایمنی ممکن نشد؛ دوباره تلاش کنید.", true);
    }
    setConnectionState(false);
  } finally {
    if (requestGeneration === sessionGeneration) {
      setSafetyBusy(false);
    }
  }
}

async function runSafetyEvaluation() {
  if (
    !canRunSafetyEvaluation()
    || !currentSafetyVisitId
    || !currentSafetyInbox
    || safetyRequestInProgress
  ) {
    return;
  }
  const confirmed = await requestConfirmation({
    kicker: "ثبت snapshot جدید",
    title: "اجرای قواعد ایمنی مصوب",
    copy: (
      "قواعد فعال روی زمینهٔ بالینی فعلی اجرا و نتیجه به‌صورت تغییرناپذیر ثبت می‌شود. "
      + "خروجی تشخیص، توصیهٔ درمانی یا مجوز بالینی نیست. ادامه می‌دهید؟"
    ),
  });
  if (!confirmed) {
    return;
  }

  const requestGeneration = sessionGeneration;
  setSafetyBusy(true, "در حال ارزیابی…");
  showSafetyMessage("در حال اعتبارسنجی زمینه و اجرای قواعد مصوب در backend…");
  try {
    await apiRequest(
      `/visits/${encodeURIComponent(currentSafetyVisitId)}/safety-evaluations`,
      {
        method: "POST",
        body: JSON.stringify({
          expected_clinical_context_sha256: (
            currentSafetyInbox.current_clinical_context_sha256
          ),
        }),
      },
    );
    const inbox = await apiRequest(
      `/visits/${encodeURIComponent(currentSafetyVisitId)}/safety-inbox`,
    );
    if (!accessToken || requestGeneration !== sessionGeneration) {
      return;
    }
    renderSafetyInbox(inbox);
    showSafetyMessage(
      "snapshot جدید ثبت شد؛ نتیجه همچنان مجوز بالینی یا جایگزین قضاوت پزشک نیست.",
    );
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      showLogin();
      elements.loginMessage.textContent = "نشست شما پایان یافته است؛ دوباره وارد شوید.";
      return;
    }
    if (error instanceof ApiError && error.status === 409) {
      showSafetyMessage(
        "زمینه یا قواعد تغییر کرده است؛ صندوق را دوباره بارگذاری و سپس ارزیابی کنید.",
        true,
      );
    } else if (error instanceof ApiError && error.status === 403) {
      showSafetyMessage("اجرای ارزیابی فقط برای مدیر یا پزشک فعال مجاز است.", true);
    } else {
      showSafetyMessage("اجرای ارزیابی ممکن نشد؛ دوباره تلاش کنید.", true);
    }
  } finally {
    if (requestGeneration === sessionGeneration) {
      setSafetyBusy(false);
    }
  }
}

async function recordSafetyReview(form) {
  if (!canRecordSafetyReview() || safetyRequestInProgress || !form.reportValidity()) {
    return;
  }
  const action = form.elements.action.value;
  const confirmed = await requestConfirmation({
    kicker: "ثبت تغییرناپذیر",
    title: safetyReviewActionLabels[action] || "ثبت رویداد پیگیری",
    copy: (
      "این رویداد به زنجیرهٔ پیگیری همان snapshot افزوده می‌شود و قابل ویرایش "
      + "یا حذف نیست. نتیجهٔ ارزیابی را تغییر نمی‌دهد و مجوز بالینی ایجاد نمی‌کند."
    ),
  });
  if (!confirmed) {
    return;
  }

  const payload = {
    action,
    expected_evaluation_result_sha256: form.dataset.evaluationHash,
    note: form.elements.note.value.trim() || null,
  };
  if (action === "assessed") {
    payload.disposition = form.elements.disposition.value;
    payload.reason_code = form.elements.reason_code.value;
  }

  const requestGeneration = sessionGeneration;
  setSafetyBusy(true, "در حال ثبت…");
  showSafetyMessage("در حال ثبت رویداد در زنجیرهٔ تغییرناپذیر…");
  try {
    await apiRequest(
      `/visits/${encodeURIComponent(currentSafetyVisitId)}/safety-findings/${encodeURIComponent(form.dataset.findingId)}/reviews`,
      { method: "POST", body: JSON.stringify(payload) },
    );
    const inbox = await apiRequest(
      `/visits/${encodeURIComponent(currentSafetyVisitId)}/safety-inbox`,
    );
    if (!accessToken || requestGeneration !== sessionGeneration) {
      return;
    }
    renderSafetyInbox(inbox);
    await loadSafetyEscalations({ quiet: true });
    showSafetyMessage("رویداد پیگیری ثبت شد؛ نتیجهٔ ارزیابی بدون تغییر باقی ماند.");
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      showLogin();
      elements.loginMessage.textContent = "نشست شما پایان یافته است؛ دوباره وارد شوید.";
      return;
    }
    if (error instanceof ApiError && error.status === 409) {
      showSafetyMessage(
        "زنجیره یا snapshot تغییر کرده است؛ صندوق را دوباره بارگذاری کنید.",
        true,
      );
    } else if (error instanceof ApiError && error.status === 403) {
      showSafetyMessage("نقش شما اجازهٔ ثبت این نوع رویداد را ندارد.", true);
    } else {
      showSafetyMessage("ثبت رویداد ممکن نشد؛ ورودی‌ها را بررسی کنید.", true);
    }
  } finally {
    if (requestGeneration === sessionGeneration) {
      setSafetyBusy(false);
    }
  }
}

function requestConfirmation({ kicker, title, copy }) {
  return new Promise((resolve) => {
    elements.dialogKicker.textContent = kicker;
    elements.dialogTitle.textContent = title;
    elements.dialogCopy.textContent = copy;
    elements.actionDialog.returnValue = "";
    elements.actionDialog.addEventListener(
      "close",
      () => resolve(elements.actionDialog.returnValue === "confirm"),
      { once: true },
    );
    elements.actionDialog.showModal();
  });
}

function requestActionConfirmation(item, action) {
  const actionLabel = actionLabels[action.code] || action.label;
  return requestConfirmation({
    kicker: "تأیید اقدام",
    title: "تغییر وضعیت جلسه",
    copy: (
      `آیا «${actionLabel}» برای ${item.patient_name} ثبت شود؟ `
      + "این اقدام در backend بررسی و ثبت خواهد شد."
    ),
  });
}

async function createEvidenceBrief(event) {
  event.preventDefault();
  if (
    !canCreateEvidence()
    || !currentEvidenceVisitId
    || !currentClinicalContext
    || !elements.evidenceBriefForm.reportValidity()
  ) {
    return;
  }
  if (!currentClinicalContext.intake || !selectedFacts.size) {
    showEvidenceMessage("حداقل یک منبع و یک شرح حال نهایی لازم است.", true);
    return;
  }

  const confirmed = await requestConfirmation({
    kicker: "ثبت تغییرناپذیر",
    title: "ایجاد خلاصهٔ شواهد",
    copy: (
      `این خلاصه با ${toPersianNumber(selectedFacts.size)} منبع انتخابی و زمینهٔ `
      + "فعلی ثبت می‌شود و قابل ویرایش یا حذف نیست. ادامه می‌دهید؟"
    ),
  });
  if (!confirmed) {
    return;
  }

  const requestGeneration = sessionGeneration;
  setEvidenceBusy(true, "در حال ثبت خلاصه…");
  showEvidenceMessage("در حال اعتبارسنجی زمینه و منابع در backend…");
  try {
    const created = await apiRequest(
      `/visits/${encodeURIComponent(currentEvidenceVisitId)}/evidence-briefs`,
      {
        method: "POST",
        body: JSON.stringify({
          clinical_question: elements.clinicalQuestion.value.trim(),
          expected_clinical_context_sha256: (
            currentClinicalContext.clinical_context_sha256
          ),
          facts: Array.from(selectedFacts.values(), (fact) => ({
            fact_id: fact.id,
            expected_content_sha256: fact.content_sha256,
          })),
        }),
      },
    );
    if (!accessToken || requestGeneration !== sessionGeneration) {
      return;
    }
    currentEvidenceBriefs = await apiRequest(
      `/visits/${encodeURIComponent(currentEvidenceVisitId)}/evidence-briefs`,
    );
    if (!accessToken || requestGeneration !== sessionGeneration) {
      return;
    }
    selectedFacts.clear();
    elements.evidenceBriefForm.reset();
    renderKnowledgeFacts(currentKnowledgeFacts);
    renderEvidenceBriefs(currentEvidenceBriefs);
    showEvidenceMessage(`خلاصهٔ تغییرناپذیر با شناسهٔ ${created.id} ثبت شد.`);
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      showLogin();
      elements.loginMessage.textContent = "نشست شما پایان یافته است؛ دوباره وارد شوید.";
      return;
    }
    if (error instanceof ApiError && error.status === 409) {
      showEvidenceMessage(
        "زمینه یا یکی از منابع تغییر کرده است؛ پیش از ثبت، ویزیت را دوباره بارگذاری کنید.",
        true,
      );
    } else if (error instanceof ApiError && error.status === 403) {
      showEvidenceMessage("ایجاد خلاصه فقط برای پزشک فعال مجاز است.", true);
    } else {
      showEvidenceMessage("ثبت خلاصه ممکن نشد؛ داده‌ها را بررسی و دوباره تلاش کنید.", true);
    }
  } finally {
    if (requestGeneration === sessionGeneration) {
      setEvidenceBusy(false);
      updateSelectedFacts();
    }
  }
}

async function performAction(item, action) {
  const confirmed = await requestActionConfirmation(item, action);

  if (!confirmed) {
    return;
  }

  const requestGeneration = sessionGeneration;
  actionInProgress = true;
  elements.flowBoard.setAttribute("aria-busy", "true");
  elements.dialogConfirm.disabled = true;
  showConsoleMessage("در حال ثبت اقدام…");

  try {
    await apiRequest(`/treatment-sessions/${encodeURIComponent(item.session_id)}/workflow`, {
      method: "PATCH",
      body: JSON.stringify({ operational_status: action.target_status }),
    });
    if (!accessToken || requestGeneration !== sessionGeneration) {
      return;
    }
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
    if (requestGeneration === sessionGeneration) {
      actionInProgress = false;
      elements.flowBoard.removeAttribute("aria-busy");
      elements.dialogConfirm.disabled = false;
    }
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

function availableWorkspaceTabs() {
  return [
    { workspace: "flow", tab: elements.flowTab },
    { workspace: "copilot", tab: elements.copilotTab },
    { workspace: "evidence", tab: elements.evidenceTab },
    { workspace: "safety", tab: elements.safetyTab },
  ].filter((entry) => !entry.tab.hidden);
}

elements.loginForm.addEventListener("submit", handleLogin);
elements.logoutButton.addEventListener("click", showLogin);
elements.refreshButton.addEventListener("click", () => {
  if (activeWorkspace === "copilot" && currentCopilotVisitId) {
    loadCopilotWorkspace(currentCopilotVisitId);
  } else if (activeWorkspace === "evidence" && currentEvidenceVisitId) {
    loadEvidenceWorkspace(currentEvidenceVisitId);
  } else if (activeWorkspace === "safety" && currentSafetyVisitId) {
    loadSafetyEscalations({ quiet: true });
    loadSafetyWorkspace(currentSafetyVisitId);
  } else if (activeWorkspace === "safety") {
    loadSafetyEscalations();
  } else {
    loadFlow();
  }
});
elements.flowTab.addEventListener("click", () => setWorkspace("flow"));
elements.copilotTab.addEventListener("click", () => setWorkspace("copilot"));
elements.evidenceTab.addEventListener("click", () => setWorkspace("evidence"));
elements.safetyTab.addEventListener("click", () => setWorkspace("safety"));
for (const tab of [
  elements.flowTab,
  elements.copilotTab,
  elements.evidenceTab,
  elements.safetyTab,
]) {
  tab.addEventListener("keydown", (event) => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) {
      return;
    }
    event.preventDefault();
    const entries = availableWorkspaceTabs();
    const currentIndex = Math.max(
      0,
      entries.findIndex((entry) => entry.workspace === activeWorkspace),
    );
    let targetIndex = currentIndex;
    if (event.key === "Home") {
      targetIndex = 0;
    } else if (event.key === "End") {
      targetIndex = entries.length - 1;
    } else if (event.key === "ArrowLeft") {
      targetIndex = (currentIndex + 1) % entries.length;
    } else {
      targetIndex = (currentIndex - 1 + entries.length) % entries.length;
    }
    const target = entries[targetIndex];
    setWorkspace(target.workspace);
    target.tab.focus();
  });
}
elements.copilotVisitForm.addEventListener("submit", (event) => {
  event.preventDefault();
  if (elements.copilotVisitForm.reportValidity()) {
    loadCopilotWorkspace(elements.copilotVisitId.value);
  }
});
elements.evidenceVisitForm.addEventListener("submit", (event) => {
  event.preventDefault();
  if (elements.evidenceVisitForm.reportValidity()) {
    loadEvidenceWorkspace(elements.evidenceVisitId.value);
  }
});
elements.knowledgeSearchForm.addEventListener("submit", (event) => {
  event.preventDefault();
  loadApprovedFacts(elements.knowledgeSearch.value);
});
elements.knowledgeResetButton.addEventListener("click", () => {
  elements.knowledgeSearch.value = "";
  loadApprovedFacts();
});
elements.knowledgeFacts.addEventListener("change", (event) => {
  const checkbox = event.target.closest("input[data-fact-id]");
  if (!checkbox || !canCreateEvidence()) {
    return;
  }
  const fact = currentKnowledgeFacts.find(
    (candidate) => candidate.id === checkbox.dataset.factId,
  );
  if (!fact) {
    checkbox.checked = false;
    showEvidenceMessage("این منبع دیگر در نتیجهٔ فعلی وجود ندارد؛ دوباره جست‌وجو کنید.", true);
    return;
  }

  if (checkbox.checked) {
    if (selectedFacts.size >= MAX_SELECTED_FACTS) {
      checkbox.checked = false;
      showEvidenceMessage("حداکثر ۲۰ منبع را می‌توان در یک خلاصه ثبت کرد.", true);
      return;
    }
    selectedFacts.set(fact.id, fact);
  } else {
    selectedFacts.delete(fact.id);
  }
  showEvidenceMessage("");
  updateSelectedFacts();
});
elements.clinicalQuestion.addEventListener("input", updateCreateButton);
elements.evidenceAcknowledgement.addEventListener("change", updateCreateButton);
elements.evidenceBriefForm.addEventListener("submit", createEvidenceBrief);
elements.safetyVisitForm.addEventListener("submit", (event) => {
  event.preventDefault();
  if (elements.safetyVisitForm.reportValidity()) {
    loadSafetyWorkspace(elements.safetyVisitId.value);
  }
});
elements.runSafetyEvaluationButton.addEventListener("click", runSafetyEvaluation);
elements.loadSafetyEscalationsButton.addEventListener("click", () => {
  loadSafetyEscalations();
});
elements.safetyEscalations.addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-escalation-visit-id]");
  if (!button || safetyRequestInProgress) {
    return;
  }
  await loadSafetyWorkspace(button.dataset.escalationVisitId);
});
elements.safetyFindings.addEventListener("change", (event) => {
  if (!event.target.matches("select[name='action']")) {
    return;
  }
  const form = event.target.closest("form.safety-review-form");
  if (form) {
    syncSafetyReviewForm(form);
  }
});
elements.safetyFindings.addEventListener("submit", async (event) => {
  const form = event.target.closest("form.safety-review-form");
  if (!form) {
    return;
  }
  event.preventDefault();
  await recordSafetyReview(form);
});

elements.flowBoard.addEventListener("click", async (event) => {
  const copilotButton = event.target.closest("button[data-copilot-visit-id]");
  if (copilotButton && canReadCopilot() && !copilotRequestInProgress) {
    setWorkspace("copilot");
    await loadCopilotWorkspace(copilotButton.dataset.copilotVisitId);
    return;
  }

  const safetyButton = event.target.closest("button[data-safety-visit-id]");
  if (safetyButton && canReadSafety() && !safetyRequestInProgress) {
    setWorkspace("safety");
    await loadSafetyWorkspace(safetyButton.dataset.safetyVisitId);
    return;
  }

  const evidenceButton = event.target.closest("button[data-evidence-visit-id]");
  if (evidenceButton && canReadEvidence() && !evidenceRequestInProgress) {
    setWorkspace("evidence");
    await loadEvidenceWorkspace(evidenceButton.dataset.evidenceVisitId);
    return;
  }

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
  if (!document.hidden && accessToken && activeWorkspace === "flow") {
    loadFlow({ quiet: true });
  }
});

window.addEventListener("online", () => {
  setConnectionState(true);
  if (activeWorkspace === "flow") {
    loadFlow({ quiet: true });
  } else if (activeWorkspace === "copilot" && currentCopilotVisitId) {
    loadCopilotWorkspace(currentCopilotVisitId);
  } else if (activeWorkspace === "evidence" && currentEvidenceVisitId) {
    loadEvidenceWorkspace(currentEvidenceVisitId);
  } else if (activeWorkspace === "safety" && currentSafetyVisitId) {
    loadSafetyEscalations({ quiet: true });
    loadSafetyWorkspace(currentSafetyVisitId);
  } else if (activeWorkspace === "safety") {
    loadSafetyEscalations({ quiet: true });
  }
});

window.addEventListener("offline", () => setConnectionState(false));

elements.username.focus();
