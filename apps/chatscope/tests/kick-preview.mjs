// Offline UI contracts for Kick. Rendering/network are tested through the real worker separately.
import { chromium } from 'playwright';
import { createServer } from 'node:http';
import { readFile, mkdir } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import assert from 'node:assert/strict';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const server=createServer(async(req,res)=>{
  const file={'/':'index.html','/app.js':'app.js','/style.css':'style.css','/fonts/InterVariable.woff2':'fonts/InterVariable.woff2'}[req.url];
  if(!file){res.writeHead(404);return res.end();}
  res.setHeader('Content-Type',file.endsWith('.js')?'application/javascript':file.endsWith('.css')?'text/css':file.endsWith('.woff2')?'font/woff2':'text/html');
  res.end(await readFile(path.join(root,'ui',file)));
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const browser=await chromium.launch({channel:'msedge',headless:true});const errors=[];
try{
  const page=await browser.newPage({viewport:{width:900,height:600}});page.on('pageerror',e=>errors.push(e.message));
  await page.addInitScript(()=>{
    const empty={provider:'',source:null,status:'',detail:'',total:0,matched:0,position:0,elapsed:0,messages:[],analysis:{users:0,reactions:0,bins:[],highlights:[]},moments:[],canExport:false};
    let session={...empty};window.kickCalls=[];window.kickScenario='ready';
    window.__TAURI__={core:{invoke:async(name,args)=>{
      window.kickCalls.push({name,args});
      if(name==='get_snapshot')return session;
      if(name==='get_production')return {status:'idle',busy:false,clips:[]};
      if(name==='start_capture'){
        const connecting=window.kickScenario==='connecting';
        session={...empty,provider:'kick',status:connecting?'connecting':'complete',detail:'Teste Kick',canExport:!connecting,
          source:connecting?null:{url:args.url,kind:'kick_live',id:'example',title:'<img src=x onerror="window.injected=true">',channel:'Example',start:0,end:60,duration:60},
          video:connecting?null:{signal:'audio_energy',availability:'available',timeOrigin:'recording',points:[{start_time:0,end_time:20,value:.1},{start_time:20,end_time:40,value:.9},{start_time:40,end_time:60,value:.1}]},
          moments:connecting?[]:[{start:0,end:30,peak:20,signal:'audio_energy',strength:.9,reason:'Pico de áudio'}]};return;
      }
      if(name==='stop_capture'){session={...session,status:'stopped'};return;}
    }}};
  });
  await page.goto(`http://127.0.0.1:${server.address().port}`);
  await page.locator('#url').fill('https://kick.com/example');
  assert.equal(await page.locator('#start').textContent(),'Analisar Kick');await page.locator('#start').click();
  await page.waitForFunction(()=>document.getElementById('video-heading').textContent.includes('kick'));
  assert(await page.locator('#youtube-panel').isVisible());assert(await page.locator('#twitch-panel').isHidden());
  assert(await page.locator('#open-youtube').isHidden());assert.equal(await page.locator('#video-signal').textContent(),'Energia do áudio');
  assert.equal(await page.locator('#source-title img').count(),0);
  await page.locator('#render-start').fill('2');await page.locator('#render-end').fill('7');await page.locator('#render-selection').click();
  const call=await page.evaluate(()=>window.kickCalls.find(c=>c.name==='create_clips'));
  assert.equal(call.args.start,'2');assert.equal(call.args.end,'7');assert.equal(call.args.renderProfile.aspect,'9:16');
  await page.evaluate(()=>window.kickScenario='connecting');await page.locator('#start').click();
  await page.waitForFunction(()=>!document.getElementById('stop').classList.contains('hidden'));
  assert(await page.locator('#youtube-panel').isVisible());assert(await page.locator('#twitch-panel').isHidden());
  await page.locator('#stop').click();await page.waitForFunction(()=>!document.getElementById('start').classList.contains('hidden'));
  assert.deepEqual(errors,[]);assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  await mkdir(path.join(root,'artifacts'),{recursive:true});await page.screenshot({path:path.join(root,'artifacts/kick-ui.png')});
  console.log('Kick UI: audio timeline, safe metadata, manual cuts, connecting/cancel states and compact layout passed.');
}finally{await browser.close();server.close();}
