// Explicit network integration: tiny CC test cut plus optional bounded NASA live capture.
import { spawnSync } from 'node:child_process';
import { mkdir, readFile, writeFile, stat } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import assert from 'node:assert/strict';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const executable=process.env.CHATSCOPE_EXE || path.join(root,'dist/ChatScope.exe');
const artifacts=path.join(root,'artifacts');await mkdir(artifacts,{recursive:true});
async function test(name,url,live=false){
  const folder=path.join(artifacts,`${name}-${Date.now()}`);await mkdir(folder,{recursive:true});
  const output=path.join(folder,'result.json');const job=path.join(folder,'request.json');
  const start=live?5:10,end=start+5;
  await writeFile(job,JSON.stringify({url,...(live?{captureSeconds:30}:{start:10,end:15}),produce:true,
    clipProfile:{duration:5,beforePeak:2,maxMoments:2},renderProfile:{aspect:'9:16',fit:'pad',captions:false},
    topic:'network-test',output,outputRoot:path.join(folder,'production'),
    moments:[{start,end,peak:start+2,strength:0,signal:'manual',reason:'Teste de integração real'}]},null,2));
  const result=spawnSync(executable,['--media-job',job],{cwd:root,windowsHide:true,encoding:'utf8',timeout:240000});
  assert.equal(result.status,0,`${name}: ${result.stderr || result.error}`);
  const document=JSON.parse(await readFile(output,'utf8'));
  assert.equal(document.production.status,'complete',JSON.stringify(document.production));
  if(live){assert.equal(document.video.timeOrigin,'recording');assert(document.source.duration>=29&&document.source.duration<40);}
  const clip=document.production.clips[0];assert.deepEqual(clip.dimensions,[1080,1920]);
  assert(Math.abs(clip.duration-5)<.15);assert((await stat(clip.path)).size>10000);
  assert.equal(createHash('sha256').update(await readFile(clip.path)).digest('hex'),clip.sha256);
  console.log(`${name}: ${document.source.kind}, ${clip.duration}s MP4, SHA-256 verified`);
  return {name,output,source:document.source,clip};
}
const checks=[await test('youtube-video','https://www.youtube.com/watch?v=YE7VzlLtp-4')];
if(process.argv.includes('--live'))checks.push(await test('youtube-live','https://www.youtube.com/watch?v=ROboUHfPUrU',true));
await writeFile(path.join(artifacts,'media-network-checks.json'),JSON.stringify(checks,null,2));
