// Drives the served landing page (tests/test_spend_modal_headless.py serves it) with playwright:
// click the usage readout → the spend modal opens over the dimmed dashboard, renders the per-session
// table + the stacked histogram with its unattributed stack, the toggles re-render, a segment hover
// shows the tooltip, Escape closes it. Prints one JSON line of observations; screenshots when asked.
const { chromium } = require('playwright');
(async () => {
  const url = process.argv[2], shots = process.argv[3] || '';
  const b = await chromium.launch();
  const pg = await b.newPage({ viewport: { width: 1280, height: 820 } });
  const errs = [];
  pg.on('pageerror', (e) => errs.push(String(e)));
  await pg.goto(url);
  await pg.waitForSelector('#rail-usage', { timeout: 20000 });
  await pg.evaluate(() => { const bt = document.getElementById('romp-boot'); if (bt) bt.remove(); });
  await pg.waitForFunction(() => document.getElementById('rail-usage').children.length > 0, null, { timeout: 20000 });
  const hiddenBefore = await pg.evaluate(() => document.getElementById('rsp-back').hidden);
  await pg.evaluate(() => document.getElementById('rail-usage').click());
  await pg.waitForFunction(() => !document.getElementById('rsp-back').hidden, null, { timeout: 5000 });
  const loaderSeen = await pg.evaluate(() => !!document.querySelector('#rsp-panel .rsp-load, #rsp-panel .rsp-tbl'));
  await pg.waitForSelector('#rsp-panel .rsp-tbl', { timeout: 15000 });
  await pg.waitForSelector('#rsp-chart .rsp-svg', { timeout: 15000 });
  const out = await pg.evaluate(() => ({
    head: document.querySelector('#rsp-panel .rsp-top span').textContent,
    legend: Array.from(document.querySelectorAll('#rsp-chart .rsp-chip')).map((e) => e.textContent),
    rows: Array.from(document.querySelectorAll('#rsp-panel .rsp-tbl tbody tr')).map((tr) => tr.textContent),
    deadRows: document.querySelectorAll('#rsp-panel .rsp-tbl tbody tr.rsp-dead').length,
    segs: document.querySelectorAll('#rsp-chart .rsp-seg').length,
    hatched: document.querySelectorAll('#rsp-chart .rsp-seg[fill="url(#rsp-hatch)"]').length,
    backdrop: getComputedStyle(document.getElementById('rsp-back')).backgroundColor,
    windows: Array.from(document.querySelectorAll('#rsp-panel .ru-tip-fleetspend .ru-tip-row .ru-tip-k')).map((e) => e.textContent),
    xlabels: Array.from(document.querySelectorAll('#rsp-chart .ru-tip-gx span')).map((e) => e.textContent).join(''),
    ylabels: Array.from(document.querySelectorAll('#rsp-chart .ru-tip-gy')).map((e) => e.textContent),
    railOpacity: getComputedStyle(document.getElementById('rail-usage')).opacity,
  }));
  if (shots) { await pg.screenshot({ path: shots + '-dark.png' }); const ch = await pg.$('#rsp-chart'); if (ch) await ch.screenshot({ path: shots + '-chart.png' }); }
  const foldBefore = await pg.evaluate(() => document.querySelectorAll('#rsp-panel .rsp-tbl tbody tr').length);
  const foldBtn = await pg.$('#rsp-panel [data-act="table:all"]');
  if (foldBtn) { await foldBtn.click(); await pg.waitForFunction((n) => document.querySelectorAll('#rsp-panel .rsp-tbl tbody tr').length > n, foldBefore, { timeout: 5000 }); }
  const foldAfter = await pg.evaluate(() => document.querySelectorAll('#rsp-panel .rsp-tbl tbody tr').length);
  await pg.click('#rsp-panel [data-act="measure:tok"]');
  await pg.click('#rsp-panel [data-act="range:days"]');
  await pg.waitForFunction(() => document.querySelector('#rsp-panel [data-act="range:days"]').classList.contains('on')
    && document.querySelector('#rsp-panel [data-act="measure:tok"]').classList.contains('on'), null, { timeout: 5000 });
  const days = await pg.evaluate(() => ({
    legend: Array.from(document.querySelectorAll('#rsp-chart .rsp-chip')).map((e) => e.textContent),
    segs: document.querySelectorAll('#rsp-chart .rsp-seg').length,
    ylabels: Array.from(document.querySelectorAll('#rsp-chart .ru-tip-gy')).map((e) => e.textContent),
    xlabels: Array.from(document.querySelectorAll('#rsp-chart .ru-tip-gx span')).map((e) => e.textContent),
  }));
  // hover the TALLEST segment (a sliver has no reliable hit box); measured in the page, scrolled into view
  const bb = await pg.evaluate(() => {
    let best = null;
    document.querySelectorAll('#rsp-chart .rsp-seg').forEach((el) => {
      const r = el.getBoundingClientRect();
      if (!best || r.height > best.height) best = { x: r.x, y: r.y, width: r.width, height: r.height, d: el.getAttribute('d') };
    });
    if (best) { const svg = document.querySelector('#rsp-chart svg'); svg.scrollIntoView({ block: 'center' }); const r2 = document.querySelector('#rsp-chart .rsp-seg'); }
    return best;
  });
  if (!bb || !(bb.height > 0)) throw new Error('no measurable segment: ' + JSON.stringify(bb));
  const bb2 = await pg.evaluate((d) => { const el = Array.from(document.querySelectorAll('#rsp-chart .rsp-seg')).find((e) => e.getAttribute('d') === d); const r = el.getBoundingClientRect(); return { x: r.x, y: r.y, width: r.width, height: r.height }; }, bb.d);
  await pg.mouse.move(bb2.x + bb2.width / 2, bb2.y + bb2.height / 2);
  await pg.waitForFunction(() => { const t = document.getElementById('rsp-tip'); return t && t.style.display === 'block'; }, null, { timeout: 5000 });
  const tip = await pg.evaluate(() => document.getElementById('rsp-tip').textContent);
  if (shots) await pg.screenshot({ path: shots + '-days-tokens.png' });
  await pg.mouse.move(5, 5);
  if (shots) {
    await pg.click('#rsp-panel [data-act="measure:usd"]');
    await pg.click('#rsp-panel [data-act="range:hours"]');
    await pg.evaluate(() => document.body.classList.add('theme-light'));
    await pg.waitForTimeout(150);
    await pg.screenshot({ path: shots + '-light.png' });
    await pg.evaluate(() => document.body.classList.remove('theme-light'));
  }
  await pg.keyboard.press('Escape');
  const hiddenAfter = await pg.evaluate(() => document.getElementById('rsp-back').hidden);
  // reopen by click, close by backdrop tap
  await pg.evaluate(() => document.getElementById('rail-usage').click());
  await pg.waitForFunction(() => !document.getElementById('rsp-back').hidden, null, { timeout: 5000 });
  await pg.mouse.click(8, 8);
  const hiddenAfterTap = await pg.evaluate(() => document.getElementById('rsp-back').hidden);
  console.log(JSON.stringify({ hiddenBefore, loaderSeen, out, days, tip, hiddenAfter, hiddenAfterTap, foldBefore, foldAfter, errs }));
  await b.close();
})().catch((e) => { console.error(e); process.exit(1); });
