/* Physician-only, same-origin transcript review. No persistent browser storage. */
(() => {
  'use strict';
  const $ = id => document.getElementById('vl-' + id);
  const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
  const SHA = /^[0-9a-f]{64}$/;
  const ROOM = /^[A-Za-z0-9_.-]{1,80}$/;
  const stageNames = {reception:'پذیرش', initial_visit:'ویزیت اولیه', physician_visit:'ویزیت پزشک'};
  const mediaNames = {not_uploaded:'صوت منتقل نشده',uploading:'در حال انتقال',audio_received:'صوت دریافت شده',queued:'در صف تبدیل',running:'در حال تبدیل',failed:'تبدیل ناموفق',draft:'متن پیش‌نویس',reviewed:'متن بازبینی‌شده'};
  const state = {token:null,user:null,epoch:0,controllers:new Set(),visit:null,consents:null,
    source:null,annotations:[],currentPacket:null,pendingPacket:null,media:null,promotion:null,accessCheckEpoch:null};
  class StaleResponse extends Error {}
  const message = (text, kind='') => { $('status').textContent=text; $('status').dataset.kind=kind; };
  const identifier = (value, label) => { if (!UUID.test(value)) throw Error('شناسهٔ '+label+' معتبر نیست.'); return value; };
  const current = epoch => { if (state.epoch !== epoch) throw new StaleResponse(); };
  function invalidateRequests() {
    state.epoch += 1;
    for (const controller of state.controllers) controller.abort();
    state.controllers.clear();
  }
  function secureOrigin() {
    return location.protocol === 'https:' || (location.protocol === 'http:' && ['localhost','127.0.0.1','[::1]'].includes(location.hostname));
  }
  async function api(path, options={}) {
    if (!path.startsWith('/api/v1/')) throw Error('مقصد درخواست مجاز نیست.');
    if (!secureOrigin()) throw Error('ورود و انتقال فقط با HTTPS یا روی همین رایانهٔ آزمایشی مجاز است.');
    const {auth=true, ...rest}=options;
    if (auth && (!state.token || !state.user)) throw Error('ابتدا با حساب پزشک وارد شوید.');
    const epoch=state.epoch, token=state.token, controller=new AbortController();
    state.controllers.add(controller);
    let timedOut=false;
    const timeout=setTimeout(()=>{timedOut=true;controller.abort();},10000);
    const headers=new Headers(rest.headers || {});
    headers.set('Accept','application/json');
    if (token && auth) headers.set('Authorization','Bearer '+token);
    if (rest.body) headers.set('Content-Type','application/json');
    try {
      const response=await fetch(path,{...rest,headers,signal:controller.signal,credentials:'omit',cache:'no-store',redirect:'error'});
      current(epoch);
      if (auth && token!==state.token) throw new StaleResponse();
      if (response.status===401 || response.status===403) {
        logout();
        throw Error('دسترسی رد شد؛ متن و نشست این صفحه پاک شد. دوباره وارد شوید و رضایت‌ها را بررسی کنید.');
      }
      const data=await response.json();
      current(epoch);
      if (!response.ok) throw Error(typeof data.detail==='string' ? data.detail : 'درخواست پذیرفته نشد ('+response.status+').');
      return data;
    } catch (error) {
      if (timedOut && state.epoch===epoch) throw Error('مهلت پاسخ سامانه تمام شد؛ وضعیت ثبت را دوباره بررسی کنید.');
      throw error;
    } finally { clearTimeout(timeout);state.controllers.delete(controller); }
  }
  async function sha256(text) {
    if (!globalThis.crypto?.subtle || typeof TextEncoder==='undefined') throw Error('مرورگر برای بررسی فایل باید HTTPS و Web Crypto را پشتیبانی کند.');
    const buffer=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(text));
    return Array.from(new Uint8Array(buffer),x=>x.toString(16).padStart(2,'0')).join('');
  }
  function freshId() {
    if (typeof crypto.randomUUID==='function') return crypto.randomUUID();
    const b=crypto.getRandomValues(new Uint8Array(16)); b[6]=(b[6]&15)|64; b[8]=(b[8]&63)|128;
    const h=Array.from(b,x=>x.toString(16).padStart(2,'0')).join('');
    return h.slice(0,8)+'-'+h.slice(8,12)+'-'+h.slice(12,16)+'-'+h.slice(16,20)+'-'+h.slice(20);
  }
  function clearSource({preserveOrigin=false}={}) {
    state.source=null; state.annotations=[]; state.currentPacket=null; state.pendingPacket=null; state.media=null; state.promotion=null;
    for (const id of ['transcript','summary-preferences','origin-room','origin-device','origin-session','server-text','server-statement','promotion-statement']) {
      if (!preserveOrigin || !id.startsWith('origin-')) $(id).value='';
    }
    $('file').value=''; $('deidentified').checked=false; $('speakers-reviewed').checked=false;
    $('source-status').textContent='متنی بارگذاری نشده است.';
    $('server-panel').hidden=true; $('review-panel').hidden=true;
    $('preview-content').replaceChildren(); $('questions').replaceChildren(); $('style-content').replaceChildren();
    $('transcript').disabled=true;
    for (const id of ['origin-room','origin-device','origin-session','summary-preferences']) $(id).disabled=false;
    updateControls();
  }
  function resetVisit(id='') {
    invalidateRequests(); state.visit=null; state.consents=null; clearSource();
    $('visit-id').value=id; $('recording-id').value='';
    $('consent-status').textContent='هنوز ویزیتی انتخاب نشده است.';
    updateControls();
  }
  function logout() {
    resetVisit(); state.token=null; state.user=null;
    $('username').value=''; $('password').value=''; $('current-user').textContent='';
    $('room-filter').value=''; $('recording-list').replaceChildren(); $('queue-list').replaceChildren();
    $('workspace').hidden=true; $('login-panel').hidden=false;
    message('از حساب خارج شدید؛ متن و اطلاعات نشست از صفحه پاک شدند.');
  }
  function allowedVisit() { return Boolean(state.user && state.visit && state.consents); }
  function requireVisit() { if (!allowedVisit()) throw Error('ابتدا ویزیت و رضایت مستقل ضبط و استفادهٔ آموزشی را بررسی کنید.'); }
  function updateControls() {
    const allowed=allowedVisit(), locked=Boolean(state.currentPacket);
    $('load-server').disabled=!allowed;
    $('load-style').disabled=!allowed;
    $('file').disabled=!allowed || locked;
    $('reset-source').disabled=!state.visit;
    $('add-question').disabled=!allowed || !state.source || locked;
    $('submit').disabled=!allowed || !state.source || locked || !$('deidentified').checked || !$('speakers-reviewed').checked;
    $('save-server-review').disabled=!allowed || !state.media?.latest_draft;
    $('promote').disabled=state.currentPacket?.status!=='submitted' || !state.annotations.length || $('promotion-statement').value.trim().length<20;
  }
  async function login() {
    if (!secureOrigin()) throw Error('این صفحه باید با HTTPS یا روی localhost باز شود.');
    const username=$('username').value.trim(), password=$('password').value;
    if (!username || !password) throw Error('نام کاربری و رمز عبور را وارد کنید.');
    logout(); const epoch=state.epoch;
    let token;
    try { token=await api('/api/v1/auth/login',{auth:false,method:'POST',body:JSON.stringify({username,password})}); }
    finally { $('password').value=''; }
    current(epoch);
    if (typeof token.access_token!=='string' || !token.access_token) throw Error('پاسخ ورود معتبر نیست.');
    // Only the identity request uses this provisional token. No content can be
    // loaded until a current physician identity has been established.
    state.token=token.access_token;
    let user;
    try {
      user=await api('/api/v1/auth/me',{auth:false,headers:{Authorization:'Bearer '+state.token}});current(epoch);
    } catch (error) {
      if (state.epoch===epoch) logout();
      throw error;
    }
    if (user.role!=='physician' || user.is_active===false) { logout(); throw Error('این بخش فقط برای پزشک فعال است.'); }
    state.user=user;
    $('current-user').textContent='پزشک: '+(user.display_name || user.username || user.id);
    $('login-panel').hidden=true; $('workspace').hidden=false;
    message('وارد شدید. ابتدا ویزیت و رضایت‌های آن را تطبیق دهید.','success'); updateControls();
  }
  function consentContext(workspace) {
    const assigned=workspace.latest_intake?.content?.assigned_physician_id;
    if (assigned!==state.user?.id) throw Error('این ویزیت به پزشک واردشده تخصیص ندارد.');
    const get=purpose=>(workspace.consents || []).find(item=>item.purpose===purpose);
    const audio=get('audio_recording'), educational=get('educational_use');
    $('consent-status').textContent='رضایت ضبط: '+(audio?.state || 'نامشخص')+' — استفادهٔ آموزشی: '+(educational?.state || 'نامشخص');
    if (audio?.state!=='granted' || educational?.state!=='granted' || !SHA.test(audio.latest_event?.sha256 || '') || !SHA.test(educational.latest_event?.sha256 || '')) {
      throw Error('برای این مسیر، رضایت مستقل و جاریِ ضبط و استفادهٔ آموزشی لازم است.');
    }
    return {audio:audio.latest_event.sha256,educational:educational.latest_event.sha256};
  }
  async function loadVisit(id=$('visit-id').value.trim()) {
    resetVisit(id); identifier(id,'ویزیت');
    const epoch=state.epoch;
    try {
      const workspace=await api('/api/v1/visits/'+id+'/reception');
      const consents=consentContext(workspace);
      state.visit=id; state.consents=consents;
      message('ویزیت و دو رضایت جاری بررسی شدند. اکنون متن همان ضبط را انتخاب کنید.','success'); updateControls();
    } catch (error) {
      if (state.epoch===epoch) {state.visit=null; state.consents=null; updateControls();}
      throw error;
    }
  }
  function roomFilter() {
    const room=$('room-filter').value.trim();
    if (room && !ROOM.test(room)) throw Error('کد اتاق فقط از حروف لاتین، عدد، نقطه، خط تیره یا زیرخط باشد.');
    return room ? '?room_code='+encodeURIComponent(room)+'&limit=50' : '?limit=50';
  }
  function listButton(container, text, action) {
    const button=document.createElement('button'); button.type='button'; button.textContent=text;
    button.addEventListener('click',()=>run(action,button)); container.append(button);
  }
  async function loadQueue() {
    const rows=await api('/api/v1/visit-learning'+roomFilter());
    const list=$('queue-list'); list.replaceChildren();
    if (!Array.isArray(rows)) throw Error('پاسخ صندوق مرور معتبر نیست.');
    if (!rows.length) list.textContent='بستهٔ قابل‌دسترسی برای این فیلتر موجود نیست.';
    for (const row of rows) listButton(list,'اتاق '+row.capture_origin.room_code+' | '+row.status+' | '+row.question_count+' سؤال | '+row.visit_id,()=>loadPacket(row.packet_id));
  }
  async function loadRecordings() {
    const result=await api('/api/v1/recording-inbox'+roomFilter());
    const list=$('recording-list'); list.replaceChildren();
    if (!Array.isArray(result.items)) throw Error('پاسخ فهرست ضبط معتبر نیست.');
    if (!result.items.length) list.textContent='ضبط پایان‌یافتهٔ قابل‌دسترسی موجود نیست.';
    for (const row of result.items) listButton(list,'اتاق '+(row.capture_origin?.room_code || 'ثبت‌نشده در نسخهٔ قدیمی')+' | '+(mediaNames[row.media_state] || row.media_state)+' | '+row.visit_id,async()=>{
      await loadVisit(row.visit_id);
      $('recording-id').value=row.recording_id;
      if (row.capture_origin) setOrigin(row.capture_origin);
      await loadServerReview();
    });
    if (result.next_offset!==null && result.next_offset!==undefined) {
      const note=document.createElement('p');note.textContent='فهرست به ۵۰ مورد محدود است؛ برای یافتن مورد موردنظر از فیلتر اتاق یا شناسهٔ ویزیت استفاده کنید.';list.append(note);
    }
  }
  function validateOrigin(origin) {
    const fields=['room_code','device_id','client_session_id'];
    if (!origin || typeof origin!=='object' || Array.isArray(origin) || Object.keys(origin).length!==fields.length || fields.some(key=>typeof origin[key]!=='string') || !ROOM.test(origin.room_code) || !UUID.test(origin.device_id) || !UUID.test(origin.client_session_id)) throw Error('کد اتاق و شناسه‌های دستگاه و نشست ضبط باید کامل باشند.');
    return {room_code:origin.room_code,device_id:origin.device_id,client_session_id:origin.client_session_id};
  }
  function setOrigin(origin) {
    validateOrigin(origin); $('origin-room').value=origin.room_code; $('origin-device').value=origin.device_id; $('origin-session').value=origin.client_session_id;
  }
  function formOrigin() { return validateOrigin({room_code:$('origin-room').value.trim(),device_id:$('origin-device').value.trim(),client_session_id:$('origin-session').value.trim()}); }
  function applySource(text, source) {
    if (typeof text!=='string' || !text.trim() || text.length>100000) throw Error('متن باید کامل و حداکثر صد هزار نویسه باشد.');
    state.source=source; state.annotations=[]; state.pendingPacket=null; state.currentPacket=null; state.promotion=null;
    $('transcript').value=text; $('transcript').disabled=false;
    $('deidentified').checked=false; $('speakers-reviewed').checked=false; $('review-panel').hidden=true;
    $('source-status').textContent=source.type==='server_reviewed_transcript' ? 'منبع: متن دارای بازبینی ثبت‌شدهٔ پزشک؛ پیش از ارسال، حذف هویت و نقش سؤال‌ها را جدا بررسی کنید.' : 'منبع: فایل متن محلی؛ موتور تبدیل یا اصالت گفتار آن توسط سامانه تأیید نشده است.';
    renderQuestions(); updateControls();
  }
  async function importArtifact(file) {
    requireVisit(); if (state.currentPacket) throw Error('ابتدا فرم متن را پاک کنید.');
    if (!file || !Number.isSafeInteger(file.size) || file.size<0 || file.size>1048576 || !/\.(json|txt)$/i.test(file.name || '')) throw Error('فایل JSON یا متن UTF-8 با حجم حداکثر یک مگابایت لازم است.');
    const epoch=state.epoch;
    let text;
    if (typeof file.arrayBuffer==='function' && typeof TextDecoder!=='undefined') {
      const bytes=await file.arrayBuffer();current(epoch);
      if (bytes.byteLength>1048576) throw Error('حجم فایل نباید از یک مگابایت بیشتر باشد.');
      try {text=new TextDecoder('utf-8',{fatal:true}).decode(bytes);} catch {throw Error('فایل باید متن UTF-8 معتبر باشد.');}
    } else text=await file.text();
    current(epoch);
    if (/\.txt$/i.test(file.name || '')) {
      identifier($('recording-id').value.trim(),'ضبط');
      applySource(text,{type:'local_transcript',reviewSha:null});
      message('فایل فقط در این صفحه خوانده شد؛ هنوز ارسال نشده است.'); return;
    }
    let artifact;
    try { artifact=JSON.parse(text); } catch { throw Error('قالب JSON فایل معتبر نیست.'); }
    const keys=['schema_id','schema_version','visit_id','recording_id','capture_origin','source_type','source_review_sha256','reviewed_text','text_sha256'];
    if (!artifact || typeof artifact!=='object' || Array.isArray(artifact) || Object.keys(artifact).length!==keys.length || Object.keys(artifact).some(key=>!keys.includes(key)) || artifact.schema_id!=='4b-mos.reviewed-transcript-file' || artifact.schema_version!=='1.0.0' || artifact.source_type!=='server_reviewed_transcript') throw Error('این فایل، خروجی متن بازبینی‌شدهٔ پشتیبانی‌شده نیست.');
    identifier(artifact.visit_id,'ویزیت'); identifier(artifact.recording_id,'ضبط');
    if (artifact.visit_id!==state.visit || ($('recording-id').value && $('recording-id').value!==artifact.recording_id)) throw Error('فایل متعلق به ویزیت یا ضبط انتخاب‌شده نیست.');
    if (!SHA.test(artifact.source_review_sha256 || '') || !SHA.test(artifact.text_sha256 || '') || typeof artifact.reviewed_text!=='string') throw Error('منشأ بازبینی یا هش فایل ناقص است.');
    const actual=await sha256(artifact.reviewed_text); current(epoch);
    if (actual!==artifact.text_sha256) throw Error('متن فایل با هش ثبت‌شده تطبیق ندارد.');
    if (artifact.capture_origin!==null && artifact.capture_origin!==undefined) setOrigin(artifact.capture_origin);
    $('recording-id').value=artifact.recording_id;
    applySource(artifact.reviewed_text,{type:'server_reviewed_transcript',reviewSha:artifact.source_review_sha256});
    message('هش فایل تطبیق داشت؛ انتخاب فایل ارسال یا آموزش انجام نداد.');
  }
  async function loadServerReview() {
    requireVisit(); const recording=identifier($('recording-id').value.trim(),'ضبط');
    invalidateRequests(); clearSource({preserveOrigin:true}); const epoch=state.epoch;
    const workspace=await api('/api/v1/visits/'+state.visit+'/recordings/'+recording+'/media/text');current(epoch);
    state.media=workspace;
    $('server-panel').hidden=false;
    $('server-state').textContent='وضعیت متن: '+(mediaNames[workspace.state] || workspace.state);
    $('server-text').value=workspace.latest_review?.edited_text || workspace.latest_draft?.content?.text || '';
    if (workspace.latest_review) applySource(workspace.latest_review.edited_text,{type:'server_reviewed_transcript',reviewSha:workspace.latest_review.sha256});
    else message('متن بازبینی‌شده موجود نیست. اگر پیش‌نویس آماده است، ابتدا اصلاح پزشک را ثبت کنید.');
    updateControls();
  }
  async function saveServerReview() {
    requireVisit(); const media=state.media;
    if (!media?.latest_draft) throw Error('پیش‌نویس قابل بازبینی موجود نیست.');
    const statement=$('server-statement').value.trim(), edited=$('server-text').value;
    if (statement.length<20 || !edited.trim()) throw Error('متن اصلاح‌شده و توضیح بازبینی حداقل ۲۰ نویسه لازم‌اند.');
    const snapshot={visit:state.visit,recording:$('recording-id').value,epoch:state.epoch};
    const workspace=await api('/api/v1/visits/'+snapshot.visit+'/recordings/'+identifier(snapshot.recording,'ضبط')+'/media/review',{method:'POST',body:JSON.stringify({expected_version:media.version,request_key:'review-'+freshId(),expected_draft_sha256:media.latest_draft.sha256,edited_text:edited,statement_fa:statement})});
    current(snapshot.epoch);
    if (!workspace.latest_review || workspace.latest_review.edited_text!==edited || $('server-text').value!==edited || $('server-statement').value.trim()!==statement) throw Error('متن هنگام ثبت تغییر کرده است؛ پیش از ادامه نسخهٔ سرور را دوباره دریافت کنید.');
    state.media=workspace;
    applySource(workspace.latest_review.edited_text,{type:'server_reviewed_transcript',reviewSha:workspace.latest_review.sha256});
    $('server-state').textContent='متن بازبینی‌شده ثبت شد. حذف هویت و انتخاب سؤال‌ها مرحلهٔ جداگانه است.';
    message('متن اصلاح‌شدهٔ پزشک در سامانه ثبت شد.','success');
  }
  function invalidateDraft({clearAnnotations=false}={}) {
    invalidateRequests();state.pendingPacket=null; state.promotion=null;
    if (state.currentPacket) {state.currentPacket=null;$('review-panel').hidden=true;}
    if (clearAnnotations) {state.annotations=[];$('deidentified').checked=false;$('speakers-reviewed').checked=false;renderQuestions();}
    updateControls();
  }
  function addQuestionSelection() {
    requireVisit(); if (!state.source || state.currentPacket) throw Error('متن قابل ویرایش موجود نیست.');
    const editor=$('transcript'), text=editor.value;
    let start=editor.selectionStart,end=editor.selectionEnd;
    while (start<end && /\s/.test(text[start])) start++;
    while (end>start && /\s/.test(text[end-1])) end--;
    if (start===end) throw Error('عبارت دقیق سؤال پزشک را در متن انتخاب کنید.');
    const a=Array.from(text.slice(0,start)).length,b=Array.from(text.slice(0,end)).length;
    if (state.annotations.some(item=>a<item.end && b>item.start)) throw Error('این بخش با یک سؤال ثبت‌شده هم‌پوشانی دارد.');
    if (state.annotations.length>=100) throw Error('حداکثر صد سؤال در هر بسته قابل ثبت است.');
    const question=text.slice(start,end);
    if (question.length<3 || question.length>1000) throw Error('عبارت سؤال باید بین سه تا هزار نویسه باشد.');
    state.annotations.push({start:a,end:b,text_fa:question,stage:$('stage').value,speaker:'clinician'});
    state.annotations.sort((x,y)=>x.start-y.start);
    invalidateDraft();$('speakers-reviewed').checked=false;renderQuestions();
    message('بخش انتخاب‌شده با نقش تأییدشدهٔ شما ثبت شد؛ این نقش از گفتار حدس زده نشده است.');
  }
  function renderQuestions() {
    const list=$('questions');list.replaceChildren();
    state.annotations.forEach((item,index)=>{
      const row=document.createElement('li'), label=document.createElement('span');
      label.textContent=(stageNames[item.stage] || item.stage)+': '+item.text_fa;row.append(label);
      if (!state.currentPacket) {
        const remove=document.createElement('button');remove.type='button';remove.className='secondary';remove.textContent='حذف';
        remove.addEventListener('click',()=>{state.annotations.splice(index,1);invalidateDraft();$('speakers-reviewed').checked=false;renderQuestions();});row.append(remove);
      }
      list.append(row);
    });
  }
  async function submitPacket() {
    requireVisit(); if (!state.source || state.currentPacket) throw Error('متن تازه‌ای برای ارسال آماده نیست.');
    if (!$('deidentified').checked || !$('speakers-reviewed').checked) throw Error('دو بازبینی انسانی را پیش از ارسال تأیید کنید.');
    const epoch=state.epoch,text=$('transcript').value;
    if (!text.trim() || text.length>100000) throw Error('متن کامل و حداکثر صد هزار نویسه لازم است.');
    if (!state.pendingPacket) {
      const packet={schema_version:'1.0.0',packet_id:freshId(),capture_origin:formOrigin(),recording_id:identifier($('recording-id').value.trim(),'ضبط'),source_type:state.source.type,source_review_sha256:state.source.reviewSha,source_text_sha256:await sha256(text),deidentified_reviewed_text:text,question_annotations:structuredClone(state.annotations),deidentification_reviewed:true,speaker_attribution_reviewed:true,expected_audio_consent_sha256:state.consents.audio,expected_educational_consent_sha256:state.consents.educational,summary_preferences_fa:$('summary-preferences').value.trim() || null};
      current(epoch);state.pendingPacket={packet,expected_version:0,request_key:'packet-'+freshId()};
    }
    const result=await api('/api/v1/visits/'+state.visit+'/visit-learning',{method:'POST',body:JSON.stringify(state.pendingPacket)});
    current(epoch); applyPacket(result); message('بسته در سامانهٔ مرکزی ثبت شد؛ بانک فعال یا قواعد پزشکی تغییر نکردند.','success');
  }
  function applyPacket(result) {
    if (!result.summary || !result.packet) throw Error('بستهٔ دریافت‌شده کامل نیست.');
    state.currentPacket=result.summary;state.pendingPacket=null;state.promotion=null;
    state.source={type:result.packet.source_type,reviewSha:result.packet.source_review_sha256};
    state.annotations=structuredClone(result.packet.question_annotations);
    $('recording-id').value=result.packet.recording_id;setOrigin(result.packet.capture_origin);
    $('transcript').value=result.packet.deidentified_reviewed_text;$('transcript').disabled=true;
    $('summary-preferences').value=result.packet.summary_preferences_fa || '';
    for (const id of ['origin-room','origin-device','origin-session','summary-preferences']) $(id).disabled=true;
    $('deidentified').checked=false;$('speakers-reviewed').checked=false;
    $('review-panel').hidden=false;$('packet-status').textContent='وضعیت بسته: '+result.summary.status+' — '+result.summary.question_count+' سؤال برای بررسی';
    $('source-status').textContent='بستهٔ ثبت‌شدهٔ مرور؛ متن این نسخه برای حفظ تاریخچه قابل تغییر نیست.';
    $('preview-content').replaceChildren();renderQuestions();updateControls();
  }
  async function loadPacket(id) {
    identifier(id,'بسته');resetVisit();
    const result=await api('/api/v1/visit-learning/'+id);
    identifier(result.summary?.visit_id,'ویزیت');
    const workspace=await api('/api/v1/visits/'+result.summary.visit_id+'/reception');
    const consents=consentContext(workspace);
    if (result.packet.expected_audio_consent_sha256!==consents.audio || result.packet.expected_educational_consent_sha256!==consents.educational) throw Error('رضایت منبع تغییر کرده است؛ بسته برای استفادهٔ آموزشی جاری نیست.');
    state.visit=result.summary.visit_id;state.consents=consents;$('visit-id').value=state.visit;
    applyPacket(result);message('نسخهٔ ثبت‌شده با دسترسی و رضایت جاری دریافت شد.','success');
  }
  async function previewBank() {
    if (!state.currentPacket) throw Error('ابتدا یک بسته را ثبت یا انتخاب کنید.');
    const preview=await api('/api/v1/visit-learning/'+state.currentPacket.packet_id+'/bank-preview');
    const container=$('preview-content');container.replaceChildren();
    if (!preview.bank) {container.textContent='سؤال انتخاب‌شده‌ای برای ساخت پیش‌نویس وجود ندارد.';return;}
    const title=document.createElement('h3');title.textContent=preview.bank.title_fa;container.append(title);
    const scope=document.createElement('p');scope.textContent=preview.bank.scope_fa;container.append(scope);
    const list=document.createElement('ol');for (const question of preview.bank.questions) {const item=document.createElement('li');item.textContent=question.text_fa;list.append(item);}container.append(list);
    if (preview.bank.summary_preferences_fa) {const preference=document.createElement('p');preference.textContent='ترجیح خلاصه: '+preview.bank.summary_preferences_fa;container.append(preference);}
    message('این‌ها پیشنهاد پرسش‌اند؛ تا تأیید جداگانه، فعال نمی‌شوند.');
  }
  async function promoteBankDraft() {
    const packet=state.currentPacket, statement=$('promotion-statement').value.trim();
    if (!packet || packet.status!=='submitted' || !state.annotations.length || statement.length<20) throw Error('بستهٔ بررسی‌نشدهٔ دارای سؤال و توضیح بررسی حداقل ۲۰ نویسه لازم است.');
    const epoch=state.epoch;
    if (!state.promotion) {
      const bank=await api('/api/v1/physicians/'+state.user.id+'/question-bank');current(epoch);
      state.promotion={expected_version:packet.version,expected_packet_sha256:packet.packet_sha256,expected_bank_version:bank.version,request_key:'bank-'+freshId(),statement_fa:statement};
    } else if (state.promotion.statement_fa!==statement) {state.promotion=null;return promoteBankDraft();}
    const result=await api('/api/v1/visit-learning/'+packet.packet_id+'/bank-draft',{method:'POST',body:JSON.stringify(state.promotion)});current(epoch);
    state.currentPacket=result.summary;state.promotion=null;
    $('packet-status').textContent='پیش‌نویس بانک پرسش ساخته شد. نسخهٔ بانک: '+result.bank_event.version+'؛ هنوز فعال نشده است.';
    message('پیش‌نویس ساخته شد. برای فعال‌سازی، در سامانهٔ اصلی نسخه و هش آن را جداگانه بررسی و تأیید کنید.','success');updateControls();
  }
  async function loadApprovedStyle() {
    requireVisit();
    const style=await api('/api/v1/visits/'+state.visit+'/interview-style');
    const container=$('style-content');container.replaceChildren();
    if (!style.has_approved_bank || !style.bank) {container.textContent='هنوز الگوی پرسش تأییدشده‌ای برای این پزشک موجود نیست.';return;}
    const heading=document.createElement('h3');heading.textContent=style.bank.title_fa;container.append(heading);
    const scope=document.createElement('p');scope.textContent=style.bank.scope_fa;container.append(scope);
    const list=document.createElement('ol');for (const question of style.bank.questions) {const item=document.createElement('li');item.textContent=question.text_fa;list.append(item);}container.append(list);
    if (style.bank.summary_preferences_fa) {const preference=document.createElement('p');preference.textContent='ترجیح خلاصه: '+style.bank.summary_preferences_fa;container.append(preference);}
  }
  function invalidateClinicalEdit() {
    invalidateRequests();state.source=null;state.annotations=[];state.currentPacket=null;state.pendingPacket=null;state.promotion=null;
    $('transcript').value='';$('transcript').disabled=true;$('deidentified').checked=false;$('speakers-reviewed').checked=false;
    $('review-panel').hidden=true;$('preview-content').replaceChildren();renderQuestions();
    $('source-status').textContent='متن بازبینی پزشک تغییر کرده و هنوز ثبت نشده است؛ ابتدا نسخهٔ بازبینی‌شده را ثبت یا از سرور بازخوانی کنید.';
    updateControls();
  }
  async function checkCurrentAccess() {
    if (!allowedVisit() || !(state.source || state.media || state.currentPacket) || state.accessCheckEpoch===state.epoch) return;
    const epoch=state.epoch, visit=state.visit, expected={...state.consents};state.accessCheckEpoch=epoch;
    try {
      const workspace=await api('/api/v1/visits/'+visit+'/reception');current(epoch);
      const consents=consentContext(workspace);
      if (consents.audio!==expected.audio || consents.educational!==expected.educational) throw Error('رضایت منبع تغییر کرده است.');
    } catch (error) {
      if (state.epoch===epoch) {resetVisit(visit);message('دسترسی یا رضایت جاری تأیید نشد؛ متن از صفحه پاک شد. ویزیت را دوباره بررسی کنید.','error');}
      if (!(error instanceof StaleResponse) && error.name!=='AbortError') return;
    } finally {if (state.accessCheckEpoch===epoch) state.accessCheckEpoch=null;}
  }
  async function downloadPacket() {
    if (!state.currentPacket) throw Error('ابتدا یک بسته را انتخاب کنید.');
    const result=await api('/api/v1/visit-learning/'+state.currentPacket.packet_id);
    const blob=new Blob([JSON.stringify(result.packet,null,2)],{type:'application/json;charset=utf-8'});
    const href=URL.createObjectURL(blob), link=document.createElement('a');link.href=href;link.download='4B-visit-learning-'+result.summary.packet_id+'.json';link.click();URL.revokeObjectURL(href);
    message('فایل به درخواست شما ساخته شد. پیش از هر انتقال بیرون از MOS، محتوا و مجوز مقصد را جدا بررسی کنید.');
  }
  async function run(action, button) {
    if (button) button.disabled=true;
    try {await action();} catch (error) {
      if (!(error instanceof StaleResponse) && error.name!=='AbortError') message(error.message || 'عملیات انجام نشد.','error');
    } finally {if (button && button.isConnected) button.disabled=false;updateControls();}
  }
  $('login-form').addEventListener('submit',event=>{event.preventDefault();run(login,$('login'));});
  $('logout').addEventListener('click',logout);
  $('visit-form').addEventListener('submit',event=>{event.preventDefault();run(()=>loadVisit(),$('load-visit'));});
  $('visit-id').addEventListener('input',()=>resetVisit($('visit-id').value));
  $('recording-id').addEventListener('input',()=>{invalidateRequests();clearSource();});
  $('queue-refresh').addEventListener('click',()=>run(loadQueue,$('queue-refresh')));
  $('recordings-refresh').addEventListener('click',()=>run(loadRecordings,$('recordings-refresh')));
  $('file').addEventListener('change',()=>run(()=>importArtifact($('file').files[0])));
  $('load-server').addEventListener('click',()=>run(loadServerReview,$('load-server')));
  $('save-server-review').addEventListener('click',()=>run(saveServerReview,$('save-server-review')));
  for (const id of ['server-text','server-statement']) $(id).addEventListener('input',invalidateClinicalEdit);
  $('load-style').addEventListener('click',()=>run(loadApprovedStyle,$('load-style')));
  $('reset-source').addEventListener('click',()=>{invalidateRequests();clearSource();message('فرم متن پاک شد؛ برای نسخهٔ تازه دوباره منبع را انتخاب کنید.');});
  $('transcript').addEventListener('input',()=>invalidateDraft({clearAnnotations:true}));
  for (const id of ['summary-preferences','origin-room','origin-device','origin-session']) $(id).addEventListener('input',()=>invalidateDraft());
  for (const id of ['deidentified','speakers-reviewed']) $(id).addEventListener('change',()=>{state.pendingPacket=null;updateControls();});
  $('promotion-statement').addEventListener('input',()=>{state.promotion=null;updateControls();});
  $('add-question').addEventListener('click',()=>run(addQuestionSelection,$('add-question')));
  $('submit').addEventListener('click',()=>run(submitPacket,$('submit')));
  $('preview').addEventListener('click',()=>run(previewBank,$('preview')));
  $('promote').addEventListener('click',()=>run(promoteBankDraft,$('promote')));
  $('download').addEventListener('click',()=>run(downloadPacket,$('download')));
  addEventListener('pagehide',logout);
  setInterval(checkCurrentAccess,30000);
  addEventListener('focus',checkCurrentAccess);
  window.MOS_VISIT_LEARNING=Object.freeze({login,logout,loadVisit,loadPacket,loadQueue,loadRecordings,
    importArtifact,addQuestionSelection,submitPacket,loadServerReview,saveServerReview,previewBank,promoteBankDraft,loadApprovedStyle,checkCurrentAccess,sha256,
    getState:()=>structuredClone({authenticated:Boolean(state.token && state.user),user:state.user,visit:state.visit,
      annotations:state.annotations,sourceType:state.source?.type || null,currentPacket:state.currentPacket,
      pendingPacket:state.pendingPacket,epoch:state.epoch})});
  updateControls();
})();
