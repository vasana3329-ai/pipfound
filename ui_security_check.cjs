#!/usr/bin/env node
// Real Chromium regressions, using only an isolated pipfound test server.
const assert = require('node:assert/strict');
const path = require('node:path');
const puppeteer = require(path.join(process.env.PF_PUPPETEER_DIR, 'puppeteer-core'));
const url = process.argv[2];
(async () => {
  const browser = await puppeteer.launch({headless: true, executablePath: process.env.PF_BROWSER,
    args: ['--disable-gpu', '--disable-dev-shm-usage']});
  try {
    const page = await browser.newPage();
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.setViewport({width: 900, height: 1400});
    await page.goto(url, {waitUntil: 'load', timeout: 30000});
    const replayText=await page.evaluate(() => {
      renderBacktest({symbol:'آزمایشی',style:'آزمایشی',timeframes:[],trades:2,closed_trades:1,open_trades:1,
        wins:0,losses:0,winrate_pct:0,total_R:0,avg_R_per_trade:0,expectancy_R:0,
        trade_log:[{result:'open',r:null,time:'test',dir:'صعودی',entry_type:'market'},
                   {result:'be',r:0,time:'test',dir:'صعودی',entry_type:'market'}]});
      return document.getElementById('btresult').textContent;
    });
    assert(replayText.includes('سربه‌سر')&&replayText.includes('باز')&&!replayText.includes('nullR'));
    assert(replayText.includes('ناخالص')&&replayText.includes('تقویمِ تاریخی'));
    const attack = '<img src=x onerror="document.body.dataset.pwned=1">';
    const saved = await page.evaluate(async (note) => {
      const dataurl='data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl6Yh0AAAAASUVORK5CYII=';
      const response = await fetch('/api/screenshot', {method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({symbol:'XAUUSD',note,dataurl})});
      return response.json();
    }, attack);
    assert(saved.added, 'actual screenshot upload failed');
    await page.evaluate(() => loadShots());
    assert.equal(await page.evaluate(() => document.body.dataset.pwned), undefined);
    assert(await page.$eval('#shotGrid .meta', el => el.textContent).then(t => t.includes(attack)));
    assert.equal(await page.$$eval('#shotGrid .meta img', els => els.length), 0);
    // Empty economic interpretation must render "unknown", not crash on gold:null.
    await page.goto(url + 'fundamental', {waitUntil:'load'});
    const card = await page.evaluate(() => scenCard('beat', {label:'fixture',ccy_dir:'',pairs:[],gold:null}));
    assert(card.includes('نامعلوم'));
    const keyAndText = await page.evaluate(() => {
      const event={iso:'2026-11-22T12:00:00+00:00',title:'A&B"<img src=x onerror="document.body.dataset.pwned=2">',
        passed:true,verdict:{found:false},country:'USD',country_fa:'دلار',impact:'High',forecast:'',previous:'',et:'test',tehran:'test'};
      const key=evKey(event); openKeys.add(key);
      const host=document.createElement('div');host.innerHTML=evCard(event,0);
      return {key,readKey:host.firstElementChild.dataset.key,opened:host.firstElementChild.classList.contains('open'),
        images:host.querySelectorAll('img').length,text:host.textContent};
    });
    assert.equal(keyAndText.key, keyAndText.readKey);
    assert(keyAndText.opened);
    assert.equal(keyAndText.images, 0);
    await page.goto(url, {waitUntil:'load'});
    await page.setRequestInterception(true);
    page.on('request', request => new URL(request.url()).pathname === '/api/analyze'
      ? request.abort('failed') : request.continue());
    await page.evaluate(() => {window._last={symbol:'XAUUSD'}; document.getElementById('sym').value='XAUUSD';});
    await page.click('#refreshBtn');
    await page.waitForFunction(() => !document.getElementById('refreshBtn').disabled, {timeout:30000});
    assert.equal(await page.$eval('#refreshBtn', el => el.classList.contains('ok')), false);
    assert(/خطا|ناموفق/.test(await page.$eval('#result', el => el.textContent)));
    await page.setViewport({width: 390, height: 844});
    await page.screenshot({path:process.argv[3],fullPage:true});
    assert.deepEqual(errors, [], 'unhandled browser runtime errors');
    console.log(JSON.stringify({ok:true,checks:['stored-XSS','literal-event-key','unknown-scenario','refresh-failure','mobile-render'],
      screenshot:process.argv[3],browser:await browser.version()}));
  } finally {await browser.close();}
})().catch(e=>{console.error(e.stack);process.exitCode=1;});
