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
  // T247d: the desktop hover ends in the affordance line, and a screenshot of the tip
  await pg.hover('#rail-usage');
  await pg.waitForFunction(() => { const t = document.getElementById('ru-tip'); return t && t.style.display === 'block'; }, null, { timeout: 5000 });
  const hoverHint = await pg.evaluate(() => { const t = document.getElementById('ru-tip'); const last = t.lastElementChild; return { text: last ? last.textContent : '', cls: last ? last.className : '', font: last ? getComputedStyle(last).fontSize : '', opacity: last ? getComputedStyle(last).opacity : '' }; });
  if (shots) { const tipEl = await pg.$('#ru-tip'); if (tipEl) await tipEl.screenshot({ path: shots + '-hover.png' }); }
  await pg.mouse.move(5, 400);
  const hiddenBefore = await pg.evaluate(() => document.getElementById('rsp-back').hidden);
  await pg.evaluate(() => document.getElementById('rail-usage').click());
  await pg.waitForFunction(() => !document.getElementById('rsp-back').hidden, null, { timeout: 5000 });
  const loaderSeen = await pg.evaluate(() => !!document.querySelector('#rsp-panel .rsp-load, #rsp-panel .rsp-tbl'));
  await pg.waitForSelector('#rsp-panel .rsp-tbl', { timeout: 15000 });
  await pg.waitForSelector('#rsp-chart .rsp-svg', { timeout: 15000 });
  const out = await pg.evaluate(() => ({
    head: document.querySelector('#rsp-panel .rsp-top span').textContent,
    legendNodes: document.querySelectorAll('#rsp-chart .rsp-leg, #rsp-chart .rsp-chip').length,
    chartFirst: (() => { const secs = Array.from(document.querySelectorAll('#rsp-panel .rsp-sec')); const ci = secs.findIndex((s) => s.querySelector('#rsp-chart')); const ti = secs.findIndex((s) => s.querySelector('#rsp-table')); return ci >= 0 && ti > ci; })(),
    swatches: document.querySelectorAll('#rsp-panel .rsp-tbl tbody tr .rsp-sw:not(.rsp-hatch)').length,
    title: (() => { const t = document.querySelector('#rsp-panel .rsp-tbl tbody tr .tab-label'); const cs = t ? getComputedStyle(t) : null; const hp = t ? t.querySelector('.host-prefix') : null; return { color: cs ? cs.color : null, weight: cs ? cs.fontWeight : null, prefix: hp ? hp.textContent : null }; })(),
    pane: (() => { const p = document.getElementById('rsp-table'); const th = document.querySelector('#rsp-panel .rsp-tbl thead th'); const panel = document.getElementById('rsp-panel'); return { scrolls: !!p && p.scrollHeight > p.clientHeight + 4, sticky: th ? getComputedStyle(th).position : null, h: p ? p.clientHeight : null, thOpacity: th ? getComputedStyle(th).opacity : null, panelScrolls: panel.scrollHeight > panel.clientHeight + 2 }; })(),
    rows: Array.from(document.querySelectorAll('#rsp-panel .rsp-tbl tbody tr')).map((tr) => tr.textContent),
    deadRows: document.querySelectorAll('#rsp-panel .rsp-tbl tbody tr.rsp-dead').length,
    segs: document.querySelectorAll('#rsp-chart .rsp-seg').length,
    hatched: document.querySelectorAll('#rsp-chart .rsp-seg[fill="url(#rsp-hatch)"]').length,
    backdrop: getComputedStyle(document.getElementById('rsp-back')).backgroundColor,
    windows: Array.from(document.querySelectorAll('#rsp-panel .ru-tip-fleetspend .ru-tip-row .ru-tip-k')).map((e) => e.textContent),
    notes: Array.from(document.querySelectorAll('#rsp-panel .rsp-note')).map((e) => e.textContent),
    xlabels: Array.from(document.querySelectorAll('#rsp-chart .ru-tip-gx span')).map((e) => e.textContent).join(''),
    ylabels: Array.from(document.querySelectorAll('#rsp-chart .ru-tip-gy')).map((e) => e.textContent),
    railOpacity: getComputedStyle(document.getElementById('rail-usage')).opacity,
  }));
  if (shots) { await pg.screenshot({ path: shots + '-dark.png' }); const ch = await pg.$('#rsp-chart'); if (ch) await ch.screenshot({ path: shots + '-chart.png' }); }
  // T247f: "your order"
  await pg.click('#rsp-panel [data-act="order:yours"]');
  await pg.waitForFunction(() => document.querySelector('#rsp-panel [data-act="order:yours"]').classList.contains('on'), null, { timeout: 5000 });
  const yourOrder = await pg.evaluate(() => {
    const rows = Array.from(document.querySelectorAll('#rsp-panel .rsp-tbl tbody tr')).map((tr) => tr.textContent.trim());
    // the bottom stack of the first bucket that has one: the path whose top edge is lowest among those sharing the first x
    const segs = Array.from(document.querySelectorAll('#rsp-chart .rsp-seg'));
    const byX = new Map(); segs.forEach((p) => { const x = p.getAttribute('d').split(/[ ,]/)[0].slice(1); if (!byX.has(x)) byX.set(x, []); byX.get(x).push(p); });
    let bottomFill = null; for (const [, ps] of byX) { const withY = ps.map((p) => ({ p, y1: parseFloat(p.getAttribute('d').split(/[ ,]/)[1]) })); withY.sort((a, b) => b.y1 - a.y1); if (withY.length > 1) { bottomFill = withY[0].p.getAttribute('fill'); break; } }
    const prefs = JSON.parse(localStorage.getItem('romp:spendModal') || '{}');
    return { rows, bottomFill, prefs, pressed: document.querySelector('#rsp-panel [data-act="order:yours"]').classList.contains('on') };
  });
  if (shots) await pg.screenshot({ path: shots + '-yourorder.png' });
  // a viewer arrangement (the strip's key) puts web first
  await pg.evaluate(() => { const rows = Array.from(document.querySelectorAll('#rsp-panel .rsp-tbl tbody tr')); const web = rows.find((tr) => tr.textContent.includes('TESTHOST:web')); const sid = web && web.getAttribute('data-sid'); localStorage.setItem('romp:vieworder', JSON.stringify(sid ? [sid] : [])); });
  await pg.click('#rsp-panel [data-act="order:spend"]'); await pg.click('#rsp-panel [data-act="order:yours"]');
  await pg.waitForFunction(() => document.querySelector('#rsp-panel [data-act="order:yours"]').classList.contains('on'), null, { timeout: 5000 });
  yourOrder.viewRows = await pg.evaluate(() => Array.from(document.querySelectorAll('#rsp-panel .rsp-tbl tbody tr')).map((tr) => tr.textContent.trim()));
  await pg.evaluate(() => { localStorage.removeItem('romp:vieworder'); });
  // leave "your order" pressed: the phone reload below must read it back (the chip pressed on open, the rows ordered)
  await pg.click('#rsp-panel [data-act="measure:tok"]');
  await pg.click('#rsp-panel [data-act="range:days"]');
  await pg.waitForFunction(() => document.querySelector('#rsp-panel [data-act="range:days"]').classList.contains('on')
    && document.querySelector('#rsp-panel [data-act="measure:tok"]').classList.contains('on'), null, { timeout: 5000 });
  const days = await pg.evaluate(() => ({
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
  // a drag-select from a table cell that ends over the backdrop is not a tap
  await pg.evaluate(() => document.getElementById('rail-usage').click());
  await pg.waitForFunction(() => !document.getElementById('rsp-back').hidden && document.querySelector('#rsp-panel .rsp-tbl td.n'), null, { timeout: 5000 });
  const cell = await (await pg.$('#rsp-panel .rsp-tbl td.n')).boundingBox();
  await pg.mouse.move(cell.x + 2, cell.y + cell.height / 2); await pg.mouse.down(); await pg.mouse.move(5, 5, { steps: 4 }); await pg.mouse.up();
  const hiddenAfterDrag = await pg.evaluate(() => document.getElementById('rsp-back').hidden);
  // the light theme's PRESSED toggle: accent chip, --accent-fg text, no hairline (T247b)
  const lightBtn = await pg.evaluate(() => {
    document.body.classList.add('theme-light');
    const b = document.querySelector('#rsp-panel .rsp-btn.on'); const cs = getComputedStyle(b);
    const out = { color: cs.color, border: cs.borderTopColor, bg: cs.backgroundColor };
    document.body.classList.remove('theme-light'); return out;
  });
  // dim once: a dead row's annotation sits at the row's level, and the fold row's button is a control
  const dim = await pg.evaluate(() => {
    const dead = document.querySelector('#rsp-panel tr.rsp-dead td.rsp-name');
    const ann = dead && dead.querySelector('.ru-tip-reset');
    return { row: dead ? getComputedStyle(dead).opacity : null, ann: ann ? getComputedStyle(ann).opacity : null };
  });
  // the loader's backstop: a fetch that never answers ends on the error + retry path (T247b)
  const timeout = await pg.evaluate(async () => {
    const f = window.fetch; window.__rompSpendTimeoutMs = 1000;
    window.fetch = (u, o) => new Promise((res, rej) => { if (o && o.signal) o.signal.addEventListener('abort', () => rej(new DOMException('aborted', 'AbortError'))); });
    try {
      // a re-open while the first fetch is pending: the superseded fetch's abort must NOT paint an error
      window.__rompOpenSpend(); window.__rompOpenSpend(); await new Promise((r) => setTimeout(r, 150));
      const early = { err: !!document.querySelector('#rsp-panel .rsp-err'), loader: !!document.querySelector('#rsp-panel .rsp-load') };
      await new Promise((r) => setTimeout(r, 1400));
      const err = document.querySelector('#rsp-panel .rsp-err'); return { early, err: err ? err.textContent : null, retry: !!document.querySelector('#rsp-panel [data-act="retry"]') }; }
    finally { window.fetch = f; delete window.__rompSpendTimeoutMs; }
  });
  await pg.keyboard.press('Escape');
  await pg.evaluate(() => document.getElementById('rail-usage').click());
  await pg.waitForSelector('#rsp-panel .rsp-tbl', { timeout: 10000 });
  // the light theme's error line, over a failed fetch
  const lightErr = await pg.evaluate(async () => {
    document.body.classList.add('theme-light');
    const f = window.fetch; window.fetch = () => Promise.reject(new Error('boom'));
    try { window.__rompOpenSpend(); await new Promise((r) => setTimeout(r, 200)); return getComputedStyle(document.querySelector('#rsp-panel .rsp-err')).color; }
    finally { window.fetch = f; document.body.classList.remove('theme-light'); }
  });
  await pg.keyboard.press('Escape');
  // the phone: no rail; the Usage panel's button is the door
  await pg.setViewportSize({ width: 390, height: 844 });
  await pg.reload(); await pg.waitForSelector('#mtabs [data-act="usage"]', { timeout: 20000 });
  await pg.evaluate(() => { const bt = document.getElementById('romp-boot'); if (bt) bt.remove(); });
  const railHidden = await pg.evaluate(() => getComputedStyle(document.querySelector('.pane-rail')).display === 'none');
  await pg.evaluate(() => window.__rompUsagePanel());
  await pg.waitForFunction(() => !!document.getElementById('ru-bysession') && document.getElementById('ru-back').classList.contains('on'), null, { timeout: 10000 });
  const btn = await pg.evaluate(() => { const bs = document.getElementById('ru-bysession');
    return { font: getComputedStyle(bs).fontSize, opacity: getComputedStyle(bs.parentNode).opacity, inAge: !!bs.closest('.ru-tip-age') }; });
  if (shots) await pg.screenshot({ path: shots + '-phone-panel.png' });
  await pg.click('#ru-bysession');
  await pg.waitForFunction(() => !document.getElementById('rsp-back').hidden && !document.getElementById('ru-back').classList.contains('on'), null, { timeout: 5000 });
  await pg.waitForSelector('#rsp-panel .rsp-tbl', { timeout: 10000 });
  if (shots) await pg.screenshot({ path: shots + '-phone.png' });
  const panelHint = await pg.evaluate(() => document.getElementById('ru-tip').textContent.includes('Click for the full breakdown'));
  const persisted = await pg.evaluate(() => ({ pressed: document.querySelector('#rsp-panel [data-act="order:yours"]').classList.contains('on'),
    first: (document.querySelector('#rsp-panel .rsp-tbl tbody tr') || {}).textContent || '' }));
  await pg.click('#rsp-panel [data-act="order:spend"]');   // restore the default for whoever runs next
  const mobile = { railHidden, panelOpened: true, modalOpened: true, btn, panelHint , persisted };
  console.log(JSON.stringify({ yourOrder, hoverHint, hiddenBefore, loaderSeen, out, days, tip, hiddenAfter, hiddenAfterTap, hiddenAfterDrag, lightErr, lightBtn, dim, timeout, mobile, errs }));
  await b.close();
})().catch((e) => { console.error(e); process.exit(1); });
