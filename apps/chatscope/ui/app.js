'use strict';
const $ = id => document.getElementById(id);
const invoke = window.__TAURI__.core.invoke;
const formatNumber = n => new Intl.NumberFormat('pt-PT').format(n);
const time = seconds => {
  const n = Math.max(0, Math.floor(seconds || 0));
  const parts = [Math.floor(n / 3600), Math.floor(n / 60) % 60, n % 60];
  return (parts[0] ? parts : parts.slice(1)).map(n => String(n).padStart(2, '0')).join(':');
};
let snapshot = null;
let lastMessagesKey = '';
let lastAnalysisKey = '';
let selectedRange = null;
let previousAutoFollow = true;
let requestRevision = 0;
let toastTimer;
let selectedYouTubeMoment = null;
function youtubeInput() {
  try { return ['youtube.com','www.youtube.com','m.youtube.com','youtu.be','www.youtu.be'].includes(new URL($('url').value.trim()).hostname); }
  catch { return false; }
}
function updateStartLabel() {
  $('start').textContent = youtubeInput() ? 'Analisar YouTube' : 'Capturar';
}
function toast(message) {
  $('toast').textContent = message;
  $('toast').classList.remove('hidden');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => $('toast').classList.add('hidden'), 9000);
}
function textNode(tag, className, value) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  node.textContent = value;
  return node;
}
function renderMessages(force = false) {
  if (!snapshot) return;
  const key = `${snapshot.total}|${snapshot.matched}|${snapshot.messages[0]?.id}|${snapshot.messages.at(-1)?.id}|${$('search').value}|${$('only-reactions').checked}|${JSON.stringify(selectedRange)}`;
  if (!force && key === lastMessagesKey) return;
  lastMessagesKey = key;
  const root = $('chat-messages');
  if (!snapshot.total) return;
  const oldScroll = root.scrollTop;
  const messages = snapshot.messages;
  const fragment = document.createDocumentFragment();
  for (const message of messages) {
    const row = document.createElement('div');
    row.className = `message${message.reaction ? ' reaction' : ''}`;
    row.append(textNode('time', '', time(message.offset)));
    const body = document.createElement('div');
    const author = textNode('span', 'message-user', message.user);
    const colors = ['#9bbde3', '#c2a5db', '#d3b087', '#87c4b5', '#b6c78b', '#cfa2b0', '#91bccc'];
    const hash = [...message.user].reduce((n, c) => (n * 31 + c.codePointAt(0)) >>> 0, 0);
    author.style.color = colors[hash % colors.length];
    body.append(author);
    body.append(textNode('span', 'message-text', message.text));
    row.title = message.reaction ? 'Reação de riso ou entusiasmo' : '';
    row.append(body);
    fragment.append(row);
  }
  if (!messages.length) fragment.append(textNode('div', 'empty-state', 'Sem mensagens para estes filtros.'));
  root.replaceChildren(fragment);
  root.scrollTop = $('autoscroll').checked ? root.scrollHeight : oldScroll;
  const filtered = selectedRange || $('search').value.trim() || $('only-reactions').checked;
  const count = snapshot.matched ?? snapshot.total;
  $('visible-count').textContent = messages.length < count
    ? `Últimas ${formatNumber(messages.length)} de ${formatNumber(count)} ${filtered ? 'resultados' : 'mensagens'}`
    : `${formatNumber(count)} ${filtered ? 'resultados' : 'mensagens'}`;
}
function selectMoment(highlight, index) {
  if (snapshot?.provider === 'youtube') {
    selectedRange = {start:highlight.start,end:highlight.end};
    selectedYouTubeMoment = highlight;
    renderYouTubeSelection();
    markSelectedMoment();
    return;
  }
  if (!selectedRange) previousAutoFollow = $('autoscroll').checked;
  selectedRange = {start:highlight.start, end:highlight.end};
  $('autoscroll').checked = false;
  $('search').value = '';
  $('only-reactions').checked = false;
  $('moment-label').textContent = `Momento ${String(index + 1).padStart(2, '0')} · ${time(highlight.start)} — ${time(highlight.end)}`;
  $('moment-view').classList.remove('hidden');
  $('chat-messages').scrollTop = 0;
  markSelectedMoment();
  poll();
}
function renderYouTubeSelection() {
  $('youtube-moment').classList.toggle('hidden', !selectedYouTubeMoment);
  if (!selectedYouTubeMoment) return;
  $('youtube-moment-range').textContent = `${time(selectedYouTubeMoment.start)} — ${time(selectedYouTubeMoment.end)}`;
  $('youtube-moment-reason').textContent = `${selectedYouTubeMoment.reason} · pico em ${time(selectedYouTubeMoment.peak)} · ${Math.round(selectedYouTubeMoment.end-selectedYouTubeMoment.start)} s`;
}
function renderYouTube(data) {
  const analysis = data.youtube;
  const points = analysis?.heatmap || [];
  const moments = data.moments || [];
  $('youtube-pill').textContent = $('chat-pill').textContent;
  $('youtube-pill').className = $('chat-pill').className;
  $('users').textContent = formatNumber(points.length);
  $('reactions').textContent = points.length ? Math.max(...points.map(point=>point.value)).toFixed(2) : '—';
  $('highlight-count').textContent = formatNumber(moments.length);
  $('youtube-description').textContent = !analysis ? data.detail : analysis.availability === 'unavailable'
    ? 'O vídeo foi consultado, mas o YouTube não disponibilizou um heatmap público.'
    : 'Usa os picos de repetição para escolher intervalos a rever no vídeo original.';
  $('youtube-timeline-section').classList.toggle('hidden', !points.length);
  const empty = analysis && !moments.length;
  $('youtube-empty').classList.toggle('hidden', !empty);
  $('youtube-empty').textContent = analysis?.availability === 'unavailable'
    ? 'Sem heatmap disponível. O vídeo pode ser demasiado recente, ter poucas visualizações ou não ser elegível. Não existe um prazo público garantido. Podes voltar a analisar mais tarde.'
    : 'Sem picos distintos no intervalo escolhido. Podes selecionar um segmento da timeline ou analisar um intervalo maior.';
  const key = JSON.stringify(['youtube',data.source?.url,data.status,analysis]);
  if (key !== lastAnalysisKey) {
    lastAnalysisKey = key;
    const bars = points.map(point=>{
      const bar = document.createElement('button');
      bar.type = 'button'; bar.className = 'youtube-bin';
      bar.style.height = `${Math.max(2,point.value*100)}%`;
      bar.title = `${time(point.start_time)} — ${time(point.end_time)} · intensidade ${point.value.toFixed(2)}/1`;
      bar.setAttribute('aria-label',bar.title);
      bar.addEventListener('click',()=>{
        const peak = (point.start_time+point.end_time)/2;
        const profile=data.clipProfile || {duration:30,beforePeak:20};
        const length=Math.min(profile.duration,data.source.end-data.source.start);
        const start=Math.max(data.source.start,Math.min(peak-profile.beforePeak,data.source.end-length));
        selectMoment({start,end:start+length,peak,
          strength:point.value,signal:'youtube_heatmap',reason:`Segmento selecionado · intensidade relativa ${point.value.toFixed(2)}/1`},0);
      });
      return bar;
    });
    $('youtube-timeline').replaceChildren(...bars);
    $('chart').replaceChildren(...points.map(point=>{
      const bar = document.createElement('div'); bar.className = 'chart-bar youtube';
      bar.style.height = `${Math.max(2,point.value*100)}%`;
      bar.title = `${time(point.start_time)} · intensidade ${point.value.toFixed(2)}/1`;
      return bar;
    }));
    if (!points.length) $('chart').append(textNode('div','chart-empty',analysis ? 'Sem heatmap' : 'A consultar…'));
    $('chart-start').textContent = $('youtube-start').textContent = time(data.source?.start);
    $('chart-end').textContent = $('youtube-end').textContent = time(data.source?.end);
    $('chart-caption').textContent = 'Repetição relativa';
    $('highlights').replaceChildren(...moments.map((moment,index)=>{
      const card = document.createElement('button'); card.className = 'highlight'; card.type = 'button';
      card.dataset.start = moment.start; card.dataset.end = moment.end;
      const content = document.createElement('span'); content.className = 'highlight-content';
      content.append(textNode('time','',`${time(moment.start)} — ${time(moment.end)}`),textNode('span','highlight-summary',moment.reason));
      card.append(textNode('span','highlight-index',String(index+1).padStart(2,'0')),content,textNode('span','highlight-arrow','›'));
      card.addEventListener('click',()=>selectMoment(moment,index));
      return card;
    }));
    if (!moments.length) $('highlights').append(textNode('div','highlight-empty',analysis ? 'Sem candidatos para este vídeo ou intervalo.' : 'A consultar o YouTube…'));
    if (!selectedYouTubeMoment && moments.length) selectMoment(moments[0],0);
  }
  renderYouTubeSelection();
  markSelectedMoment();
}
function markSelectedMoment() {
  for (const button of $('highlights').querySelectorAll('.highlight')) {
    button.setAttribute('aria-pressed', String(!!selectedRange && Number(button.dataset.start) === selectedRange.start && Number(button.dataset.end) === selectedRange.end));
  }
}
function renderAnalysis(analysis) {
  const moments=snapshot.moments ?? analysis.highlights;
  $('users').textContent = formatNumber(analysis.users);
  $('reactions').textContent = formatNumber(analysis.reactions);
  $('highlight-count').textContent = formatNumber(moments.length);
  const analysisKey = `${snapshot.total}|${JSON.stringify(moments)}`;
  if (analysisKey === lastAnalysisKey) return;
  lastAnalysisKey = analysisKey;
  if (analysis.bins.length) {
    const max = Math.max(1, ...analysis.bins.map(b => b.messages));
    const bars = analysis.bins.map(bin => {
      const bar = document.createElement('div');
      bar.className = 'chart-bar';
      bar.style.height = `${Math.max(2, bin.messages / max * 100)}%`;
      bar.title = `${time(bin.start)} · ${bin.messages} mensagens · ${bin.reactions} reações`;
      const reactions = document.createElement('div');
      reactions.className = 'chart-bar-reaction';
      reactions.style.height = `${bin.messages ? bin.reactions / bin.messages * 100 : 0}%`;
      bar.append(reactions);
      return bar;
    });
    $('chart').replaceChildren(...bars);
    $('chart-start').textContent = time(analysis.bins[0].start);
    $('chart-end').textContent = time(snapshot.position);
    $('chart-caption').textContent = analysis.bins.length > 1 ? `Janelas de ${Math.round(analysis.bins[1].start - analysis.bins[0].start)}s` : 'Janela de 10 segundos';
  } else {
    $('chart').replaceChildren(textNode('div','chart-empty','Sem dados'));
  }
  if (moments.length) {
    $('highlights').replaceChildren(...moments.map((highlight, index) => {
      const card = document.createElement('button'); card.className = 'highlight';
      card.type = 'button';
      card.dataset.start = highlight.start;
      card.dataset.end = highlight.end;
      card.title = `Abrir mensagens entre ${time(highlight.start)} e ${time(highlight.end)}`;
      const content = document.createElement('span'); content.className = 'highlight-content';
      content.append(textNode('time', '', `${time(highlight.start)} — ${time(highlight.end)}`), textNode('span', 'highlight-summary', highlight.reason || `${formatNumber(highlight.reactions)} reações · ${formatNumber(highlight.users)} participantes`));
      card.append(textNode('span', 'highlight-index', String(index + 1).padStart(2, '0')), content, textNode('span', 'highlight-arrow', '›'));
      card.addEventListener('click', () => selectMoment(highlight, index));
      return card;
    }));
  } else $('highlights').replaceChildren(textNode('div','highlight-empty','Sem momentos para esta sessão.'));
  markSelectedMoment();
}
function render(data) {
  const oldSource = snapshot?.source?.url;
  if (oldSource !== data.source?.url || snapshot?.provider !== data.provider) {
    selectedRange = null;
    selectedYouTubeMoment = null;
  }
  snapshot = data;
  const isYouTube = data.provider === 'youtube';
  $('twitch-panel').classList.toggle('hidden',isYouTube);
  $('youtube-panel').classList.toggle('hidden',!isYouTube);
  $('users-label').textContent = isYouTube ? 'segmentos' : 'participantes';
  $('reactions-label').textContent = isYouTube ? 'pico · 0–1' : 'reações';
  $('activity-title').textContent = isYouTube ? 'Repetição' : 'Atividade';
  $('chart-legend').classList.toggle('hidden',isYouTube);
  document.querySelector('.heuristic').textContent = isYouTube ? 'por repetição' : 'por atividade';
  document.querySelector('.analysis-hint').textContent = isYouTube ? 'Seleciona um momento para rever no vídeo original.' : 'Seleciona um intervalo para ver as mensagens.';
  document.querySelector('.analysis-footnote').textContent = isYouTube ? 'Sinal público de repetição. Um pico precisa de revisão no vídeo.' : 'Deteção pelo chat. O conteúdo do vídeo precisa de revisão.';
  $('export-note').textContent = isYouTube ? 'Exporta metadados, heatmap e candidatos da sessão' : 'Sessão em memória · exporta antes de fechar';
  const active = ['connecting', 'live', 'downloading', 'stopping'].includes(data.status);
  $('start').classList.toggle('hidden', active);
  $('stop').classList.toggle('hidden', !active);
  $('stop').disabled = data.status === 'stopping';
  for (const id of ['url', 'range-start', 'range-end', 'example-live', 'example-vod','example-youtube','clip-duration','clip-before','clip-count']) $(id).disabled = active;
  $('notice').className = `notice ${data.status}`;
  $('notice-text').textContent = data.detail || 'Sem sessão. Introduz um URL para começar.';
  const statusLabels = {connecting:'A LIGAR', live:'AO VIVO', downloading:'A EXTRAIR', stopped:'PARADO', complete:'CONCLUÍDO', error:'ERRO', stopping:'A PARAR'};
  $('chat-pill').textContent = statusLabels[data.status] || 'PRONTO';
  $('chat-pill').className = `pill ${data.status}`;
  $('total').textContent = formatNumber(data.total);
  $('session-duration').textContent = data.total || active ? `${time(data.elapsed)} de captura` : '';
  $('export-csv').disabled = $('export-json').disabled = !(data.canExport ?? data.total>0);
  if (data.source) {
    $('source-meta').classList.remove('hidden');
    $('source-name').textContent = data.source.channel;
    $('source-title').textContent = data.source.title;
    $('source-title').title = data.source.title;
    $('source-type').textContent = data.source.kind.toUpperCase();
    $('mode-label').textContent = isYouTube ? 'YouTube · tempo no vídeo' : data.source.kind === 'live' ? 'Ao vivo · tempo desde a captura' : 'Replay · tempo no VOD';
    $('source-clock').textContent = data.source.kind === 'live' ? `Desde o início da captura · ${time(data.elapsed)}` : `${time(data.position)} / ${time(data.source.end ?? data.source.duration)}`;
    if (oldSource && oldSource !== data.source.url) {selectedRange = null; selectedYouTubeMoment = null;}
  } else {
    $('source-meta').classList.add('hidden');
    $('mode-label').textContent = isYouTube ? 'YouTube · sinais públicos' : 'Canal, VOD ou clip';
  }
  if (isYouTube) {renderYouTube(data); return;}
  renderMessages();
  renderAnalysis(data.analysis);
}
async function poll() {
  const revision = ++requestRevision;
  try {
    const data = await invoke('get_snapshot', {query:$('search').value, reactionsOnly:$('only-reactions').checked, start:selectedRange?.start ?? null, end:selectedRange?.end ?? null});
    if (revision === requestRevision) render(data);
  } catch (error) {
    if (revision === requestRevision) $('notice-text').textContent = `Não foi possível obter a sessão: ${String(error)}`;
  }
}
$('capture-form').addEventListener('submit', async event => {
  event.preventDefault();
  const clipProfile={duration:Number($('clip-duration').value),beforePeak:Number($('clip-before').value),maxMoments:Number($('clip-count').value)};
  if (!Number.isFinite(clipProfile.duration) || clipProfile.duration<5 || clipProfile.duration>180 ||
      !Number.isFinite(clipProfile.beforePeak) || clipProfile.beforePeak<0 || clipProfile.beforePeak>clipProfile.duration ||
      !Number.isInteger(clipProfile.maxMoments) || clipProfile.maxMoments<1 || clipProfile.maxMoments>30) {
    toast('Define uma duração entre 5 e 180 s, contexto até à duração do clip e entre 1 e 30 candidatos.');
    return;
  }
  $('start').disabled = true;
  try {
    await invoke('start_capture', { url: $('url').value, start: $('range-start').value || null, end: $('range-end').value || null, clipProfile });
    selectedRange = null;
    selectedYouTubeMoment = null;
    lastMessagesKey = '';
    lastAnalysisKey = '';
    $('moment-view').classList.add('hidden');
    $('search').value = '';
    $('only-reactions').checked = false;
    // Clear the previous session immediately, including empty/error cases.
    $('chat-messages').replaceChildren(textNode('div', 'empty-state', 'A aguardar mensagens da Twitch…'));
    $('visible-count').textContent = '0 mensagens na pré-visualização';
    $('highlights').replaceChildren(textNode('div', 'highlight-empty', 'A aguardar sinais suficientes no chat.'));
    $('chart').replaceChildren(textNode('div', 'chart-empty', 'A aguardar atividade…'));
    $('source-meta').classList.add('hidden');
    $('chart-start').textContent = $('chart-end').textContent = '00:00';
    $('chart-caption').textContent = '10s / janela';
    await poll();
  } catch (error) { toast(String(error)); }
  finally { $('start').disabled = false; }
});
$('stop').addEventListener('click', async () => { try { await invoke('stop_capture'); await poll(); } catch (error) { toast(String(error)); } });
$('search').addEventListener('input', poll);
$('only-reactions').addEventListener('change', poll);
$('clear-moment').addEventListener('click', () => {
  selectedRange = null;
  $('autoscroll').checked = previousAutoFollow;
  $('moment-view').classList.add('hidden');
  markSelectedMoment();
  poll();
});
$('example-live').addEventListener('click', () => { $('url').value = 'https://www.twitch.tv/twitchplayspokemon'; $('range-start').value = ''; $('range-end').value = ''; $('url').focus(); });
$('url').addEventListener('input',updateStartLabel);
for (const id of ['clip-duration','clip-before','clip-count']) $(id).addEventListener('input',()=>{
  $('clip-profile-summary').textContent=`Perfil do clip · ${$('clip-duration').value || '—'} s`;
});
$('example-live').addEventListener('click',updateStartLabel);
$('example-youtube').addEventListener('click',()=>{
  $('url').value = 'https://www.youtube.com/watch?v=YE7VzlLtp-4';
  $('range-start').value = ''; $('range-end').value = ''; updateStartLabel(); $('url').focus();
});
$('open-youtube').addEventListener('click',async()=>{
  if (!selectedYouTubeMoment) return;
  try {await invoke('open_youtube_moment',{start:selectedYouTubeMoment.start});}
  catch(error) {toast(String(error));}
});
$('example-vod').addEventListener('click', async () => {
  $('example-vod').disabled = true;
  try {
    const example = await invoke('get_example_vod');
    // Do not change the form if a capture started while this lookup was pending.
    if (['connecting', 'live', 'downloading', 'stopping'].includes(snapshot?.status)) return;
    $('url').value = example.url;
    updateStartLabel();
    $('range-start').value = time(example.start);
    $('range-end').value = time(example.end);
    $('url').focus();
  } catch (error) { toast(String(error)); }
  finally { $('example-vod').disabled = ['connecting', 'live', 'downloading', 'stopping'].includes(snapshot?.status); }
});
for (const format of ['json', 'csv']) $(`export-${format}`).addEventListener('click', async () => {
  const button = $(`export-${format}`); button.disabled = true;
  try { const path = await invoke('export_chat', { format }); if (path) toast(`Exportado: ${path}`); }
  catch (error) { toast(String(error)); }
  finally { button.disabled = !(snapshot?.canExport ?? snapshot?.total>0); }
});
document.addEventListener('keydown', event => {
  if (event.ctrlKey && event.key === 'Enter' && !$('start').classList.contains('hidden')) {
    event.preventDefault();
    $('capture-form').requestSubmit();
  }
});
poll();
setInterval(poll, 1000);

