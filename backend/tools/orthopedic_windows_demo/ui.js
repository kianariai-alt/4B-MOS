/* Offline authoring demo. Only fixed cases contain Python-engine output.
 * The live form uses exported question conditions for visibility, never medical
 * inference, safety evaluation, conflict resolution, or treatment selection.
 */
(() => {
  "use strict";
  const data = JSON.parse(document.getElementById("mos-demo-data").textContent);
  const tree = data.tree;
  const nodes = tree.nodes;
  const byField = new Map(nodes.map(node => [node.field, node]));
  const boolFields = new Set(data.boolean_fields || []);
  const textFields = new Set(data.text_fields || []);
  const stages = [
    ["opening", "شروع و مشخص‌کردن مشکل"], ["risk_information", "اطلاعات نیازمند توجه پزشک"],
    ["symptoms", "الگوی علائم و عملکرد"], ["mechanical", "گیرکردن و محدودیت حرکت"],
    ["history", "آسیب، جراحی و درمان‌های قبلی"], ["goals", "هدف بیمار"]
  ];
  const fa = value => String(value).replace(/[0-9]/g, digit => "۰۱۲۳۴۵۶۷۸۹"[Number(digit)]);
  const valuesFa = {
    pain:"درد", swelling:"تورم", locking:"گیرکردن زانو", instability:"احساس ناپایداری", other:"سایر",
    right:"راست", left:"چپ", both:"هر دو", sudden:"ناگهانی", gradual:"تدریجی", unclear:"نامشخص",
    days:"چند روز", weeks:"چند هفته", months:"چند ماه", years:"چند سال", anterior:"جلوی زانو",
    medial:"سمت داخلی", lateral:"سمت خارجی", posterior:"پشت زانو", diffuse:"پراکنده",
    activity:"هنگام فعالیت", rest:"هنگام استراحت", night:"شب", mixed:"ترکیبی", walking:"راه‌رفتن",
    stairs:"پله", loaded_flexion:"خم‌کردن زیر بار", none:"هیچ‌کدام", mild:"کم", moderate:"متوسط",
    severe:"زیاد", sport_twist:"چرخش هنگام ورزش", fall:"زمین‌خوردن", direct_impact:"ضربهٔ مستقیم",
    improved:"بهتر شده", unchanged:"تغییری نکرده", worse:"بدتر شده", function:"بهبود عملکرد",
    decision_support:"کمک به تصمیم‌گیری", full:"کامل", restricted:"محدود"
  };
  const stateFa = {confirmed:"پاسخ گزارش‌شدهٔ کامل", unverified:"تأییدنشده", incomplete:"ناقص",
    contradictory:"متناقض", unknown:"نمی‌دانم", declined:"مایل به پاسخ نیستم", missing:"ثبت نشده"};
  const findingFa = {exam_effusion:"افیوژن در معاینه", exam_joint_line_tenderness:"حساسیت خط مفصلی در معاینه",
    exam_range_of_motion:"دامنهٔ حرکت در معاینه", imaging_kl_grade:"درجهٔ KL در تصویر",
    imaging_meniscal_lesion:"ضایعهٔ منیسک در تصویر", imaging_cartilage_lesion:"ضایعهٔ غضروف در تصویر"};
  const reasonsFa = {
    draft_tree_requires_independent_review:"این درخت و منابع به بررسی مستقل متخصص نیاز دارند.",
    existing_safety_engine_not_evaluated_by_preview:"ارزیابی موتور ایمنی در این پیش‌نمایش انجام نشده است.",
    book_population_applicability_not_assessed:"تناسب جمعیت منبع کتابی با این پرونده ارزیابی نشده است.",
    bank_export_requires_tree_routing_and_episode_constraints:"اجرای مصاحبه به شروط شاخه‌ها و تفکیک هر سابقهٔ درمان وابسته است.",
    needs_pain_presence_clarification:"وجود یا نبود درد باید صریحاً روشن شود.",
    outside_knee_scope:"موضوع خارج از دامنهٔ زانو است؛ سؤال زانو پیشنهاد نشده است.",
    body_region_requires_physician_clarification:"ناحیهٔ بدن باید توسط پزشک روشن شود.",
    treatment_episode_capture_required:"نوع هر درمان قبلی باید در سابقه‌ای جدا مشخص شود.",
    treatment_episodes_require_prior_treatment_clarification:"سابقه‌های درمان با پاسخ کلی درمان قبلی نیازمند تطبیق‌اند.",
    bilateral_history_requires_separate_side_contexts:"برای بررسی جزئیات هر زانو، زمینهٔ جداگانهٔ راست و چپ لازم است.",
    draft_hot_joint_information_requires_prompt_physician_review:"اطلاعات تورم تازه همراه تب، نیازمند بررسی سریع پزشک است.",
    draft_systemic_symptom_information_requires_physician_review:"بدحالی عمومی گزارش‌شده نیازمند بررسی پزشک است.",
    draft_neurovascular_trauma_information_requires_prompt_physician_review:"علائم عصبی‌عروقی پس از آسیب، نیازمند بررسی سریع پزشک‌اند.",
    neurovascular_report_requires_trauma_context_physician_review:"علائم عصبی‌عروقی گزارش شده اما زمینهٔ آسیب نیازمند روشن‌سازی پزشک است.",
    inconsistent_pain_presence_requires_physician_review:"گزارش وجود درد با پاسخ وابسته سازگار نیست؛ پزشک باید روشن کند.",
    draft_traumatic_motion_block_information_requires_physician_review:"گیرکردن حرکت همراه سابقهٔ آسیب، برای بررسی پزشک مشخص شده است."
  };
  let state = {mode:"cases", observations:{}, episodes:[], textDrafts:{}, nextEpisode:1, showClosed:false};
  const $ = id => document.getElementById(id);
  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }
  function labelFor(field) {
    if (field === "has_pain") return "وجود درد در دورهٔ مشکل زانو";
    return byField.get(field)?.question.text_fa || findingFa[field] || "دادهٔ ثبت‌شده";
  }
  function valueLabel(answer) {
    if (!answer) return "ثبت نشده";
    if (answer.state === "unknown" || answer.state === "declined") return stateFa[answer.state];
    if (answer.value === null || answer.value === undefined) return stateFa[answer.state] || "ثبت نشده";
    if (answer.value === true) return "بله";
    if (answer.value === false) return "خیر";
    if (typeof answer.value === "number") return fa(answer.value);
    return choiceLabel(answer.field, answer.value);
  }
  function choiceLabel(field, value) {
    const overrides = {
      care_goal:{pain:"کاهش درد", function:"بهبود عملکرد", activity:"بازگشت به فعالیت", decision_support:"کمک به تصمیم‌گیری"},
      functional_limitation:{none:"بدون محدودیت", mild:"محدودیت کم", moderate:"محدودیت متوسط", severe:"محدودیت زیاد"},
      relieving_factor:{activity:"فعالیت", rest:"استراحت", none:"هیچ‌کدام"}
    };
    return overrides[field]?.[value] || valuesFa[value] || value;
  }
  function reasonLabel(reason) {
    if (reasonsFa[reason]) return reasonsFa[reason];
    const parts = reason.split(":");
    if (stateFa[parts[0]] && parts[1]) return labelFor(parts[1]) + " — " + stateFa[parts[0]];
    if (parts[0] === "parent_child_conflict") return "پاسخ‌های وابسته نیازمند روشن‌سازی‌اند: " + labelFor(parts[1]) + " / " + labelFor(parts[2]);
    if (parts[0] === "dependent_answer_requires_parent_clarification") return "پیش‌نیاز این پاسخ روشن نیست: " + labelFor(parts[2]);
    if (parts[0].startsWith("treatment_")) return "نوع درمان یا پیش‌نیاز پاسخِ پیامد درمان نیازمند روشن‌سازی است.";
    return "یک مورد برای بازبینی پزشک مشخص شده است؛ شناسه در جزئیات فنی آمده است.";
  }
  function sourceButton(node, bookKeys = null) {
    const button = el("button", "text-button source-button", "منبع و دلیل این سؤال");
    button.type = "button";
    button.dataset.sourceFact = node.source_fact_keys?.[0] || "";
    button.dataset.questionNumber = String(node.number);
    button.addEventListener("click", () => showSources(node, bookKeys));
    return button;
  }
  function metadataDetails(title, content, id) {
    const details = el("details", "technical");
    if (id) details.id = id;
    details.append(el("summary", "", title));
    details.append(el("pre", "", content));
    return details;
  }
  function showSources(node, bookKeys) {
    $("source-title").textContent = "منابع سؤال " + fa(node.number);
    const target = $("source-content"); target.replaceChildren();
    target.append(el("p", "source-caption", "عبارت سؤال و اتصال آن به منبع، تألیف Draft و نیازمند بررسی مستقل است؛ این ارجاع اعتبارسنجی پرسشنامه نیست."));
    target.append(el("p", "", node.rationale_fa));
    const used = new Set();
    for (const fact of node.source_fact_keys || []) {
      const keys = data.fact_sources?.[fact] || [];
      const row = el("div", "source-entry");
      row.append(el("h3", "", "ارجاع دانش: " + fact));
      const index = node.source_fact_keys.indexOf(fact);
      if (node.source_content_sha256s?.[index]) row.append(el("p", "source-hash", "SHA-256: " + node.source_content_sha256s[index]));
      for (const key of keys) {
        if (used.has(key)) continue;
        used.add(key);
        const ref = (tree.source_references || []).find(item => item.source_key === key);
        if (ref) renderSource(row, ref.source);
      }
      if (!keys.length) row.append(el("p", "", "جزئیات منبع در بستهٔ دانش با این شناسه قابل‌ردیابی است."));
      target.append(row);
    }
    if (!(node.source_fact_keys || []).length) target.append(el("div", "source-entry", "این سؤال افزودهٔ طراحی برای مشخص‌کردن سمت است و ادعای پزشکیِ دارای منبع مستقل ندارد."));
    const bound = new Set(bookKeys || []);
    // In a fixed case, show only annotations actually returned by Python.
    // In the form, show available bindings with their explicit scope caveat.
    if (bookKeys === null) for (const binding of node.book_bindings || []) bound.add(binding.candidate_key);
    for (const key of bound) {
      const ref = (tree.book_source_references || []).find(item => item.candidate_key === key);
      if (!ref) continue;
      const row = el("div", "source-entry");
      row.append(el("span", "tag tag-amber", "کتاب — فقط در زمینهٔ صریح بازبینی آرتروپلاستی"));
      renderSource(row, ref.source);
      const p = ref.provenance || {};
      row.append(el("p", "", "فصل: " + (p.chapter || "نیازمند بررسی")));
      row.append(el("p", "", "صفحهٔ PDF: " + (p.pages || []).map(page => fa(page.pdf_page_number)).join("، ") + "؛ صفحهٔ چاپیِ متنی: " + (p.reported_printed_pages || "تأییدنشده")));
      row.append(el("p", "", "تأیید بصری صفحه انجام نشده و بررسی مستقل منبع باقی است."));
      for (const limitation of ref.limitations || []) row.append(el("p", "", "• " + limitation));
      target.append(row);
    }
    $("source-panel").hidden = false;
    $("source-panel").scrollIntoView?.({behavior:"smooth", block:"start"});
    $("source-panel").focus({preventScroll:true});
  }
  function renderSource(target, source) {
    if (!source) return;
    target.append(el("h3", "", source.title || "منبع علمی"));
    if (source.citation) target.append(el("p", "citation", source.citation));
    if (source.guideline_version) target.append(el("p", "", "نسخه: " + source.guideline_version));
    if (source.doi) target.append(el("p", "citation", "DOI: " + source.doi));
    // Source URLs are text only: this portable review has no network actions.
    if (source.url) target.append(el("p", "citation", source.url));
  }
  function answerList(observations, extraLabel = "") {
    const list = el("ul", "answer-list");
    for (const answer of observations || []) {
      const item = el("li", "");
      item.dataset.field = answer.field;
      item.append(el("span", "label", (extraLabel ? extraLabel + " · " : "") + labelFor(answer.field)));
      item.append(el("span", "value", valueLabel(answer)));
      item.append(el("span", "answer-meta", stateFa[answer.state] || "گزارش خام"));
      list.append(item);
    }
    if (!list.children.length) list.append(el("li", "muted", "پاسخی ثبت نشده است."));
    return list;
  }
  function renderCase() {
    const index = Number($("case-select").value || 0);
    const item = data.cases[index]; if (!item) return;
    const preview = item.preview;
    const context = item.request.context;
    const root = $("case-content"); root.replaceChildren();
    root.append(el("h3", "case-title", item.description_fa));
    const metrics = el("div", "metric-row");
    for (const [count, text] of [[preview.question_candidates.length,"پرسش پیشنهادی یا روشن‌سازی"], [preview.information_gaps.length,"شکاف اطلاعاتی ثبت‌شده"], [0,"محتوای Approved در این مسیر"]]) {
      const metric = el("div", "metric"); metric.append(el("strong", "", fa(count)), el("span", "", text)); metrics.append(metric);
    }
    root.append(metrics);
    const grid = el("div", "case-grid");
    const left = el("div", ""); const inputs = el("section", "panel");
    inputs.append(el("h3", "", "اطلاعات اولیهٔ پروندهٔ ساختگی"));
    inputs.append(el("p", "muted", "این‌ها ورودی‌های اولیه‌اند؛ ممکن است با هم ناسازگار یا تأییدنشده باشند. ابهام‌ها و نیاز به روشن‌سازی در خروجی موتور مشخص می‌شوند."));
    const domain = context.body_region === "knee" ? "زانو" : context.body_region === "other" ? "خارج از زانو" : "نامشخص";
    inputs.append(el("p", "muted", "دامنه: " + domain));
    inputs.append(answerList(context.observations));
    for (const [number, episode] of (context.treatment_episodes || []).entries()) {
      inputs.append(el("h4", "clinical-channel", "درمان ساختگی " + fa(number + 1)));
      inputs.append(answerList(episode.observations));
    }
    if (context.clinical_findings?.length) {
      inputs.append(el("h4", "clinical-channel", "کانال جدا: معاینه و تصویربرداری"));
      inputs.append(answerList(context.clinical_findings));
    }
    left.append(inputs);
    const gaps = el("section", "panel"); gaps.append(el("h3", "", "اطلاعات ناقص یا نیازمند روشن‌سازی"));
    const gapList = el("ul", "gap-list");
    for (const gap of preview.information_gaps) {
      const label = labelFor(gap.field) + " — " + (stateFa[gap.reason] || gap.reason) + (gap.episode_ref ? "؛ مربوط به همان سابقهٔ درمان" : "");
      gapList.append(el("li", "", label));
    }
    if (!gapList.children.length) gapList.append(el("li", "", "در این خروجی شکاف اطلاعاتی گزارش نشده است؛ این به معنی تأیید ایمنی نیست."));
    gaps.append(gapList); left.append(gaps); grid.append(left);
    const right = el("section", ""); right.append(el("h3", "case-title", "موتور چه سؤال‌هایی پیشنهاد کرده است؟"));
    for (const candidate of preview.question_candidates) {
      const node = byField.get(candidate.field); if (!node) continue;
      const card = el("article", "candidate-card case-question");
      card.dataset.field = candidate.field; card.dataset.number = String(candidate.number); card.dataset.episodeRef = candidate.episode_ref || "";
      const top = el("div", "candidate-top"); top.append(el("span", "question-number", fa(candidate.number)), el("span", "candidate-text", candidate.question.text_fa)); card.append(top);
      card.append(el("p", "", candidate.rationale_fa));
      if (candidate.episode_ref) card.append(el("p", "", "این سؤال فقط به همان سابقهٔ درمان اختصاص دارد: " + candidate.episode_ref));
      const foot = el("div", "candidate-foot"); foot.append(el("span", "tag " + (candidate.action === "physician_clarification" ? "tag-amber" : "tag-muted"), candidate.action === "physician_clarification" ? "روشن‌سازی توسط پزشک" : "تکمیل اطلاعات ثبت‌نشده"), sourceButton(node, candidate.book_candidate_keys)); card.append(foot); right.append(card);
    }
    if (!preview.question_candidates.length) right.append(el("div", "empty-state", "در این زمینه سؤال زانو پیشنهاد نشده است. دلیل را در بخش بازبینی ببینید."));
    grid.append(right); root.append(grid);
    const review = el("section", "panel"); review.append(el("h3", "", "مواردی که باید هنگام بازبینی دیده شوند"));
    const list = el("ul", "review-list");
    for (const reason of preview.review_reasons) list.append(el("li", "", reasonLabel(reason)));
    review.append(list);
    review.append(metadataDetails("شناسه‌ها و هش خروجی واقعی موتور", JSON.stringify({case_id:item.id, request_sha256:preview.request_sha256, rules_sha256:preview.rules_sha256, result_sha256:preview.result_sha256, review_reasons:preview.review_reasons}, null, 2), "case-metadata"));
    root.append(review);
  }
  function currentAnswer(field, episodeRef) {
    return episodeRef ? state.episodes.find(item => item.ref === episodeRef)?.answers[field] : state.observations[field];
  }
  function setAnswer(field, answer, episodeRef) {
    const answers = episodeRef ? state.episodes.find(item => item.ref === episodeRef).answers : state.observations;
    if (answer) answers[field] = {field, ...answer}; else delete answers[field];
  }
  function parentConditionsOpen(node) {
    return (node.conditions || []).every(condition => {
      const parent = state.observations[condition.field];
      return parent?.state === "confirmed" && parent.value === condition.equals;
    });
  }
  function nodeOpen(node, episodeRef) {
    if (!parentConditionsOpen(node)) return false;
    if (node.repeat_per_treatment && !episodeRef) return false;
    if (node.requires_treatment_description) {
      const description = currentAnswer("treatment_description", episodeRef);
      return description?.state === "confirmed" && typeof description.value === "string" && Boolean(description.value.trim());
    }
    return true;
  }
  function controlId(field, episodeRef) { return episodeRef ? "form-episode-" + episodeRef + "-" + field : "form-field-" + field; }
  function selectedValue(answer) {
    if (!answer) return "";
    if (answer.state === "unknown" || answer.state === "declined") return answer.state;
    if (answer.value === true) return "yes";
    if (answer.value === false) return "no";
    return answer.value === null || answer.value === undefined ? "" : String(answer.value);
  }
  function option(select, value, text) { const item = el("option", "", text); item.value = value; select.append(item); }
  function makeControl(field, episodeRef, enabled, idOverride) {
    const answer = currentAnswer(field, episodeRef);
    const host = el("div", "question-control");
    const id = idOverride || controlId(field, episodeRef);
    if (textFields.has(field)) {
      const draftKey = (episodeRef || "general") + ":" + field;
      if (!(draftKey in state.textDrafts) && answer?.state === "confirmed") state.textDrafts[draftKey] = answer.value || "";
      const mode = el("select", "answer-state");
      mode.id = episodeRef ? "form-episode-state-" + episodeRef + "-" + field : "form-state-" + field;
      mode.setAttribute("aria-label", "وضعیت پاسخ: " + labelFor(field));
      option(mode, "confirmed", "ورود متن پاسخ ساختگی"); option(mode, "unknown", "نمی‌دانم"); option(mode, "declined", "مایل به پاسخ نیستم");
      mode.value = answer?.state === "unknown" || answer?.state === "declined" ? answer.state : "confirmed";
      mode.disabled = !enabled;
      const textarea = el("textarea", ""); textarea.id = id; textarea.maxLength = 1000;
      textarea.placeholder = "فقط اطلاعات ساختگی؛ حداکثر ۱۰۰۰ نویسه";
      textarea.setAttribute("aria-label", labelFor(field));
      textarea.value = state.textDrafts[draftKey] || "";
      textarea.disabled = !enabled || mode.value !== "confirmed";
      textarea.addEventListener("input", () => {
        const value = textarea.value.slice(0, 1000);
        state.textDrafts[draftKey] = value;
        setAnswer(field, value.trim() ? {state:"confirmed",value} : null, episodeRef);
        renderSummary();
      });
      textarea.addEventListener("change", renderForm);
      mode.addEventListener("change", () => {
        const draft = state.textDrafts[draftKey] || "";
        setAnswer(field, mode.value === "confirmed" ? (draft.trim() ? {state:"confirmed",value:draft} : null) : {state:mode.value,value:null}, episodeRef);
        renderForm();
      });
      host.append(mode, textarea);
      if (mode.value !== "confirmed" && textarea.value) host.append(el("p", "muted", "متن قبلی در حافظه حفظ شده است؛ تا تغییر وضعیت پاسخ، به‌عنوان پاسخ قابل‌استفاده در نظر گرفته نمی‌شود."));
      return host;
    }
    const select = el("select", ""); select.id = id;
    select.dataset.field = field; if (episodeRef) select.dataset.episodeRef = episodeRef;
    select.setAttribute("aria-label", labelFor(field));
    option(select, "", "هنوز پاسخ نداده‌ام");
    if (boolFields.has(field)) { option(select, "yes", "بله"); option(select, "no", "خیر"); }
    else if (field === "pain_score_now") { for (let number = 0; number <= 10; number++) option(select, String(number), fa(number)); }
    else for (const value of data.choices[field] || []) option(select, value, choiceLabel(field, value));
    option(select, "unknown", "نمی‌دانم"); option(select, "declined", "مایل به پاسخ نیستم");
    select.value = selectedValue(answer); select.disabled = !enabled;
    select.addEventListener("change", () => {
      const chosen = select.value;
      let answer = null;
      if (chosen === "unknown" || chosen === "declined") answer = {state:chosen,value:null};
      else if (chosen !== "") answer = {state:"confirmed",value:boolFields.has(field) ? chosen === "yes" : field === "pain_score_now" ? Number(chosen) : chosen};
      setAnswer(field, answer, episodeRef);
      if (field === "prior_treatment" && answer?.value === true && state.episodes.length === 0) addEpisode(false);
      renderForm();
    });
    host.append(select); return host;
  }
  function conditionText(node) {
    if (node.requires_treatment_description) return "این شاخه پس از ثبت نوع همان درمان باز می‌شود.";
    const parent = node.conditions?.[0]?.field;
    const labels = {trauma:"آسیب قبلی", has_pain:"وجود درد", mechanical_locking:"گیرکردن زانو", prior_surgery:"جراحی قبلی", prior_treatment:"درمان قبلی"};
    return "این شاخه فقط با پاسخ کامل «بله» به «" + (labels[parent] || "پیش‌نیاز") + "» باز می‌شود.";
  }
  function questionCard(node, episodeRef) {
    const open = nodeOpen(node, episodeRef);
    const card = el("article", "question-card" + (open ? "" : " is-closed"));
    card.dataset.field = node.field; card.dataset.number = String(node.number); card.dataset.branchOpen = String(open);
    if (episodeRef) card.dataset.episodeRef = episodeRef;
    card.hidden = !open && !state.showClosed;
    const top = el("div", "question-top");
    const label = el("label", "", node.question.text_fa); label.htmlFor = controlId(node.field, episodeRef);
    top.append(el("span", "question-number", fa(node.number)), label); card.append(top);
    card.append(makeControl(node.field, episodeRef, open));
    if (!open) card.append(el("p", "question-help", conditionText(node)));
    const source = el("div", "question-source"); source.append(sourceButton(node)); card.append(source);
    return card;
  }
  function addEpisode(render = true) {
    if (state.episodes.length >= 20) return;
    state.episodes.push({ref:"treatment-" + state.nextEpisode++,answers:{}});
    if (render) renderForm();
  }
  function renderForm() {
    const root = $("form-content"); root.replaceChildren();
    const nav = $("stage-nav"); nav.replaceChildren();
    let visible = 0;
    for (const [index, [stage, title]] of stages.entries()) {
      const section = el("section", "stage-section"); section.id = "form-stage-" + stage;
      const heading = el("div", "stage-heading"); heading.append(el("span", "", fa(index + 1)), el("h3", "", title)); section.append(heading);
      const link = el("a", "", title); link.href = "#" + section.id; nav.append(link);
      for (const node of nodes.filter(item => item.stage === stage && !item.repeat_per_treatment)) {
        const card = questionCard(node); if (nodeOpen(node)) visible++;
        section.append(card);
        if (node.field === "duration") {
          const routing = el("article", "question-card routing-card");
          routing.append(el("h4", "", "پیش‌نیاز شاخهٔ درد"));
          const label = el("label", "question-help", "آیا در دورهٔ این مشکل، درد زانو وجود داشته است؟"); label.htmlFor = "has-pain"; routing.append(label);
          routing.append(makeControl("has_pain", null, true, "has-pain"));
          routing.append(el("p", "question-help", "این کنترل، وضعیت صریح مسیریابی است؛ سؤال شمارهٔ ۳۱ نیست. درد در دورهٔ مشکل می‌تواند با دردِ صفر همین حالا همراه باشد.")); section.append(routing);
        }
        if (node.field === "prior_treatment") {
          const enabled = state.observations.prior_treatment?.state === "confirmed" && state.observations.prior_treatment.value === true;
          const block = el("div", "treatments"); block.id = "treatment-episodes"; block.hidden = !enabled && !state.showClosed;
          for (const [episodeIndex, episode] of state.episodes.entries()) {
            const group = el("section", "episode"); group.dataset.episodeRef = episode.ref;
            const titleRow = el("div", "episode-heading"); titleRow.append(el("h4", "", "سابقهٔ درمان " + fa(episodeIndex + 1)));
            titleRow.append(el("span", "tag tag-muted", "پاسخ مستقل برای همین درمان")); group.append(titleRow);
            for (const episodeNode of nodes.filter(item => item.repeat_per_treatment)) {
              group.append(questionCard(episodeNode, episode.ref));
              if (nodeOpen(episodeNode, episode.ref)) visible++;
            }
            block.append(group);
          }
          const add = el("button", "button button-primary", "افزودن یک درمان دیگر"); add.id = "add-treatment"; add.type = "button";
          add.disabled = !enabled || state.episodes.length >= 20; add.addEventListener("click", () => addEpisode()); block.append(add);
          section.append(block);
        }
      }
      root.append(section);
    }
    $("visible-count").textContent = fa(visible);
    $("bilateral-notice").hidden = !(state.observations.laterality?.value === "both");
    renderSummary();
  }
  function renderSummary() {
    const target = $("form-summary-output"); target.replaceChildren();
    const entries = [];
    let closedCount = 0;
    for (const [field, answer] of Object.entries(state.observations)) {
      const node = byField.get(field);
      const open = !node || nodeOpen(node);
      if (!open) closedCount++;
      entries.push({answer,open,label:""});
    }
    for (const [index, episode] of state.episodes.entries()) for (const [field, answer] of Object.entries(episode.answers)) {
      const node = byField.get(field); const open = nodeOpen(node, episode.ref);
      if (!open) closedCount++;
      entries.push({answer,open,label:"درمان " + fa(index + 1)});
    }
    if (!entries.length) target.append(el("div", "empty-state", "هنوز پاسخی وارد نشده است. با سؤال‌های بالا شروع کنید."));
    const list = el("ul", "answer-list");
    for (const entry of entries) {
      const item = el("li", ""); item.dataset.field = entry.answer.field; item.dataset.branchOpen = String(entry.open);
      item.append(el("span", "label", (entry.label ? entry.label + " · " : "") + labelFor(entry.answer.field)));
      item.append(el("span", "value", valueLabel(entry.answer)));
      item.append(el("span", "answer-meta", entry.open ? "گزارش خام فرم؛ بررسی موتور انجام نشده" : "حفظ‌شده در حافظه؛ شاخه بسته و پاسخ از مسیر فعلی کنار گذاشته شده است")); list.append(item);
    }
    if (entries.length) target.append(list);
    $("closed-answers").hidden = closedCount === 0;
    $("closed-answers").textContent = closedCount ? fa(closedCount) + " پاسخِ شاخهٔ بسته در حافظه حفظ شده است. این پاسخ‌ها در مسیر فعلی استفاده نمی‌شوند؛ برای اصلاح می‌توانید پیش‌نیاز همان شاخه را تغییر دهید." : "";
  }
  function switchMode(mode) {
    state.mode = mode === "form" ? "form" : "cases";
    $("cases-view").hidden = state.mode !== "cases"; $("form-view").hidden = state.mode !== "form";
    for (const item of ["cases","form"]) { $("mode-" + item).classList.toggle("active", state.mode === item); $("mode-" + item).setAttribute("aria-pressed", String(state.mode === item)); }
    $("source-panel").hidden = true;
    if (state.mode === "form") renderForm();
  }
  function reset() { state.observations = {}; state.episodes = []; state.textDrafts = {}; state.nextEpisode = 1; state.showClosed = false; $("show-closed").checked = false; $("source-panel").hidden = true; renderForm(); }
  $("mode-cases").addEventListener("click", () => switchMode("cases"));
  $("mode-form").addEventListener("click", () => switchMode("form"));
  $("case-select").addEventListener("change", renderCase);
  $("form-reset").addEventListener("click", reset);
  $("source-close").addEventListener("click", () => { $("source-panel").hidden = true; });
  $("show-closed").addEventListener("change", () => { state.showClosed = $("show-closed").checked; renderForm(); });
  for (const [index, item] of data.cases.entries()) option($("case-select"), String(index), "پروندهٔ " + fa(index + 1) + " — " + item.description_fa);
  const buildInfo = data.build || {};
  $("build-info").textContent = JSON.stringify({version:buildInfo.version || data.schema_version, source_commit:buildInfo.source_commit || buildInfo.commit_sha || null, tree_sha256:tree.tree_sha256, fixed_case_count:data.cases.length}, null, 2);
  renderCase(); renderForm();
  window.MOS_DEMO = Object.freeze({
    getState: () => JSON.parse(JSON.stringify(state)),
    getVisibleFields: () => nodes.filter(node => !node.repeat_per_treatment && nodeOpen(node)).map(node => node.field),
    switchMode, reset
  });
  document.documentElement.dataset.demoReady = "true";
  document.documentElement.dataset.renderedCaseCount = String(data.cases.length);
})();
