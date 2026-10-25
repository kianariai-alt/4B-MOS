/* Exercise the shipped single-file offline demo through browser DOM events. */
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const {pathToFileURL} = require('node:url');
const {JSDOM, VirtualConsole} = require(process.env.MOS_UI_QA_MODULES
  ? path.join(process.env.MOS_UI_QA_MODULES, 'jsdom') : 'jsdom');

const filename = process.argv[2] || process.env.MOS_WINDOWS_DEMO_HTML;
assert.ok(filename, 'Pass the generated single HTML artifact as the first argument.');
const html = fs.readFileSync(filename, 'utf8');
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));

async function openDemo(source) {
  const errors = [];
  const counts = {network: 0, storage: 0};
  const virtualConsole = new VirtualConsole();
  virtualConsole.on('jsdomError', error => errors.push(error.stack || String(error)));
  const dom = new JSDOM(source, {
    url: pathToFileURL(path.resolve(filename)).href,
    runScripts: 'dangerously',
    pretendToBeVisual: true,
    virtualConsole,
    beforeParse(window) {
      const rejectNetwork = () => { counts.network++; throw Error('Offline demo attempted a network request.'); };
      window.fetch = rejectNetwork;
      window.XMLHttpRequest = rejectNetwork;
      window.WebSocket = rejectNetwork;
      window.EventSource = rejectNetwork;
      window.navigator.sendBeacon = rejectNetwork;
      for (const name of ['localStorage', 'sessionStorage']) {
        Object.defineProperty(window, name, {
          configurable: true,
          get() { counts.storage++; throw Error('Demo attempted persistent browser storage.'); },
        });
      }
      window.confirm = () => true;
      window.scrollTo = () => {};
      window.HTMLElement.prototype.scrollIntoView = () => {};
    },
  });
  const w = dom.window;
  for (let index = 0; index < 100 && w.document.documentElement.dataset.demoReady !== 'true'; index++) {
    await delay(10);
  }
  assert.equal(w.document.documentElement.dataset.demoReady, 'true', errors.join('\n') || 'Demo did not finish startup.');
  assert.deepEqual(errors, [], 'Unexpected browser error during startup.');
  return {dom, w, doc: w.document, counts, errors};
}

function fire(w, element, value, event = 'change') {
  assert.ok(element, 'Expected form control is present.');
  element.value = value;
  element.dispatchEvent(new w.Event(event, {bubbles: true}));
  if (event === 'input' && element.tagName === 'TEXTAREA') {
    element.dispatchEvent(new w.Event('change', {bubbles: true}));
  }
}

function candidateTargets(root) {
  return Array.from(root.querySelectorAll('.case-question')).map(card => ({
    field: card.dataset.field,
    number: Number(card.dataset.number),
    episode_ref: card.dataset.episodeRef || null,
  })).sort((a, b) => JSON.stringify(a).localeCompare(JSON.stringify(b)));
}

async function main() {
  const session = await openDemo(html);
  const {dom, w, doc, counts, errors} = session;
  try {
    const data = JSON.parse(doc.getElementById('mos-demo-data').textContent);
    assert.equal(data.tree.nodes.length, 30);
    assert.deepEqual(data.tree.nodes.map(node => node.number).sort((a, b) => a - b),
      Array.from({length: 30}, (_, index) => index + 1));
    assert.equal(data.cases.length, 10);
    assert.equal(doc.documentElement.dataset.renderedCaseCount, '10');
    assert.equal(data.tree.bank_export_is_executable_tree, false);

    // Every displayed case is an actual immutable Python result, including
    // per-treatment targets, source metadata and the traceable result hash.
    doc.getElementById('mode-cases').click();
    const selector = doc.getElementById('case-select');
    assert.equal(selector.options.length, 10);
    for (const [index, sample] of data.cases.entries()) {
      fire(w, selector, String(index));
      const root = doc.getElementById('case-content');
      const expected = sample.preview.question_candidates.map(candidate => ({
        field: candidate.field, number: candidate.number, episode_ref: candidate.episode_ref || null,
      })).sort((a, b) => JSON.stringify(a).localeCompare(JSON.stringify(b)));
      assert.deepEqual(candidateTargets(root), expected, 'Displayed candidates must match the Python case: ' + sample.id);
      for (const candidate of sample.preview.question_candidates) {
        assert.ok(root.textContent.includes(candidate.question.text_fa));
      }
      assert.ok(doc.getElementById('case-metadata').textContent.includes(sample.preview.result_sha256));
      assert.equal(sample.preview.governance_status, 'draft');
      assert.equal(sample.preview.approved_fact_count, 0);
      assert.equal(sample.preview.safety_evaluation, 'not_performed');
    }

    // An actual source lookup must expose reference metadata, without a
    // browser request or fabricated medical fact.
    const sourceCaseIndex = data.cases.findIndex(sample => sample.preview.question_candidates.some(candidate => candidate.source_fact_keys.length));
    assert.ok(sourceCaseIndex >= 0);
    fire(w, selector, String(sourceCaseIndex));
    const sourceButton = doc.querySelector('#case-content .source-button[data-source-fact]:not([data-source-fact=""])');
    assert.ok(sourceButton);
    const factKey = sourceButton.dataset.sourceFact;
    assert.ok(data.tree.nodes.some(node => node.source_fact_keys.includes(factKey)));
    sourceButton.click();
    assert.equal(doc.getElementById('source-panel').hidden, false);
    assert.ok(doc.querySelector('#source-panel .source-entry'));

    doc.getElementById('mode-form').click();
    const disclaimer = doc.getElementById('form-disclaimer').textContent;
    assert.ok(disclaimer.includes('فرم'));
    assert.ok(/موتور|Python/.test(disclaimer));
    const control = field => doc.getElementById('form-field-' + field);
    const visible = field => {
      const input = control(field);
      const card = input && input.closest('[data-number]');
      return Boolean(card && !card.hidden && !input.hidden);
    };
    const painFields = ['pain_location', 'pain_score_now', 'pain_pattern', 'aggravating_factor', 'relieving_factor'];
    const traumaFields = ['sensory_change', 'weakness', 'foot_coldness', 'foot_color_change', 'trauma_mechanism'];
    assert.ok(painFields.every(field => !visible(field)));
    assert.ok(traumaFields.every(field => !visible(field)));

    // Unknown/declined are distinct from No; a principal complaint never
    // silently supplies the supplemental pain-presence prerequisite.
    fire(w, control('chief_complaint'), 'pain');
    assert.ok(painFields.every(field => !visible(field)));
    fire(w, doc.getElementById('has-pain'), 'unknown');
    assert.ok(painFields.every(field => !visible(field)));
    fire(w, doc.getElementById('has-pain'), 'declined');
    assert.ok(painFields.every(field => !visible(field)));
    fire(w, doc.getElementById('has-pain'), 'yes');
    assert.ok(painFields.every(visible));
    fire(w, control('pain_score_now'), '0');
    assert.equal(control('pain_score_now').value, '0');
    assert.equal(w.MOS_DEMO.getState().observations.pain_score_now.value, 0);
    fire(w, doc.getElementById('has-pain'), 'no');
    assert.ok(painFields.every(field => !visible(field)));
    fire(w, doc.getElementById('has-pain'), 'yes');
    assert.equal(control('pain_score_now').value, '0', 'Closing a branch must preserve its raw report.');

    fire(w, control('trauma'), 'unknown');
    assert.ok(traumaFields.every(field => !visible(field)));
    fire(w, control('trauma'), 'yes');
    assert.ok(traumaFields.every(visible));
    fire(w, control('weakness'), 'no');
    assert.equal(w.MOS_DEMO.getState().observations.weakness.value, false);
    fire(w, control('trauma'), 'no');
    assert.ok(traumaFields.every(field => !visible(field)));
    assert.ok(doc.getElementById('closed-answers').textContent.trim());
    fire(w, control('trauma'), 'yes');
    assert.equal(control('weakness').value, 'no');

    fire(w, control('mechanical_locking'), 'no');
    assert.equal(visible('pain_limited_motion'), false);
    fire(w, control('mechanical_locking'), 'yes');
    assert.equal(visible('pain_limited_motion'), true);
    fire(w, control('prior_surgery'), 'yes');
    assert.equal(visible('surgery_description'), true);
    fire(w, control('laterality'), 'both');
    assert.equal(doc.getElementById('bilateral-notice').hidden, false);

    // Treatment results must remain tied to their own explicit episode.
    fire(w, control('prior_treatment'), 'yes');
    let descriptions = Array.from(doc.querySelectorAll('[id^="form-episode-"][id$="-treatment_description"]'));
    if (!descriptions.length) {
      doc.getElementById('add-treatment').click();
      descriptions = Array.from(doc.querySelectorAll('[id^="form-episode-"][id$="-treatment_description"]'));
    }
    assert.ok(descriptions.length >= 1);
    fire(w, descriptions[0], 'درمان ساختگی الف', 'input');
    doc.getElementById('add-treatment').click();
    descriptions = Array.from(doc.querySelectorAll('[id^="form-episode-"][id$="-treatment_description"]'));
    assert.equal(descriptions.length, 2);
    fire(w, descriptions[1], 'درمان ساختگی ب', 'input');
    const firstPrefix = descriptions[0].id.slice(0, -'treatment_description'.length);
    const secondPrefix = descriptions[1].id.slice(0, -'treatment_description'.length);
    fire(w, doc.getElementById(firstPrefix + 'treatment_pain_response'), 'improved');
    fire(w, doc.getElementById(secondPrefix + 'treatment_pain_response'), 'worse');
    assert.equal(doc.getElementById(firstPrefix + 'treatment_pain_response').value, 'improved');
    assert.equal(doc.getElementById(secondPrefix + 'treatment_pain_response').value, 'worse');
    fire(w, control('prior_treatment'), 'unknown');
    fire(w, control('prior_treatment'), 'yes');
    assert.equal(doc.getElementById(firstPrefix + 'treatment_pain_response').value, 'improved');
    assert.equal(doc.getElementById(secondPrefix + 'treatment_pain_response').value, 'worse');

    // Literal user text must remain text; it must not execute markup or become
    // an automatically interpreted state/diagnosis.
    const hostile = '<img id="user-injection" src=x onerror="window.injected=true"> unknown';
    fire(w, control('medication_list'), hostile, 'input');
    doc.getElementById('form-summary').click();
    const summary = doc.getElementById('form-summary-output');
    assert.ok(summary.textContent.includes(hostile));
    assert.equal(summary.querySelector('#user-injection'), null);
    assert.equal(w.injected, undefined);
    const medicationState = doc.getElementById('form-state-medication_list');
    assert.equal(medicationState.value, 'confirmed');
    fire(w, medicationState, 'unknown');
    assert.equal(control('medication_list').value, hostile);
    assert.equal(w.MOS_DEMO.getState().observations.medication_list.value, null);
    fire(w, doc.getElementById('form-state-medication_list'), 'confirmed');
    assert.equal(control('medication_list').value, hostile);
    fire(w, control('medication_list'), 'ی'.repeat(1200), 'input');
    assert.equal(control('medication_list').value.length, 1000);
    assert.equal(w.MOS_DEMO.getState().observations.medication_list.value.length, 1000);

    doc.getElementById('form-reset').click();
    assert.equal(control('chief_complaint').value, '');
    assert.equal(doc.getElementById('has-pain').value, '');
    assert.equal(control('medication_list').value, '');
    assert.ok(painFields.every(field => !visible(field)));
    assert.equal(doc.getElementById('bilateral-notice').hidden, true);
    assert.equal(doc.querySelectorAll('[id^="form-episode-"][id$="-treatment_description"]').length, 0);
    assert.equal(counts.network, 0);
    assert.equal(counts.storage, 0);
    assert.deepEqual(errors, []);
    console.log('PASS: ten Python cases, source/hash display, 30-question branches, uncertainty, false/zero, retained reports, separate treatments, bilateral review, safe text, offline reset.');
  } finally {
    dom.window.close();
  }
}

main().catch(error => { console.error(error.stack || error); process.exitCode = 1; });
