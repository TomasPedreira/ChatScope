// Real hidden WebView2 -> Tauri -> worker -> FFmpeg. No desktop input or network.
import { chromium } from 'playwright';
import { spawn, execFileSync } from 'node:child_process';
import { createServer } from 'node:net';
import { readFile, writeFile, mkdir, stat } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';
import assert from 'node:assert/strict';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const artifacts=path.join(root,'artifacts');await mkdir(artifacts,{recursive:true});
const source=path.join(artifacts,`native-source-${Date.now()}.mp4`);
execFileSync(path.join(root,'.venv-youtube/Scripts/python.exe'),['-c',
  'import sys;sys.path.insert(0,"tests");from test_pipeline import synthetic;from pathlib import Path;synthetic(Path(sys.argv[1]))',source],{cwd:root,windowsHide:true});
const executable=process.env.CHATSCOPE_EXE || path.join(root,'dist/ChatScope.exe');
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const errors=[];let app,browser,page,logs='';
async function launch(){
  const reserve=createServer();await new Promise(resolve=>reserve.listen(0,'127.0.0.1',resolve));
  const port=reserve.address().port;await new Promise(resolve=>reserve.close(resolve));
  app=spawn(executable,['--isolated-test'],{cwd:root,windowsHide:true,stdio:'pipe',env:{...process.env,
    WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS:`--remote-debugging-port=${port} --remote-debugging-address=127.0.0.1`,
    WEBVIEW2_USER_DATA_FOLDER:path.join(artifacts,`media-native-profile-${port}`)}});
  app.stdout.on('data',data=>logs+=data);app.stderr.on('data',data=>logs+=data);
  let ready=false;
  for(let i=0;i<100;i++){
    if(app.exitCode!==null)throw new Error(`App exited ${app.exitCode}: ${logs}`);
    try{ready=(await fetch(`http://127.0.0.1:${port}/json/version`)).ok;}catch{}
    if(ready)break;await delay(200);
  }
  assert(ready,'WebView2 did not start');browser=await chromium.connectOverCDP(`http://127.0.0.1:${port}`);
  for(let i=0;i<70;i++){
    page=browser.contexts().flatMap(c=>c.pages()).find(p=>p.url().includes('tauri.localhost'));
    if(page)break;await delay(100);
  }
  assert(page);page.on('pageerror',error=>errors.push(error.message));
  await page.waitForFunction(()=>window.__TAURI__?.core && document.getElementById('render-selection'));
  assert.equal(await page.evaluate(()=>window.__TAURI__.window.getCurrentWindow().isVisible()),false);
}
const invoke=(name,args)=>page.evaluate(({name,args})=>window.__TAURI__.core.invoke(name,args),{name,args});
async function waitFor(name,predicate,seconds=90){
  let value;
  for(let i=0;i<seconds*5;i++){
    value=await invoke(name);if(predicate(value))return value;
    if(name==='get_production'&&value.status==='error'&&!value.busy)throw new Error(JSON.stringify(value));
    await delay(200);
  }
  throw new Error(`Timed out ${name}: ${JSON.stringify(value)}`);
}
async function analyze(){
  await invoke('start_capture',{url:pathToFileURL(source).href,start:'0',end:'12',
    clipProfile:{duration:5,beforePeak:2,maxMoments:2}});
  const snapshot=await waitFor('get_snapshot',s=>['complete','error'].includes(s.status));
  assert.equal(snapshot.status,'complete',snapshot.detail);
  assert.equal(snapshot.provider,'local');assert.equal(snapshot.video.signal,'audio_energy');
  assert(snapshot.moments.length>0);assert.equal(snapshot.video.timeOrigin,'source');
  await page.waitForFunction(()=>document.getElementById('source-type').textContent==='LOCAL');
  return snapshot;
}
const args={start:'2',end:'7',all:false,renderProfile:{aspect:'9:16',fit:'pad',captions:false},topic:'native-tests'};
try{
  await launch();const snapshot=await analyze();
  await page.locator('#render-start').fill('2');await page.locator('#render-end').fill('7');
  await page.locator('#render-topic').fill('native-tests');
  await page.locator('#render-selection').click();
  const completed=await waitFor('get_production',s=>s.status==='complete'&&!s.busy);
  assert.equal(completed.clips.length,1);const clip=completed.clips[0];
  assert.deepEqual(clip.dimensions,[1080,1920]);assert(Math.abs(clip.duration-5)<.15);
  assert.equal(clip.moment.start,2);assert.equal(clip.moment.end,7);
  assert((await stat(clip.path)).size>10000);
  const hash=createHash('sha256').update(await readFile(clip.path)).digest('hex');assert.equal(hash,clip.sha256);
  await assert.rejects(()=>invoke('create_clips',{...args,start:'11',end:'16'}),/intervalos válidos/);
  await assert.rejects(()=>invoke('create_clips',{...args,topic:'../bad'}),/tema/);
  await invoke('create_clips',args);
  await waitFor('get_production',s=>s.clips?.some(c=>c.status==='rendering'));
  await invoke('cancel_production');
  const cancelled=await waitFor('get_production',s=>!s.busy&&s.status==='cancelled');
  assert(cancelled.clips.some(c=>c.status==='cancelled'));
  assert.equal(JSON.parse(await readFile(path.join(cancelled.folder,'job.json'),'utf8')).status,'cancelled');
  await invoke('retry_production');
  const retried=await waitFor('get_production',s=>!s.busy&&s.status==='complete');
  assert.notEqual(retried.id,cancelled.id);
  assert.equal(createHash('sha256').update(await readFile(clip.path)).digest('hex'),hash);
  await invoke('create_clips',args);
  await waitFor('get_production',s=>s.clips?.some(c=>c.status==='rendering'));
  app.kill();await delay(500);await browser.close();browser=null;
  await launch();
  const recovered=await invoke('get_production');assert.equal(recovered.status,'interrupted');assert.equal(recovered.busy,false);
  await invoke('retry_production');
  const final=await waitFor('get_production',s=>!s.busy&&s.status==='complete');
  assert.equal(createHash('sha256').update(await readFile(clip.path)).digest('hex'),hash);
  await page.locator('#production-results').evaluate(el=>el.open=true);
  await page.waitForFunction(()=>document.getElementById('production-clips').textContent.includes('Rever MP4'));
  for(const viewport of [{width:1280,height:860},{width:900,height:600}]){
    await page.setViewportSize(viewport);
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    const bounds=await page.locator('.export-bar').boundingBox();assert(bounds.y+bounds.height<=viewport.height+1);
    const moments=await page.locator('.highlights-section').boundingBox();
    const footnote=await page.locator('.analysis-footnote').boundingBox();
    assert(moments.y+moments.height<=footnote.y+1,'Analysis sections must not overlap');
  }
  await page.screenshot({path:path.join(artifacts,'media-native.png')});assert.deepEqual(errors,[]);
  await writeFile(path.join(artifacts,'media-native-checks.json'),JSON.stringify({source,analysis:snapshot.video.signal,
    ready:clip,rendering:'passed',invalidBounds:'passed',topicTraversal:'passed',cancel:'passed',retry:'passed',restartRecovery:'passed',
    preservedHash:hash,finalJob:final.id,javascriptErrors:errors},null,2));
  console.log('Native media: local analysis, real MP4, bounds, cancellation, retry and restart recovery passed.');
}finally{if(browser)await browser.close();if(app&&app.exitCode===null)app.kill();}
