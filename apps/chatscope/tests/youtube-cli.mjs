// Explicit spawning also waits correctly for Windows GUI executables in CLI mode.
import {spawnSync} from 'node:child_process';
import {readFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
import assert from 'node:assert/strict';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const result=spawnSync(path.join(root,'dist/ChatScope.exe'),[
  '--scope-youtube','https://youtu.be/YE7VzlLtp-4','--duration','60',
  '--before-peak','40','--max-moments','3','--output','artifacts/youtube-cli-profile.json',
],{cwd:root,windowsHide:true,encoding:'utf8',timeout:65000});
assert.ifError(result.error);
assert.equal(result.status,0,result.stderr);
const report=JSON.parse(await readFile(path.join(root,'artifacts/youtube-cli-profile.json'),'utf8'));
assert.equal(report.clipProfile.duration,60);
assert.equal(report.clipProfile.beforePeak,40);
assert.equal(report.heatmap.length,100);
assert(report.moments.length>0 && report.moments.length<=3);
assert(report.moments.every(moment=>Math.abs(moment.end-moment.start-60)<0.001));
console.log(`CLI passed: ${report.heatmap.length} bins, ${report.moments.length} moments of 60s.`);
