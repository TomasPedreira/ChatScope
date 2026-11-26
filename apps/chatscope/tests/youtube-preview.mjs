// Offline UI contracts: available, missing, failed, cancelled and source changes.
import { chromium } from 'playwright';
import { createServer } from 'node:http';
import { readFile, mkdir, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import assert from 'node:assert/strict';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const video = JSON.parse(await readFile(path.join(root,'tests/fixtures/youtube.json'),'utf8'));
await mkdir(path.join(root,'artifacts'),{recursive:true});
const server = createServer(async(req,res)=>{
  const file = {'/':'index.html','/app.js':'app.js','/style.css':'style.css','/fonts/InterVariable.woff2':'fonts/InterVariable.woff2'}[req.url];
  if(!file){res.writeHead(404);return res.end();}
  res.setHeader('Content-Type',file.endsWith('.js')?'application/javascript':file.endsWith('.css')?'text/css':file.endsWith('.woff2')?'font/woff2':'text/html');
  res.end(await readFile(path.join(root,'ui',file)));
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const browser = await chromium.launch({channel:'msedge',headless:true});
const errors=[];
try {
  const page=await browser.newPage({viewport:{width:1280,height:860}});
  page.on('pageerror',error=>errors.push(error.message));
  await page.addInitScript(({video})=>{
    const blank={users:0,reactions:0,bins:[],highlights:[]};
    const empty={provider:'',source:null,youtube:null,moments:[],status:'',detail:'',total:0,matched:0,position:0,elapsed:0,messages:[],analysis:blank,canExport:false};
    let session={...empty};
    window.scoperCalls=[];
    window.scoperScenario='available';
    window.__TAURI__={core:{invoke:async(name,args)=>{
      window.scoperCalls.push({name,args});
      if(name==='get_snapshot')return session;
      if(name==='start_capture'){
        if(args.url.includes('twitch.tv')){session={...empty,provider:'twitch',status:'complete',detail:'Sessão Twitch sem mensagens'};return;}
        const scenario=window.scoperScenario;
        const source={url:args.url,id:video.id,title:'<img src=x onerror="window.injected=true">',channel:video.channel,kind:'youtube',duration:video.duration,start:0,end:video.duration};
        const moments=[{start:100,end:130,peak:120,strength:0.92,signal:'youtube_heatmap',reason:'Pico de repetição · intensidade relativa 0.92/1'}];
        session={...empty,provider:'youtube',source,status:'complete',detail:'Análise concluída',position:video.duration,elapsed:2,canExport:true,clipProfile:args.clipProfile,
          youtube:{availability:scenario==='missing'?'unavailable':'available',heatmap:scenario==='missing'?[]:video.heatmap,extractorVersion:video.extractorVersion},moments:scenario==='missing'?[]:moments};
        if(scenario==='error')session={...empty,provider:'youtube',status:'error',detail:'YouTube: ligação indisponível'};
        if(scenario==='slow')session={...empty,provider:'youtube',status:'connecting',detail:'A consultar o YouTube…'};
        return;
      }
      if(name==='stop_capture'){session={...session,status:'stopped',detail:'Operação parada'};return;}
      if(['open_youtube_moment','export_chat'].includes(name))return null;
      throw new Error(`Unexpected command ${name}`);
    }}};
  },{video});
  await page.goto(`http://127.0.0.1:${server.address().port}`);
  await page.locator('#example-youtube').click();
  assert.equal(await page.locator('#start').textContent(),'Analisar YouTube');
  await page.locator('.clip-profile summary').click();
  await page.locator('#clip-duration').fill('60');
  await page.locator('#clip-before').fill('40');
  await page.locator('#clip-count').fill('4');
  await page.locator('#start').click();
  await page.locator('#youtube-panel').waitFor({state:'visible'});
  assert.equal(await page.locator('#twitch-panel').isVisible(),false);
  assert.equal(await page.locator('.youtube-bin').count(),100);
  assert.equal(await page.locator('.highlight').count(),1);
  assert.deepEqual(await page.evaluate(()=>window.scoperCalls.find(call=>call.name==='start_capture').args.clipProfile),{duration:60,beforePeak:40,maxMoments:4});
  await page.locator('.clip-profile summary').click();
  assert.equal(await page.locator('#source-title img').count(),0,'Untrusted metadata is text');
  assert.equal(await page.evaluate(()=>window.injected),undefined);
  assert.equal(await page.locator('#export-json').isEnabled(),true,'YouTube exports work without chat messages');
  await page.locator('#open-youtube').click();
  assert.equal(await page.evaluate(()=>window.scoperCalls.find(call=>call.name==='open_youtube_moment').args.start),100);
  await page.locator('.youtube-bin').nth(20).click();
  await page.locator('#open-youtube').click();
  assert.notEqual(await page.evaluate(()=>window.scoperCalls.filter(call=>call.name==='open_youtube_moment').at(-1).args.start),100);
  await page.locator('#export-json').click();
  assert.equal(await page.evaluate(()=>window.scoperCalls.some(call=>call.name==='export_chat'&&call.args.format==='json')),true);
  await page.screenshot({path:path.join(root,'artifacts/youtube-ui.png')});
  for(const viewport of [{width:1020,height:700},{width:900,height:600}]){
    await page.setViewportSize(viewport);
    const bounds=await page.locator('.export-bar').boundingBox();
    assert(bounds.y+bounds.height<=viewport.height);
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  }
  await page.screenshot({path:path.join(root,'artifacts/youtube-ui-compact.png')});
  await page.evaluate(()=>window.scoperScenario='missing');
  await page.locator('#start').click();
  await page.waitForFunction(()=>document.querySelectorAll('.youtube-bin').length===0);
  assert.equal(await page.locator('#youtube-moment').isVisible(),false);
  assert.match(await page.locator('#youtube-empty').textContent(),/Sem heatmap disponível/);
  assert.equal(await page.locator('#youtube-pill').textContent(),'CONCLUÍDO');
  await page.screenshot({path:path.join(root,'artifacts/youtube-ui-missing.png')});
  await page.evaluate(()=>window.scoperScenario='error');
  await page.locator('#start').click();
  await page.waitForFunction(()=>document.getElementById('youtube-pill').textContent==='ERRO');
  assert.equal(await page.locator('#youtube-empty').isVisible(),false,'Extraction errors are distinct from missing signals');
  assert.equal(await page.locator('#export-json').isEnabled(),false);
  await page.evaluate(()=>window.scoperScenario='slow');
  await page.locator('#start').click();
  await page.locator('#stop').waitFor({state:'visible'});
  assert.equal(await page.locator('#example-youtube').isDisabled(),true);
  await page.locator('#stop').click();
  await page.waitForFunction(()=>document.getElementById('youtube-pill').textContent==='PARADO');
  await page.locator('#example-live').click();
  await page.locator('#start').click();
  await page.locator('#twitch-panel').waitFor({state:'visible'});
  assert.equal(await page.locator('#youtube-panel').isVisible(),false);
  assert.equal(await page.locator('#users-label').textContent(),'participantes');
  const callsBefore=await page.evaluate(()=>window.scoperCalls.filter(call=>call.name==='start_capture').length);
  await page.locator('.clip-profile summary').click();
  await page.locator('#clip-before').fill('100');
  await page.locator('#start').click();
  assert.equal(await page.evaluate(()=>window.scoperCalls.filter(call=>call.name==='start_capture').length),callsBefore,'Invalid profiles preserve the current session');
  assert.deepEqual(errors,[]);
  await writeFile(path.join(root,'artifacts/youtube-ui-checks.json'),JSON.stringify({passed:true,checks:['real heatmap fixture','candidate and timeline navigation','timestamp opening','JSON export with zero chat messages','untrusted metadata escaping','missing versus failed extraction','cancellation','YouTube to Twitch switch','1280x860 / 1020x700 / 900x600 layout'],errors},null,2));
  console.log('YouTube headless UI checks passed.');
}finally{await browser.close();server.close();}
