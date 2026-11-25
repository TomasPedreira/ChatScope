// Real Kick VOD -> hidden desktop UI -> IPC -> provider -> master -> local MP4.
import {chromium} from 'playwright';
import {spawn} from 'node:child_process';
import {createServer} from 'node:net';
import {readFile,writeFile,mkdir} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
import assert from 'node:assert/strict';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const url=process.argv[2];assert(url?.startsWith('https://kick.com/'),'Pass a current public Kick VOD URL');
const reserve=createServer();await new Promise(resolve=>reserve.listen(0,'127.0.0.1',resolve));
const port=reserve.address().port;await new Promise(resolve=>reserve.close(resolve));
const app=spawn(process.env.CHATSCOPE_EXE||path.join(root,'dist/ChatScope.exe'),['--isolated-test'],{cwd:root,windowsHide:true,stdio:'pipe',env:{...process.env,
  WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS:`--remote-debugging-port=${port} --remote-debugging-address=127.0.0.1`,
  WEBVIEW2_USER_DATA_FOLDER:path.join(root,`artifacts/kick-native-profile-${port}`)}});
let browser,page,logs='';const errors=[];const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
app.stderr.on('data',data=>logs+=data);app.stdout.on('data',data=>logs+=data);
async function wait(name,predicate){
  let value;
  for(let i=0;i<500;i++){
    value=await page.evaluate(name=>window.__TAURI__.core.invoke(name),name);
    if(predicate(value))return value;
    if(value.status==='error')throw new Error(JSON.stringify(value));await delay(200);
  }
  throw new Error(`Timed out: ${JSON.stringify(value)}`);
}
try{
  let ready=false;
  for(let i=0;i<100;i++){
    if(app.exitCode!==null)throw new Error(`App exited: ${logs}`);
    try{ready=(await fetch(`http://127.0.0.1:${port}/json/version`)).ok;}catch{}
    if(ready)break;await delay(200);
  }
  assert(ready);browser=await chromium.connectOverCDP(`http://127.0.0.1:${port}`);
  for(let i=0;i<70;i++){page=browser.contexts().flatMap(c=>c.pages()).find(p=>p.url().includes('tauri.localhost'));if(page)break;await delay(100);}
  assert(page);page.on('pageerror',e=>errors.push(e.message));await page.waitForFunction(()=>window.__TAURI__?.core);
  assert.equal(await page.evaluate(()=>window.__TAURI__.window.getCurrentWindow().isVisible()),false);
  await page.locator('#url').fill(url);await page.locator('#range-start').fill('10');await page.locator('#range-end').fill('20');
  await page.locator('.clip-profile summary').click();await page.locator('#clip-duration').fill('5');await page.locator('#clip-before').fill('2');await page.locator('#clip-count').fill('2');await page.locator('.clip-profile summary').click();
  assert.equal(await page.locator('#start').textContent(),'Analisar Kick');await page.locator('#start').click();
  const snapshot=await wait('get_snapshot',s=>s.status==='complete');
  assert.equal(snapshot.provider,'kick');assert.equal(snapshot.video.signal,'audio_energy');assert.equal(snapshot.video.timeOrigin,'source');
  assert.equal(snapshot.source.start,10);assert.equal(snapshot.source.end,20);assert(snapshot.video.points.length>=9);
  await page.waitForFunction(()=>document.getElementById('source-type').textContent==='KICK');
  assert(await page.locator('#open-youtube').isHidden());assert((await page.locator('#mode-label').textContent()).includes('Kick'));
  await page.locator('#render-start').fill('10');await page.locator('#render-end').fill('15');await page.locator('#render-topic').fill('kick-native-test');await page.locator('#render-selection').click();
  const job=await wait('get_production',s=>!s.busy&&s.status==='complete');const clip=job.clips[0];
  assert.equal(clip.moment.start,10);assert.equal(clip.moment.end,15);assert.deepEqual(clip.dimensions,[1080,1920]);assert(Math.abs(clip.duration-5)<.15);
  assert.equal(createHash('sha256').update(await readFile(clip.path)).digest('hex'),clip.sha256);
  await page.waitForFunction(()=>document.getElementById('production-clips').textContent.includes('Rever MP4'));
  assert.deepEqual(errors,[]);await mkdir(path.join(root,'artifacts'),{recursive:true});
  await page.screenshot({path:path.join(root,'artifacts/kick-native.png')});
  await writeFile(path.join(root,'artifacts/kick-native-checks.json'),JSON.stringify({url,source:snapshot.source,signal:snapshot.video.signal,clip,javascriptErrors:errors},null,2));
  console.log('Kick native: UI -> Rust provider -> public VOD -> audio -> selected MP4 passed.');
}finally{if(browser)await browser.close();if(app.exitCode===null)app.kill();}
