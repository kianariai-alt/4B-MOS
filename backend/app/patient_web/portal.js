"use strict";
(() => {
  const $ = (id) => document.getElementById(id);
  const form = $("intake");
  let csrf = "", current = null, step = 0, notice = "", requestKey = crypto.randomUUID();
  let messageKey = null, messageText = null, pendingSubmission = null, generation = 0;
  let interview = null, answerKey = null, answerBody = null;
  const statuses = {submitted:"در انتظار بررسی کارکنان", linked:"به ویزیت کلینیک متصل شد", withdrawn:"درخواست پس گرفته شد"};
  function status(text) { $("status").textContent = text; }
  async function api(path, options = {}) {
    const headers = new Headers(options.headers || {});
    if (csrf) headers.set("X-Portal-CSRF", csrf);
    if (options.body && !(options.body instanceof File)) headers.set("Content-Type", "application/json");
    const response = await fetch("/api/v1/patient-portal" + path, {...options, headers, credentials:"same-origin", cache:"no-store"});
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "اطلاعات را بررسی کنید و دوباره تلاش کنید.");
    return data;
  }
  function lines(name) {return form.elements[name].value.split(/\r?\n/).map(x=>x.trim()).filter(Boolean);}
  function data() {
    const out = {request_key:requestKey, processing_notice_version:notice};
    for (const name of ["entry_mode","first_name","last_name","complaint","laterality"]) out[name] = form.elements[name].value.trim();
    for (const name of ["contact_phone","date_of_birth","symptom_onset_date","symptom_history","body_region"]) out[name] = form.elements[name].value.trim() || null;
    out.pain_score = form.elements.pain_score.value === "" ? null : Number(form.elements.pain_score.value);
    for (const name of ["conditions","allergies","other_specialists"]) out[name] = lines(name);
    out.medications = lines("medications").map(name=>({name, use_status:"taking"}));
    for (const name of ["processing_consent","marketing_opt_in","wants_prompt_contact"]) out[name] = form.elements[name].checked;
    return out;
  }
  function showStep() {
    document.querySelectorAll("[data-step]").forEach(el=>el.hidden=Number(el.dataset.step)!==step);
    $("step-label").textContent = ["۱ / ۴ · آشنایی","۲ / ۴ · علائم","۳ / ۴ · سوابق","۴ / ۴ · مرور و ارسال"][step];
    $("back").hidden = step === 0; $("next").hidden = step === 3; $("submit").hidden = step !== 3;
    if (step===3) { const d=data(); $("review").textContent=`${d.first_name} ${d.last_name}\nنوع درخواست: ${d.entry_mode==="clinic_arrival"?"حضور در کلینیک":"بررسی از راه دور"}\nتماس: ${d.contact_phone||"ثبت نشده"}\nشکایت: ${d.complaint}\nشرح علائم: ${d.symptom_history||"ثبت نشده"}\nشدت درد: ${d.pain_score===null?"ثبت نشده":d.pain_score}\nسوابق: ${d.conditions.join("، ")||"ثبت نشده"}\nداروها: ${d.medications.map(x=>x.name).join("، ")||"ثبت نشده"}\nحساسیت‌ها: ${d.allergies.join("، ")||"ثبت نشده"}\nسایر متخصصان: ${d.other_specialists.join("، ")||"ثبت نشده"}`; }
  }
  function validStep() { for (const el of document.querySelector(`[data-step="${step}"]`).querySelectorAll("input,select,textarea")) if (!el.reportValidity()) return false; return true; }
  $("next").onclick=()=>{if(validStep()){step++;showStep();form.scrollIntoView({block:"start",behavior:"smooth"});}};
  $("back").onclick=()=>{step--;showStep();};
  form.elements.body_region.onchange=()=>{
    const region=form.elements.body_region.selectedOptions[0].textContent;
    $("followup-hint").textContent=`برای بررسی ${region}، لطفاً داروها، سوابق و تخصص پزشکان دیگری را که تحت نظرشان هستید نیز بنویسید.`;
    $("service-copy").textContent=["skin","hair"].includes(form.elements.body_region.value)?"برای آشنایی با خدمات پوست و مو، ابتدا وضعیت و هدف شما بررسی می‌شود؛ سپس پزشک دربارهٔ گزینه‌های متناسب توضیح می‌دهد.":"در ارزیابی مشکلات مفاصل، علائم، مدارک و شرایط زمینه‌ای شما کنار هم بررسی می‌شوند. تیم کلینیک مسیر ارزیابی و خدمات مرتبط را توضیح می‌دهد.";
  };
  form.addEventListener("input",()=>{if(pendingSubmission){pendingSubmission=null;requestKey=crypto.randomUUID();}});
  form.onsubmit=async(event)=>{event.preventDefault(); if(!validStep())return; const epoch=generation;$("submit").disabled=true;
    try { if(!pendingSubmission) pendingSubmission=data(); const result=await api("/requests",{method:"POST",body:JSON.stringify(pendingSubmission)});if(epoch!==generation)return;current=result.id;await load();if(epoch!==generation)return;form.hidden=true;status("درخواست ثبت شد. اکنون می‌توانید مدارک را ارسال کنید."); }
    catch(error){if(epoch===generation)status(error.message);} finally{if(epoch===generation)$("submit").disabled=false;}
  };
  async function load() {
    const epoch=generation,id=current;
    const item=await api("/requests/"+id);
    if(epoch!==generation||id!==current)return;
    $("receipt").hidden=false; $("receipt-code").textContent=item.receipt; $("request-state").textContent=statuses[item.state]||item.state;
    $("messages").replaceChildren(); for(const message of item.messages){const el=document.createElement("p");el.className="message";el.textContent=(message.from==="clinician"?"پزشک: ":"شما: ")+message.text;$("messages").append(el);}
    if(!item.messages.length)$("messages").textContent="هنوز پرسشی ثبت نشده است. برای مشاهدهٔ پیام‌های جدید، بررسی وضعیت را بزنید.";
    $("files").replaceChildren(); for(const file of item.attachments){const li=document.createElement("li");li.textContent=file.name+" · دریافت شد";$("files").append(li);}
    for(const id of ["upload","reply","withdraw"])$(id).disabled=item.state==="withdrawn";
    interview=item.interview||{available:false};renderInterview();
  }
  function renderInterview(){
    const question=interview.next_question;$("interview").hidden=!interview.available||!interview.accepting_answers||!question;
    $("interview-status").textContent=!interview.available?(interview.reason||"پرسش‌نامه‌ای تعیین نشده است."):!interview.accepting_answers?"پرسش‌نامه بسته است؛ برای ادامه از پزشک پیگیری کنید.":interview.complete?"پاسخ‌های اولیه ثبت شد و برای مرور پزشک در دسترس است.":interview.title+" · پرسش‌ها از گنجینهٔ تأییدشدهٔ پزشک انتخاب می‌شوند.";
    if(!question)return;$("interview-question").textContent=question.text_fa;$("interview-purpose").textContent=question.purpose_fa;$("interview-text").value="";$("interview-choice").replaceChildren();
    const choices=question.answer_type==="yes_no"?[{value:"yes",label:"بله"},{value:"no",label:"خیر"}]:question.choices.map(value=>({value,label:value}));
    $("interview-text-label").hidden=question.answer_type!=="text";$("interview-choice-label").hidden=question.answer_type==="text";
    for(const choice of [{value:"",label:"انتخاب کنید"},...choices]){const option=document.createElement("option");option.value=choice.value;option.textContent=choice.label;$("interview-choice").append(option);}
  }
  async function answer(state){if(!interview?.next_question)return;const epoch=generation,id=current,q=interview.next_question;const value=state==="answered"?(q.answer_type==="text"?$("interview-text").value.trim():$("interview-choice").value):null;if(state==="answered"&&!value){status("پاسخ را وارد کنید یا گزینهٔ نمی‌دانم را بزنید.");return;}
    const body={question_id:q.id,expected_version:interview.version,state,value};const signature=JSON.stringify(body);if(signature!==answerBody){answerBody=signature;answerKey=crypto.randomUUID();}for(const b of ["interview-answer","interview-unknown","interview-decline"])$(b).disabled=true;
    try{const result=await api(`/requests/${id}/interview-answers`,{method:"POST",body:JSON.stringify({...body,request_key:answerKey})});if(epoch!==generation||id!==current)return;interview=result;renderInterview();status("پاسخ ثبت شد.");}catch(error){if(epoch===generation)status(error.message);}finally{if(epoch===generation)for(const b of ["interview-answer","interview-unknown","interview-decline"])$(b).disabled=false;}}
  $("interview-answer").onclick=()=>answer("answered");$("interview-unknown").onclick=()=>answer("unknown");$("interview-decline").onclick=()=>answer("declined");
  $("refresh").onclick=()=>{const epoch=generation;load().then(()=>{if(epoch===generation)status("وضعیت به‌روز شد.");}).catch(error=>{if(epoch===generation)status(error.message);});};
  $("reply").onclick=async()=>{const text=$("reply-text").value.trim();if(text.length<3){status("پاسخ را بنویسید.");return;}$("reply").disabled=true;
    const epoch=generation,id=current;try{if(text!==messageText){messageKey=crypto.randomUUID();messageText=text;}await api(`/requests/${id}/messages`,{method:"POST",body:JSON.stringify({text,request_key:messageKey})});if(epoch!==generation||id!==current)return;$("reply-text").value="";messageText=null;await load();if(epoch===generation)status("پاسخ ثبت شد.");}catch(error){if(epoch===generation)status(error.message);}finally{if(epoch===generation)$("reply").disabled=$("request-state").textContent===statuses.withdrawn;}};
  $("upload").onclick=async()=>{const file=$("file").files[0];if(!file||file.size>5*1024*1024||!["image/png","image/jpeg"].includes(file.type)){status("یک تصویر JPG یا PNG تا ۵ مگابایت انتخاب کنید.");return;}$("upload").disabled=true;
    const epoch=generation,id=current;try{await api(`/requests/${id}/attachments`,{method:"POST",body:file});if(epoch!==generation||id!==current)return;$("file").value="";await load();if(epoch===generation)status("مدرک دریافت شد.");}catch(error){if(epoch===generation)status(error.message);}finally{if(epoch===generation)$("upload").disabled=$("request-state").textContent===statuses.withdrawn;}};
  $("withdraw").onclick=async()=>{if(!confirm("درخواست از صف بررسی خارج شود؟"))return;const epoch=generation,id=current;try{await api(`/requests/${id}/withdraw`,{method:"POST"});if(epoch!==generation||id!==current)return;await load();if(epoch===generation)status("درخواست پس گرفته شد.");}catch(error){if(epoch===generation)status(error.message);}};
  $("logout").onclick=async()=>{generation++;interview=null;answerBody=null;answerKey=null;$("interview").hidden=true;$("interview-question").textContent="";$("interview-purpose").textContent="";$("interview-text").value="";$("interview-choice").replaceChildren();const closing=api("/logout",{method:"POST"});csrf="";current=null;form.reset();form.hidden=true;$("receipt").hidden=true;$("previous").hidden=true;$("previous-list").replaceChildren();$("messages").replaceChildren();$("files").replaceChildren();$("review").textContent="";$("receipt-code").textContent="";$("request-state").textContent="";$("reply-text").value="";$("file").value="";pendingSubmission=null;messageKey=null;messageText=null;$("logout").hidden=true;try{await closing;status("نشست بسته شد. برای ورود جدید، صفحه را دوباره باز کنید.");}catch(error){status("اطلاعات صفحه پاک شد؛ پایان نشست روی سرور تأیید نشد. مرورگر را روی دستگاه مشترک ببندید.");}};
  async function start(){try{const info=await api("/info");notice=info.notice_version;$("notice-version").textContent=notice;$("clinic-name").textContent=info.clinic_name;const session=await api("/session",{method:"POST"});csrf=session.csrf_token;$("logout").hidden=false;form.hidden=false;
    if(session.requests.length){$("previous").hidden=false;for(const row of session.requests){const button=document.createElement("button");button.type="button";button.className="quiet";button.textContent=row.receipt+" · "+statuses[row.state];button.onclick=()=>{current=row.id;form.hidden=true;load().catch(error=>status(error.message));};$("previous-list").append(button);}}
    status("برای شروع، مراحل زیر را تکمیل کنید.");showStep();}catch(error){status(error.message);}}
  start();
})();
