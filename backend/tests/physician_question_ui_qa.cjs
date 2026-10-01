const fs=require('fs');const assert=require('node:assert/strict');const path=require('node:path');
const {JSDOM}=require(process.env.MOS_UI_QA_MODULES ? path.join(process.env.MOS_UI_QA_MODULES,'jsdom'):'jsdom');
const root=path.resolve(__dirname,'../app/web');
const dom=new JSDOM(fs.readFileSync(root+'/index.html','utf8'),{url:'https://localhost/app/',runScripts:'outside-only'});
const w=dom.window;w.Headers=Headers;w.assert=assert;
let snapshot={physician_id:'doctor',version:0,latest:null,active_bank:null,has_approved_bank:false};const requests=[];
w.fetch=async(url,options={})=>{
 requests.push({url,options});
 if(options.method==='POST'){
  const command=JSON.parse(options.body);const action=url.endsWith('/drafts')?'draft':url.endsWith('/approve')?'approve':'retire';
  assert.equal(command.expected_version,snapshot.version);
  if(action!=='draft')assert.equal(command.expected_bank_sha256,(action==='approve'?snapshot.latest:snapshot.active_bank).sha256);
  const event={id:`event-${snapshot.version+1}`,action,content:action==='draft'?command:snapshot.latest.content,sha256:String(snapshot.version+1).repeat(64)};
  snapshot.version++;snapshot.latest=event;
  if(action==='approve'){snapshot.active_bank=event;snapshot.has_approved_bank=true;}
  if(action==='retire'){snapshot.active_bank=null;snapshot.has_approved_bank=false;}
 }
 return {ok:true,headers:new Headers({'Content-Type':'application/json'}),json:async()=>structuredClone(snapshot)};
};w.requests=requests;
w.eval(fs.readFileSync(root+'/app.js','utf8')+`\n(async()=>{
 const check=window.assert;
 currentUser={id:'doctor',role:'physician',display_name:'Synthetic doctor'};accessToken='synthetic';showConsole();
 check.equal(bankNode('physician-bank-section').hidden,false);
 bankNode('bank-load').click();await new Promise(r=>setTimeout(r,10));
 const form=bankNode('bank-form');form.elements.title_fa.value='گنجینه آزمایشی';form.elements.scope_fa.value='مصاحبه اولیه';
 const card=bankNode('bank-questions').firstElementChild;card.querySelector('[name=text_fa]').value='<img src=x> شکایت چیست؟';card.querySelector('[name=purpose_fa]').value='شرح حال بیمار';
 form.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));await new Promise(r=>setTimeout(r,20));
 check.equal(physicianBank.version,1);check.equal(bankNode('bank-questions').querySelector('img'),null);
 const rev=bankNode('bank-review-form');rev.elements.statement_fa.value='پرسش و ترتیب این نسخه را بررسی کرده‌ام.';rev.elements.acknowledge.checked=true;
 bankNode('bank-form').dispatchEvent(new Event('input',{bubbles:true}));
 await bankReview('approve');check.equal(physicianBank.version,1);
 bankDirty=false;await bankReview('approve');check.equal(physicianBank.has_approved_bank,true);
 rev.elements.statement_fa.value='نسخه فعال را پس از بررسی بازنشسته می‌کنم.';rev.elements.acknowledge.checked=true;
 await bankReview('retire');check.equal(physicianBank.has_approved_bank,false);
 showLogin();check.equal(physicianBank,null);check.equal(bankNode('bank-questions').children.length,0);
 currentUser={id:'operator',role:'operator',display_name:'Synthetic operator'};accessToken='synthetic';showConsole();check.equal(bankNode('physician-bank-section').hidden,true);
 showLogin();window.qaResult='PASS: physician editor, draft, hash-bound approval, unsaved edit guard, retirement, role visibility, logout clearing.';
})().catch(e=>{window.qaError=e.stack});`);
(async()=>{for(let i=0;i<100;i++){if(w.qaResult||w.qaError)break;await new Promise(r=>setTimeout(r,20));}if(w.qaError)throw Error(w.qaError);assert.ok(w.qaResult,'QA timed out');console.log(w.qaResult);dom.window.close();})().catch(e=>{console.error(e);dom.window.close();process.exit(1)});
