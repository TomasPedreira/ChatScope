// Runs a NEW HIDDEN native Tauri instance with its own WebView2 profile. CDP
// sends input to that renderer only: no OS mouse/keyboard or window activation.
import { chromium } from 'playwright';
import { spawn } from 'node:child_process';
import { createServer } from 'node:net';
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import assert from 'node:assert/strict';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const delay = ms => new Promise(resolve => setTimeout(resolve,ms));
const reserve = createServer();
await new Promise(resolve => reserve.listen(0,'127.0.0.1',resolve));
const port = reserve.address().port;
await new Promise(resolve => reserve.close(resolve));
const app = spawn(path.join(root,'dist/ChatScope.exe'),['--isolated-test'],{
  cwd:root, windowsHide:true, stdio:'pipe',
  env:{...process.env,
    WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS:`--remote-debugging-port=${port} --remote-debugging-address=127.0.0.1`,
    WEBVIEW2_USER_DATA_FOLDER:path.join(root,'artifacts','isolated-webview-profile')
  }
});
let logs = '';
app.stdout.on('data',data=>{logs += data;});
app.stderr.on('data',data=>{logs += data;});
let browser;
const errors = [];
const checks = [];
try {
  let ready = false;
  for(let n=0;n<80;n++) {
    if(app.exitCode !== null) throw new Error(`Native app exited (${app.exitCode}): ${logs}`);
    try { const response = await fetch(`http://127.0.0.1:${port}/json/version`); ready = response.ok; } catch {}
    if(ready) break;
    await delay(250);
  }
  assert(ready,`Isolated WebView2 CDP did not start: ${logs}`);
  browser = await chromium.connectOverCDP(`http://127.0.0.1:${port}`);
  let page;
  for(let n=0;n<40;n++) {
    page = browser.contexts().flatMap(c=>c.pages()).find(p=>p.url().includes('tauri.localhost'));
    if(page) break;
    await delay(250);
  }
  assert(page,'Native Tauri page was not found');
  page.on('pageerror',error=>errors.push(error.message));
  await page.waitForFunction(()=>window.__TAURI__?.core && document.getElementById('url'));
  await page.evaluate(()=>document.fonts.ready);
  // Verify this instance is hidden before interacting with the renderer.
  assert.equal(await page.evaluate(()=>window.__TAURI__.window.getCurrentWindow().isVisible()),false);
  checks.push('Separate native instance remained hidden; no desktop input');

  await page.locator('#url').fill('https://www.twitch.tv/videos/2929044358');
  await page.locator('#range-start').fill('10:00');
  await page.locator('#range-end').fill('15:00');
  await page.locator('#start').click();
  await page.waitForFunction(()=>document.getElementById('chat-pill').textContent==='CONCLUÍDO' || document.getElementById('chat-pill').textContent==='ERRO',{},{timeout:90000});
  const vod = await page.evaluate(()=>window.__TAURI__.core.invoke('get_snapshot'));
  assert.equal(vod.status,'complete',vod.detail);
  assert(vod.total>100,'Expected real paginated VOD chat');
  assert.equal(vod.messages.length,400);
  assert(vod.analysis.highlights.length>0);
  assert.equal(await page.locator('.message').count(),400);
  await page.screenshot({path:path.join(root,'artifacts/native-vod.png')});
  await writeFile(path.join(root,'artifacts/native-vod-snapshot.json'),JSON.stringify(vod,null,2));
  checks.push(`Native GUI → Rust IPC → Twitch VOD: ${vod.total} real messages`);
  await delay(1100);
  assert.equal((await page.evaluate(()=>window.__TAURI__.core.invoke('get_snapshot'))).elapsed,vod.elapsed,'Completed capture timer must stop');
  const fixture = JSON.parse(await readFile(path.join(root,'tests/fixtures/vod.json'),'utf8'));
  await page.locator('.highlight').first().click();
  const moment = vod.analysis.highlights[0];
  const expectedMoment = fixture.messages.filter(m=>m.offset>=moment.start && m.offset<moment.end);
  await page.waitForFunction(n=>document.querySelectorAll('.message').length===n,Math.min(400,expectedMoment.length));
  assert(await page.locator('#moment-view').isVisible());
  const momentTimes = await page.locator('.message time').allTextContents();
  assert.equal(momentTimes[0],`${String(Math.floor(expectedMoment[0].offset/60)).padStart(2,'0')}:${String(Math.floor(expectedMoment[0].offset%60)).padStart(2,'0')}`);
  await page.screenshot({path:path.join(root,'artifacts/native-moment.png')});
  await page.locator('#clear-moment').click();
  await page.waitForFunction(()=>document.querySelectorAll('.message').length===400);
  checks.push('Candidate opens earlier captured messages; returning restores recent chat');
  checks.push('Completed session timer stays fixed');
  await page.locator('#only-reactions').check();
  await page.waitForFunction(n=>document.querySelectorAll('.message').length===n,Math.min(400,fixture.messages.filter(m=>m.reaction).length));
  await page.locator('#search').fill('NO_MATCH_870478');
  await page.waitForFunction(()=>document.querySelectorAll('.message').length===0);
  checks.push('Native text/reaction filtering covers the entire captured session');

  // Invalid URL: the existing completed session must remain available.
  const rejection = await page.evaluate(async()=>{
    try { await window.__TAURI__.core.invoke('start_capture',{url:'https://twitch.tv.evil.com/foo',start:null,end:null}); return null; }
    catch(error) { return String(error); }
  });
  assert(rejection?.includes('twitch.tv'));
  assert.equal((await page.evaluate(()=>window.__TAURI__.core.invoke('get_snapshot'))).total,vod.total);
  checks.push('Invalid URL rejected without discarding completed data');

  await page.locator('#example-live').click();
  await page.locator('#start').click();
  await page.waitForFunction(()=>document.getElementById('chat-pill').textContent==='AO VIVO',{},{timeout:45000});
  await page.waitForFunction(()=>document.getElementById('total').textContent!=='0',{},{timeout:60000});
  await page.locator('#stop').click();
  await page.waitForFunction(()=>document.getElementById('chat-pill').textContent==='PARADO',{},{timeout:10000});
  const live = await page.evaluate(()=>window.__TAURI__.core.invoke('get_snapshot'));
  assert(live.total>0);
  await page.screenshot({path:path.join(root,'artifacts/native-live.png')});
  await writeFile(path.join(root,'artifacts/native-live-snapshot.json'),JSON.stringify(live,null,2));
  checks.push(`Native live capture and stop: ${live.total} real messages preserved`);
  assert.equal(await page.evaluate(()=>window.__TAURI__.window.getCurrentWindow().isVisible()),false);
  assert.deepEqual(errors,[]);
  await writeFile(path.join(root,'artifacts/native-checks.json'),JSON.stringify({testedAt:new Date().toISOString(),hidden:true,checks,vodMessages:vod.total,liveMessages:live.total,javascriptErrors:errors},null,2));
  console.log(checks.join('\n'));
} catch(error) {
  console.error(logs.slice(-3000));
  throw error;
} finally {
  if(browser) await browser.close().catch(()=>{});
  app.kill();
}
