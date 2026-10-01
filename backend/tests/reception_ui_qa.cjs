const fs=require('fs');
const assert=require('node:assert/strict');
const path=require('node:path');
const {JSDOM}=require(process.env.MOS_UI_QA_MODULES ? path.join(process.env.MOS_UI_QA_MODULES, 'jsdom') : 'jsdom');
const root=path.resolve(__dirname, '../app/web');
const dom=new JSDOM(fs.readFileSync(root+'/index.html','utf8'),{url:'https://localhost/app/',runScripts:'outside-only'});
const w=dom.window; w.Headers=Headers;
const requests=[];
const snapshot={visit_id:'synthetic-visit',patient_id:'synthetic-patient',intake_version:0,consent_version:0,latest_intake:null,consents:['care','audio_recording','educational_use','follow_up_contact','marketing'].map(p=>({purpose:p,state:'unknown',latest_event:null}))};
let resolveDelayed=null;
w.fetch=async (url, options)=>{
 requests.push({url,options});
 if(url.endsWith('/intakes')){snapshot.intake_version++;snapshot.latest_intake={content:JSON.parse(options.body)};}
 if(url.endsWith('/consents')){const data=JSON.parse(options.body);snapshot.consent_version++;const c=snapshot.consents.find(c=>c.purpose===data.purpose);c.state=data.state;c.latest_event={created_at:new Date().toISOString()};}
 if(url.includes('delayed-visit')) return new Promise(resolve=>{resolveDelayed=()=>resolve({ok:true,headers:new Headers({'Content-Type':'application/json'}),json:async()=>snapshot});});
 return {ok:true,headers:new Headers({'Content-Type':'application/json'}),json:async()=>structuredClone(snapshot)};
};
w.assert=assert;w.requests=requests;w.resolveRequest=()=>resolveDelayed();
w.eval(fs.readFileSync(root+'/app.js','utf8')+`\n
(async()=>{
 const check=window.assert;
 currentUser={id:'operator-1',role:'operator',display_name:'Synthetic operator'};accessToken='synthetic-token';showConsole();setWorkspace('reception');
 check.equal(document.querySelector('#reception-workspace').hidden,false);
 check.equal(document.querySelector('#reception-tab').getAttribute('aria-selected'),'true');
 check.equal(document.querySelector('#reception-tab').hidden,false);
 document.querySelector('#reception-visit-id').value='synthetic-visit';
 document.querySelector('#reception-load-form').dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));
 await new Promise(r=>setTimeout(r,10));
 check.equal(receptionSnapshot.visit_id,'synthetic-visit');
 check.equal(document.querySelector('#reception-consent-states').children.length,5);
 check.equal(document.querySelector('#reception-consent-purpose').value,'');
 check.equal(document.querySelector('#reception-consent-state').value,'');
 document.querySelector('#reception-complaint').value='<img src=x onerror=alert(1)> Synthetic statement';
 document.querySelector('#reception-intake-form').dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));
 await new Promise(r=>setTimeout(r,10));
 check.equal(receptionSnapshot.intake_version,1);
 check.equal(document.querySelector('#reception-content img'),null);
 const form=document.querySelector('#reception-consent-form');form.elements.purpose.value='marketing';form.elements.state.value='declined';form.elements.document_version.value='FA-1';form.elements.evidence_reference.value='SYNTHETIC-DOC';form.elements.confirmed_at.value='2026-01-01T12:00:00';form.elements.acknowledge.checked=true;
 form.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));await new Promise(r=>setTimeout(r,10));
 check.equal(receptionSnapshot.consents.find(c=>c.purpose==='marketing').state,'declined');
 check.equal(receptionSnapshot.consents.find(c=>c.purpose==='audio_recording').state,'unknown');
 const command=JSON.parse(window.requests.find(r=>r.url.endsWith('/consents')).options.body);
 check.equal(command.expected_version,0);check.ok(command.request_key);check.ok(command.confirmed_at.endsWith('Z'));
 const pending=receptionAction(active=>fetchReception('delayed-visit',active));await new Promise(r=>setTimeout(r,5));showLogin();window.resolveRequest();await pending;
 check.equal(receptionSnapshot,null);check.equal(document.querySelector('#reception-content').hidden,true);check.equal(document.querySelector('#reception-complaint').value,'');
 currentUser={id:'nurse-1',role:'nurse',display_name:'Synthetic nurse'};accessToken='synthetic-token';showConsole();setWorkspace('reception');renderReception(${JSON.stringify(snapshot)});
 check.equal(document.querySelector('#reception-save').disabled,true);check.equal(document.querySelector('#reception-consent-form').hidden,true);
 showLogin();
 window.qaResult='PASS: role UI, intake, independent consents, safe rendering, stale response after logout, data clearing.';
})().catch(e=>{window.qaError=e.stack});`);
(async()=>{for(let i=0;i<100;i++){if(w.qaResult||w.qaError)break;await new Promise(r=>setTimeout(r,20));} if(w.qaError)throw Error(w.qaError);assert.ok(w.qaResult,'QA timed out');console.log(w.qaResult);dom.window.close();})().catch(e=>{console.error(e);dom.window.close();process.exit(1)});
