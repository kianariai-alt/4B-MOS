// Real OHIF/Chromium rendering of generated data; no external URLs or patient files.
const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
  try {
    const page = await browser.newPage();
    const frame = page.waitForResponse(r => r.url().startsWith('http://127.0.0.1:18080/dicom-web/') && r.url().includes('/frames/') && r.status() === 200, { timeout: 90000 });
    await page.goto('http://127.0.0.1:18080/viewer?StudyInstanceUIDs=1.2.826.0.1.3680043.10.543.2001', { waitUntil: 'domcontentloaded' });
    await frame;
    await page.locator('canvas').first().waitFor({ state: 'visible', timeout: 30000 });
    await page.screenshot({ path: '/tmp/4b-imaging-lab.png', fullPage: true });
    console.log('OHIF loaded a synthetic DICOMweb frame and displayed a canvas.');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error('Synthetic OHIF browser check failed:', error.message); process.exit(1); });
