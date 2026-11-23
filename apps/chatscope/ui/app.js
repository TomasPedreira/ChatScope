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
function markSelectedMoment() {
  for (const button of $('highlights').querySelectorAll('.highlight')) {
    button.setAttribute('aria-pressed', String(!!selectedRange && Number(button.dataset.start) === selectedRange.start && Number(button.dataset.end) === selectedRange.end));
  }
}
function renderAnalysis(analysis) {
  $('users').textContent = formatNumber(analysis.users);
  $('reactions').textContent = formatNumber(analysis.reactions);
  $('highlight-count').textContent = formatNumber(analysis.highlights.length);
  const analysisKey = `${snapshot.total}|${JSON.stringify(analysis.highlights)}`;
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
  }
  if (analysis.highlights.length) {
    $('highlights').replaceChildren(...analysis.highlights.map((highlight, index) => {
      const card = document.createElement('button'); card.className = 'highlight';
      card.type = 'button';
      card.dataset.start = highlight.start;
      card.dataset.end = highlight.end;
      card.title = `Abrir mensagens entre ${time(highlight.start)} e ${time(highlight.end)}`;
      const content = document.createElement('span'); content.className = 'highlight-content';
      content.append(textNode('time', '', `${time(highlight.start)} — ${time(highlight.end)}`), textNode('span', 'highlight-summary', `${formatNumber(highlight.reactions)} reações · ${formatNumber(highlight.users)} participantes`));
      card.append(textNode('span', 'highlight-index', String(index + 1).padStart(2, '0')), content, textNode('span', 'highlight-arrow', '›'));
      card.addEventListener('click', () => selectMoment(highlight, index));
      return card;
    }));
  }
  markSelectedMoment();
}
function render(data) {
  const oldSource = snapshot?.source?.url;
  snapshot = data;
  const active = ['connecting', 'live', 'downloading', 'stopping'].includes(data.status);
  $('start').classList.toggle('hidden', active);
  $('stop').classList.toggle('hidden', !active);
  $('stop').disabled = data.status === 'stopping';
  for (const id of ['url', 'range-start', 'range-end', 'example-live', 'example-vod']) $(id).disabled = active;
  $('notice').className = `notice ${data.status}`;
  $('notice-text').textContent = data.detail || 'Sem sessão. Introduz um URL para começar.';
  const statusLabels = {connecting:'A LIGAR', live:'AO VIVO', downloading:'A EXTRAIR', stopped:'PARADO', complete:'CONCLUÍDO', error:'ERRO', stopping:'A PARAR'};
  $('chat-pill').textContent = statusLabels[data.status] || 'PRONTO';
  $('chat-pill').className = `pill ${data.status}`;
  $('total').textContent = formatNumber(data.total);
  $('session-duration').textContent = data.total || active ? `${time(data.elapsed)} de captura` : '';
  $('export-csv').disabled = $('export-json').disabled = !data.total;
  if (data.source) {
    $('source-meta').classList.remove('hidden');
    $('source-name').textContent = data.source.channel;
    $('source-title').textContent = data.source.title;
    $('source-title').title = data.source.title;
    $('source-type').textContent = data.source.kind.toUpperCase();
    $('mode-label').textContent = data.source.kind === 'live' ? 'Ao vivo · tempo desde a captura' : 'Replay · tempo no VOD';
    $('source-clock').textContent = data.source.kind === 'live' ? `Desde o início da captura · ${time(data.elapsed)}` : `${time(data.position)} / ${time(data.source.end ?? data.source.duration)}`;
    if (oldSource && oldSource !== data.source.url) selectedRange = null;
  }
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
  $('start').disabled = true;
  try {
    await invoke('start_capture', { url: $('url').value, start: $('range-start').value || null, end: $('range-end').value || null });
    selectedRange = null;
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
$('example-vod').addEventListener('click', async () => {
  $('example-vod').disabled = true;
  try {
    const example = await invoke('get_example_vod');
    // Do not change the form if a capture started while this lookup was pending.
    if (['connecting', 'live', 'downloading', 'stopping'].includes(snapshot?.status)) return;
    $('url').value = example.url;
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
  finally { button.disabled = !snapshot?.total; }
});
document.addEventListener('keydown', event => {
  if (event.ctrlKey && event.key === 'Enter' && !$('start').classList.contains('hidden')) {
    event.preventDefault();
    $('capture-form').requestSubmit();
  }
});
poll();
setInterval(poll, 1000);

