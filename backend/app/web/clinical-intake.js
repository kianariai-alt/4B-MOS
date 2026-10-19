"use strict";

// Patient content is kept only in memory and cleared on logout or visit change.
let clinicalEditorEpoch = 0;
let clinicalEditorVisit = null;
let clinicalEditorRecord = null;
let clinicalEditorSavedContent = null;
let clinicalEditorBusy = false;
const clinicalListFields = ["functional_limitations", "relevant_history", "current_medications", "allergies", "red_flags"];
const clinicalTextFields = ["chief_complaint", "history_present_illness", "body_region", "laterality", "symptom_onset_date", "exam_findings", "clinical_impression", "care_goal"];
const clinicalEditorForm = document.querySelector("#clinical-intake-form");

function clinicalEditorMessage(message) {
  const node = document.querySelector("#clinical-intake-message");
  node.textContent = message;
  node.hidden = !message;
  if (message) node.scrollIntoView?.({block: "nearest", behavior: "smooth"});
}

function resetClinicalIntakeEditor() {
  clinicalEditorEpoch += 1;
  clinicalEditorVisit = null;
  clinicalEditorRecord = null;
  clinicalEditorSavedContent = null;
  clinicalEditorBusy = false;
  clinicalEditorForm.reset();
  document.querySelector("#clinical-patient-source")?.remove();
  document.querySelector("#clinical-intake-editor").hidden = true;
  document.querySelector("#clinical-intake-status").textContent = "";
  document.querySelector("#clinical-intake-acknowledge").checked = false;
  document.querySelector("#clinical-intake-revision-reason").value = "";
  document.querySelector("#clinical-intake-finalize-section").hidden = true;
  document.querySelector("#clinical-intake-correction-section").hidden = true;
  clinicalEditorMessage("");
}

function clinicalEditorContent() {
  const content = {};
  for (const name of clinicalTextFields) {
    content[name] = name === "symptom_onset_date"
      ? MosSolarDate.readDate(clinicalEditorForm.elements[name])
      : clinicalEditorForm.elements[name].value.trim() || null;
  }
  for (const name of clinicalListFields) {
    const seen = new Set();
    content[name] = clinicalEditorForm.elements[name].value.split(/\r?\n/).map(value => value.trim()).filter(value => {
      if (!value || seen.has(value.toLowerCase())) return false;
      seen.add(value.toLowerCase());
      return true;
    });
  }
  const pain = clinicalEditorForm.elements.pain_score.value;
  content.pain_score = pain === "" ? null : Number(pain);
  return content;
}

function clinicalEditorDirty() {
  return clinicalEditorSavedContent !== JSON.stringify(clinicalEditorContent());
}

function updateClinicalEditorControls() {
  const draft = clinicalEditorVisit && canReadCopilot() && (!clinicalEditorRecord || clinicalEditorRecord.status === "draft");
  for (const field of clinicalEditorForm.elements) field.disabled = clinicalEditorBusy || !draft;
  document.querySelector("#clinical-intake-reload").disabled = clinicalEditorBusy;
  document.querySelector("#clinical-intake-correction").disabled = clinicalEditorBusy;
  document.querySelector("#clinical-intake-revision-reason").disabled = clinicalEditorBusy;
  const acknowledge = document.querySelector("#clinical-intake-acknowledge");
  acknowledge.disabled = clinicalEditorBusy || clinicalEditorDirty();
  if (clinicalEditorDirty()) acknowledge.checked = false;
  document.querySelector("#clinical-intake-finalize").disabled = clinicalEditorBusy
    || !clinicalEditorRecord || clinicalEditorRecord.status !== "draft"
    || clinicalEditorDirty() || !acknowledge.checked;
}

function renderClinicalEditor(record) {
  clinicalEditorRecord = record;
  clinicalEditorForm.reset();
  const region = clinicalEditorForm.elements.body_region;
  region.querySelectorAll("[data-existing-region]").forEach(option => option.remove());
  if (record && record.body_region && ![...region.options].some(option => option.value === record.body_region)) {
    const option = document.createElement("option");
    option.value = record.body_region;
    option.textContent = record.body_region;
    option.dataset.existingRegion = "true";
    region.append(option);
  }
  for (const name of clinicalTextFields) {
    const input = clinicalEditorForm.elements[name];
    input.setCustomValidity("");
    input.value = name === "symptom_onset_date" ? MosSolarDate.toSolar(record?.[name]) : record?.[name] ?? (name === "laterality" ? "unknown" : "");
  }
  for (const name of clinicalListFields) clinicalEditorForm.elements[name].value = (record?.[name] || []).join("\n");
  clinicalEditorForm.elements.pain_score.value = record?.pain_score ?? "";
  clinicalEditorSavedContent = JSON.stringify(clinicalEditorContent());
  document.querySelector("#clinical-intake-status").textContent = record
    ? `نسخهٔ ${toPersianNumber(record.version)} — ${record.status === "draft" ? "پیش‌نویس؛ هنوز وارد زمینهٔ بالینی نهایی نشده است" : record.status === "final" ? "نهایی و فقط‌خواندنی" : "برای ادامه، سابقهٔ نسخه‌ها باید بررسی شود"}`
    : "شرح‌حال بالینی هنوز ثبت نشده است.";
  document.querySelector("#clinical-intake-finalize-section").hidden = !record || record.status !== "draft";
  document.querySelector("#clinical-intake-correction-section").hidden = !record || record.status !== "final";
  document.querySelector("#clinical-intake-acknowledge").checked = false;
  document.querySelector("#clinical-intake-editor").hidden = false;
  updateClinicalEditorControls();
}

function clinicalEditorError(error) {
  if (error instanceof ApiError && error.status === 401) {
    showLogin();
    elements.loginMessage.textContent = "نشست شما پایان یافته است؛ دوباره وارد شوید.";
    return;
  }
  const message = error instanceof ApiError && error.status === 409
    ? "شرح‌حال یا وضعیت ویزیت تغییر کرده است؛ پیش از ثبت دوباره، شرح‌حال ذخیره‌شده را بازخوانی کنید."
    : error instanceof ApiError && error.status === 403
      ? "حساب شما اجازهٔ ثبت یا تأیید این شرح‌حال را ندارد."
      : error instanceof ApiError && error.status === 422
        ? "فیلدهای شرح‌حال را بررسی کنید؛ تاریخ شروع نباید در آینده باشد و هر موردِ فهرست حداکثر ۵۰۰ نویسه است."
        : "نتیجهٔ درخواست مشخص نیست؛ برای جلوگیری از ثبت تکراری، ابتدا شرح‌حال ذخیره‌شده را بازخوانی کنید.";
  clinicalEditorMessage(message);
}

async function loadClinicalIntakeEditor(visitId, generation = sessionGeneration) {
  resetClinicalIntakeEditor();
  if (!canReadCopilot()) return;
  clinicalEditorVisit = visitId;
  const epoch = clinicalEditorEpoch;
  clinicalEditorBusy = true;
  const active = () => epoch === clinicalEditorEpoch && generation === sessionGeneration
    && canReadCopilot() && currentCopilotVisitId === visitId;
  try {
    const records = await apiRequest(`/visits/${encodeURIComponent(visitId)}/clinical-intakes`);
    if (!active()) return;
    const record = [...records].sort((a, b) => b.version - a.version)[0] || null;
    renderClinicalEditor(record);
    try {
      const source = await apiRequest(`/portal-staff/visits/${encodeURIComponent(visitId)}/patient-report`);
      if (!active() || !source?.content) return;
      const panel = document.createElement("section");
      panel.id = "clinical-patient-source";
      const title = document.createElement("h3");
      title.textContent = "اطلاعات ارسالی بیمار — نیازمند بررسی پزشک";
      panel.append(title);
      const details = document.createElement("pre");
      details.style.whiteSpace = "pre-wrap";
      const data = source.content;
      details.textContent = [data.complaint, data.symptom_history,
        ...(data.other_specialists || []).map(value => "پزشک همکار: " + value),
        ...(source.messages || []).map(message => (message.from === "patient" ? "بیمار: " : "پزشک: ") + message.text),
        ...((Array.isArray(source.interview?.answers) ? source.interview.answers : []).map(answer => JSON.stringify(answer)))
      ].filter(Boolean).join("\n\n");
      panel.append(details);
      for (const file of source.attachments || []) {
        const label = document.createElement("p");
        label.textContent = file.name + " — مشاهده در صندوق درخواست‌های بیماران";
        panel.append(label);
      }
      clinicalEditorForm.before(panel);
      // Seed only a new, untouched editor. Existing clinician records always win.
      if (!record && !clinicalEditorDirty()) {
        const seed = {
          chief_complaint: data.complaint,
          history_present_illness: data.symptom_history,
          body_region: data.body_region, laterality: data.laterality,
          symptom_onset_date: data.symptom_onset_date, pain_score: data.pain_score,
          relevant_history: data.conditions, allergies: data.allergies,
          current_medications: (data.medications || []).map(medication =>
            [medication.name, medication.dose_as_reported, medication.frequency_as_reported,
              medication.use_status === "stopped" ? "قطع‌شده به اظهار بیمار" : ""].filter(Boolean).join(" — ")),
        };
        renderClinicalEditor(seed);
        clinicalEditorRecord = null;
        document.querySelector("#clinical-intake-status").textContent = "اطلاعات بیمار در فرم قرار گرفت؛ پس از بررسی و تکمیل، پیش‌نویس را ذخیره کنید.";
        document.querySelector("#clinical-intake-finalize-section").hidden = true;
      }
    } catch (sourceError) {
      if (!active()) return;
      if (!(sourceError instanceof ApiError && sourceError.status === 404))
        clinicalEditorMessage("اطلاعات درگاه بیمار بارگذاری نشد؛ دسترسی صندوق درخواست‌ها و اتصال سامانه را بررسی کنید.");
    }
  } catch (error) {
    if (!active()) return;
    // Show the reload control, but prevent creating records after a failed read.
    document.querySelector("#clinical-intake-editor").hidden = false;
    clinicalEditorVisit = null;
    clinicalEditorError(error);
  } finally {
    if (active()) {
      clinicalEditorBusy = false;
      updateClinicalEditorControls();
      if (!clinicalEditorVisit) for (const field of clinicalEditorForm.elements) field.disabled = true;
    }
  }
}

async function clinicalEditorAction(callback) {
  if (clinicalEditorBusy || !clinicalEditorVisit || !canReadCopilot()
      || clinicalEditorVisit !== currentCopilotVisitId) return;
  const generation = sessionGeneration, epoch = clinicalEditorEpoch;
  const active = () => generation === sessionGeneration && epoch === clinicalEditorEpoch && canReadCopilot();
  clinicalEditorBusy = true;
  updateClinicalEditorControls();
  try { await callback(active); }
  catch (error) { if (active()) clinicalEditorError(error); }
  finally { if (active()) { clinicalEditorBusy = false; updateClinicalEditorControls(); } }
}

clinicalEditorForm.addEventListener("input", updateClinicalEditorControls);
clinicalEditorForm.addEventListener("change", updateClinicalEditorControls);
document.querySelector("#clinical-intake-acknowledge").addEventListener("change", updateClinicalEditorControls);
document.querySelector("#clinical-intake-reload").addEventListener("click", () => {
  if (!clinicalEditorBusy && currentCopilotVisitId) loadClinicalIntakeEditor(currentCopilotVisitId);
});
clinicalEditorForm.addEventListener("submit", event => {
  event.preventDefault();
  if (!clinicalEditorForm.reportValidity() || (clinicalEditorRecord && clinicalEditorRecord.status !== "draft")) return;
  const content = clinicalEditorContent();
  const record = clinicalEditorRecord;
  const endpoint = record ? `/clinical-intakes/${encodeURIComponent(record.id)}`
    : `/visits/${encodeURIComponent(clinicalEditorVisit)}/clinical-intakes`;
  clinicalEditorAction(async active => {
    const saved = await apiRequest(endpoint, {method: record ? "PUT" : "POST",
      headers: record ? {"If-Match": record.content_sha256} : {}, body: JSON.stringify(content)});
    if (!active()) return;
    renderClinicalEditor(saved);
    clinicalEditorMessage("پیش‌نویس ذخیره شد. آن را بازبینی کنید؛ تأیید نهایی هنوز انجام نشده است.");
  });
});
document.querySelector("#clinical-intake-finalize").addEventListener("click", () => {
  if (!clinicalEditorRecord || clinicalEditorRecord.status !== "draft" || clinicalEditorDirty()
      || !document.querySelector("#clinical-intake-acknowledge").checked) return;
  const record = clinicalEditorRecord, visitId = clinicalEditorVisit, generation = sessionGeneration;
  clinicalEditorAction(async active => {
    const saved = await apiRequest(`/clinical-intakes/${encodeURIComponent(record.id)}/finalize`,
      {method: "POST", headers: {"If-Match": record.content_sha256}});
    if (!active()) return;
    renderClinicalEditor(saved);
    await loadCopilotWorkspace(visitId);
    if (generation === sessionGeneration && currentCopilotVisitId === visitId && canReadCopilot()) {
      clinicalEditorMessage("شرح‌حال نهایی شد؛ وضعیت پزشک‌یار دوباره بارگذاری شد.");
    }
  });
});
document.querySelector("#clinical-intake-correction").addEventListener("click", () => {
  if (!clinicalEditorRecord || clinicalEditorRecord.status !== "final") return;
  const reason = document.querySelector("#clinical-intake-revision-reason").value.trim();
  if (reason.length < 10) { clinicalEditorMessage("دلیل اصلاح را با حداقل ۱۰ نویسه وارد کنید."); return; }
  const record = clinicalEditorRecord, content = clinicalEditorContent();
  clinicalEditorAction(async active => {
    const saved = await apiRequest(`/clinical-intakes/${encodeURIComponent(record.id)}/supersede`,
      {method: "POST", body: JSON.stringify({...content, revision_reason: reason})});
    if (!active()) return;
    renderClinicalEditor(saved);
    clinicalEditorMessage("نسخهٔ اصلاحی به‌صورت پیش‌نویس ساخته شد؛ نسخهٔ نهایی قبلی تا تأیید اصلاحیه حفظ می‌شود.");
  });
});
