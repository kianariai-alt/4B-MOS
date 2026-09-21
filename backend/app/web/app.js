"use strict";

const API_BASE = "/api/v1";
const REFRESH_INTERVAL_MS = 30_000;
const MAX_SELECTED_FACTS = 20;
const EVIDENCE_READ_ROLES = new Set(["admin", "physician", "nurse"]);

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
  evidenceTab: document.querySelector("#evidence-tab"),
  flowWorkspace: document.querySelector("#flow-workspace"),
  evidenceWorkspace: document.querySelector("#evidence-workspace"),
  flowBoard: document.querySelector("#flow-board"),
  metricActive: document.querySelector("#metric-active"),
  metricCheckedIn: document.querySelector("#metric-checked-in"),
  metricReady: document.querySelector("#metric-ready"),
  metricTreatment: document.querySelector("#metric-treatment"),
  metricAttention: document.querySelector("#metric-attention"),
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
let evidenceRequestInProgress = false;
let activeWorkspace = "flow";
let currentEvidenceVisitId = null;
let currentClinicalContext = null;
let currentKnowledgeFacts = [];
let currentEvidenceBriefs = [];
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

function canReadEvidence() {
  return Boolean(currentUser && EVIDENCE_READ_ROLES.has(currentUser.role));
}

function canCreateEvidence() {
  return Boolean(currentUser && currentUser.role === "physician");
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

function showEvidenceMessage(message, isError = false) {
  elements.evidenceMessage.textContent = message;
  elements.evidenceMessage.classList.toggle("is-error", isError);
  elements.evidenceMessage.hidden = !message;
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
  if (workspace === "evidence" && !canReadEvidence()) {
    return;
  }

  activeWorkspace = workspace;
  const isFlow = workspace === "flow";
  elements.flowWorkspace.hidden = !isFlow;
  elements.evidenceWorkspace.hidden = isFlow;
  elements.flowTab.setAttribute("aria-selected", String(isFlow));
  elements.evidenceTab.setAttribute("aria-selected", String(!isFlow));
  elements.flowTab.tabIndex = isFlow ? 0 : -1;
  elements.evidenceTab.tabIndex = isFlow ? -1 : 0;

  if (isFlow) {
    startAutoRefresh();
    if (accessToken && currentFlow) {
      loadFlow({ quiet: true });
    }
  } else {
    stopAutoRefresh();
  }
}

function showLogin() {
  stopAutoRefresh();
  sessionGeneration += 1;
  accessToken = null;
  currentUser = null;
  requestInProgress = false;
  evidenceRequestInProgress = false;
  actionInProgress = false;
  elements.refreshButton.disabled = false;
  elements.refreshButton.textContent = "تازه‌سازی";
  elements.loadEvidenceButton.disabled = false;
  elements.loadEvidenceButton.textContent = "بارگذاری زمینه و خلاصه‌ها";
  elements.knowledgeSearchButton.disabled = false;
  elements.knowledgeResetButton.disabled = false;
  elements.dialogConfirm.disabled = false;
  resetOperationalState();
  resetEvidenceState();
  activeWorkspace = "flow";
  elements.flowWorkspace.hidden = false;
  elements.evidenceWorkspace.hidden = true;
  elements.flowTab.setAttribute("aria-selected", "true");
  elements.evidenceTab.setAttribute("aria-selected", "false");
  elements.flowTab.tabIndex = 0;
  elements.evidenceTab.tabIndex = -1;
  elements.evidenceTab.hidden = true;
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
  elements.evidenceTab.hidden = !canReadEvidence();
  elements.evidenceComposer.hidden = !canCreateEvidence();
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

elements.loginForm.addEventListener("submit", handleLogin);
elements.logoutButton.addEventListener("click", showLogin);
elements.refreshButton.addEventListener("click", () => {
  if (activeWorkspace === "evidence" && currentEvidenceVisitId) {
    loadEvidenceWorkspace(currentEvidenceVisitId);
  } else {
    loadFlow();
  }
});
elements.flowTab.addEventListener("click", () => setWorkspace("flow"));
elements.evidenceTab.addEventListener("click", () => setWorkspace("evidence"));
for (const tab of [elements.flowTab, elements.evidenceTab]) {
  tab.addEventListener("keydown", (event) => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) {
      return;
    }
    event.preventDefault();
    const targetWorkspace = event.key === "Home"
      ? "flow"
      : event.key === "End"
        ? "evidence"
        : activeWorkspace === "flow" ? "evidence" : "flow";
    if (targetWorkspace === "evidence" && !canReadEvidence()) {
      return;
    }
    setWorkspace(targetWorkspace);
    (targetWorkspace === "flow" ? elements.flowTab : elements.evidenceTab).focus();
  });
}
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

elements.flowBoard.addEventListener("click", async (event) => {
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
  } else if (currentEvidenceVisitId) {
    loadEvidenceWorkspace(currentEvidenceVisitId);
  }
});

window.addEventListener("offline", () => setConnectionState(false));

elements.username.focus();
