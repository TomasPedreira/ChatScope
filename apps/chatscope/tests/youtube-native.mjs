// Real UI -> Tauri IPC -> Python -> YouTube, in a separate hidden WebView2 process.
import { chromium } from 'playwright';
import { spawn } from 'node:child_process';
import { createServer } from 'node:net';
import { writeFile, mkdir } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import assert from 'node:assert/strict';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
await mkdir(path.join(root,'artifacts'),{recursive:true});
const reserve=createServer();
await new Promise(resolve=>reserve.listen(0,'127.0.0.1',resolve));
const port=reserve.address().port;
await new Promise(resolve=>reserve.close(resolve));
const executable=process.env.CHATSCOPE_EXE || path.join(root,'dist/ChatScope.exe');
const app=spawn(executable,['--isolated-test'],{cwd:root,windowsHide:true,stdio:'pipe',env:{...process.env,
  WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS:`--remote-debugging-port=${port} --remote-debugging-address=127.0.0.1`,
  WEBVIEW2_USER_DATA_FOLDER:path.join(root,'artifacts/youtube-native-profile')}});
let logs='';let browser;
app.stdout.on('data',data=>logs+=data);app.stderr.on('data',data=>logs+=data);
app.on('error',error=>logs+=error.message);
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function waitSnapshot(page,predicate) {
  const deadline=Date.now()+65000;
  let state;
  while(Date.now()<deadline){
    state=await page.evaluate(()=>window.__TAURI__.core.invoke('get_snapshot'));
    if(predicate(state))return state;
    await delay(200);
  }
  throw new Error(`Timed out waiting for native result: ${state?.status} ${state?.detail}`);
}
const errors=[];
try{
  let ready=false;
  for(let attempt=0;attempt<100;attempt++){
    if(app.exitCode!==null)throw new Error(`Native app exited ${app.exitCode}: ${logs}`);
    try{ready=(await fetch(`http://127.0.0.1:${port}/json/version`)).ok;}catch{}
    if(ready)break;
    await delay(200);
  }
  assert(ready,`WebView2 did not start: ${logs}`);
  browser=await chromium.connectOverCDP(`http://127.0.0.1:${port}`);
  let page;
  for(let attempt=0;attempt<60;attempt++){
    page=browser.contexts().flatMap(context=>context.pages()).find(page=>page.url().includes('tauri.localhost'));
    if(page)break;
    await delay(200);
  }
  assert(page,'Missing native renderer');
  page.on('pageerror',error=>errors.push(error.message));
  await page.waitForFunction(()=>window.__TAURI__?.core && document.getElementById('url'));
  assert.equal(await page.evaluate(()=>window.__TAURI__.window.getCurrentWindow().isVisible()),false);
  await page.locator('#example-youtube').click();
  await page.locator('.clip-profile summary').click();
  await page.locator('#clip-duration').fill('60');
  await page.locator('#clip-before').fill('40');
  await page.locator('#clip-count').fill('3');
  await page.locator('.clip-profile summary').click();
  await page.locator('#start').click();
  const snapshot=await waitSnapshot(page,state=>['complete','error'].includes(state.status));
  assert.equal(snapshot.status,'complete',snapshot.detail);
  assert.equal(snapshot.provider,'youtube');
  assert.equal(snapshot.youtube.availability,'available');
  assert.equal(snapshot.youtube.heatmap.length,100);
  assert(snapshot.moments.length>0);
  assert.equal(snapshot.clipProfile.duration,60);
  assert.equal(snapshot.clipProfile.beforePeak,40);
  assert(snapshot.moments.length<=3);
  assert(snapshot.moments.every(moment=>Math.abs(moment.end-moment.start-60)<0.001));
  assert.equal(snapshot.total,0);
  assert.equal(snapshot.canExport,true);
  await page.waitForFunction(()=>document.querySelectorAll('.video-bin').length===100);
  assert.equal(await page.locator('.video-bin').count(),100);
  assert.equal(await page.locator('.highlight').count(),snapshot.moments.length);
  await page.locator('.highlight').last().click();
  assert.equal(await page.locator('#video-moment').isVisible(),true);
  await page.screenshot({path:path.join(root,'artifacts/youtube-native.png')});
  const rejection=await page.evaluate(async()=>{
    try{await window.__TAURI__.core.invoke('start_capture',{url:'https://youtube.com.evil.org/watch?v=YE7VzlLtp-4',start:null,end:null});return null;}
    catch(error){return String(error);}
  });
  assert(rejection);
  assert.equal((await page.evaluate(()=>window.__TAURI__.core.invoke('get_snapshot'))).source.id,snapshot.source.id);
  const profileRejection=await page.evaluate(async()=>{
    try {await window.__TAURI__.core.invoke('start_capture',{url:'https://youtu.be/YE7VzlLtp-4',start:null,end:null,clipProfile:{duration:1,beforePeak:0,maxMoments:3}});return null;}
    catch(error){return String(error);}
  });
  assert(profileRejection);
  assert.equal((await page.evaluate(()=>window.__TAURI__.core.invoke('get_snapshot'))).clipProfile.duration,60);
  await page.locator('#range-start').fill('01:00');
  await page.locator('#range-end').fill('03:00');
  await page.locator('#start').click();
  const interval=await waitSnapshot(page,state=>state.status==='error' || (state.status==='complete' && state.source?.start===60));
  assert.equal(interval.status,'complete',interval.detail);
  assert.equal(interval.source.start,60);
  assert.equal(interval.source.end,180);
  assert(interval.youtube.heatmap.every(point=>point.start_time>=60 && point.end_time<=180));
  assert(interval.moments.every(moment=>moment.start>=60 && moment.end<=180));
  // Cancellation before a network operation completes must stop the child process.
  await page.evaluate(async()=>{
    await window.__TAURI__.core.invoke('start_capture',{url:'https://youtu.be/dQw4w9WgXcQ',start:null,end:null});
    await window.__TAURI__.core.invoke('stop_capture');
  });
  await page.waitForFunction(()=>document.getElementById('video-pill').textContent==='PARADO',{},{timeout:10000});
  const stopped=await page.evaluate(()=>window.__TAURI__.core.invoke('get_snapshot'));
  assert.equal(stopped.status,'stopped');
  await delay(1500);
  assert.equal((await page.evaluate(()=>window.__TAURI__.core.invoke('get_snapshot'))).status,'stopped','Late extraction must not overwrite cancellation');
  assert.equal(await page.evaluate(()=>window.__TAURI__.window.getCurrentWindow().isVisible()),false);
  assert.deepEqual(errors,[]);
  await writeFile(path.join(root,'artifacts/youtube-native-snapshot.json'),JSON.stringify(snapshot,null,2));
  await writeFile(path.join(root,'artifacts/youtube-native-checks.json'),JSON.stringify({testedAt:new Date().toISOString(),hidden:true,passed:true,intervalPoints:interval.youtube.heatmap.length,moments:snapshot.moments.length,checks:['real UI -> Rust -> isolated Python -> YouTube','100 real heatmap bins','candidate selection','export eligibility without chat','URL validation preserves previous session','requested interval bounds','cancellation and stale completion protection'],errors},null,2));
  console.log(`Native YouTube checks passed: ${snapshot.youtube.heatmap.length} bins, ${snapshot.moments.length} moments; interval and cancellation passed.`);
}finally{
  if(browser)await browser.close().catch(()=>{});
  app.kill();
}
