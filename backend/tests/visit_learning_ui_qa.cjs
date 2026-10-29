/* Synthetic browser workflow checks; no real speech, patients or model training. */
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const {JSDOM} = require(process.env.MOS_UI_QA_MODULES
  ? path.join(process.env.MOS_UI_QA_MODULES, 'jsdom') : 'jsdom');
const root = path.resolve(__dirname, '../app/web');
const ids = {
  visitA: '11111111-1111-4111-8111-111111111111',
  visitB: '22222222-2222-4222-8222-222222222222',
  recording: '33333333-3333-4333-8333-333333333333',
  device: '44444444-4444-4444-8444-444444444444',
  session: '55555555-5555-4555-8555-555555555555',
  physician: '66666666-6666-4666-8666-666666666666',
};
const hashes = {audio:'a'.repeat(64), educational:'b'.repeat(64), packet:'c'.repeat(64), review:'d'.repeat(64)};
const exactText = '😀 پزشک: درد از چه زمانی شروع شد؟\nبیمار: دیروز.\nپزشک: درد را کجا احساس می‌کنید؟';
const question = 'درد از چه زمانی شروع شد؟';
const sha256 = text => crypto.createHash('sha256').update(text, 'utf8').digest('hex');
const clone = value => JSON.parse(JSON.stringify(value));
const tick = () => new Promise(resolve => setTimeout(resolve, 0));
const response = (data, status=200) => ({
  ok: status >= 200 && status < 300, status,
  headers: new Headers({'Content-Type':'application/json'}),
  json: async () => clone(data), text: async () => JSON.stringify(data),
});
const consent = () => ({
  latest_intake:{content:{assigned_physician_id:ids.physician}},
  consents:[
    {purpose:'audio_recording', state:'granted', latest_event:{sha256:hashes.audio}},
    {purpose:'educational_use', state:'granted', latest_event:{sha256:hashes.educational}},
  ],
});
const artifact = (changes={}) => ({
  schema_id:'4b-mos.reviewed-transcript-file', schema_version:'1.0.0',
  visit_id:ids.visitA, recording_id:ids.recording,
  capture_origin:{room_code:'room-1', device_id:ids.device, client_session_id:ids.session},
  source_type:'server_reviewed_transcript', source_review_sha256:hashes.review,
  reviewed_text:exactText, text_sha256:sha256(exactText), ...changes,
});

function harness({url='https://localhost/app/visit-learning.html', role='physician'}={}) {
  const dom = new JSDOM(fs.readFileSync(path.join(root, 'visit-learning.html'), 'utf8'),
    {url, runScripts:'outside-only'});
  const w = dom.window;
  w.Headers = Headers;
  w.TextEncoder = TextEncoder;
  w.TextDecoder = TextDecoder;
  w.structuredClone = structuredClone;
  Object.defineProperty(w.crypto, 'subtle', {value:crypto.webcrypto.subtle});
  Object.defineProperty(w.crypto, 'randomUUID', {value:crypto.randomUUID});
  Object.defineProperty(w, 'localStorage', {get(){throw Error('No localStorage permitted for this workflow.');}});
  Object.defineProperty(w, 'sessionStorage', {get(){throw Error('No sessionStorage permitted for this workflow.');}});
  const mock = {requests:[], packet:null, summary:null, failSubmissionOnce:false,
    queueStatus:200, delayVisit:null, resolveDelayed:null, identityError:false,
    recordings:[], receptionResponse:null, receptionError:false, delaySave:false, resolveSave:null,
    media:{recording_id:ids.recording,version:3,state:'reviewed',
      latest_draft:{sha256:'e'.repeat(64),content:{text:exactText}},
      latest_review:{sha256:hashes.review,edited_text:exactText,draft_sha256:'e'.repeat(64)}}};
  w.fetch = async (url, options={}) => {
    const endpoint = String(url);
    mock.requests.push({url:endpoint, options});
    const method = options.method || 'GET';
    if (endpoint === '/api/v1/auth/login') return response({access_token:'synthetic-memory-token'});
    if (endpoint === '/api/v1/auth/me') {
      if (mock.identityError) throw Error('Synthetic identity request failed');
      return response({id:ids.physician,role,display_name:'پزشک ساختگی',is_active:true});
    }
    if (endpoint.startsWith('/api/v1/recording-inbox')) return response({items:mock.recordings,limit:50});
    if (/\/visits\/[^/]+\/reception$/.test(endpoint)) {
      if (endpoint.includes(mock.delayVisit || '__never__')) {
        return new Promise(resolve => { mock.resolveDelayed = (status=200) => resolve(response(consent(), status)); });
      }
      if (mock.receptionError) throw Error('Synthetic access refresh failed');
      return response(mock.receptionResponse || consent());
    }
    if (endpoint.endsWith('/media/text')) return response(mock.media);
    if (endpoint.endsWith('/media/review') && method==='POST') {
      const body=JSON.parse(options.body);
      const saved={...mock.media,version:4,latest_review:{sha256:'9'.repeat(64),edited_text:body.edited_text,draft_sha256:body.expected_draft_sha256}};
      if (mock.delaySave) return new Promise(resolve=>{mock.resolveSave=()=>resolve(response(saved,201));});
      return response(saved,201);
    }
    if (endpoint.endsWith('/interview-style')) return response({has_approved_bank:true,
      bank:{title_fa:'بانک تأییدشدهٔ ساختگی',scope_fa:'سبک پرسشگری',summary_preferences_fa:'خلاصهٔ کوتاه',
        questions:[{text_fa:'<img src=x onerror=alert(1)> پرسش تأییدشده'}]}});
    if (endpoint.startsWith('/api/v1/visit-learning?') || endpoint === '/api/v1/visit-learning') {
      return response(mock.summary ? [mock.summary] : [], mock.queueStatus);
    }
    if (/\/visits\/[^/]+\/visit-learning$/.test(endpoint) && method === 'POST') {
      const body = JSON.parse(options.body);
      if (mock.failSubmissionOnce) {
        mock.failSubmissionOnce = false;
        return response({detail:'Synthetic temporary failure'}, 503);
      }
      mock.packet = body.packet;
      mock.summary = {
        packet_id:body.packet.packet_id, visit_id:ids.visitA, recording_id:ids.recording,
        physician_id:ids.physician,capture_origin:body.packet.capture_origin,
        source_type:body.packet.source_type,version:1,status:'submitted',packet_sha256:hashes.packet,
        event_sha256:'e'.repeat(64),question_count:body.packet.question_annotations.length,
        created_at:'2026-10-28T09:00:00+00:00',bank_event_id:null,
      };
      return response({summary:mock.summary,packet:mock.packet,model_training_performed:false}, 201);
    }
    if (endpoint.endsWith('/bank-preview')) return response({
      summary:mock.summary,
      bank:{title_fa:'پیشنهاد ساختگی',scope_fa:'مرور سؤال پزشک',summary_preferences_fa:null,
        questions:[{id:'learned.synthetic.1',text_fa:'<img src=x onerror=alert(1)> سؤال ساختگی',
          purpose_fa:'منشأ ساختگی',answer_type:'text',choices:[]}]},
      review_requirements_fa:['بازبینی مستقل پرسش و منبع'],activation_performed:false,
    });
    if (endpoint === `/api/v1/physicians/${ids.physician}/question-bank`) return response({version:3,has_approved_bank:false});
    if (endpoint.endsWith('/bank-draft') && method === 'POST') {
      mock.summary = {...mock.summary,version:2,status:'bank_draft',bank_event_id:'synthetic-bank-event'};
      return response({summary:mock.summary,bank_event:{id:'synthetic-bank-event',version:4,
        action:'draft',sha256:'f'.repeat(64)},activation_performed:false,model_training_performed:false},201);
    }
    if (/\/api\/v1\/visit-learning\/[^/]+$/.test(endpoint)) {
      return response({summary:mock.summary,packet:mock.packet,model_training_performed:false});
    }
    throw Error('Unexpected synthetic endpoint: ' + method + ' ' + endpoint);
  };
  w.eval(fs.readFileSync(path.join(root, 'visit-learning.js'), 'utf8'));
  const ui = w.MOS_VISIT_LEARNING;
  assert.ok(ui, 'The standalone workflow must initialize its testable controller.');
  const field = id => {
    const element = w.document.getElementById(id);
    assert.ok(element, 'Missing workflow control: ' + id);
    return element;
  };
  const file = data => ({name:'synthetic-transcript.json',size:Buffer.byteLength(JSON.stringify(data)),
    text:async()=>JSON.stringify(data)});
  const login = async () => {
    field('vl-username').value='synthetic-doctor';
    field('vl-password').value='Synthetic-Password-For-Test';
    return ui.login();
  };
  return {dom,w,ui,mock,field,file,login};
}

async function expectFailure(promise, reason) {
  let failed = false;
  try { await promise; } catch { failed = true; }
  assert.ok(failed, reason);
}

async function main() {
  const h = harness();
  const {w,ui,mock,field} = h;
  try {
    await h.login();
    assert.equal(ui.getState().authenticated, true);
    assert.equal(field('vl-password').value, '', 'Passwords must be cleared after login.');
    assert.ok(!JSON.stringify(ui.getState()).includes('synthetic-memory-token'), 'No bearer in public snapshots.');
    await ui.loadVisit(ids.visitA);
    assert.equal(ui.getState().visit, ids.visitA);
    assert.ok(field('vl-consent-status').textContent);
    const uploads = () => mock.requests.filter(item => (item.options.method || 'GET') === 'POST'
      && item.url.endsWith('/visit-learning'));
    await expectFailure(ui.importArtifact(h.file(artifact({visit_id:ids.visitB}))), 'Wrong-visit files must be rejected.');
    assert.equal(field('vl-transcript').value, '');
    await expectFailure(ui.importArtifact(h.file(artifact({text_sha256:'0'.repeat(64)}))), 'Changed source text requires a matching hash.');
    assert.equal(field('vl-transcript').value, '');
    await ui.importArtifact(h.file(artifact()));
    assert.equal(field('vl-transcript').value, exactText);
    assert.equal(ui.getState().sourceType, 'server_reviewed_transcript');
    assert.equal(uploads().length, 0, 'Opening a file must never upload it.');
    assert.equal(field('vl-deidentified').checked, false);
    assert.equal(field('vl-speakers-reviewed').checked, false);
    field('vl-stage').value='physician_visit';
    const start16 = exactText.indexOf(question);
    field('vl-transcript').setSelectionRange(start16, start16 + question.length);
    ui.addQuestionSelection();
    const annotation = clone(ui.getState().annotations)[0];
    assert.equal(annotation.text_fa, question);
    assert.equal(annotation.start, Array.from(exactText.slice(0,start16)).length);
    assert.equal(annotation.end - annotation.start, Array.from(question).length);
    assert.equal(annotation.speaker, 'clinician');
    assert.equal(annotation.stage, 'physician_visit');
    await expectFailure(ui.submitPacket(), 'Submission requires both explicit human attestations.');
    assert.equal(uploads().length,0);
    field('vl-deidentified').checked=true;
    field('vl-speakers-reviewed').checked=true;
    field('vl-transcript').value=exactText + '\n';
    field('vl-transcript').dispatchEvent(new w.Event('input',{bubbles:true}));
    assert.equal(ui.getState().annotations.length,0, 'Edited text invalidates source spans.');
    assert.equal(field('vl-deidentified').checked,false);
    assert.equal(field('vl-speakers-reviewed').checked,false);
    // Restore the exact reviewed artifact, then create the packet deliberately.
    await ui.importArtifact(h.file(artifact()));
    field('vl-transcript').setSelectionRange(start16,start16+question.length);
    ui.addQuestionSelection();
    field('vl-deidentified').checked=true;
    field('vl-speakers-reviewed').checked=true;
    mock.failSubmissionOnce=true;
    await expectFailure(ui.submitPacket(), 'A failed upload must not become a successful receipt.');
    assert.equal(ui.getState().currentPacket,null);
    await ui.submitPacket();
    assert.equal(uploads().length,2);
    const posted = JSON.parse(uploads()[0].options.body);
    assert.deepEqual(JSON.parse(uploads()[1].options.body), posted, 'Unchanged retry reuses one packet and request key.');
    assert.equal(posted.packet.source_text_sha256,sha256(exactText));
    assert.equal(posted.packet.source_type,'server_reviewed_transcript');
    assert.equal(posted.packet.source_review_sha256,hashes.review);
    assert.equal(posted.packet.question_annotations[0].text_fa,question);
    assert.ok(ui.getState().currentPacket);
    await ui.previewBank();
    assert.equal(w.document.querySelector('#vl-preview-content img'),null,'Source text must not become executable HTML.');
    assert.ok(field('vl-preview-content').textContent.includes('<img'));
    const bankWrites = () => mock.requests.filter(item => item.url.endsWith('/bank-draft') && item.options.method==='POST');
    await expectFailure(ui.promoteBankDraft(), 'Promotion requires a review statement.');
    assert.equal(bankWrites().length,0);
    field('vl-promotion-statement').value='این پیشنهاد ساختگی و ترتیب پرسش‌ها را برای پیش‌نویس بازبینی کرده‌ام.';
    await ui.promoteBankDraft();
    assert.equal(bankWrites().length,1);
    const command=JSON.parse(bankWrites()[0].options.body);
    assert.equal(command.expected_bank_version,3);
    assert.equal(command.expected_packet_sha256,hashes.packet);
    assert.equal(mock.summary.status,'bank_draft');
    assert.equal(field('vl-promote').disabled,true,'A finished proposal cannot be submitted as another bank draft.');
    await expectFailure(ui.promoteBankDraft(),'A completed proposal requires no repeat promotion.');
    assert.equal(bankWrites().length,1);
    assert.ok(!mock.requests.some(item => /\/approve$|medical-knowledge|safety-rules/.test(item.url)),
      'Workflow authoring must not approve a bank or change medical knowledge.');
    for (const request of mock.requests) {
      assert.ok(request.url.startsWith('/api/v1/'), 'Only same-origin MOS endpoints are contacted.');
      assert.equal(request.options.redirect,'error');
      assert.equal(request.options.cache,'no-store');
      assert.equal(request.options.credentials,'omit');
    }
    mock.queueStatus=401;
    await expectFailure(ui.loadQueue(),'Unauthorized data access must clear the session.');
    assert.equal(ui.getState().authenticated,false);
    assert.equal(field('vl-transcript').value,'');
    assert.equal(ui.getState().annotations.length,0);
    assert.equal(field('vl-workspace').hidden,true);
  } finally { h.dom.window.close(); }

  const race=harness();
  try {
    await race.login();
    race.mock.delayVisit=ids.visitB;
    const old=race.ui.loadVisit(ids.visitB);
    await tick();
    assert.equal(typeof race.mock.resolveDelayed,'function');
    await race.ui.loadVisit(ids.visitA);
    race.mock.resolveDelayed(403);
    await old.catch(()=>{});
    assert.equal(race.ui.getState().authenticated,true,'A late old request cannot log out the current visit.');
    assert.equal(race.ui.getState().visit,ids.visitA);
    race.mock.delayVisit=ids.visitB;
    const logoutPending=race.ui.loadVisit(ids.visitB);
    await tick();
    race.ui.logout();
    race.mock.resolveDelayed();
    await logoutPending.catch(()=>{});
    assert.equal(race.ui.getState().visit,null,'A late response cannot restore data after logout.');
    assert.equal(race.field('vl-transcript').value,'');
  } finally { race.dom.window.close(); }

  const central=harness();
  try {
    await central.login();await central.ui.loadVisit(ids.visitA);
    central.mock.recordings=[{visit_id:ids.visitA,recording_id:ids.recording,media_state:'reviewed',
      capture_origin:{room_code:'room-1',device_id:ids.device,client_session_id:ids.session}}];
    await central.ui.loadRecordings();
    central.field('vl-recording-list').querySelector('button').click();
    for(let i=0;i<6;i++) await tick();
    assert.equal(central.field('vl-origin-room').value,'room-1','Loading a central recording must retain its reported room.');
    assert.equal(central.field('vl-origin-device').value,ids.device);
    assert.equal(central.field('vl-transcript').value,exactText);
    await central.ui.loadApprovedStyle();
    assert.equal(central.w.document.querySelector('#vl-style-content img'),null);
    assert.ok(central.field('vl-style-content').textContent.includes('<img'));
    const edited=exactText+'\nاصلاح ثبت‌شدهٔ ساختگی';
    central.field('vl-server-text').value=edited;
    central.field('vl-server-text').dispatchEvent(new central.w.Event('input',{bubbles:true}));
    central.field('vl-server-statement').value='این متن ساختگی را بازبینی و اصلاح کرده‌ام.';
    central.field('vl-server-statement').dispatchEvent(new central.w.Event('input',{bubbles:true}));
    assert.equal(central.ui.getState().sourceType,null,'Unsaved clinical edits cannot be learning evidence.');
    central.mock.delaySave=true;
    const oldSave=central.ui.saveServerReview();await tick();
    assert.equal(typeof central.mock.resolveSave,'function');
    const newer=edited+'\nویرایش تازه و ذخیره‌نشده';
    central.field('vl-server-text').value=newer;
    central.field('vl-server-text').dispatchEvent(new central.w.Event('input',{bubbles:true}));
    central.mock.resolveSave();await oldSave.catch(()=>{});
    assert.equal(central.field('vl-server-text').value,newer,'Late save responses cannot discard new editor text.');
    assert.equal(central.ui.getState().sourceType,null);
    await central.ui.importArtifact(central.file(artifact()));
    const withdrawn=consent();withdrawn.consents[1].state='withdrawn';central.mock.receptionResponse=withdrawn;
    await central.ui.checkCurrentAccess();
    assert.equal(central.ui.getState().visit,null,'Changed educational consent invalidates the displayed source.');
    assert.equal(central.field('vl-transcript').value,'');
    assert.equal(central.field('vl-server-text').value,'');
  } finally {central.dom.window.close();}

  const malformed=harness();
  try {
    await malformed.login();await malformed.ui.loadVisit(ids.visitA);
    await expectFailure(malformed.ui.importArtifact(malformed.file(artifact({capture_origin:{...artifact().capture_origin,room_code:1}}))),
      'Reported source fields must retain their strict JSON types.');
    await expectFailure(malformed.ui.importArtifact({name:'invalid.txt',size:2,arrayBuffer:async()=>new Uint8Array([0xc3,0x28]).buffer}),
      'Malformed UTF-8 must not be silently replaced and treated as an intact source.');
    assert.equal(malformed.field('vl-transcript').value,'');
    await malformed.ui.importArtifact(malformed.file(artifact()));
    malformed.mock.receptionError=true;await malformed.ui.checkCurrentAccess();
    assert.equal(malformed.field('vl-transcript').value,'','Failed permission refresh must clear sensitive source text.');
  } finally {malformed.dom.window.close();}

  const identityFailure=harness();
  try {
    identityFailure.mock.identityError=true;
    await expectFailure(identityFailure.login(),'Identity failure must discard the provisional login session.');
    assert.equal(identityFailure.ui.getState().authenticated,false);
    assert.equal(identityFailure.field('vl-workspace').hidden,true);
    assert.equal(identityFailure.field('vl-password').value,'');
  } finally {identityFailure.dom.window.close();}

  const denied=harness({role:'operator'});
  try {
    await expectFailure(denied.login(),'Only a physician may open the learning workspace.');
    assert.equal(denied.ui.getState().authenticated,false);
    assert.equal(denied.field('vl-password').value,'');
  } finally { denied.dom.window.close(); }

  const insecure=harness({url:'http://clinic.example/app/visit-learning.html'});
  try {
    await expectFailure(insecure.login(),'Remote plaintext HTTP must not receive credentials.');
    assert.equal(insecure.mock.requests.length,0);
  } finally { insecure.dom.window.close(); }
  console.log('PASS: central visit-learning UI auth, consent/source boundaries, file hashes, Unicode spans, explicit review, stable retry, Draft-only promotion, safe text and stale-response isolation.');
}

main().catch(error=>{console.error(error);process.exitCode=1;});
