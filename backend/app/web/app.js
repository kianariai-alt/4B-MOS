"use strict";

const API_BASE = "/api/v1";
const REFRESH_INTERVAL_MS = 30_000;
const MAX_SELECTED_FACTS = 20;
const COPILOT_READ_ROLES = new Set(["admin", "physician"]);
const LEARNING_READ_ROLES = new Set(["admin", "physician"]);
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

const pilotCheckLabels = Object.freeze({
  runtime_configuration: "پیکربندی Production",
  database_schema: "Schema دیتابیس",
  database_engine: "موتور دیتابیس",
  role_separation: "تفکیک نقش‌های کارکنان",
  protocol_registry: "Registry و Lineage پروتکل",
  clinical_safety_registry: "Registry قواعد ایمنی",
  clinical_feedback_integrity: "یکپارچگی Decision → Treatment → Outcome",
  protocol_governance_integrity: "یکپارچگی Governance history",
});

const pilotManualGateLabels = Object.freeze({
  clinical_protocol_signoff: "تأیید بالینی محتوای پروتکل‌ها",
  clinical_safety_signoff: "تأیید بالینی قواعد ایمنی",
  backup_restore: "تمرین Backup / Restore",
  security_perimeter: "بازبینی امنیت محیط و شبکه",
  monitoring_alerting: "اعتبارسنجی Monitoring / Alerting",
  human_ui_acceptance: "پذیرش انسانی رابط کاربری",
  privacy_retention_legal: "بازبینی حریم خصوصی، نگهداری و الزامات حقوقی",
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

const learningFlagLabels = Object.freeze({
  fewer_than_5_treatments_with_outcomes: "کمتر از ۵ درمان دارای outcome",
  no_decision_linked_treatments: "هنوز Treatment متصل به Decision ثبت نشده",
  patient_rating_incomplete: "پوشش امتیاز بیمار ناقص است",
  physician_rating_incomplete: "پوشش امتیاز پزشک ناقص است",
  pain_score_incomplete: "پوشش pain score ناقص است",
  function_score_incomplete: "پوشش function score ناقص است",
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
  learningTab: document.querySelector("#learning-tab"),
  evidenceTab: document.querySelector("#evidence-tab"),
  safetyTab: document.querySelector("#safety-tab"),
  flowWorkspace: document.querySelector("#flow-workspace"),
  copilotWorkspace: document.querySelector("#copilot-workspace"),
  learningWorkspace: document.querySelector("#learning-workspace"),
  evidenceWorkspace: document.querySelector("#evidence-workspace"),
  safetyWorkspace: document.querySelector("#safety-workspace"),
  pilotReadinessTab: document.querySelector("#pilot-readiness-tab"),
  pilotReadinessWorkspace: document.querySelector("#pilot-readiness-workspace"),
  loadPilotReadinessButton: document.querySelector("#load-pilot-readiness-button"),
  pilotReadinessMessage: document.querySelector("#pilot-readiness-message"),
  pilotReadinessSummary: document.querySelector("#pilot-readiness-summary"),
  pilotReadinessChecks: document.querySelector("#pilot-readiness-checks"),
  pilotManualGates: document.querySelector("#pilot-manual-gates"),
  pilotLaunchPreview: document.querySelector("#pilot-launch-preview"),
  pilotLaunchHistory: document.querySelector("#pilot-launch-history"),
  freezePilotLaunchPackageButton: document.querySelector(
    "#freeze-pilot-launch-package-button",
  ),
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
  copilotDecisionSection: document.querySelector("#copilot-decision-section"),
  copilotDecisionForm: document.querySelector("#copilot-decision-form"),
  copilotDecisionType: document.querySelector("#copilot-decision-type"),
  copilotDecisionOptions: document.querySelector("#copilot-decision-options"),
  copilotDecisionRationale: document.querySelector("#copilot-decision-rationale"),
  copilotDecisionModification: document.querySelector("#copilot-decision-modification"),
  copilotPatientPreference: document.querySelector("#copilot-patient-preference"),
  createTreatmentDecisionButton: document.querySelector("#create-treatment-decision-button"),
  copilotDecisionMessage: document.querySelector("#copilot-decision-message"),
  copilotDecisionHistory: document.querySelector("#copilot-decision-history"),
  copilotOutcomes: document.querySelector("#copilot-outcomes"),
  copilotEvidence: document.querySelector("#copilot-evidence"),
  loadLearningButton: document.querySelector("#load-learning-button"),
  learningMessage: document.querySelector("#learning-message"),
  learningReviewHash: document.querySelector("#learning-review-hash"),
  learningSummary: document.querySelector("#learning-summary"),
  learningProtocols: document.querySelector("#learning-protocols"),
  learningGovernanceSignals: document.querySelector("#learning-governance-signals"),
  learningGovernanceCases: document.querySelector("#learning-governance-cases"),
  learningGovernanceMessage: document.querySelector("#learning-governance-message"),
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
let decisionRequestInProgress = false;
let learningRequestInProgress = false;
let governanceRequestInProgress = false;
let evidenceRequestInProgress = false;
let safetyRequestInProgress = false;
let safetyEscalationRequestInProgress = false;
let pilotReadinessRequestInProgress = false;
let activeWorkspace = "flow";
let currentCopilotVisitId = null;
let currentCopilotSnapshot = null;
let currentTreatmentRoadmap = null;
let currentTreatmentDecisions = [];
let currentLearningReview = null;
let currentGovernanceSignals = [];
let currentGovernanceCases = [];
let currentEvidenceVisitId = null;
let currentClinicalContext = null;
let currentKnowledgeFacts = [];
let currentEvidenceBriefs = [];
let currentSafetyVisitId = null;
let currentSafetyInbox = null;
let currentSafetyEscalations = null;
let currentPilotReadiness = null;
let currentPilotGateStatuses = [];
let currentPilotLaunchPreview = null;
let currentPilotLaunchPackages = [];
let currentPilotReleaseDecisions = [];
let sessionGeneration = 0;
const selectedFacts = new Map();
const selectedDecisionProtocols = new Set();

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

function canCreateTreatmentDecision() {
  return Boolean(currentUser && currentUser.role === "physician");
}

function canReadLearning() {
  return Boolean(currentUser && LEARNING_READ_ROLES.has(currentUser.role));
}

function canCreateGovernanceCase() {
  return Boolean(currentUser && currentUser.role === "physician");
}

function canReviewGovernanceClinically(caseItem) {
  return Boolean(
    currentUser
    && currentUser.role === "physician"
    && currentUser.id !== caseItem.created_by_user_id
    && !caseItem.release
    && !caseItem.recovery
  );
}

function canReviewGovernanceOperationally() {
  return Boolean(currentUser && currentUser.role === "admin");
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

function canReadPilotReadiness() {
  return Boolean(
    currentUser
    && ["admin", "physician"].includes(currentUser.role)
  );
}

function pilotGateRequiredRole(gateName) {
  return [
    "clinical_protocol_signoff",
    "clinical_safety_signoff",
  ].includes(gateName)
    ? "physician"
    : "admin";
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

function showDecisionMessage(message, isError = false) {
  elements.copilotDecisionMessage.textContent = message;
  elements.copilotDecisionMessage.classList.toggle("is-error", isError);
  elements.copilotDecisionMessage.hidden = !message;
}

function showLearningMessage(message, isError = false) {
  elements.learningMessage.textContent = message;
  elements.learningMessage.classList.toggle("is-error", isError);
  elements.learningMessage.hidden = !message;
}

function showGovernanceMessage(message, isError = false) {
  elements.learningGovernanceMessage.textContent = message;
  elements.learningGovernanceMessage.classList.toggle("is-error", isError);
  elements.learningGovernanceMessage.hidden = !message;
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

function showPilotReadinessMessage(message, isError = false) {
  elements.pilotReadinessMessage.textContent = message;
  elements.pilotReadinessMessage.classList.toggle("is-error", isError);
  elements.pilotReadinessMessage.hidden = !message;
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

function setLearningBusy(isBusy) {
  learningRequestInProgress = isBusy;
  elements.loadLearningButton.disabled = isBusy;
  elements.loadLearningButton.textContent = isBusy
    ? "در حال دریافت…"
    : "تازه‌سازی مرور یادگیری";
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

function setPilotReadinessBusy(isBusy) {
  pilotReadinessRequestInProgress = isBusy;
  elements.loadPilotReadinessButton.disabled = isBusy;
  elements.loadPilotReadinessButton.textContent = isBusy
    ? "در حال بررسی…"
    : "اجرای دوبارهٔ Gate";
  elements.freezePilotLaunchPackageButton.disabled = isBusy;
  for (const field of [
    ...elements.pilotManualGates.querySelectorAll(
      "button, select, textarea, input",
    ),
    ...elements.pilotLaunchHistory.querySelectorAll(
      "button, select, textarea, input",
    ),
  ]) {
    field.disabled = isBusy;
  }
}

function resetCopilotState() {
  currentCopilotVisitId = null;
  currentCopilotSnapshot = null;
  currentTreatmentRoadmap = null;
  currentTreatmentDecisions = [];
  selectedDecisionProtocols.clear();
  elements.copilotVisitForm.reset();
  elements.copilotDecisionForm.reset();
  elements.copilotDecisionSection.hidden = true;
  elements.copilotContent.hidden = true;
  elements.copilotSummary.replaceChildren();
  elements.copilotEscalations.replaceChildren();
  elements.copilotRoadmap.replaceChildren();
  elements.copilotDecisionOptions.replaceChildren();
  elements.copilotDecisionHistory.replaceChildren();
  elements.copilotOutcomes.replaceChildren();
  elements.copilotEvidence.replaceChildren();
  showCopilotMessage("");
  showDecisionMessage("");
}

function formatCoverage(coverage) {
  if (!coverage || coverage.total_count === 0) {
    return "بدون داده";
  }
  const percent = coverage.proportion === null
    ? "—"
    : `${Number(coverage.proportion * 100).toLocaleString("fa-IR", { maximumFractionDigits: 1 })}٪`;
  return (
    `${toPersianNumber(coverage.present_count)} از `
    + `${toPersianNumber(coverage.total_count)} · ${percent}`
  );
}

function renderClinicalLearningReview(review) {
  currentLearningReview = review;
  elements.learningReviewHash.textContent = review.review_sha256;

  const quality = review.data_quality;
  const summary = document.createElement("article");
  summary.className = "context-card context-intake";
  summary.append(
    createTextElement("h4", "", "پوشش زنجیرهٔ یادگیری"),
    createDefinitionGrid([
      ["رویدادهای Decision", toPersianNumber(quality.decision_event_count)],
      ["Decision فعلی", toPersianNumber(quality.current_decision_count)],
      ["Decision فعلی قابل اجرا", toPersianNumber(quality.current_actionable_decision_count)],
      ["Treatment متصل به Decision", toPersianNumber(quality.decision_linked_treatment_count)],
      ["Treatment قدیمی/بدون Decision", toPersianNumber(quality.legacy_or_unlinked_treatment_count)],
      ["Treatment دارای Outcome", toPersianNumber(quality.treatment_with_outcome_count)],
      ["کل Outcomeها", toPersianNumber(quality.outcome_record_count)],
      ["پوشش امتیاز بیمار", formatCoverage(quality.patient_rating_coverage)],
      ["پوشش امتیاز پزشک", formatCoverage(quality.physician_rating_coverage)],
      ["پوشش pain score", formatCoverage(quality.pain_score_coverage)],
      ["پوشش function score", formatCoverage(quality.function_score_coverage)],
      ["Outcome دارای عارضه ثبت‌شده", toPersianNumber(quality.outcome_with_documented_adverse_event_count)],
      ["رتبه‌بندی درمان", "ندارد"],
      ["Learning score", "ساخته نمی‌شود"],
    ], "safety-summary-grid"),
  );
  elements.learningSummary.replaceChildren(summary);

  const fragment = document.createDocumentFragment();
  if (!review.protocols.length) {
    fragment.append(createTextElement(
      "p",
      "empty-state",
      "هنوز پروتکل نسخه‌بندی‌شده‌ای برای مرور یادگیری وجود ندارد.",
    ));
  }
  for (const item of review.protocols) {
    const card = document.createElement("article");
    card.className = "evidence-brief-card";
    card.append(
      createTextElement(
        "h4",
        "",
        `${item.protocol_name} · ${item.protocol_code} · نسخه ${item.protocol_version}`,
      ),
      createDefinitionGrid([
        ["نوع درمان", item.treatment_type],
        ["وضعیت پروتکل", item.is_active ? "فعال" : "غیرفعال"],
        ["ارجاع در Decisionها", toPersianNumber(item.decision_event_reference_count)],
        ["ارجاع در Decision فعلی", toPersianNumber(item.current_decision_reference_count)],
        ["Treatmentها", toPersianNumber(item.treatment_count)],
        ["Treatment متصل به Decision", toPersianNumber(item.decision_linked_treatment_count)],
        ["Treatment دارای Outcome", toPersianNumber(item.treatment_with_outcome_count)],
        ["Outcome record", toPersianNumber(item.outcome_record_count)],
        ["حجم داده", roadmapVolumeLabels[item.data_volume] || item.data_volume],
        ["Follow-up ۲۸–۷۰ روز", toPersianNumber(item.follow_up_counts.early_28_to_70_days)],
        ["Follow-up ۷۱–۱۸۰ روز", toPersianNumber(item.follow_up_counts.intermediate_71_to_180_days)],
        ["Follow-up ۱۸۱–۳۶۵ روز", toPersianNumber(item.follow_up_counts.long_term_181_to_365_days)],
        ["خارج از پنجره‌های استاندارد", toPersianNumber(item.follow_up_counts.outside_standard_windows)],
        ["پوشش امتیاز بیمار", formatCoverage(item.patient_rating_coverage)],
        ["پوشش امتیاز پزشک", formatCoverage(item.physician_rating_coverage)],
        ["پوشش pain score", formatCoverage(item.pain_score_coverage)],
        ["پوشش function score", formatCoverage(item.function_score_coverage)],
      ], "safety-summary-grid"),
    );

    if (item.data_quality_flags.length) {
      const list = document.createElement("ul");
      list.className = "safety-flags";
      for (const flag of item.data_quality_flags) {
        list.append(createTextElement(
          "li",
          "",
          learningFlagLabels[flag] || flag,
        ));
      }
      card.append(list);
    } else {
      card.append(createTextElement(
        "p",
        "queue-current",
        "در فیلدهای اصلی outcome این نسخه، missingness ثبت‌شده‌ای دیده نمی‌شود.",
      ));
    }
    card.append(createTextElement(
      "p",
      "ordering-note",
      "این کارت کیفیت و حجم داده را توصیف می‌کند؛ امتیاز عملکرد یا مقایسهٔ اثربخشی درمان نیست.",
    ));
    fragment.append(card);
  }
  elements.learningProtocols.replaceChildren(fragment);
}

const governanceSignalLabels = Object.freeze({
  insufficient_outcome_volume: "حجم outcome برای تحلیل انسانی کافی نیست",
  limited_outcome_volume: "حجم outcome هنوز محدود است",
  no_decision_linked_treatments: "Treatment متصل به Decision ثبت نشده است",
  patient_rating_incomplete: "امتیاز بیمار ناقص است",
  physician_rating_incomplete: "امتیاز پزشک ناقص است",
  pain_score_incomplete: "Pain score ناقص است",
  function_score_incomplete: "Function score ناقص است",
  early_followup_gap: "شکاف follow-up زودهنگام",
  intermediate_followup_gap: "شکاف follow-up میان‌مدت",
  long_term_followup_gap: "شکاف follow-up بلندمدت",
  eligible_for_human_pattern_review: "داده برای مرور الگو توسط انسان بالغ‌تر شده است",
});

const governanceStatusLabels = Object.freeze({
  awaiting_clinical_review: "در انتظار مرور بالینی مستقل",
  changes_requested: "نیازمند اصلاح",
  clinically_rejected: "رد بالینی",
  awaiting_operational_review: "در انتظار مرور عملیاتی",
  operational_hold: "توقف عملیاتی",
  approved_for_manual_action: "تأییدشده برای اقدام دستی",
  released: "منتشرشده / اجراشده",
  recovered: "Recovery اجراشده",
});

const governanceCaseTypeLabels = Object.freeze({
  collect_more_data: "جمع‌آوری دادهٔ بیشتر",
  monitor_no_change: "پایش بدون تغییر",
  revision_candidate: "نامزد بازنگری نسخه",
  deactivation_candidate: "نامزد غیرفعال‌سازی",
  reactivation_candidate: "نامزد فعال‌سازی مجدد",
  rollback_revision_candidate: "نامزد بازگشت Governed به نسخه قبلی",
});

function appendGovernanceField(form, labelText, field) {
  const label = document.createElement("label");
  label.textContent = labelText;
  form.append(label, field);
}

function governanceTextarea({ name, minLength = 0, maxLength = 5000, rows = 3 }) {
  const field = document.createElement("textarea");
  field.name = name;
  field.rows = rows;
  field.maxLength = maxLength;
  if (minLength) {
    field.minLength = minLength;
    field.required = true;
  }
  return field;
}

function governanceSubmitButton(label) {
  const button = createTextElement(
    "button",
    "button button-secondary",
    label,
  );
  button.type = "submit";
  return button;
}

function renderGovernanceSignals(signals) {
  currentGovernanceSignals = signals;
  const fragment = document.createDocumentFragment();

  if (!signals.length) {
    fragment.append(createTextElement(
      "p",
      "empty-state",
      "هنوز پروتکلی برای Governance review ثبت نشده است.",
    ));
  }

  for (const item of signals) {
    const card = document.createElement("article");
    card.className = "evidence-brief-card";
    card.append(
      createTextElement(
        "h4",
        "",
        `${item.protocol_name} · ${item.protocol_code} · نسخه ${item.protocol_version}`,
      ),
      createDefinitionGrid([
        ["نوع درمان", item.treatment_type],
        ["حجم داده", item.data_volume],
        ["فعال", item.is_active ? "بله" : "خیر"],
        ["تغییر پیشنهادی سیستم", "خیر"],
      ]),
    );

    const list = document.createElement("ul");
    if (!item.signals.length) {
      list.append(createTextElement(
        "li",
        "",
        "Signal داده‌ای خاصی در مرور فعلی ثبت نشده است.",
      ));
    } else {
      for (const signal of item.signals) {
        list.append(createTextElement(
          "li",
          "",
          governanceSignalLabels[signal] || signal,
        ));
      }
    }
    card.append(list);

    if (canCreateGovernanceCase()) {
      const form = document.createElement("form");
      form.className = "brief-form governance-case-form";
      form.dataset.protocolCode = item.protocol_code;
      form.dataset.protocolVersion = item.protocol_version;

      const caseType = document.createElement("select");
      caseType.name = "case_type";
      caseType.required = true;
      const caseOptions = [
        ["collect_more_data", "جمع‌آوری دادهٔ بیشتر"],
        ["monitor_no_change", "پایش بدون تغییر"],
      ];
      if (item.is_active) {
        caseOptions.push([
          "deactivation_candidate",
          "نامزد غیرفعال‌سازی",
        ]);
      }
      for (const [value, labelText] of caseOptions) {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = labelText;
        caseType.append(option);
      }
      appendGovernanceField(form, "نوع پرونده", caseType);
      appendGovernanceField(
        form,
        "دلیل پزشک",
        governanceTextarea({
          name: "rationale",
          minLength: 20,
          maxLength: 5000,
          rows: 4,
        }),
      );
      appendGovernanceField(
        form,
        "داده/شواهد موردنیاز، هر مورد در یک خط",
        governanceTextarea({
          name: "evidence_needed",
          maxLength: 3000,
          rows: 3,
        }),
      );
      form.append(governanceSubmitButton("باز کردن پرونده Governance"));
      card.append(form);
    }
    fragment.append(card);
  }

  elements.learningGovernanceSignals.replaceChildren(fragment);
}

function renderGovernanceCases(cases) {
  currentGovernanceCases = cases;
  const fragment = document.createDocumentFragment();
  const recoverySourceReleaseIds = new Set(
    cases
      .filter((item) => item.source_release_id)
      .map((item) => item.source_release_id),
  );

  if (!cases.length) {
    fragment.append(createTextElement(
      "p",
      "empty-state",
      "هنوز پرونده Governance ثبت نشده است.",
    ));
  }

  for (const item of cases) {
    const card = document.createElement("article");
    card.className = "evidence-brief-card";
    card.append(
      createTextElement(
        "h4",
        "",
        `${item.protocol_code} · ${item.protocol_version} · ${governanceCaseTypeLabels[item.case_type] || item.case_type}`,
      ),
      createDefinitionGrid([
        ["وضعیت", governanceStatusLabels[item.status] || item.status],
        ["زمان ایجاد", formatDateTime(item.created_at)],
        ["Reviewها", toPersianNumber(item.reviews.length)],
        ["SHA-256 پرونده", item.sha256],
        ["تغییر خودکار پروتکل", "خیر"],
      ]),
      createTextElement("p", "", item.rationale),
    );

    if (item.evidence_needed.length) {
      card.append(createTextElement(
        "p",
        "ordering-note",
        `نیاز داده/شواهد: ${item.evidence_needed.join("، ")}`,
      ));
    }

    if (item.proposed_protocol) {
      card.append(createTextElement(
        "p",
        "ordering-note",
        `نسخه پیشنهادی: ${item.proposed_protocol.version} · فقط برای اقدام دستی پس از Governance`,
      ));
    }

    for (const review of item.reviews) {
      card.append(createTextElement(
        "p",
        "ordering-note",
        `${review.action} · ${formatDateTime(review.created_at)} · ${review.rationale}`,
      ));
    }

    if (item.release) {
      card.append(
        createTextElement("h5", "context-subheading", "Governed Release"),
        createDefinitionGrid([
          ["Action", item.release.action],
          ["زمان اجرا", formatDateTime(item.release.created_at)],
          ["Release ID", item.release.id],
          ["SHA-256 Release", item.release.sha256],
          [
            "نسخه منتشرشده",
            item.release.released_protocol_snapshot
              ? item.release.released_protocol_snapshot.version
              : "—",
          ],
          ["حفظ تاریخچه", item.release.preserves_history ? "بله" : "خیر"],
        ], "safety-summary-grid"),
        createTextElement(
          "p",
          "ordering-note",
          `یادداشت اجرا: ${item.release.execution_note}`,
        ),
      );

      if (
        canCreateGovernanceCase()
        && !recoverySourceReleaseIds.has(item.release.id)
      ) {
        const recoveryCaseForm = document.createElement("form");
        recoveryCaseForm.className = "brief-form governance-recovery-case-form";
        recoveryCaseForm.dataset.releaseId = item.release.id;
        recoveryCaseForm.dataset.releaseSha256 = item.release.sha256;
        appendGovernanceField(
          recoveryCaseForm,
          "دلیل پزشک برای باز کردن Recovery Case",
          governanceTextarea({
            name: "rationale",
            minLength: 20,
            maxLength: 5000,
            rows: 4,
          }),
        );
        appendGovernanceField(
          recoveryCaseForm,
          "داده/شواهد موردنیاز، هر مورد در یک خط",
          governanceTextarea({
            name: "evidence_needed",
            maxLength: 3000,
            rows: 3,
          }),
        );
        recoveryCaseForm.append(
          governanceSubmitButton("باز کردن Governed Recovery Case"),
        );
        card.append(recoveryCaseForm);
      }
    }

    if (item.recovery) {
      card.append(
        createTextElement("h5", "context-subheading", "Governed Recovery"),
        createDefinitionGrid([
          ["Action", item.recovery.action],
          ["زمان اجرا", formatDateTime(item.recovery.created_at)],
          ["Recovery ID", item.recovery.id],
          ["Source Release ID", item.recovery.source_release_id],
          ["SHA-256 Recovery", item.recovery.sha256],
          [
            "نسخه فعال‌شده",
            item.recovery.after_snapshots.reactivated_protocol.version,
          ],
          [
            "نسخه غیرفعال‌شده",
            item.recovery.after_snapshots.deactivated_protocol
              ? item.recovery.after_snapshots.deactivated_protocol.version
              : "—",
          ],
          ["حفظ تاریخچه", item.recovery.preserves_history ? "بله" : "خیر"],
        ], "safety-summary-grid"),
        createTextElement(
          "p",
          "ordering-note",
          `یادداشت Recovery: ${item.recovery.execution_note}`,
        ),
      );
    }

    if (
      canReviewGovernanceOperationally()
      && item.status === "approved_for_manual_action"
      && !item.release
      && ["revision_candidate", "deactivation_candidate"].includes(item.case_type)
    ) {
      const releaseForm = document.createElement("form");
      releaseForm.className = "brief-form governance-release-form";
      releaseForm.dataset.caseId = item.id;
      releaseForm.dataset.caseSha256 = item.sha256;
      appendGovernanceField(
        releaseForm,
        "یادداشت اجرای Release",
        governanceTextarea({
          name: "execution_note",
          minLength: 10,
          maxLength: 5000,
          rows: 3,
        }),
      );
      releaseForm.append(
        governanceSubmitButton("اجرای Governed Release"),
      );
      card.append(releaseForm);
    }

    if (
      canReviewGovernanceOperationally()
      && item.status === "approved_for_manual_action"
      && !item.recovery
      && [
        "reactivation_candidate",
        "rollback_revision_candidate",
      ].includes(item.case_type)
    ) {
      const recoveryForm = document.createElement("form");
      recoveryForm.className = "brief-form governance-recovery-execute-form";
      recoveryForm.dataset.caseId = item.id;
      recoveryForm.dataset.caseSha256 = item.sha256;
      appendGovernanceField(
        recoveryForm,
        "یادداشت اجرای Recovery",
        governanceTextarea({
          name: "execution_note",
          minLength: 10,
          maxLength: 5000,
          rows: 3,
        }),
      );
      recoveryForm.append(
        governanceSubmitButton("اجرای Governed Recovery"),
      );
      card.append(recoveryForm);
    }

    if (canReviewGovernanceClinically(item)) {
      const form = document.createElement("form");
      form.className = "brief-form governance-review-form";
      form.dataset.caseId = item.id;
      form.dataset.caseSha256 = item.sha256;

      const action = document.createElement("select");
      action.name = "action";
      action.required = true;
      for (const [value, labelText] of [
        ["clinical_approve", "تأیید بالینی برای ادامه Governance"],
        ["request_changes", "درخواست اصلاح"],
        ["clinical_reject", "رد بالینی"],
      ]) {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = labelText;
        action.append(option);
      }
      appendGovernanceField(form, "مرور بالینی مستقل", action);
      appendGovernanceField(
        form,
        "دلیل Review",
        governanceTextarea({
          name: "rationale",
          minLength: 10,
          maxLength: 5000,
          rows: 3,
        }),
      );
      form.append(governanceSubmitButton("ثبت Review بالینی"));
      card.append(form);
    }

    if (
      canReviewGovernanceOperationally()
      && ["awaiting_operational_review", "operational_hold"].includes(item.status)
    ) {
      const form = document.createElement("form");
      form.className = "brief-form governance-review-form";
      form.dataset.caseId = item.id;
      form.dataset.caseSha256 = item.sha256;

      const action = document.createElement("select");
      action.name = "action";
      action.required = true;
      for (const [value, labelText] of [
        ["operational_acknowledge", "تأیید آمادگی برای اقدام دستی"],
        ["operational_hold", "توقف عملیاتی"],
      ]) {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = labelText;
        action.append(option);
      }
      appendGovernanceField(form, "مرور عملیاتی", action);
      appendGovernanceField(
        form,
        "دلیل Review",
        governanceTextarea({
          name: "rationale",
          minLength: 10,
          maxLength: 5000,
          rows: 3,
        }),
      );
      form.append(governanceSubmitButton("ثبت Review عملیاتی"));
      card.append(form);
    }

    fragment.append(card);
  }

  elements.learningGovernanceCases.replaceChildren(fragment);
}

async function loadProtocolGovernance() {
  const [signals, cases] = await Promise.all([
    apiRequest("/learning/governance/signals"),
    apiRequest("/protocol-governance/cases"),
  ]);
  renderGovernanceSignals(signals);
  renderGovernanceCases(cases);
}

async function createGovernanceCase(form) {
  if (
    !canCreateGovernanceCase()
    || governanceRequestInProgress
    || !currentLearningReview
  ) {
    return;
  }
  if (!form.reportValidity()) {
    return;
  }
  governanceRequestInProgress = true;
  showGovernanceMessage("در حال ثبت پرونده Governance…");
  const evidenceNeeded = form.elements.evidence_needed.value
    .split("\n")
    .map((item) => item.trim())
    .filter(Boolean);

  try {
    await apiRequest("/protocol-governance/cases", {
      method: "POST",
      body: JSON.stringify({
        protocol_code: form.dataset.protocolCode,
        protocol_version: form.dataset.protocolVersion,
        source_learning_review_sha256: currentLearningReview.review_sha256,
        case_type: form.elements.case_type.value,
        rationale: form.elements.rationale.value.trim(),
        evidence_needed: evidenceNeeded,
      }),
    });
    form.reset();
    await loadProtocolGovernance();
    showGovernanceMessage(
      "پرونده Governance ثبت شد؛ هیچ تغییری در پروتکل اعمال نشده است.",
    );
  } catch (error) {
    showGovernanceMessage(
      error instanceof ApiError && error.status === 409
        ? "Learning Review تغییر کرده است یا پرونده با وضعیت فعلی سازگار نیست؛ صفحه را تازه‌سازی کنید."
        : "ثبت پرونده Governance ممکن نشد.",
      true,
    );
  } finally {
    governanceRequestInProgress = false;
  }
}

async function reviewGovernanceCase(form) {
  if (governanceRequestInProgress) {
    return;
  }
  if (!form.reportValidity()) {
    return;
  }
  governanceRequestInProgress = true;
  showGovernanceMessage("در حال ثبت Review تغییرناپذیر…");
  try {
    await apiRequest(
      `/protocol-governance/cases/${encodeURIComponent(form.dataset.caseId)}/reviews`,
      {
        method: "POST",
        body: JSON.stringify({
          expected_case_sha256: form.dataset.caseSha256,
          action: form.elements.action.value,
          rationale: form.elements.rationale.value.trim(),
        }),
      },
    );
    await loadProtocolGovernance();
    showGovernanceMessage(
      "Review ثبت شد؛ وضعیت Governance به‌روزرسانی شد و پروتکل همچنان بدون تغییر است.",
    );
  } catch (error) {
    showGovernanceMessage(
      error instanceof ApiError && error.status === 403
        ? "این نقش یا این کاربر اجازهٔ انجام این Review را ندارد."
        : "ثبت Review Governance ممکن نشد.",
      true,
    );
  } finally {
    governanceRequestInProgress = false;
  }
}

async function createGovernanceRecoveryCase(form) {
  if (
    !canCreateGovernanceCase()
    || governanceRequestInProgress
    || !currentLearningReview
  ) {
    return;
  }
  if (!form.reportValidity()) {
    return;
  }
  governanceRequestInProgress = true;
  showGovernanceMessage("در حال ثبت Governed Recovery Case…");
  const evidenceNeeded = form.elements.evidence_needed.value
    .split("\n")
    .map((item) => item.trim())
    .filter(Boolean);
  try {
    await apiRequest(
      `/protocol-governance/releases/${encodeURIComponent(form.dataset.releaseId)}/recovery-cases`,
      {
        method: "POST",
        body: JSON.stringify({
          expected_release_sha256: form.dataset.releaseSha256,
          expected_learning_review_sha256: currentLearningReview.review_sha256,
          rationale: form.elements.rationale.value.trim(),
          evidence_needed: evidenceNeeded,
        }),
      },
    );
    await loadProtocolGovernance();
    showGovernanceMessage(
      "Recovery Case ثبت شد؛ هیچ وضعیت پروتکلی هنوز تغییر نکرده است.",
    );
  } catch (error) {
    showGovernanceMessage(
      error instanceof ApiError && error.status === 409
        ? "Release یا Learning Review تغییر کرده است؛ پیش از ادامه صفحه را تازه‌سازی کنید."
        : "ثبت Governed Recovery Case ممکن نشد.",
      true,
    );
  } finally {
    governanceRequestInProgress = false;
  }
}

async function executeGovernanceRecovery(form) {
  if (
    !canReviewGovernanceOperationally()
    || governanceRequestInProgress
  ) {
    return;
  }
  if (!form.reportValidity()) {
    return;
  }
  governanceRequestInProgress = true;
  showGovernanceMessage("در حال اجرای Governed Protocol Recovery…");
  try {
    await apiRequest(
      `/protocol-governance/cases/${encodeURIComponent(form.dataset.caseId)}/recovery`,
      {
        method: "POST",
        body: JSON.stringify({
          expected_case_sha256: form.dataset.caseSha256,
          execution_note: form.elements.execution_note.value.trim(),
        }),
      },
    );
    await loadProtocolGovernance();
    showGovernanceMessage(
      "Recovery اجرا شد؛ release قبلی حفظ و recovery جدید به lineage افزوده شد.",
    );
  } catch (error) {
    showGovernanceMessage(
      error instanceof ApiError && error.status === 409
        ? "پرونده دیگر قابل Recovery نیست یا lineage تغییر کرده است؛ صفحه را تازه‌سازی کنید."
        : "اجرای Governed Recovery ممکن نشد.",
      true,
    );
  } finally {
    governanceRequestInProgress = false;
  }
}

async function executeGovernanceRelease(form) {
  if (
    !canReviewGovernanceOperationally()
    || governanceRequestInProgress
  ) {
    return;
  }
  if (!form.reportValidity()) {
    return;
  }
  governanceRequestInProgress = true;
  showGovernanceMessage("در حال اجرای Governed Protocol Release…");
  try {
    await apiRequest(
      `/protocol-governance/cases/${encodeURIComponent(form.dataset.caseId)}/release`,
      {
        method: "POST",
        body: JSON.stringify({
          expected_case_sha256: form.dataset.caseSha256,
          execution_note: form.elements.execution_note.value.trim(),
        }),
      },
    );
    await loadProtocolGovernance();
    showGovernanceMessage(
      "Release اجرا شد؛ lineage و snapshot قبل/بعد به‌صورت تغییرناپذیر ثبت شدند.",
    );
  } catch (error) {
    showGovernanceMessage(
      error instanceof ApiError && error.status === 409
        ? "پرونده دیگر قابل release نیست یا source protocol تغییر کرده است؛ صفحه را تازه‌سازی کنید."
        : "اجرای Governed Release ممکن نشد.",
      true,
    );
  } finally {
    governanceRequestInProgress = false;
  }
}

async function loadClinicalLearningReview({ quiet = false } = {}) {
  if (!canReadLearning() || learningRequestInProgress) {
    return;
  }
  const requestGeneration = sessionGeneration;
  setLearningBusy(true);
  if (!quiet) {
    showLearningMessage("در حال اعتبارسنجی زنجیرهٔ Decision، Treatment و Outcome…");
  }
  try {
    const review = await apiRequest("/learning/review");
    if (!accessToken || requestGeneration !== sessionGeneration) {
      return;
    }
    if (
      review.ranks_treatments !== false
      || review.produces_learning_score !== false
      || review.automatically_changes_protocols !== false
      || review.is_cross_protocol_effectiveness_comparison !== false
    ) {
      throw new ApiError(409, "Unexpected clinical learning contract.");
    }
    renderClinicalLearningReview(review);
    await loadProtocolGovernance();
    showLearningMessage(
      "مرور کیفیت داده بارگذاری شد؛ این نما درمان‌ها را رتبه‌بندی نمی‌کند.",
    );
    setConnectionState(true);
  } catch (error) {
    currentLearningReview = null;
    elements.learningReviewHash.textContent = "";
    elements.learningSummary.replaceChildren();
    elements.learningProtocols.replaceChildren();
    elements.learningGovernanceSignals.replaceChildren();
    elements.learningGovernanceCases.replaceChildren();
    if (error instanceof ApiError && error.status === 401) {
      showLogin();
      return;
    }
    if (error instanceof ApiError && error.status === 403) {
      showLearningMessage("نقش کاربری شما اجازهٔ مرور دادهٔ یادگیری را ندارد.", true);
    } else if (error instanceof ApiError && error.status === 409) {
      showLearningMessage("اعتبار یکی از زنجیره‌های Decision یا Outcome تأیید نشد.", true);
    } else {
      showLearningMessage("دریافت مرور یادگیری ممکن نشد؛ دوباره تلاش کنید.", true);
    }
    setConnectionState(false);
  } finally {
    if (requestGeneration === sessionGeneration) {
      setLearningBusy(false);
    }
  }
}

function resetLearningState() {
  currentLearningReview = null;
  currentGovernanceSignals = [];
  currentGovernanceCases = [];
  elements.learningReviewHash.textContent = "";
  elements.learningSummary.replaceChildren();
  elements.learningProtocols.replaceChildren();
  elements.learningGovernanceSignals.replaceChildren();
  elements.learningGovernanceCases.replaceChildren();
  showLearningMessage("");
  showGovernanceMessage("");
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

function resetPilotReadinessState() {
  currentPilotReadiness = null;
  currentPilotGateStatuses = [];
  currentPilotLaunchPreview = null;
  currentPilotLaunchPackages = [];
  currentPilotReleaseDecisions = [];
  elements.pilotReadinessSummary.replaceChildren();
  elements.pilotReadinessChecks.replaceChildren();
  elements.pilotManualGates.replaceChildren();
  elements.pilotLaunchPreview.replaceChildren();
  elements.pilotLaunchHistory.replaceChildren();
  elements.freezePilotLaunchPackageButton.hidden = true;
  showPilotReadinessMessage("");
}

function createPilotField(labelText, control) {
  const wrapper = document.createElement("label");
  wrapper.className = "field-group";
  wrapper.append(
    createTextElement("span", "", labelText),
    control,
  );
  return wrapper;
}

function createPilotAttestationForm(gateName, latest) {
  const form = document.createElement("form");
  form.className = "brief-form pilot-attestation-form";
  form.dataset.gateName = gateName;
  if (latest) {
    form.dataset.supersedesAttestationId = latest.id;
    form.dataset.expectedSupersedesSha256 = latest.sha256;
  }

  const releaseRef = document.createElement("input");
  releaseRef.name = "release_ref";
  releaseRef.type = "text";
  releaseRef.maxLength = 200;
  releaseRef.required = true;
  releaseRef.autocomplete = "off";

  const evidenceReference = document.createElement("input");
  evidenceReference.name = "evidence_reference";
  evidenceReference.type = "text";
  evidenceReference.maxLength = 500;
  evidenceReference.required = true;
  evidenceReference.autocomplete = "off";

  const statement = document.createElement("textarea");
  statement.name = "statement";
  statement.minLength = 20;
  statement.maxLength = 5000;
  statement.rows = 4;
  statement.required = true;

  const submit = document.createElement("button");
  submit.className = "button button-primary";
  submit.type = "submit";
  submit.textContent = latest
    ? "ثبت نسل جدید Attestation"
    : "ثبت Attestation";

  form.append(
    createPilotField("Release reference", releaseRef),
    createPilotField("Evidence reference", evidenceReference),
    createPilotField("Statement", statement),
    submit,
  );
  return form;
}

function createPilotReviewForm(attestation) {
  const form = document.createElement("form");
  form.className = "brief-form pilot-review-form";
  form.dataset.attestationId = attestation.id;
  form.dataset.attestationSha256 = attestation.sha256;

  const action = document.createElement("select");
  action.name = "action";
  action.required = true;
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = "انتخاب نتیجه review";
  placeholder.selected = true;
  placeholder.disabled = true;
  const approve = document.createElement("option");
  approve.value = "approve";
  approve.textContent = "Approve";
  const reject = document.createElement("option");
  reject.value = "reject";
  reject.textContent = "Reject";
  action.append(placeholder, approve, reject);

  const rationale = document.createElement("textarea");
  rationale.name = "rationale";
  rationale.minLength = 10;
  rationale.maxLength = 5000;
  rationale.rows = 3;
  rationale.required = true;

  const submit = document.createElement("button");
  submit.className = "button button-primary";
  submit.type = "submit";
  submit.textContent = "ثبت review مستقل";

  form.append(
    createPilotField("نتیجه review", action),
    createPilotField("Rationale", rationale),
    submit,
  );
  return form;
}

function renderPilotLaunchPackage(preview, packages, decisions) {
  currentPilotLaunchPreview = preview;
  currentPilotLaunchPackages = packages;
  currentPilotReleaseDecisions = decisions;

  const previewCard = document.createElement("article");
  previewCard.className = "context-card context-intake";
  const issueText = preview.issues.length
    ? preview.issues.join("، ")
    : "بدون مانع";
  previewCard.append(
    createTextElement("h4", "", "Launch Package Preview"),
    createDefinitionGrid([
      [
        "وضعیت",
        preview.status === "packageable" ? "PACKAGEABLE" : "BLOCKED",
      ],
      ["Release ref", preview.release_ref || "—"],
      ["Readiness SHA-256", preview.readiness_sha256],
      [
        "Manual gates",
        `${toPersianNumber(preview.approved_gate_count)} / ${toPersianNumber(preview.required_gate_count)}`,
      ],
      ["Issues", issueText],
      ["مجوز Launch", "خیر"],
    ], "safety-summary-grid"),
  );
  elements.pilotLaunchPreview.replaceChildren(previewCard);

  elements.freezePilotLaunchPackageButton.hidden = !(
    currentUser
    && currentUser.role === "admin"
    && preview.status === "packageable"
  );

  const history = document.createDocumentFragment();
  if (!packages.length) {
    history.append(createTextElement(
      "p",
      "empty-state",
      "هنوز Launch Package تغییرناپذیری ثبت نشده است.",
    ));
  }
  const decisionByPackage = new Map(
    decisions.map((decision) => [decision.package_id, decision]),
  );
  for (const item of packages) {
    const card = document.createElement("article");
    card.className = "evidence-brief-card";
    const decision = decisionByPackage.get(item.id) || null;
    card.append(
      createTextElement("h4", "", `Package · ${item.release_ref}`),
      createDefinitionGrid([
        ["Package ID", item.id],
        ["Readiness SHA-256", item.readiness_sha256],
        ["Package SHA-256", item.sha256],
        ["Manual gates", toPersianNumber(item.attestation_manifest.length)],
        ["زمان Freeze", formatDateTime(item.created_at)],
        [
          "Human release decision",
          decision
            ? decision.action === "authorize" ? "AUTHORIZE" : "HOLD"
            : "ثبت نشده",
        ],
        [
          "Pilot release authorized",
          decision && decision.controlled_pilot_release_authorized ? "بله" : "خیر",
        ],
        ["Clinical clearance", "خیر"],
      ]),
    );

    if (decision) {
      card.append(
        createDefinitionGrid([
          ["Decision SHA-256", decision.sha256],
          ["شروع scope", formatDateTime(decision.starts_at)],
          ["پایان scope", formatDateTime(decision.expires_at)],
          [
            "سقف ویزیت",
            decision.max_enrolled_visits === null
              ? "—"
              : toPersianNumber(decision.max_enrolled_visits),
          ],
          [
            "Protocol codes",
            decision.allowed_protocol_codes.length
              ? decision.allowed_protocol_codes.join("، ")
              : "—",
          ],
          ["درمان فردی را مجاز می‌کند", "خیر"],
        ]),
      );
    } else if (
      currentUser
      && currentUser.role === "admin"
      && currentUser.id !== item.created_by_user_id
    ) {
      card.append(createPilotReleaseDecisionForm(item));
    } else if (
      currentUser
      && currentUser.role === "admin"
      && currentUser.id === item.created_by_user_id
    ) {
      card.append(createTextElement(
        "p",
        "ordering-note",
        "سازندهٔ Package نمی‌تواند تصمیم انسانی Release همان Package را ثبت کند.",
      ));
    }
    history.append(card);
  }
  elements.pilotLaunchHistory.replaceChildren(history);
}

function createPilotReleaseDecisionForm(packageItem) {
  const form = document.createElement("form");
  form.className = "brief-form pilot-release-decision-form";
  form.dataset.packageId = packageItem.id;
  form.dataset.packageSha256 = packageItem.sha256;

  const action = document.createElement("select");
  action.name = "action";
  action.required = true;
  for (const [value, label] of [
    ["", "انتخاب تصمیم"],
    ["authorize", "Authorize controlled pilot"],
    ["hold", "Hold"],
  ]) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    if (!value) {
      option.disabled = true;
      option.selected = true;
    }
    action.append(option);
  }

  const startsAt = document.createElement("input");
  startsAt.name = "starts_at";
  startsAt.type = "datetime-local";

  const expiresAt = document.createElement("input");
  expiresAt.name = "expires_at";
  expiresAt.type = "datetime-local";

  const maxVisits = document.createElement("input");
  maxVisits.name = "max_enrolled_visits";
  maxVisits.type = "number";
  maxVisits.min = "1";
  maxVisits.max = "100";

  const protocolCodes = document.createElement("textarea");
  protocolCodes.name = "allowed_protocol_codes";
  protocolCodes.rows = 3;
  protocolCodes.placeholder = "هر کد پروتکل در یک خط";

  const rationale = document.createElement("textarea");
  rationale.name = "rationale";
  rationale.minLength = 20;
  rationale.maxLength = 5000;
  rationale.rows = 4;
  rationale.required = true;

  const submit = document.createElement("button");
  submit.className = "button button-primary";
  submit.type = "submit";
  submit.textContent = "ثبت تصمیم انسانی Release";

  form.append(
    createPilotField("Decision", action),
    createPilotField("شروع scope", startsAt),
    createPilotField("پایان scope", expiresAt),
    createPilotField("حداکثر ویزیت پایلوت", maxVisits),
    createPilotField("Protocol codes", protocolCodes),
    createPilotField("Rationale", rationale),
    submit,
  );
  return form;
}

async function createPilotReleaseDecision(form) {
  if (
    !currentUser
    || currentUser.role !== "admin"
    || pilotReadinessRequestInProgress
    || !form.reportValidity()
  ) {
    return;
  }
  const action = form.elements.action.value;
  const payload = {
    expected_package_sha256: form.dataset.packageSha256,
    action,
    rationale: form.elements.rationale.value.trim(),
    starts_at: null,
    expires_at: null,
    max_enrolled_visits: null,
    allowed_protocol_codes: [],
  };
  if (action === "authorize") {
    const codes = form.elements.allowed_protocol_codes.value
      .split("\n")
      .map((item) => item.trim())
      .filter(Boolean);
    if (
      !form.elements.starts_at.value
      || !form.elements.expires_at.value
      || !form.elements.max_enrolled_visits.value
      || !codes.length
    ) {
      showPilotReadinessMessage(
        "برای authorize باید بازه زمانی، سقف ویزیت و حداقل یک کد پروتکل ثبت شود.",
        true,
      );
      return;
    }
    payload.starts_at = new Date(form.elements.starts_at.value).toISOString();
    payload.expires_at = new Date(form.elements.expires_at.value).toISOString();
    payload.max_enrolled_visits = Number(form.elements.max_enrolled_visits.value);
    payload.allowed_protocol_codes = codes;
  }

  setPilotReadinessBusy(true);
  try {
    await apiRequest(
      `/pilot-readiness/manual-gates/launch-packages/${encodeURIComponent(form.dataset.packageId)}/release-decisions`,
      {
        method: "POST",
        body: JSON.stringify(payload),
      },
    );
    setPilotReadinessBusy(false);
    await loadPilotReadiness({ quiet: true });
    showPilotReadinessMessage(
      action === "authorize"
        ? "تصمیم انسانی Release ثبت شد؛ این تصمیم هنوز مجوز درمان فردی نیست."
        : "Release روی HOLD ثبت شد.",
    );
  } catch (error) {
    showPilotReadinessMessage(
      error instanceof ApiError && [403, 409].includes(error.status)
        ? error.message
        : "ثبت تصمیم انسانی Release ممکن نشد.",
      true,
    );
  } finally {
    setPilotReadinessBusy(false);
  }
}

async function freezePilotLaunchPackage() {
  if (
    pilotReadinessRequestInProgress
    || !currentPilotLaunchPreview
    || currentPilotLaunchPreview.status !== "packageable"
    || !currentUser
    || currentUser.role !== "admin"
  ) {
    return;
  }

  setPilotReadinessBusy(true);
  try {
    await apiRequest(
      "/pilot-readiness/manual-gates/launch-packages",
      {
        method: "POST",
        body: JSON.stringify({
          expected_readiness_sha256:
            currentPilotLaunchPreview.readiness_sha256,
          expected_release_ref:
            currentPilotLaunchPreview.release_ref,
          expected_attestations:
            currentPilotLaunchPreview.attestation_manifest.map((item) => ({
              gate_name: item.gate_name,
              attestation_sha256: item.attestation_sha256,
            })),
        }),
      },
    );
    setPilotReadinessBusy(false);
    await loadPilotReadiness({ quiet: true });
    showPilotReadinessMessage(
      "Launch Package تغییرناپذیر ثبت شد؛ هنوز تصمیم انسانی نهایی برای launch لازم است.",
    );
  } catch (error) {
    showPilotReadinessMessage(
      error instanceof ApiError && error.status === 409
        ? "شواهد launch تغییر کرده‌اند یا Package قبلاً ثبت شده است؛ صفحه را تازه‌سازی کنید."
        : "Freeze کردن Launch Package ممکن نشد.",
      true,
    );
  } finally {
    setPilotReadinessBusy(false);
  }
}

function renderPilotReadiness(report, gateStatuses) {
  currentPilotReadiness = report;
  currentPilotGateStatuses = gateStatuses;

  const summary = document.createElement("article");
  summary.className = "context-card context-intake";
  summary.append(
    createTextElement("h4", "", "نتیجهٔ Controlled-Pilot Gate"),
    createDefinitionGrid([
      [
        "وضعیت خودکار",
        report.status === "automated_prerequisites_passed"
          ? "پیش‌نیازهای خودکار پاس شده‌اند"
          : "مسدود",
      ],
      ["زمان بررسی", formatDateTime(report.generated_at)],
      ["موتور دیتابیس", report.database_dialect],
      ["Readiness SHA-256", report.readiness_sha256],
      ["مجوز پایلوت صادر شده", "خیر"],
      ["Clinical clearance", "خیر"],
      ["تصمیم انسانی Release", "الزامی"],
    ], "safety-summary-grid"),
  );
  elements.pilotReadinessSummary.replaceChildren(summary);

  const checks = document.createDocumentFragment();
  for (const item of report.automated_checks) {
    const card = document.createElement("article");
    card.className = "evidence-brief-card";
    card.append(
      createTextElement(
        "h4",
        "",
        pilotCheckLabels[item.name] || item.name,
      ),
      createDefinitionGrid([
        [
          "وضعیت",
          item.status === "pass"
            ? "PASS"
            : item.status === "blocked"
              ? "BLOCKED"
              : "FAIL",
        ],
        ["کد", item.code],
      ]),
    );
    checks.append(card);
  }
  elements.pilotReadinessChecks.replaceChildren(checks);

  const statusByGate = new Map(
    gateStatuses.map((item) => [item.gate_name, item]),
  );
  const manual = document.createDocumentFragment();
  for (const item of report.manual_gates) {
    const state = statusByGate.get(item.name);
    const latest = state ? state.latest_attestation : null;
    const requiredRole = pilotGateRequiredRole(item.name);
    const card = document.createElement("article");
    card.className = "evidence-brief-card";

    const statusText = !state || state.status === "not_attested"
      ? "ثبت نشده"
      : state.status === "pending_review"
        ? "در انتظار review مستقل"
        : state.status === "approved"
          ? "تأیید شده"
          : "رد شده";

    const rows = [
      ["وضعیت", statusText],
      ["نقش لازم", roleLabels[requiredRole] || requiredRole],
      ["کد", item.code],
    ];
    if (latest) {
      rows.push(
        ["Generation", toPersianNumber(latest.generation)],
        ["Release ref", latest.release_ref],
        ["Evidence ref", latest.evidence_reference],
        ["Attestation SHA-256", latest.sha256],
        ["زمان ثبت", formatDateTime(latest.created_at)],
      );
      if (latest.review) {
        rows.push(
          [
            "Review",
            latest.review.action === "approve" ? "Approve" : "Reject",
          ],
          ["Review SHA-256", latest.review.sha256],
          ["زمان review", formatDateTime(latest.review.created_at)],
        );
      }
    }

    card.append(
      createTextElement(
        "h4",
        "",
        pilotManualGateLabels[item.name] || item.name,
      ),
      createDefinitionGrid(rows),
    );

    const roleMatches = (
      currentUser
      && currentUser.role === requiredRole
      && report.status === "automated_prerequisites_passed"
    );
    if (roleMatches) {
      if (!latest || ["approved", "rejected"].includes(state.status)) {
        card.append(createPilotAttestationForm(item.name, latest));
      } else if (
        state.status === "pending_review"
        && latest.attested_by_user_id !== currentUser.id
      ) {
        card.append(createPilotReviewForm(latest));
      } else if (state.status === "pending_review") {
        card.append(createTextElement(
          "p",
          "ordering-note",
          "این attestation را شما ثبت کرده‌اید؛ review باید توسط فرد هم‌نقش دیگری انجام شود.",
        ));
      }
    }
    manual.append(card);
  }
  elements.pilotManualGates.replaceChildren(manual);

  showPilotReadinessMessage(
    report.status === "automated_prerequisites_passed"
      ? "پیش‌نیازهای خودکار پاس شده‌اند؛ Manual Gateها باید با review مستقل تکمیل شوند و هنوز مجوز بالینی صادر نشده است."
      : "Controlled-Pilot Gate مسدود است؛ checkهای FAIL/BLOCKED را پیش از attestation برطرف کنید.",
    report.status !== "automated_prerequisites_passed",
  );
}

async function createPilotManualAttestation(form) {
  if (
    !currentPilotReadiness
    || pilotReadinessRequestInProgress
    || !form.reportValidity()
  ) {
    return;
  }
  setPilotReadinessBusy(true);
  try {
    await apiRequest(
      "/pilot-readiness/manual-gates/attestations",
      {
        method: "POST",
        body: JSON.stringify({
          gate_name: form.dataset.gateName,
          expected_readiness_sha256: currentPilotReadiness.readiness_sha256,
          release_ref: form.elements.release_ref.value.trim(),
          evidence_reference: form.elements.evidence_reference.value.trim(),
          statement: form.elements.statement.value.trim(),
          supersedes_attestation_id:
            form.dataset.supersedesAttestationId || null,
          expected_supersedes_sha256:
            form.dataset.expectedSupersedesSha256 || null,
        }),
      },
    );
    setPilotReadinessBusy(false);
    await loadPilotReadiness({ quiet: true });
    showPilotReadinessMessage(
      "Attestation ثبت شد و تا review مستقل هیچ gateای تأییدشده محسوب نمی‌شود.",
    );
  } catch (error) {
    showPilotReadinessMessage(
      error instanceof ApiError && error.status === 409
        ? "Readiness یا نسل این gate تغییر کرده است؛ صفحه را دوباره بارگذاری کنید."
        : "ثبت attestation ممکن نشد.",
      true,
    );
  } finally {
    setPilotReadinessBusy(false);
  }
}

async function reviewPilotManualAttestation(form) {
  if (pilotReadinessRequestInProgress || !form.reportValidity()) {
    return;
  }
  setPilotReadinessBusy(true);
  try {
    await apiRequest(
      `/pilot-readiness/manual-gates/attestations/${encodeURIComponent(form.dataset.attestationId)}/review`,
      {
        method: "POST",
        body: JSON.stringify({
          expected_attestation_sha256: form.dataset.attestationSha256,
          action: form.elements.action.value,
          rationale: form.elements.rationale.value.trim(),
        }),
      },
    );
    setPilotReadinessBusy(false);
    await loadPilotReadiness({ quiet: true });
    showPilotReadinessMessage(
      "Review مستقل ثبت شد؛ تاریخچه قبلی بدون بازنویسی حفظ شده است.",
    );
  } catch (error) {
    showPilotReadinessMessage(
      error instanceof ApiError && error.status === 409
        ? "Attestation یا readiness تغییر کرده است؛ صفحه را دوباره بارگذاری کنید."
        : "ثبت review ممکن نشد.",
      true,
    );
  } finally {
    setPilotReadinessBusy(false);
  }
}

async function loadPilotReadiness({ quiet = false } = {}) {
  if (
    !canReadPilotReadiness()
    || pilotReadinessRequestInProgress
  ) {
    return;
  }

  setPilotReadinessBusy(true);
  if (!quiet) {
    showPilotReadinessMessage("در حال بررسی پیش‌نیازهای پایلوت…");
  }

  try {
    const [
      report,
      gateStatuses,
      launchPreview,
      launchPackages,
      releaseDecisions,
    ] = await Promise.all([
      apiRequest("/pilot-readiness"),
      apiRequest("/pilot-readiness/manual-gates"),
      apiRequest("/pilot-readiness/manual-gates/launch-package-preview"),
      apiRequest("/pilot-readiness/manual-gates/launch-packages"),
      apiRequest("/pilot-readiness/manual-gates/release-decisions"),
    ]);
    renderPilotReadiness(report, gateStatuses);
    renderPilotLaunchPackage(launchPreview, launchPackages, releaseDecisions);
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      showLogin();
      return;
    }
    showPilotReadinessMessage(
      "بررسی آمادگی پایلوت ممکن نشد؛ وضعیت backend و دسترسی release role را بررسی کنید.",
      true,
    );
  } finally {
    setPilotReadinessBusy(false);
  }
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
  if (workspace === "learning" && !canReadLearning()) {
    return;
  }
  if (workspace === "evidence" && !canReadEvidence()) {
    return;
  }
  if (workspace === "safety" && !canReadSafety()) {
    return;
  }
  if (workspace === "pilot" && !canReadPilotReadiness()) {
    return;
  }

  activeWorkspace = workspace;
  const isFlow = workspace === "flow";
  const isCopilot = workspace === "copilot";
  const isLearning = workspace === "learning";
  const isEvidence = workspace === "evidence";
  const isSafety = workspace === "safety";
  const isPilot = workspace === "pilot";
  elements.flowWorkspace.hidden = !isFlow;
  elements.copilotWorkspace.hidden = !isCopilot;
  elements.learningWorkspace.hidden = !isLearning;
  elements.evidenceWorkspace.hidden = !isEvidence;
  elements.safetyWorkspace.hidden = !isSafety;
  elements.pilotReadinessWorkspace.hidden = !isPilot;
  elements.flowTab.setAttribute("aria-selected", String(isFlow));
  elements.copilotTab.setAttribute("aria-selected", String(isCopilot));
  elements.learningTab.setAttribute("aria-selected", String(isLearning));
  elements.evidenceTab.setAttribute("aria-selected", String(isEvidence));
  elements.safetyTab.setAttribute("aria-selected", String(isSafety));
  elements.pilotReadinessTab.setAttribute("aria-selected", String(isPilot));
  elements.flowTab.tabIndex = isFlow ? 0 : -1;
  elements.copilotTab.tabIndex = isCopilot ? 0 : -1;
  elements.learningTab.tabIndex = isLearning ? 0 : -1;
  elements.evidenceTab.tabIndex = isEvidence ? 0 : -1;
  elements.safetyTab.tabIndex = isSafety ? 0 : -1;
  elements.pilotReadinessTab.tabIndex = isPilot ? 0 : -1;

  if (isFlow) {
    startAutoRefresh();
    if (accessToken && currentFlow) {
      loadFlow({ quiet: true });
    }
  } else {
    stopAutoRefresh();
  }
  if (
    isLearning
    && accessToken
    && currentLearningReview === null
    && !learningRequestInProgress
  ) {
    loadClinicalLearningReview({ quiet: true });
  }
  if (
    isSafety
    && accessToken
    && currentSafetyEscalations === null
    && !safetyEscalationRequestInProgress
  ) {
    loadSafetyEscalations({ quiet: true });
  }
  if (
    isPilot
    && accessToken
    && currentPilotReadiness === null
    && !pilotReadinessRequestInProgress
  ) {
    loadPilotReadiness({ quiet: true });
  }
}

function showLogin() {
  stopAutoRefresh();
  sessionGeneration += 1;
  accessToken = null;
  currentUser = null;
  requestInProgress = false;
  copilotRequestInProgress = false;
  decisionRequestInProgress = false;
  learningRequestInProgress = false;
  governanceRequestInProgress = false;
  evidenceRequestInProgress = false;
  safetyRequestInProgress = false;
  safetyEscalationRequestInProgress = false;
  pilotReadinessRequestInProgress = false;
  actionInProgress = false;
  elements.refreshButton.disabled = false;
  elements.refreshButton.textContent = "تازه‌سازی";
  elements.loadCopilotButton.disabled = false;
  elements.loadCopilotButton.textContent = "بارگذاری snapshot پزشک‌یار";
  elements.loadLearningButton.disabled = false;
  elements.loadLearningButton.textContent = "تازه‌سازی مرور یادگیری";
  elements.loadEvidenceButton.disabled = false;
  elements.loadEvidenceButton.textContent = "بارگذاری زمینه و خلاصه‌ها";
  elements.knowledgeSearchButton.disabled = false;
  elements.knowledgeResetButton.disabled = false;
  elements.loadSafetyButton.disabled = false;
  elements.loadSafetyButton.textContent = "بارگذاری صندوق ایمنی";
  elements.runSafetyEvaluationButton.disabled = false;
  elements.loadSafetyEscalationsButton.disabled = false;
  elements.loadSafetyEscalationsButton.textContent = "تازه‌سازی صف";
  elements.loadPilotReadinessButton.disabled = false;
  elements.loadPilotReadinessButton.textContent = "اجرای دوبارهٔ Gate";
  elements.dialogConfirm.disabled = false;
  resetOperationalState();
  resetCopilotState();
  resetLearningState();
  resetEvidenceState();
  resetSafetyState();
  resetPilotReadinessState();
  activeWorkspace = "flow";
  elements.flowWorkspace.hidden = false;
  elements.copilotWorkspace.hidden = true;
  elements.learningWorkspace.hidden = true;
  elements.evidenceWorkspace.hidden = true;
  elements.safetyWorkspace.hidden = true;
  elements.pilotReadinessWorkspace.hidden = true;
  elements.flowTab.setAttribute("aria-selected", "true");
  elements.copilotTab.setAttribute("aria-selected", "false");
  elements.learningTab.setAttribute("aria-selected", "false");
  elements.evidenceTab.setAttribute("aria-selected", "false");
  elements.safetyTab.setAttribute("aria-selected", "false");
  elements.pilotReadinessTab.setAttribute("aria-selected", "false");
  elements.flowTab.tabIndex = 0;
  elements.copilotTab.tabIndex = -1;
  elements.learningTab.tabIndex = -1;
  elements.evidenceTab.tabIndex = -1;
  elements.safetyTab.tabIndex = -1;
  elements.pilotReadinessTab.tabIndex = -1;
  elements.copilotTab.hidden = true;
  elements.learningTab.hidden = true;
  elements.evidenceTab.hidden = true;
  elements.safetyTab.hidden = true;
  elements.pilotReadinessTab.hidden = true;
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
  elements.learningTab.hidden = !canReadLearning();
  elements.evidenceTab.hidden = !canReadEvidence();
  elements.safetyTab.hidden = !canReadSafety();
  elements.pilotReadinessTab.hidden = !canReadPilotReadiness();
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

function decisionProtocolKey(option) {
  return [
    option.protocol_code,
    option.protocol_version,
    option.treatment_type,
  ].join("@@");
}

function selectedDecisionReferences() {
  if (!currentTreatmentRoadmap) {
    return [];
  }
  return currentTreatmentRoadmap.options
    .filter((option) => selectedDecisionProtocols.has(decisionProtocolKey(option)))
    .map((option) => ({
      protocol_code: option.protocol_code,
      protocol_version: option.protocol_version,
      treatment_type: option.treatment_type,
      source: "roadmap_option",
    }));
}

function renderSelectedDecisionProtocols() {
  const fragment = document.createDocumentFragment();
  const selected = selectedDecisionReferences();
  if (!selected.length) {
    fragment.append(createTextElement(
      "p",
      "empty-state",
      "هنوز گزینه‌ای برای این تصمیم انتخاب نشده است.",
    ));
  }
  for (const item of selected) {
    fragment.append(createTextElement(
      "span",
      "count-pill",
      `${item.protocol_code} · ${item.protocol_version} · ${item.treatment_type}`,
    ));
  }
  elements.copilotDecisionOptions.replaceChildren(fragment);
}

function syncDecisionForm() {
  const type = elements.copilotDecisionType.value;
  const needsModification = ["modify_option", "combine_options"].includes(type);
  const ignoresOptions = ["defer", "no_treatment"].includes(type);
  elements.copilotDecisionModification.required = needsModification;
  elements.copilotDecisionModification.disabled = ignoresOptions;
  if (ignoresOptions) {
    elements.copilotDecisionModification.value = "";
  }
  for (const checkbox of elements.copilotRoadmap.querySelectorAll(
    "input[data-decision-protocol-key]",
  )) {
    checkbox.disabled = ignoresOptions || !canCreateTreatmentDecision();
  }
  renderSelectedDecisionProtocols();
}

function renderTreatmentDecisionHistory(decisions) {
  currentTreatmentDecisions = decisions;
  const fragment = document.createDocumentFragment();
  if (!decisions.length) {
    fragment.append(createTextElement(
      "p",
      "empty-state",
      "هنوز تصمیم تغییرناپذیری برای این ویزیت ثبت نشده است.",
    ));
  }
  const labels = {
    select_option: "انتخاب یک گزینه",
    modify_option: "اصلاح یک گزینه",
    combine_options: "ترکیب چند گزینه",
    choose_outside_roadmap: "پروتکل خارج از Roadmap",
    defer: "تعویق تصمیم",
    no_treatment: "عدم درمان در این مرحله",
  };
  for (const decision of [...decisions].reverse()) {
    const card = document.createElement("article");
    card.className = "evidence-brief-card";
    const protocolText = decision.selected_protocols.length
      ? decision.selected_protocols
        .map((item) => `${item.protocol_code} · ${item.protocol_version}`)
        .join("، ")
      : "بدون انتخاب پروتکل";
    card.append(
      createTextElement(
        "h4",
        "",
        `${labels[decision.decision_type] || decision.decision_type}${decision.is_current_decision ? " · تصمیم فعلی" : ""}`,
      ),
      createDefinitionGrid([
        ["زمان", formatDateTime(decision.decided_at)],
        ["پروتکل‌ها", protocolText],
        ["Treatment متصل", toPersianNumber(decision.linked_treatment_ids.length)],
        ["Outcome متصل", toPersianNumber(decision.linked_outcome_ids.length)],
        ["SHA-256 تصمیم", decision.sha256],
        ["تصمیم سیستم", "خیر"],
      ]),
      createTextElement("p", "", decision.rationale),
    );
    if (decision.modification_summary) {
      card.append(createTextElement(
        "p",
        "ordering-note",
        `شرح اصلاح/ترکیب: ${decision.modification_summary}`,
      ));
    }
    if (decision.patient_preference_summary) {
      card.append(createTextElement(
        "p",
        "ordering-note",
        `ترجیح بیمار: ${decision.patient_preference_summary}`,
      ));
    }
    fragment.append(card);
  }
  elements.copilotDecisionHistory.replaceChildren(fragment);
}

async function loadTreatmentDecisions(visitId) {
  const decisions = await apiRequest(
    `/visits/${encodeURIComponent(visitId)}/treatment-decisions`,
  );
  renderTreatmentDecisionHistory(decisions);
  return decisions;
}

async function createTreatmentDecision(event) {
  event.preventDefault();
  if (
    !canCreateTreatmentDecision()
    || decisionRequestInProgress
    || !currentTreatmentRoadmap
    || !currentCopilotVisitId
  ) {
    return;
  }
  if (!elements.copilotDecisionForm.reportValidity()) {
    return;
  }

  const decisionType = elements.copilotDecisionType.value;
  const selected = selectedDecisionReferences();
  if (
    ["select_option", "modify_option"].includes(decisionType)
    && selected.length !== 1
  ) {
    showDecisionMessage("برای این نوع تصمیم دقیقاً یک گزینه را انتخاب کنید.", true);
    return;
  }
  if (decisionType === "combine_options" && selected.length < 2) {
    showDecisionMessage("برای تصمیم ترکیبی حداقل دو گزینه را انتخاب کنید.", true);
    return;
  }
  if (["defer", "no_treatment"].includes(decisionType) && selected.length) {
    showDecisionMessage("برای تعویق یا عدم درمان، گزینه‌های Roadmap را از حالت انتخاب خارج کنید.", true);
    return;
  }

  const previous = currentTreatmentDecisions.length
    ? currentTreatmentDecisions[currentTreatmentDecisions.length - 1]
    : null;
  decisionRequestInProgress = true;
  elements.createTreatmentDecisionButton.disabled = true;
  showDecisionMessage("در حال ثبت تصمیم تغییرناپذیر پزشک…");

  try {
    await apiRequest(
      `/visits/${encodeURIComponent(currentCopilotVisitId)}/treatment-decisions`,
      {
        method: "POST",
        body: JSON.stringify({
          expected_clinical_context_sha256: (
            currentTreatmentRoadmap.target_profile.clinical_context_sha256
          ),
          expected_roadmap_sha256: currentTreatmentRoadmap.roadmap_sha256,
          expected_previous_decision_sha256: previous ? previous.sha256 : null,
          decision_type: decisionType,
          selected_protocols: ["defer", "no_treatment"].includes(decisionType)
            ? []
            : selected,
          rationale: elements.copilotDecisionRationale.value.trim(),
          modification_summary: ["modify_option", "combine_options"].includes(decisionType)
            ? elements.copilotDecisionModification.value.trim()
            : null,
          patient_preference_summary: (
            elements.copilotPatientPreference.value.trim() || null
          ),
          evidence_brief_ids: [],
        }),
      },
    );
    await loadTreatmentDecisions(currentCopilotVisitId);
    selectedDecisionProtocols.clear();
    elements.copilotDecisionForm.reset();
    for (const checkbox of elements.copilotRoadmap.querySelectorAll(
      "input[data-decision-protocol-key]",
    )) {
      checkbox.checked = false;
    }
    syncDecisionForm();
    showDecisionMessage(
      "تصمیم پزشک به‌صورت append-only ثبت شد و برای Treatment و Outcome قابل ردیابی است.",
    );
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      showLogin();
      return;
    }
    if (error instanceof ApiError && error.status === 409) {
      showDecisionMessage(
        "زمینه، Roadmap یا تصمیم قبلی تغییر کرده است؛ پزشک‌یار را تازه‌سازی کنید.",
        true,
      );
    } else if (error instanceof ApiError && error.status === 403) {
      showDecisionMessage("فقط پزشک می‌تواند تصمیم درمانی ثبت کند.", true);
    } else {
      showDecisionMessage("ثبت تصمیم ممکن نشد؛ دوباره تلاش کنید.", true);
    }
  } finally {
    decisionRequestInProgress = false;
    elements.createTreatmentDecisionButton.disabled = false;
  }
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
    if (canCreateTreatmentDecision() && roadmap.roadmap_status === "options_available") {
      const chooser = document.createElement("label");
      chooser.className = "acknowledgement";
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.dataset.decisionProtocolKey = decisionProtocolKey(option);
      checkbox.checked = selectedDecisionProtocols.has(
        checkbox.dataset.decisionProtocolKey,
      );
      chooser.append(
        checkbox,
        createTextElement("span", "", "افزودن این گزینه به تصمیم پزشک"),
      );
      card.append(chooser);
    }
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
  elements.copilotDecisionSection.hidden = false;
  elements.copilotDecisionForm.hidden = !canCreateTreatmentDecision();
  syncDecisionForm();
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
  currentTreatmentDecisions = [];
  selectedDecisionProtocols.clear();
  elements.copilotVisitId.value = normalizedVisitId;
  elements.copilotContent.hidden = true;
  elements.copilotSummary.replaceChildren();
  elements.copilotEscalations.replaceChildren();
  elements.copilotRoadmap.replaceChildren();
  elements.copilotDecisionOptions.replaceChildren();
  elements.copilotDecisionHistory.replaceChildren();
  elements.copilotDecisionSection.hidden = true;
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
      await loadTreatmentDecisions(normalizedVisitId);
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
    { workspace: "learning", tab: elements.learningTab },
    { workspace: "evidence", tab: elements.evidenceTab },
    { workspace: "safety", tab: elements.safetyTab },
    { workspace: "pilot", tab: elements.pilotReadinessTab },
  ].filter((entry) => !entry.tab.hidden);
}

elements.loginForm.addEventListener("submit", handleLogin);
elements.logoutButton.addEventListener("click", showLogin);
elements.refreshButton.addEventListener("click", () => {
  if (activeWorkspace === "copilot" && currentCopilotVisitId) {
    loadCopilotWorkspace(currentCopilotVisitId);
  } else if (activeWorkspace === "learning") {
    loadClinicalLearningReview();
  } else if (activeWorkspace === "evidence" && currentEvidenceVisitId) {
    loadEvidenceWorkspace(currentEvidenceVisitId);
  } else if (activeWorkspace === "safety" && currentSafetyVisitId) {
    loadSafetyEscalations({ quiet: true });
    loadSafetyWorkspace(currentSafetyVisitId);
  } else if (activeWorkspace === "safety") {
    loadSafetyEscalations();
  } else if (activeWorkspace === "pilot") {
    loadPilotReadiness();
  } else {
    loadFlow();
  }
});
elements.flowTab.addEventListener("click", () => setWorkspace("flow"));
elements.copilotTab.addEventListener("click", () => setWorkspace("copilot"));
elements.learningTab.addEventListener("click", () => setWorkspace("learning"));
elements.loadLearningButton.addEventListener("click", () => loadClinicalLearningReview());
elements.learningGovernanceSignals.addEventListener("submit", async (event) => {
  const form = event.target.closest("form.governance-case-form");
  if (!form) {
    return;
  }
  event.preventDefault();
  await createGovernanceCase(form);
});
elements.learningGovernanceCases.addEventListener("submit", async (event) => {
  const recoveryCaseForm = event.target.closest(
    "form.governance-recovery-case-form",
  );
  if (recoveryCaseForm) {
    event.preventDefault();
    await createGovernanceRecoveryCase(recoveryCaseForm);
    return;
  }
  const recoveryForm = event.target.closest(
    "form.governance-recovery-execute-form",
  );
  if (recoveryForm) {
    event.preventDefault();
    await executeGovernanceRecovery(recoveryForm);
    return;
  }
  const releaseForm = event.target.closest("form.governance-release-form");
  if (releaseForm) {
    event.preventDefault();
    await executeGovernanceRelease(releaseForm);
    return;
  }
  const reviewForm = event.target.closest("form.governance-review-form");
  if (!reviewForm) {
    return;
  }
  event.preventDefault();
  await reviewGovernanceCase(reviewForm);
});
elements.evidenceTab.addEventListener("click", () => setWorkspace("evidence"));
elements.safetyTab.addEventListener("click", () => setWorkspace("safety"));
elements.pilotReadinessTab.addEventListener("click", () => setWorkspace("pilot"));
elements.loadPilotReadinessButton.addEventListener("click", () => loadPilotReadiness());
elements.freezePilotLaunchPackageButton.addEventListener(
  "click",
  freezePilotLaunchPackage,
);
elements.pilotLaunchHistory.addEventListener("submit", async (event) => {
  const form = event.target.closest("form.pilot-release-decision-form");
  if (!form) {
    return;
  }
  event.preventDefault();
  await createPilotReleaseDecision(form);
});
elements.pilotManualGates.addEventListener("submit", async (event) => {
  const attestationForm = event.target.closest("form.pilot-attestation-form");
  if (attestationForm) {
    event.preventDefault();
    await createPilotManualAttestation(attestationForm);
    return;
  }
  const reviewForm = event.target.closest("form.pilot-review-form");
  if (reviewForm) {
    event.preventDefault();
    await reviewPilotManualAttestation(reviewForm);
  }
});
for (const tab of [
  elements.flowTab,
  elements.copilotTab,
  elements.learningTab,
  elements.evidenceTab,
  elements.safetyTab,
  elements.pilotReadinessTab,
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
elements.copilotRoadmap.addEventListener("change", (event) => {
  const checkbox = event.target.closest("input[data-decision-protocol-key]");
  if (!checkbox || !canCreateTreatmentDecision()) {
    return;
  }
  if (checkbox.checked) {
    selectedDecisionProtocols.add(checkbox.dataset.decisionProtocolKey);
  } else {
    selectedDecisionProtocols.delete(checkbox.dataset.decisionProtocolKey);
  }
  renderSelectedDecisionProtocols();
});
elements.copilotDecisionType.addEventListener("change", syncDecisionForm);
elements.copilotDecisionForm.addEventListener("submit", createTreatmentDecision);
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
  } else if (activeWorkspace === "learning") {
    loadClinicalLearningReview({ quiet: true });
  } else if (activeWorkspace === "evidence" && currentEvidenceVisitId) {
    loadEvidenceWorkspace(currentEvidenceVisitId);
  } else if (activeWorkspace === "safety" && currentSafetyVisitId) {
    loadSafetyEscalations({ quiet: true });
    loadSafetyWorkspace(currentSafetyVisitId);
  } else if (activeWorkspace === "safety") {
    loadSafetyEscalations({ quiet: true });
  } else if (activeWorkspace === "pilot") {
    loadPilotReadiness({ quiet: true });
  }
});

window.addEventListener("offline", () => setConnectionState(false));

elements.username.focus();
