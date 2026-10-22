const fs = require('fs');
const path = require('path');
const assert = require('node:assert/strict');
const {JSDOM} = require(process.env.MOS_UI_QA_MODULES ? path.join(process.env.MOS_UI_QA_MODULES, 'jsdom') : 'jsdom');
const root = path.resolve(__dirname, '../app');
const tick = () => new Promise(resolve => setTimeout(resolve, 10));
const response = (data, status=200) => ({ok:status<400, status, json:async()=>structuredClone(data)});
function dom(file) {
  const d = new JSDOM(fs.readFileSync(root+'/'+file,'utf8'), {url:'https://portal.example/patient/',runScripts:'outside-only'});
  d.window.Headers = Headers;
  d.window.HTMLElement.prototype.scrollIntoView = () => {};
  d.window.confirm = () => true;
  d.window.eval(fs.readFileSync(root+'/patient_web/solar-date.js','utf8'));
  return d;
}
const content = {first_name:'Synthetic',last_name:'Patient',complaint:'<img src=x onerror=alert(1)>',entry_mode:'clinic_arrival',conditions:[],medications:[],allergies:[],other_specialists:[],pain_score:null,laterality:'unknown',marketing_opt_in:false};
const record = {id:'request-1', receipt:'MOS-SYNTHETIC', state:'submitted', content, messages:[],attachments:[],missing_information:['Synthetic missing detail'],visit_id:null,
  interview:{available:true,accepting_answers:true,complete:false,version:0,title:'Synthetic approved bank',bank_sha256:'synthetic-hash',answers:[],next_question:{id:'one',text_fa:'<img src=x> Synthetic question?',purpose_fa:'Synthetic purpose',answer_type:'yes_no',choices:[]}}};
const firstQuestion = record.interview.next_question;
const numericQuestion = {id:'pain',text_fa:'Synthetic numeric question',purpose_fa:'Synthetic purpose',answer_type:'number',choices:[],numeric_unit:'score',numeric_min:0,numeric_max:10};

async function interviewRaceQA() {
  const d=dom('patient_web/index.html'),w=d.window,$=id=>w.document.getElementById(id);
  const snapshot=(version,label)=>({...record.interview,version,next_question:{...numericQuestion,text_fa:label}});
  const other={...record,id:'request-2',receipt:'MOS-SYNTHETIC-2'};
  const server={
    'request-1':{...record,interview:snapshot(1,'Synthetic A initial')},
    'request-2':{...other,interview:snapshot(1,'Synthetic B initial')}
  };
  const reads=[],posts=[];let deferReads=false;
  w.fetch=async(url,options={})=>{
    if(url.endsWith('/info'))return response({clinic_name:'Synthetic clinic',notice_version:'portal-processing-v1'});
    if(url.endsWith('/session'))return response({csrf_token:'synthetic-csrf',requests:[record,other]});
    if(url.endsWith('/logout'))return response({closed:true});
    if(url.endsWith('/interview-answers'))return new Promise(resolve=>posts.push({body:JSON.parse(options.body),resolve:data=>resolve(response(data))}));
    if(url.endsWith('/messages')||url.endsWith('/attachments'))return response({id:'synthetic-action'});
    const id=url.split('/').at(-1);
    if(server[id]){
      const data=structuredClone(server[id]);
      return deferReads?new Promise(resolve=>reads.push(()=>resolve(response(data)))):response(data);
    }
    throw new Error('Unexpected race request '+url);
  };
  w.eval(fs.readFileSync(root+'/patient_web/portal.js','utf8'));await tick();
  const open=index=>$('previous-list').querySelectorAll('button')[index].click();
  const send=()=>{$('interview-number').value='0';$('interview-answer').click();};
  const setA=(version,label)=>{server['request-1']={...record,interview:snapshot(version,label)};};
  open(0);await tick();

  // A read begun before an answer must never replace that answer's view.
  deferReads=true;setA(1,'Synthetic stale pre-answer read');$('refresh').click();await tick();
  send();await tick();assert.equal($('interview-answer').disabled,true);
  reads.shift()();await tick();assert.equal($('interview-question').textContent,'Synthetic A initial');
  assert.equal($('interview-answer').disabled,true);
  posts.shift().resolve(snapshot(2,'Synthetic after first answer'));await tick();
  assert.equal($('interview-question').textContent,'Synthetic after first answer');assert.equal($('interview-answer').disabled,false);

  // Reply/upload refreshes must retain the POST lock. Their newer snapshot
  // wins if an older POST response arrives afterward.
  send();await tick();deferReads=false;setA(4,'Synthetic newer reply snapshot');
  $('reply-text').value='Synthetic reply during answer';await $('reply').onclick();
  assert.equal($('interview-answer').disabled,true);assert.equal($('interview-question').textContent,'Synthetic after first answer');
  setA(5,'Synthetic newer upload snapshot');
  Object.defineProperty($('file'),'files',{configurable:true,value:[new w.File(['synthetic'],'test.png',{type:'image/png'})]});
  await $('upload').onclick();assert.equal($('interview-answer').disabled,true);
  posts.shift().resolve(snapshot(3,'Synthetic older POST'));await tick();
  assert.equal($('interview-question').textContent,'Synthetic newer upload snapshot');assert.equal($('interview-answer').disabled,false);

  // A read initiated during the POST may finish after it with an old version.
  send();await tick();assert.equal(posts[0].body.expected_version,5);
  deferReads=true;setA(5,'Synthetic delayed read during POST');$('reply-text').value='Synthetic delayed reply';
  const reply=$('reply').onclick();await tick();posts.shift().resolve(snapshot(6,'Synthetic newest POST'));await tick();
  reads.shift()();await reply;assert.equal($('interview-question').textContent,'Synthetic newest POST');
  assert.equal($('interview-answer').disabled,false);

  send();await tick();deferReads=false;
  server['request-1']={...record,state:'withdrawn',interview:{...snapshot(7,'Synthetic closed read'),accepting_answers:false}};
  $('reply-text').value='Synthetic closure check';await $('reply').onclick();
  assert.equal($('interview-answer').disabled,true);
  posts.shift().resolve(snapshot(7,'Synthetic earlier open POST'));await tick();
  assert.equal($('interview').hidden,true,'A later closed snapshot wins over an equal-version open POST');

  // A -> B -> A creates distinct views, even though the request id returns
  // to A. Neither an old read nor an old POST can mutate the new A view.
  deferReads=true;setA(6,'Synthetic old A read');open(0);await tick();
  deferReads=false;open(1);await tick();setA(7,'Synthetic reopened A');open(0);await tick();
  reads.shift()();await tick();assert.equal($('interview-question').textContent,'Synthetic reopened A');
  send();await tick();const oldPost=posts.shift();
  open(1);await tick();setA(8,'Synthetic current A view');open(0);await tick();send();await tick();
  oldPost.resolve(snapshot(9,'Synthetic old A POST'));await tick();
  assert.equal($('interview-question').textContent,'Synthetic current A view');
  assert.equal($('interview-answer').disabled,true,'An old view must not release the current POST lock');
  posts.shift().resolve(snapshot(10,'Synthetic current A POST'));await tick();
  assert.equal($('interview-question').textContent,'Synthetic current A POST');assert.equal($('interview-answer').disabled,false);
  send();await tick();await $('logout').onclick();posts.shift().resolve(snapshot(11,'Synthetic after logout'));await tick();
  assert.equal($('receipt').hidden,true);assert.equal($('interview-question').textContent,'');assert.equal($('interview-answers').textContent,'');
  d.window.close();
}

(async()=>{
  const d=dom('patient_web/index.html'), w=d.window, $=id=>w.document.getElementById(id);
  let sent=null, delayed=null, readsDelayed=false, calls=[];
  let interviewState=structuredClone(record.interview);
  w.fetch=async(url,options={})=>{
    calls.push({url,options});
    if(url.endsWith('/info'))return response({clinic_name:'Synthetic clinic',notice_version:'portal-processing-v1'});
    if(url.endsWith('/session'))return response({csrf_token:'synthetic-csrf',requests:[]});
    if(url.endsWith('/logout'))return response({closed:true});
    if(url.endsWith('/interview-answers')){
      const body=JSON.parse(options.body), question=body.question_id==='one'?firstQuestion:numericQuestion;
      const answer={...body,question:question.text_fa,question_definition:question};
      const answers=body.question_id==='one'?[answer]:[interviewState.answers[0],answer];
      interviewState={...record.interview,answers,next_question:body.question_id==='one'&&body.value==='yes'?numericQuestion:null,complete:body.question_id!=='one'||body.value!=='yes',version:interviewState.version+1};
      return response(interviewState);
    }
    if(url.endsWith('/requests')&&options.method==='POST'){sent=JSON.parse(options.body);return response(record,201);}
    if(url.endsWith('/requests/request-1'))return readsDelayed?new Promise(resolve=>{delayed=()=>resolve(response(record));}):response(record);
    throw new Error('Unexpected request '+url);
  };
  w.eval(fs.readFileSync(root+'/patient_web/portal.js','utf8'));await tick();
  assert.equal($('intake').hidden,false);
  assert.equal($('intake').elements.marketing_opt_in.checked,false);
  const f=$('intake');f.elements.date_of_birth.value='۱۳۷۰/۰۵/۲۱';f.elements.symptom_onset_date.value='۱۴۰۳/۱۲/۳۰';f.elements.first_name.value='Synthetic';f.elements.last_name.value='Patient';
  $('next').click();assert.match($('step-label').textContent,/۲/);
  f.elements.complaint.value=content.complaint;f.elements.body_region.value='knee';f.elements.body_region.dispatchEvent(new w.Event('change'));
  assert.match($('followup-hint').textContent,/زانو/);
  $('next').click();$('next').click();f.elements.processing_consent.checked=true;
  await f.onsubmit(new w.Event('submit',{cancelable:true}));
  assert.equal(sent.date_of_birth,'1991-08-12');assert.equal(sent.symptom_onset_date,'2025-03-20');
  assert.equal(sent.pain_score,null);assert.equal(sent.marketing_opt_in,false);assert.equal(sent.processing_consent,true);
  assert.equal($('receipt').hidden,false);assert.equal($('receipt-code').textContent,record.receipt);
  assert.equal(w.document.querySelector('#review img'),null);
  const post=calls.find(x=>x.options.body&&x.url.endsWith('/requests'));
  assert.equal(post.options.headers.get('X-Portal-CSRF'),'synthetic-csrf');
  assert.equal($('interview').hidden,false);assert.equal($('interview-question').querySelector('img'),null);
  $('interview-choice').value='yes';$('interview-answer').click();await tick();
  const answer=calls.find(x=>x.url.endsWith('/interview-answers'));
  assert.equal(JSON.parse(answer.options.body).value,'yes');assert.equal(JSON.parse(answer.options.body).expected_version,0);
  assert.equal($('interview-number-label').hidden,false);assert.equal($('interview-number').min,'0');assert.equal($('interview-number').max,'10');assert.equal($('interview-unit').textContent,'score');
  const answerCount=()=>calls.filter(x=>x.url.endsWith('/interview-answers')).length;
  $('interview-answer').click();await tick();assert.equal(answerCount(),1,'An empty numeric value must not become zero');
  $('interview-number').value='11';$('interview-answer').click();await tick();assert.equal(answerCount(),1,'Out-of-range number must not be submitted');
  $('interview-number').value='0';$('interview-supplementary').value='<img src=x> Synthetic explanation';$('interview-answer').click();await tick();
  let latest=JSON.parse(calls.filter(x=>x.url.endsWith('/interview-answers')).at(-1).options.body);
  assert.equal(latest.value,0);assert.equal(typeof latest.value,'number');assert.equal(latest.unit,'score');assert.equal(latest.expected_version,1);assert.equal(latest.supplementary_text,'<img src=x> Synthetic explanation');
  assert.equal($('interview').hidden,true);
  assert.equal($('interview-answers').querySelector('img'),null);assert.match($('interview-answers').textContent,/0 score/);
  $('interview-answers').querySelector('[data-question-id="pain"]').click();
  assert.equal($('interview').hidden,false);assert.equal($('interview-number').value,'0');assert.equal($('interview-editing').hidden,false);
  $('interview-unknown').click();await tick();latest=JSON.parse(calls.filter(x=>x.url.endsWith('/interview-answers')).at(-1).options.body);
  assert.equal(latest.state,'unknown');assert.equal(latest.value,null);assert.equal(latest.unit,null);assert.equal(latest.expected_version,2);assert.match($('interview-answers').textContent,/نمی‌دانم/);
  $('interview-answers').querySelector('[data-question-id="one"]').click();$('interview-choice').value='no';$('interview-answer').click();await tick();
  latest=JSON.parse(calls.filter(x=>x.url.endsWith('/interview-answers')).at(-1).options.body);
  assert.equal(latest.question_id,'one');assert.equal(latest.value,'no');assert.equal(latest.expected_version,3);
  assert.equal($('interview-answers').querySelector('[data-question-id="pain"]'),null,'Irrelevant child answers must leave the active view after correction');
  readsDelayed=true;$('refresh').click();await tick();await $('logout').onclick();delayed();await tick();
  assert.equal($('receipt').hidden,true);assert.equal($('receipt-code').textContent,'');assert.equal(f.elements.first_name.value,'');
  assert.equal($('interview-answers').textContent,'');assert.equal($('interview-number').value,'');assert.equal($('interview-supplementary').value,'');assert.equal($('interview-status').textContent,'');
  assert.equal(w.localStorage.length,0);assert.equal(w.sessionStorage.length,0);
  w.close();

  const pendingDom=dom('patient_web/index.html'), pw=pendingDom.window, p=id=>pw.document.getElementById(id);
  let resolveAnswer;
  pw.fetch=async(url)=>{
    if(url.endsWith('/info'))return response({clinic_name:'Synthetic clinic',notice_version:'portal-processing-v1'});
    if(url.endsWith('/session'))return response({csrf_token:'synthetic-csrf',requests:[record]});
    if(url.endsWith('/logout'))return response({closed:true});
    if(url.endsWith('/requests/request-1'))return response({...record,interview:{...record.interview,next_question:numericQuestion}});
    if(url.endsWith('/interview-answers'))return new Promise(resolve=>{resolveAnswer=()=>resolve(response(interviewState));});
    throw new Error('Unexpected pending request '+url);
  };
  pw.eval(fs.readFileSync(root+'/patient_web/portal.js','utf8'));await tick();p('previous-list').querySelector('button').click();await tick();
  p('interview-number').value='0';p('interview-supplementary').value='Synthetic pending detail';p('interview-answer').click();await tick();
  assert.equal(p('interview-answer').disabled,true);await p('logout').onclick();resolveAnswer();await tick();
  assert.equal(p('receipt').hidden,true);assert.equal(p('interview').hidden,true);assert.equal(p('interview-answers').textContent,'');assert.equal(p('interview-number').value,'');assert.equal(p('interview-supplementary').value,'');pw.close();

  await interviewRaceQA();

  const s=dom('web/portal-inbox.html'), sw=s.window, q=id=>sw.document.getElementById(id);
  let accepted=null, pending=null, delay=false;
  sw.fetch=async(url,options={})=>{
    if(url.endsWith('/auth/login'))return response({access_token:'synthetic-token'});
    if(url.endsWith('/auth/me'))return response({role:'physician'});
    if(url.includes('/portal-staff/requests?'))return response([record]);
    if(url.endsWith('/accept')){accepted=JSON.parse(options.body);return response({visit_id:'visit-synthetic'});}
    if(url.endsWith('/requests/request-1')){const staffRecord={...record,interview:{...record.interview,assistant_summary:{schema_version:'1.0.0',summary_fa:'Synthetic assistant summary <img src=x>'}}};return delay?new Promise(resolve=>{pending=()=>resolve(response(staffRecord));}):response(staffRecord);}
    throw new Error('Unexpected staff request '+url);
  };
  sw.eval(fs.readFileSync(root+'/web/portal-inbox.js','utf8'));
  q('username').value='synthetic';q('password').value='not-real';await q('login').onsubmit(new sw.Event('submit',{cancelable:true}));
  q('queue').querySelector('button').click();await tick();
  assert.equal(q('detail').hidden,false);assert.equal(q('summary').querySelector('img'),null);assert.match(q('summary').textContent,/<img/);
  assert.match(q('interview-summary').textContent,/Synthetic assistant summary/);assert.equal(q('interview-summary').querySelector('img'),null);
  await q('accept').onsubmit(new sw.Event('submit',{cancelable:true}));assert.equal(accepted,null);
  q('identity-checked').checked=true;await q('accept').onsubmit(new sw.Event('submit',{cancelable:true}));
  assert.deepEqual(accepted,{identity_checked:true,existing_patient_id:null});
  delay=true;q('queue').querySelector('button').click();await tick();q('logout').click();pending();await tick();
  assert.equal(q('detail').hidden,true);assert.equal(q('summary').textContent,'');assert.equal(q('password').value,'');
  assert.equal(sw.localStorage.length,0);assert.equal(sw.sessionStorage.length,0);
  sw.close();
  process.stdout.write('Patient portal and staff inbox UI QA passed\n');
})().catch(error=>{console.error(error);process.exitCode=1;});
