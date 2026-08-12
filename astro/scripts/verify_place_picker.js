/*
 * Birth-place picker: end-to-end reachability check.
 *
 * The dropdown is absolutely positioned under the input, and the birth-place
 * field sits low in the form. On a standard 1280x800 laptop the list used to
 * open at y=792 in an 800px viewport -- rendered, populated and clickable, but
 * 8px of it visible and the rest below the fold. Nobody could pick a city.
 *
 * That bug survived a browser test suite because Playwright's locator.click()
 * scrolls its target into view first. A human does not. So this script drives
 * the picker with raw pointer events at real coordinates and fails if the row
 * is not already on screen when the user goes to click it.
 *
 *   node scripts/verify_place_picker.js http://127.0.0.1:5001
 */
const { chromium } = require('playwright-core');
const BASE = process.env.BASE || process.argv[2] || 'http://127.0.0.1:5001';

// Deliberately never uses locator.click(): Playwright scrolls the target into
// view first, which is exactly the behaviour that hid this bug. Real pointer
// events at real coordinates only.
async function e2e(b, { label, viewport, city, expect, row = 0 }) {
  const ctx = await b.newContext({ viewport });
  const p = await ctx.newPage();
  const errs = []; p.on('pageerror', e => errs.push(e.message));
  await p.goto(BASE, { waitUntil: 'networkidle' });

  const cta = await p.locator('.nav-cta').boundingBox();
  await p.mouse.click(cta.x + cta.width / 2, cta.y + cta.height / 2);
  await p.waitForTimeout(700);

  // A user scrolls to the field before typing in it. That is ordinary and not
  // what is under test -- the dropdown's reachability *after* focus is.
  await p.evaluate(() => document.getElementById('place').scrollIntoView({ block: 'center' }));
  await p.waitForTimeout(250);
  const field = await p.locator('#place').boundingBox();
  await p.mouse.click(field.x + field.width / 2, field.y + field.height / 2);
  await p.keyboard.type(city, { delay: 60 });
  await p.waitForTimeout(800);

  const rows = await p.locator('#suggestions .suggestion').count();
  if (!rows) return report(label, viewport, 'FAIL', 'no suggestions rendered', errs, ctx);

  const box = await p.locator('#suggestions .suggestion').nth(Math.min(row, rows - 1)).boundingBox();
  if (box.y < 0 || box.y + box.height > viewport.height) {
    return report(label, viewport, 'FAIL', `row unreachable (y=${Math.round(box.y)}, viewport=${viewport.height})`, errs, ctx);
  }

  await p.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
  await p.waitForTimeout(400);
  const picked = await p.inputValue('#place');
  const hint = (await p.textContent('#place-hint')).trim();
  if (!hint) return report(label, viewport, 'FAIL', 'click did not select', errs, ctx);

  // Carry it all the way through to a calculated chart.
  await p.fill('#name', 'E2E');
  await p.fill('#date', '1992-06-14');
  await p.fill('#time', '08:30');
  await p.evaluate(() => document.getElementById('submit').scrollIntoView({ block: 'center' }));
  await p.waitForTimeout(250);
  const submit = await p.locator('#submit').boundingBox();
  await p.mouse.click(submit.x + submit.width / 2, submit.y + submit.height / 2);
  try {
    await p.waitForSelector('#view-dashboard:not(.hidden)', { timeout: 60000 });
  } catch (e) {
    const banner = await p.textContent('#error').catch(() => '');
    return report(label, viewport, 'FAIL', `submit did not proceed: ${banner || e.message}`, errs, ctx);
  }
  await p.waitForTimeout(600);

  const birthLine = (await p.textContent('#dash-birth-line')).trim();
  const archetype = (await p.textContent('#dash-archetype')).trim();
  const ok = birthLine.includes(expect) && archetype.length > 3;
  return report(label, viewport, ok ? 'PASS' : 'FAIL',
    `${picked} | ${hint.split('·')[0].trim()} | ${birthLine.split('·').pop().trim()} | ${archetype}`, errs, ctx);
}

async function report(label, vp, status, detail, errs, ctx) {
  console.log(`${status === 'PASS' ? '✓' : '✗'} ${label.padEnd(30)} ${status}  ${detail}`);
  if (errs.length) console.log('    page errors:', errs);
  await ctx.close();
  return status === 'PASS';
}

(async () => {
  const b = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const V = (w, h) => ({ width: w, height: h });
  const results = [];
  results.push(await e2e(b, { label: 'laptop 1280x800',   viewport: V(1280, 800), city: 'Dublin',   expect: 'Dublin' }));
  results.push(await e2e(b, { label: 'laptop 1280x760',   viewport: V(1280, 760), city: 'Lisbon',   expect: 'Lisbon' }));
  results.push(await e2e(b, { label: 'macbook 1440x900',  viewport: V(1440, 900), city: 'Nairobi',  expect: 'Nairobi' }));
  results.push(await e2e(b, { label: 'small 1280x620',    viewport: V(1280, 620), city: 'Osaka',    expect: 'Osaka' }));
  results.push(await e2e(b, { label: 'mobile 390x844',    viewport: V(390, 844),  city: 'Bogota',   expect: 'Bogot' }));
  results.push(await e2e(b, { label: 'mobile 390x664',    viewport: V(390, 664),  city: 'Oslo',     expect: 'Oslo' }));
  results.push(await e2e(b, { label: 'tablet 820x1180',   viewport: V(820, 1180), city: 'Auckland', expect: 'Auckland' }));
  results.push(await e2e(b, { label: '2nd row, 1280x800', viewport: V(1280, 800), city: 'London',   expect: 'Canada', row: 1 }));
  const passed = results.filter(Boolean).length;
  console.log(`\n  ${passed}/${results.length} passed end to end`);
  await b.close();
  process.exit(passed === results.length ? 0 : 1);
})();
