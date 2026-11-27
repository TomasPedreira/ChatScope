import {
  $,
  formatNumber,
  formatMediaTime,
  createTextElement,
  showToast,
} from "./dom_helpers.js";
import { invokeTauriCommand } from "./tauri_client.js";
import { createClipProductionView } from "./clip_production_view.js";

let sessionSnapshot = null;
let lastRenderedMessageSignature = "";
let lastRenderedAnalysisSignature = "";
let selectedClipTimeRange = null;
let wasChatAutoScrollEnabled = true;
let latestSnapshotRequestId = 0;
let selectedVideoCandidate = null;
function isYouTubeUrlInput() {
  try {
    return [
      "youtube.com",
      "www.youtube.com",
      "m.youtube.com",
      "youtu.be",
      "www.youtu.be",
    ].includes(new URL($("url").value.trim()).hostname);
  } catch {
    return false;
  }
}
function updateStartLabel() {
  let isKickUrl = false;
  try {
    isKickUrl = ["kick.com", "www.kick.com"].includes(
      new URL($("url").value).hostname,
    );
  } catch {}
  $("start").textContent = isKickUrl
    ? "Analisar Kick"
    : isYouTubeUrlInput()
      ? "Analisar YouTube"
      : $("url").value.startsWith("file:")
        ? "Analisar vídeo"
        : "Capturar";
}
function renderChatMessages(force = false) {
  if (!sessionSnapshot) return;
  const key = `${sessionSnapshot.total}|${sessionSnapshot.matched}|${sessionSnapshot.messages[0]?.id}|${sessionSnapshot.messages.at(-1)?.id}|${$("search").value}|${$("only-reactions").checked}|${JSON.stringify(selectedClipTimeRange)}`;
  if (!force && key === lastRenderedMessageSignature) return;
  lastRenderedMessageSignature = key;
  const root = $("chat-messages");
  if (!sessionSnapshot.total) return;
  const oldScroll = root.scrollTop;
  const messages = sessionSnapshot.messages;
  const fragment = document.createDocumentFragment();
  for (const message of messages) {
    const row = document.createElement("div");
    row.className = `message${message.reaction ? " reaction" : ""}`;
    row.append(createTextElement("time", "", formatMediaTime(message.offset)));
    const body = document.createElement("div");
    const author = createTextElement("span", "message-user", message.user);
    const colors = [
      "#9bbde3",
      "#c2a5db",
      "#d3b087",
      "#87c4b5",
      "#b6c78b",
      "#cfa2b0",
      "#91bccc",
    ];
    const hash = [...message.user].reduce(
      (n, c) => (n * 31 + c.codePointAt(0)) >>> 0,
      0,
    );
    author.style.color = colors[hash % colors.length];
    body.append(author);
    body.append(createTextElement("span", "message-text", message.text));
    row.title = message.reaction ? "Reação de riso ou entusiasmo" : "";
    row.append(body);
    fragment.append(row);
  }
  if (!messages.length)
    fragment.append(
      createTextElement(
        "div",
        "empty-state",
        "Sem mensagens para estes filtros.",
      ),
    );
  root.replaceChildren(fragment);
  root.scrollTop = $("autoscroll").checked ? root.scrollHeight : oldScroll;
  const filtered =
    selectedClipTimeRange ||
    $("search").value.trim() ||
    $("only-reactions").checked;
  const count = sessionSnapshot.matched ?? sessionSnapshot.total;
  $("visible-count").textContent =
    messages.length < count
      ? `Últimas ${formatNumber(messages.length)} de ${formatNumber(count)} ${filtered ? "resultados" : "mensagens"}`
      : `${formatNumber(count)} ${filtered ? "resultados" : "mensagens"}`;
}
function selectClipCandidate(highlight, index) {
  $("render-start").value = String(Number(highlight.start.toFixed(3)));
  $("render-end").value = String(Number(highlight.end.toFixed(3)));
  if (sessionSnapshot?.video || sessionSnapshot?.provider === "youtube") {
    selectedClipTimeRange = { start: highlight.start, end: highlight.end };
    selectedVideoCandidate = highlight;
    renderSelectedVideoCandidate();
    markSelectedClipCandidate();
    return;
  }
  if (!selectedClipTimeRange)
    wasChatAutoScrollEnabled = $("autoscroll").checked;
  selectedClipTimeRange = { start: highlight.start, end: highlight.end };
  $("autoscroll").checked = false;
  $("search").value = "";
  $("only-reactions").checked = false;
  $("moment-label").textContent =
    `Momento ${String(index + 1).padStart(2, "0")} · ${formatMediaTime(highlight.start)} — ${formatMediaTime(highlight.end)}`;
  $("moment-view").classList.remove("hidden");
  $("chat-messages").scrollTop = 0;
  markSelectedClipCandidate();
  refreshAnalysisSession();
}
function renderSelectedVideoCandidate() {
  $("video-moment").classList.toggle("hidden", !selectedVideoCandidate);
  if (!selectedVideoCandidate) return;
  $("video-moment-range").textContent =
    `${formatMediaTime(selectedVideoCandidate.start)} — ${formatMediaTime(selectedVideoCandidate.end)}`;
  $("video-moment-reason").textContent =
    `${selectedVideoCandidate.reason} · pico em ${formatMediaTime(selectedVideoCandidate.peak)} · ${Math.round(selectedVideoCandidate.end - selectedVideoCandidate.start)} s`;
}
function renderVideoAnalysis(data) {
  const analysis = data.video || data.youtube;
  const points = analysis?.points || analysis?.heatmap || [];
  const audio =
    analysis?.signal === "audio_energy" ||
    (!analysis && ["kick", "local"].includes(data.provider));
  $("video-heading").textContent =
    data.provider === "local" ? "Vídeo local" : `Vídeo ${data.provider}`;
  $("video-signal").textContent = audio ? "Energia do áudio" : "Most replayed";
  $("timeline-heading").textContent = audio
    ? "Variação da energia no áudio"
    : "Onde as pessoas voltam a ver";
  $("open-youtube").classList.toggle(
    "hidden",
    data.provider !== "youtube" || analysis?.timeOrigin === "recording",
  );
  $("video-explanation").textContent = audio
    ? "O volume pode destacar música, ruído ou entusiasmo. É uma sugestão heurística: confirma o contexto. Num direto, os tempos referem-se à gravação local."
    : "O heatmap é um sinal relativo de repetição, sem contagens de cliques ou percentagens de espectadores. A disponibilidade depende do vídeo e pode mudar.";
  const moments = data.moments || [];
  $("video-pill").textContent = $("chat-pill").textContent;
  $("video-pill").className = $("chat-pill").className;
  $("users").textContent = formatNumber(points.length);
  $("reactions").textContent = points.length
    ? Math.max(...points.map((point) => point.value)).toFixed(2)
    : "—";
  $("highlight-count").textContent = formatNumber(moments.length);
  $("video-description").textContent = !analysis
    ? data.detail
    : audio && analysis.availability === "unavailable"
      ? "O vídeo não tem áudio utilizável. Podes escolher um corte manual para criar o MP4."
      : analysis.availability === "unavailable"
        ? "O vídeo foi consultado, mas o YouTube não disponibilizou um heatmap público."
        : audio
          ? "Analisa os picos de áudio e revê os intervalos. Podes ajustar o corte e criar um MP4 local."
          : "Usa os picos de repetição para escolher intervalos a rever no vídeo original.";
  $("video-timeline-section").classList.toggle("hidden", !points.length);
  const empty = analysis && !moments.length;
  $("video-empty").classList.toggle("hidden", !empty);
  $("video-empty").textContent = audio
    ? "Sem picos distintos de áudio. Podes definir o início e o fim do corte manualmente."
    : analysis?.availability === "unavailable"
      ? "Sem heatmap disponível. O vídeo pode ser demasiado recente, ter poucas visualizações ou não ser elegível. Não existe um prazo público garantido. Podes voltar a analisar mais tarde."
      : "Sem picos distintos no intervalo escolhido. Podes selecionar um segmento da timeline ou analisar um intervalo maior.";
  const key = JSON.stringify([
    "video",
    data.source?.url,
    data.status,
    analysis,
  ]);
  if (key !== lastRenderedAnalysisSignature) {
    lastRenderedAnalysisSignature = key;
    const bars = points.map((point) => {
      const bar = document.createElement("button");
      bar.type = "button";
      bar.className = "video-bin";
      bar.style.height = `${Math.max(2, point.value * 100)}%`;
      bar.title = `${formatMediaTime(point.start_time)} — ${formatMediaTime(point.end_time)} · intensidade ${point.value.toFixed(2)}/1`;
      bar.setAttribute("aria-label", bar.title);
      bar.addEventListener("click", () => {
        const peak = (point.start_time + point.end_time) / 2;
        const profile = data.clipProfile || { duration: 30, beforePeak: 20 };
        const length = Math.min(
          profile.duration,
          data.source.end - data.source.start,
        );
        const start = Math.max(
          data.source.start,
          Math.min(peak - profile.beforePeak, data.source.end - length),
        );
        selectClipCandidate(
          {
            start,
            end: start + length,
            peak,
            strength: point.value,
            signal: analysis?.signal || "youtube_heatmap",
            reason: `Segmento selecionado · intensidade relativa ${point.value.toFixed(2)}/1`,
          },
          0,
        );
      });
      return bar;
    });
    $("video-timeline").replaceChildren(...bars);
    $("chart").replaceChildren(
      ...points.map((point) => {
        const bar = document.createElement("div");
        bar.className = "chart-bar video";
        bar.style.height = `${Math.max(2, point.value * 100)}%`;
        bar.title = `${formatMediaTime(point.start_time)} · intensidade ${point.value.toFixed(2)}/1`;
        return bar;
      }),
    );
    if (!points.length)
      $("chart").append(
        createTextElement(
          "div",
          "chart-empty",
          analysis ? "Sem heatmap" : "A consultar…",
        ),
      );
    $("chart-start").textContent = $("video-start").textContent =
      formatMediaTime(data.source?.start);
    $("chart-end").textContent = $("video-end").textContent = formatMediaTime(
      data.source?.end,
    );
    $("chart-caption").textContent = audio
      ? "Energia relativa do áudio"
      : "Repetição relativa";
    $("highlights").replaceChildren(
      ...moments.map((moment, index) => {
        const card = document.createElement("button");
        card.className = "highlight";
        card.type = "button";
        card.dataset.start = moment.start;
        card.dataset.end = moment.end;
        const content = document.createElement("span");
        content.className = "highlight-content";
        content.append(
          createTextElement(
            "time",
            "",
            `${formatMediaTime(moment.start)} — ${formatMediaTime(moment.end)}`,
          ),
          createTextElement("span", "highlight-summary", moment.reason),
        );
        card.append(
          createTextElement(
            "span",
            "highlight-index",
            String(index + 1).padStart(2, "0"),
          ),
          content,
          createTextElement("span", "highlight-arrow", "›"),
        );
        card.addEventListener("click", () =>
          selectClipCandidate(moment, index),
        );
        return card;
      }),
    );
    if (!moments.length)
      $("highlights").append(
        createTextElement(
          "div",
          "highlight-empty",
          analysis
            ? "Sem candidatos para este vídeo ou intervalo."
            : "A consultar o YouTube…",
        ),
      );
    if (!selectedVideoCandidate && !isManualCutEdited && moments.length)
      selectClipCandidate(moments[0], 0);
  }
  renderSelectedVideoCandidate();
  markSelectedClipCandidate();
}
function markSelectedClipCandidate() {
  for (const button of $("highlights").querySelectorAll(".highlight")) {
    button.setAttribute(
      "aria-pressed",
      String(
        !!selectedClipTimeRange &&
          Number(button.dataset.start) === selectedClipTimeRange.start &&
          Number(button.dataset.end) === selectedClipTimeRange.end,
      ),
    );
  }
}
function renderChatActivity(analysis) {
  const moments = sessionSnapshot.moments ?? analysis.highlights;
  $("users").textContent = formatNumber(analysis.users);
  $("reactions").textContent = formatNumber(analysis.reactions);
  $("highlight-count").textContent = formatNumber(moments.length);
  const analysisKey = `${sessionSnapshot.total}|${JSON.stringify(moments)}`;
  if (analysisKey === lastRenderedAnalysisSignature) return;
  lastRenderedAnalysisSignature = analysisKey;
  if (analysis.bins.length) {
    const max = Math.max(1, ...analysis.bins.map((b) => b.messages));
    const bars = analysis.bins.map((bin) => {
      const bar = document.createElement("div");
      bar.className = "chart-bar";
      bar.style.height = `${Math.max(2, (bin.messages / max) * 100)}%`;
      bar.title = `${formatMediaTime(bin.start)} · ${bin.messages} mensagens · ${bin.reactions} reações`;
      const reactions = document.createElement("div");
      reactions.className = "chart-bar-reaction";
      reactions.style.height = `${bin.messages ? (bin.reactions / bin.messages) * 100 : 0}%`;
      bar.append(reactions);
      return bar;
    });
    $("chart").replaceChildren(...bars);
    $("chart-start").textContent = formatMediaTime(analysis.bins[0].start);
    $("chart-end").textContent = formatMediaTime(sessionSnapshot.position);
    $("chart-caption").textContent =
      analysis.bins.length > 1
        ? `Janelas de ${Math.round(analysis.bins[1].start - analysis.bins[0].start)}s`
        : "Janela de 10 segundos";
  } else {
    $("chart").replaceChildren(
      createTextElement("div", "chart-empty", "Sem dados"),
    );
  }
  if (moments.length) {
    $("highlights").replaceChildren(
      ...moments.map((highlight, index) => {
        const card = document.createElement("button");
        card.className = "highlight";
        card.type = "button";
        card.dataset.start = highlight.start;
        card.dataset.end = highlight.end;
        card.title = `Abrir mensagens entre ${formatMediaTime(highlight.start)} e ${formatMediaTime(highlight.end)}`;
        const content = document.createElement("span");
        content.className = "highlight-content";
        content.append(
          createTextElement(
            "time",
            "",
            `${formatMediaTime(highlight.start)} — ${formatMediaTime(highlight.end)}`,
          ),
          createTextElement(
            "span",
            "highlight-summary",
            highlight.reason ||
              `${formatNumber(highlight.reactions)} reações · ${formatNumber(highlight.users)} participantes`,
          ),
        );
        card.append(
          createTextElement(
            "span",
            "highlight-index",
            String(index + 1).padStart(2, "0"),
          ),
          content,
          createTextElement("span", "highlight-arrow", "›"),
        );
        card.addEventListener("click", () =>
          selectClipCandidate(highlight, index),
        );
        return card;
      }),
    );
  } else
    $("highlights").replaceChildren(
      createTextElement(
        "div",
        "highlight-empty",
        "Sem momentos para esta sessão.",
      ),
    );
  markSelectedClipCandidate();
}
function renderSessionSnapshot(data) {
  const oldSource = sessionSnapshot?.source?.url;
  if (
    oldSource !== data.source?.url ||
    sessionSnapshot?.provider !== data.provider
  ) {
    selectedClipTimeRange = null;
    selectedVideoCandidate = null;
    isManualCutEdited = false;
    $("render-start").value = $("render-end").value = "";
  }
  sessionSnapshot = data;
  const isVideoAnalysis =
    ["youtube", "kick", "local"].includes(data.provider) || !!data.video;
  const isAudio = data.video?.signal === "audio_energy";
  $("twitch-panel").classList.toggle("hidden", isVideoAnalysis);
  $("video-panel").classList.toggle("hidden", !isVideoAnalysis);
  $("users-label").textContent = isVideoAnalysis
    ? "segmentos"
    : "participantes";
  $("reactions-label").textContent = isVideoAnalysis ? "pico · 0–1" : "reações";
  $("activity-title").textContent = isAudio
    ? "Energia do áudio"
    : isVideoAnalysis
      ? "Repetição"
      : "Atividade";
  $("chart-legend").classList.toggle("hidden", isVideoAnalysis);
  document.querySelector(".heuristic").textContent = isAudio
    ? "por áudio"
    : isVideoAnalysis
      ? "por repetição"
      : "por atividade";
  document.querySelector(".analysis-hint").textContent = isVideoAnalysis
    ? "Seleciona um momento para rever no vídeo original."
    : "Seleciona um intervalo para ver as mensagens.";
  document.querySelector(".analysis-footnote").textContent = isAudio
    ? "Energia do áudio. Música e ruído também podem criar picos: revê o vídeo."
    : isVideoAnalysis
      ? "Sinal público de repetição. Um pico precisa de revisão no vídeo."
      : "Deteção pelo chat. O conteúdo do vídeo precisa de revisão.";
  $("export-note").textContent = isAudio
    ? "Exporta sinais de áudio e candidatos da sessão"
    : isVideoAnalysis
      ? "Exporta metadados, heatmap e candidatos da sessão"
      : "Sessão em memória · exporta antes de fechar";
  $("render-selection").disabled = !data.source || productionView.isRunning();
  $("render-all").disabled =
    !data.moments?.length || productionView.isRunning();
  const active = ["connecting", "live", "downloading", "stopping"].includes(
    data.status,
  );
  $("start").classList.toggle("hidden", active);
  $("stop").classList.toggle("hidden", !active);
  $("stop").disabled = data.status === "stopping";
  for (const id of [
    "url",
    "range-start",
    "range-end",
    "example-live",
    "example-vod",
    "example-youtube",
    "clip-duration",
    "clip-before",
    "clip-count",
    "video-mode",
    "capture-seconds",
    "local-source",
  ])
    $(id).disabled = active;
  $("notice").className = `notice ${data.status}`;
  $("notice-text").textContent =
    data.detail || "Sem sessão. Introduz um URL para começar.";
  const statusLabels = {
    connecting: "A LIGAR",
    live: "AO VIVO",
    downloading: "A EXTRAIR",
    stopped: "PARADO",
    complete: "CONCLUÍDO",
    error: "ERRO",
    stopping: "A PARAR",
  };
  $("chat-pill").textContent = statusLabels[data.status] || "PRONTO";
  $("chat-pill").className = `pill ${data.status}`;
  $("total").textContent = formatNumber(data.total);
  $("session-duration").textContent =
    data.total || active ? `${formatMediaTime(data.elapsed)} de captura` : "";
  $("export-csv").disabled = $("export-json").disabled = !(
    data.canExport ?? data.total > 0
  );
  if (data.source) {
    $("source-meta").classList.remove("hidden");
    $("source-name").textContent = data.source.channel;
    $("source-title").textContent = data.source.title;
    $("source-title").title = data.source.title;
    $("source-type").textContent = data.source.kind.toUpperCase();
    const platform =
      data.provider === "local"
        ? "Ficheiro local"
        : data.provider === "kick"
          ? "Kick"
          : "YouTube";
    $("mode-label").textContent = isVideoAnalysis
      ? `${platform} · ${data.video?.timeOrigin === "recording" ? "tempo na captura" : "tempo no vídeo"}`
      : data.source.kind === "live"
        ? "Ao vivo · tempo desde a captura"
        : "Replay · tempo no VOD";
    $("source-clock").textContent =
      data.source.kind === "live"
        ? `Desde o início da captura · ${formatMediaTime(data.elapsed)}`
        : `${formatMediaTime(data.position)} / ${formatMediaTime(data.source.end ?? data.source.duration)}`;
    if (oldSource && oldSource !== data.source.url) {
      selectedClipTimeRange = null;
      selectedVideoCandidate = null;
    }
  } else {
    $("source-meta").classList.add("hidden");
    $("mode-label").textContent = isVideoAnalysis
      ? "A preparar sinais do vídeo"
      : "Canal, VOD ou clip";
  }
  if (isVideoAnalysis) {
    renderVideoAnalysis(data);
    return;
  }
  renderChatMessages();
  renderChatActivity(data.analysis);
}
async function refreshAnalysisSession() {
  const revision = ++latestSnapshotRequestId;
  try {
    const data = await invokeTauriCommand("get_snapshot", {
      query: $("search").value,
      reactionsOnly: $("only-reactions").checked,
      start: selectedClipTimeRange?.start ?? null,
      end: selectedClipTimeRange?.end ?? null,
    });
    if (revision === latestSnapshotRequestId) renderSessionSnapshot(data);
  } catch (error) {
    if (revision === latestSnapshotRequestId)
      $("notice-text").textContent =
        `Não foi possível obter a sessão: ${String(error)}`;
  }
}
$("capture-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const clipProfile = {
    duration: Number($("clip-duration").value),
    beforePeak: Number($("clip-before").value),
    maxMoments: Number($("clip-count").value),
  };
  if (
    !Number.isFinite(clipProfile.duration) ||
    clipProfile.duration < 5 ||
    clipProfile.duration > 180 ||
    !Number.isFinite(clipProfile.beforePeak) ||
    clipProfile.beforePeak < 0 ||
    clipProfile.beforePeak > clipProfile.duration ||
    !Number.isInteger(clipProfile.maxMoments) ||
    clipProfile.maxMoments < 1 ||
    clipProfile.maxMoments > 30
  ) {
    showToast(
      "Define uma duração entre 5 e 180 s, contexto até à duração do clip e entre 1 e 30 candidatos.",
    );
    return;
  }
  $("start").disabled = true;
  try {
    await invokeTauriCommand("start_capture", {
      url: $("url").value,
      start: $("range-start").value || null,
      end: $("range-end").value || null,
      clipProfile,
      videoMode: $("video-mode").checked,
      captureSeconds: Number($("capture-seconds").value),
    });
    selectedClipTimeRange = null;
    selectedVideoCandidate = null;
    lastRenderedMessageSignature = "";
    lastRenderedAnalysisSignature = "";
    $("moment-view").classList.add("hidden");
    $("search").value = "";
    $("only-reactions").checked = false;
    // Clear the previous session immediately, including empty/error cases.
    $("chat-messages").replaceChildren(
      createTextElement(
        "div",
        "empty-state",
        "A aguardar mensagens da Twitch…",
      ),
    );
    $("visible-count").textContent = "0 mensagens na pré-visualização";
    $("highlights").replaceChildren(
      createTextElement(
        "div",
        "highlight-empty",
        "A aguardar sinais suficientes no chat.",
      ),
    );
    $("chart").replaceChildren(
      createTextElement("div", "chart-empty", "A aguardar atividade…"),
    );
    $("source-meta").classList.add("hidden");
    $("chart-start").textContent = $("chart-end").textContent = "00:00";
    $("chart-caption").textContent = "10s / janela";
    await refreshAnalysisSession();
  } catch (error) {
    showToast(String(error));
  } finally {
    $("start").disabled = false;
  }
});
$("stop").addEventListener("click", async () => {
  try {
    await invokeTauriCommand("stop_capture");
    await refreshAnalysisSession();
  } catch (error) {
    showToast(String(error));
  }
});
$("search").addEventListener("input", refreshAnalysisSession);
$("only-reactions").addEventListener("change", refreshAnalysisSession);
$("clear-moment").addEventListener("click", () => {
  selectedClipTimeRange = null;
  $("autoscroll").checked = wasChatAutoScrollEnabled;
  $("moment-view").classList.add("hidden");
  markSelectedClipCandidate();
  refreshAnalysisSession();
});
$("example-live").addEventListener("click", () => {
  $("url").value = "https://www.twitch.tv/twitchplayspokemon";
  $("range-start").value = "";
  $("range-end").value = "";
  $("url").focus();
});
$("url").addEventListener("input", updateStartLabel);
for (const id of ["clip-duration", "clip-before", "clip-count"])
  $(id).addEventListener("input", () => {
    $("clip-profile-summary").textContent =
      `Perfil do clip · ${$("clip-duration").value || "—"} s`;
  });
$("example-live").addEventListener("click", updateStartLabel);
$("example-youtube").addEventListener("click", () => {
  $("url").value = "https://www.youtube.com/watch?v=YE7VzlLtp-4";
  $("range-start").value = "";
  $("range-end").value = "";
  updateStartLabel();
  $("url").focus();
});
$("open-youtube").addEventListener("click", async () => {
  if (!selectedVideoCandidate) return;
  try {
    await invokeTauriCommand("open_youtube_moment", {
      start: selectedVideoCandidate.start,
    });
  } catch (error) {
    showToast(String(error));
  }
});
$("example-vod").addEventListener("click", async () => {
  $("example-vod").disabled = true;
  try {
    const example = await invokeTauriCommand("get_example_vod");
    // Do not change the form if a capture started while this lookup was pending.
    if (
      ["connecting", "live", "downloading", "stopping"].includes(
        sessionSnapshot?.status,
      )
    )
      return;
    $("url").value = example.url;
    updateStartLabel();
    $("range-start").value = formatMediaTime(example.start);
    $("range-end").value = formatMediaTime(example.end);
    $("url").focus();
  } catch (error) {
    showToast(String(error));
  } finally {
    $("example-vod").disabled = [
      "connecting",
      "live",
      "downloading",
      "stopping",
    ].includes(sessionSnapshot?.status);
  }
});
for (const format of ["json", "csv"])
  $(`export-${format}`).addEventListener("click", async () => {
    const button = $(`export-${format}`);
    button.disabled = true;
    try {
      const path = await invokeTauriCommand("export_chat", { format });
      if (path) showToast(`Exportado: ${path}`);
    } catch (error) {
      showToast(String(error));
    } finally {
      button.disabled = !(
        sessionSnapshot?.canExport ?? sessionSnapshot?.total > 0
      );
    }
  });
document.addEventListener("keydown", (event) => {
  if (
    event.ctrlKey &&
    event.key === "Enter" &&
    !$("start").classList.contains("hidden")
  ) {
    event.preventDefault();
    $("capture-form").requestSubmit();
  }
});

let isManualCutEdited = false;
for (const id of ["render-start", "render-end"])
  $(id).addEventListener("input", () => {
    isManualCutEdited = true;
  });
$("local-source").addEventListener("click", async () => {
  try {
    const url = await invokeTauriCommand("pick_media_source");
    if (url) {
      $("url").value = url;
      updateStartLabel();
      $("range-start").value = "";
      $("range-end").value = "";
    }
  } catch (error) {
    showToast(String(error));
  }
});

const productionView = createClipProductionView(() => sessionSnapshot);
refreshAnalysisSession();
setInterval(refreshAnalysisSession, 1000);
