// Isolated rendering checks. Uses an actual captured VOD as a fixture; this
// script tests the frontend, not the network. Native integration is separate.
import { chromium } from 'playwright';
import { createServer } from 'node:http';
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import assert from 'node:assert/strict';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const fixture = JSON.parse(await readFile(path.join(root, 'tests/fixtures/vod.json'), 'utf8'));
await mkdir(path.join(root, 'artifacts'), {recursive:true});
const server = createServer(async (req, res) => {
  try {
    const file = {'/':'index.html','/style.css':'style.css','/app.js':'app.js', '/dom_helpers.js':'dom_helpers.js', '/tauri_client.js':'tauri_client.js', '/clip_production_view.js':'clip_production_view.js','/fonts/InterVariable.woff2':'fonts/InterVariable.woff2'}[req.url];
    if (!file) { res.writeHead(404); return res.end(); }
    res.setHeader('Content-Type', file.endsWith('.css') ? 'text/css' : file.endsWith('.js') ? 'application/javascript' : file.endsWith('.woff2') ? 'font/woff2' : 'text/html');
    res.end(await readFile(path.join(root, 'ui', file)));
  } catch { res.writeHead(500); res.end(); }
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const browser = await chromium.launch({channel:'msedge',headless:true});
const errors = [];
try {
  const page = await browser.newPage({viewport:{width:1280,height:860},deviceScaleFactor:1});
  page.on('pageerror', error => errors.push(error.message));
  await page.addInitScript(({fixture}) => {
    const emptyAnalysis = {users:0,reactions:0,bins:[],highlights:[]};
    let session = {source:null,status:'',detail:'',total:0,position:0,elapsed:0,messages:[],analysis:emptyAnalysis};
    window.__TAURI__ = {core:{invoke:async (name, args) => {
      if (name === 'get_snapshot') {
        const query = (args?.query || '').toLowerCase();
        const messages = session.messages.filter(m=>(!args?.reactionsOnly || m.reaction) && (!query || `${m.user} ${m.text}`.toLowerCase().includes(query)) && (args?.start == null || m.offset>=args.start) && (args?.end == null || m.offset<args.end));
        return {...session,matched:messages.length,messages:messages.slice(-400)};
      }
      if (name === 'get_example_vod') return {url:fixture.source.url,start:600,end:900};
      if (name === 'start_capture') {
        session = {source:fixture.source,status:'complete',detail:'Extração concluída · mensagens prontas para exportar',total:fixture.messageCount,position:900,elapsed:14,messages:fixture.messages,analysis:fixture.analysis};
        return;
      }
      if (name === 'export_chat') return null;
      throw new Error(`Unexpected invocation: ${name}`);
    }}};
  }, {fixture});
  await page.goto(`http://127.0.0.1:${server.address().port}`);
  await page.locator('#notice-text').getByText('Sem sessão', {exact:false}).waitFor();
  await page.evaluate(() => document.fonts.ready);
  await page.screenshot({path:path.join(root,'artifacts/ui-empty.png')});
  await page.locator('#example-vod').click();
  await page.waitForFunction(() => document.getElementById('url').value.includes('/videos/'));
  await page.locator('#start').click();
  await page.waitForFunction(() => document.getElementById('total').textContent !== '0');
  assert.equal(await page.locator('.message').count(),400);
  assert.equal(await page.locator('.highlight').count(),fixture.analysis.highlights.length);
  await page.screenshot({path:path.join(root,'artifacts/ui-recorded-vod.png')});
  await page.locator('.highlight').first().click();
  const firstMoment = fixture.analysis.highlights[0];
  const momentCount = fixture.messages.filter(m=>m.offset>=firstMoment.start && m.offset<firstMoment.end).length;
  await page.waitForFunction(count=>document.querySelectorAll('.message').length===count, Math.min(400,momentCount));
  assert(await page.locator('#moment-view').isVisible());
  await page.screenshot({path:path.join(root,'artifacts/ui-moment.png')});
  await page.locator('#clear-moment').click();
  await page.waitForFunction(()=>document.querySelectorAll('.message').length===400);
  await page.locator('#only-reactions').check();
  await page.waitForFunction(count=>document.querySelectorAll('.message').length===count, Math.min(400,fixture.messages.filter(m=>m.reaction).length));
  await page.locator('#search').fill('NO_MATCH_7658');
  await page.waitForFunction(()=>document.querySelectorAll('.message').length===0);
  await page.locator('#search').fill('');
  await page.locator('#only-reactions').uncheck();
  await page.waitForFunction(()=>document.querySelectorAll('.message').length===400);
  await page.setViewportSize({width:1020,height:700});
  const bounds = await page.locator('.export-bar').boundingBox();
  assert(bounds.y+bounds.height<=700, 'Export controls must remain on screen');
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,'No horizontal overflow');
  await page.screenshot({path:path.join(root,'artifacts/ui-compact.png')});
  assert.deepEqual(errors,[]);
  await writeFile(path.join(root,'artifacts/ui-checks.json'),JSON.stringify({scope:'Isolated headless frontend, real recorded VOD fixture',messages:fixture.messageCount,renderedMessages:400,highlights:fixture.analysis.highlights.length,viewports:['1280x860','1020x700'],filtering:'passed',momentNavigation:'passed',overflow:'passed',javascriptErrors:errors},null,2));
  console.log('Headless UI: rendering, filtering, compact layout passed. No desktop input.');
} finally { await browser.close(); server.close(); }
