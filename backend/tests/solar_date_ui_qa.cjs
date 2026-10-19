const fs = require('fs');
const path = require('path');
const assert = require('node:assert/strict');
const {JSDOM} = require(process.env.MOS_UI_QA_MODULES ? path.join(process.env.MOS_UI_QA_MODULES, 'jsdom') : 'jsdom');
const dom = new JSDOM('<form><input data-solar-date name="date"><input data-solar-datetime name="time"></form>', {runScripts:'outside-only'});
const w = dom.window;
w.eval(fs.readFileSync(path.join(__dirname,'../app/patient_web/solar-date.js'),'utf8'));
const solar = w.MosSolarDate;
assert.equal(solar.fromSolar('۱۴۰۵/۰۷/۲۷'),'2026-10-19');
assert.equal(solar.fromSolar('١٤٠٥/٠٧/٢٧'),'2026-10-19');
assert.equal(solar.fromSolar('14050727'),'2026-10-19');
assert.equal(solar.fromSolar('۱۳۷۰/۰۵/۲۱'),'1991-08-12');
assert.equal(solar.toSolar('2026-10-19'),'1405/07/27');
assert.equal(solar.fromSolar('۱۴۰۳/۱۲/۳۰'),'2025-03-20');
assert.equal(solar.fromSolar('۱۳۹۹/۱۲/۳۰'),'2021-03-20');
assert.equal(solar.fromSolar('1404/01/01'),'2025-03-21');
for(const invalid of ['1404/12/30','1403/07/31','1405/13/01','1405/00/01','1405/01/00','wrong','<script>'])
  assert.throws(()=>solar.fromSolar(invalid));
assert.throws(()=>solar.toSolar('2026-02-30'));
assert.equal(solar.fromSolar(''),null);
assert.equal(solar.formatDate('2026-10-19'),'۱۴۰۵/۰۷/۲۷');
assert.equal(solar.fromSolarTime('۱۴۰۵/۰۷/۲۷ ۱۵:۳۰'),'2026-10-19T12:00:00.000Z');
assert.equal(solar.fromSolarTime('1405/07/27 00:15:08'),'2026-10-18T20:45:08.000Z');
assert.throws(()=>solar.fromSolarTime('1405/07/27 24:00'));
assert.throws(()=>solar.fromSolarTime('1405/07/27 12:60'));
assert.match(solar.formatDateTime('2026-10-19T12:00:00Z'),/۱۵:۳۰/);
assert.match(solar.formatDateTime('2026-10-19T12:00:00Z'),/۱۴۰۵/);
const input=w.document.querySelector('[name=date]');
input.value='1404/12/30';assert.equal(solar.validate(input),false);assert.equal(input.validity.valid,false);
input.value='1403/12/30';assert.equal(solar.readDate(input),'2025-03-20');assert.equal(input.validity.valid,true);
input.value='';assert.equal(solar.readDate(input),null);
input.setAttribute('data-solar-past','');input.value='1499/01/01';assert.equal(solar.validate(input),false);
// Round trips use calendar dates, independent of the machine's timezone.
for(let stamp=Date.UTC(1930,0,1);stamp<Date.UTC(2031,0,1);stamp+=17*86400000){
  const iso=new Date(stamp).toISOString().slice(0,10);
  assert.equal(solar.fromSolar(solar.toSolar(iso)),iso);
}
dom.window.close();
console.log('PASS: Persian/Arabic/Latin input, leap years, invalid dates, ISO round trips and Tehran timestamps.');
