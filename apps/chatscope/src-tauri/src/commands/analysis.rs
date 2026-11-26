use crate::{
    analysis_session::{AnalysisSession, SessionSnapshot, SharedAnalysisSession},
    clip_profiles, source_links, source_providers, twitch_chat,
};
use std::{sync::atomic::Ordering, time::Instant};
use tauri::State;
use twitch_chat::Update;
#[tauri::command]
pub(crate) fn get_source_capabilities() -> Vec<source_providers::Capabilities> {
    source_providers::ProviderRegistry::default().capabilities()
}

#[tauri::command]
pub(crate) async fn get_example_vod() -> Result<serde_json::Value, String> {
    twitch_chat::example_vod().await
}

#[tauri::command]
pub(crate) fn start_capture(
    url: String,
    start: Option<String>,
    end: Option<String>,
    clip_profile: Option<clip_profiles::ClipProfile>,
    video_mode: Option<bool>,
    capture_seconds: Option<u32>,
    state: State<'_, SharedAnalysisSession>,
) -> Result<(), String> {
    let input = source_providers::parse_source_input(&url)?;
    let clip_profile = clip_profile.unwrap_or_default();
    clip_profile.validate()?;
    let capture_seconds = capture_seconds.unwrap_or(120);
    if !(30..=600).contains(&capture_seconds) {
        return Err("A captura de um direto deve durar entre 30 e 600 segundos.".into());
    }
    let options = source_providers::CaptureOptions {
        video_mode: video_mode.unwrap_or(false),
        capture_seconds,
    };
    let parse_optional = |s: Option<String>| {
        s.filter(|s| !s.trim().is_empty())
            .map(|s| twitch_chat::parse_time(&s))
            .transpose()
    };
    let start = parse_optional(start)?;
    let end = parse_optional(end)?;
    if end.is_some_and(|end| end <= start.unwrap_or(0.0)) {
        return Err("O fim tem de ser posterior ao início.".into());
    }
    let shared = state.inner().clone();
    let (generation, cancel) = {
        let mut session = shared.lock().map_err(|_| "Sessão indisponível.")?;
        if matches!(
            session.status.as_str(),
            "connecting" | "live" | "downloading" | "stopping"
        ) {
            return Err("Para a sessão atual antes de iniciar outra.".into());
        }
        session
            .cancellation_requested
            .store(true, Ordering::Relaxed);
        let generation = session.generation + 1;
        *session = AnalysisSession {
            clip_profile: clip_profile.clone(),
            provider: input.provider().into(),
            generation,
            status: "connecting".into(),
            detail: if input.provider() == "youtube" {
                "A consultar o vídeo e o heatmap no YouTube…"
            } else {
                "A preparar a origem e os sinais disponíveis…"
            }
            .into(),
            started: Some(Instant::now()),
            ..AnalysisSession::default()
        };
        (generation, session.cancellation_requested.clone())
    };
    tauri::async_runtime::spawn(async move {
        let result = async {
            let prepared = source_providers::ProviderRegistry::default()
                .prepare(&input, start, end, &clip_profile, options, cancel.clone())
                .await?;
            let source = match prepared {
                source_providers::PreparedSource::Video(source, analysis) => {
                    if cancel.load(Ordering::Relaxed) {
                        return Ok(());
                    }
                    if let Ok(mut session) = shared.lock() {
                        if session.generation == generation {
                            session.position_seconds = source.end.unwrap_or(0.0);
                            session.source = Some(source);
                            session.video_analysis = Some(analysis);
                        }
                    }
                    return Ok(());
                }
                source_providers::PreparedSource::Chat(source) => source,
            };
            if cancel.load(Ordering::Relaxed) {
                return Ok(());
            }
            let shared_update = shared.clone();
            twitch_chat::capture(source, cancel.clone(), move |update| {
                if let Ok(mut session) = shared_update.lock() {
                    if session.generation != generation {
                        return;
                    }
                    match update {
                        Update::MediaSource(source) => {
                            session.position_seconds = source.start;
                            session.source = Some(source);
                        }
                        Update::Messages(messages, position) => {
                            session.chat_messages.extend(messages);
                            session.position_seconds = position;
                        }
                        Update::Status(status, detail) => {
                            if session.status != "stopping" {
                                session.status = status;
                                session.detail = detail;
                            }
                        }
                    }
                }
            })
            .await
        }
        .await;
        if let Ok(mut session) = shared.lock() {
            if session.generation != generation {
                return;
            }
            session.finished = Some(Instant::now());
            match result {
                _ if cancel.load(Ordering::Relaxed) => {
                    session.status = "stopped".into();
                    session.detail =
                        "Operação parada · os dados já recebidos foram preservados".into();
                }
                Ok(()) => {
                    session.status = if cancel.load(Ordering::Relaxed) {
                        "stopped"
                    } else {
                        "complete"
                    }
                    .into();
                    session.detail = if let Some(analysis) = &session.video_analysis {
                        if analysis.signal == "audio_energy" {
                            if analysis.clip_candidates.is_empty() { "Áudio analisado · sem picos distintos; podes definir um corte manual" }
                            else { "Análise de áudio concluída · momentos prontos para criar MP4 locais" }
                        } else {
                        if analysis.availability == "unavailable" {
                            "Vídeo consultado · o YouTube não disponibilizou um heatmap público"
                        } else if analysis.clip_candidates.is_empty() {
                            "Heatmap recebido · sem picos distintos no intervalo escolhido"
                        } else {
                            "Análise concluída · momentos prontos para rever e exportar"
                        }
                        }
                    } else if session.chat_messages.is_empty() {
                        "Sessão terminada · nenhuma mensagem no intervalo"
                    } else if cancel.load(Ordering::Relaxed) {
                        "Captura parada · mensagens prontas para exportar"
                    } else {
                        "Extração concluída · mensagens prontas para exportar"
                    }
                    .into();
                }
                Err(error) => {
                    session.status = "error".into();
                    session.detail = error;
                }
            }
        }
    });
    Ok(())
}

#[tauri::command]
pub(crate) fn stop_capture(state: State<'_, SharedAnalysisSession>) -> Result<(), String> {
    let mut session = state.lock().map_err(|_| "Sessão indisponível.")?;
    if matches!(
        session.status.as_str(),
        "connecting" | "downloading" | "live"
    ) {
        session
            .cancellation_requested
            .store(true, Ordering::Relaxed);
        session.status = "stopping".into();
        session.detail = "A terminar e preservar os resultados disponíveis…".into();
    }
    Ok(())
}

#[tauri::command]
pub(crate) fn get_snapshot(
    query: Option<String>,
    reactions_only: Option<bool>,
    start: Option<f64>,
    end: Option<f64>,
    state: State<'_, SharedAnalysisSession>,
) -> Result<SessionSnapshot, String> {
    if start.is_some_and(|s| !s.is_finite() || s < 0.0)
        || end.is_some_and(|e| !e.is_finite() || e <= start.unwrap_or(0.0))
    {
        return Err("Intervalo de consulta inválido.".into());
    }
    let mut session = state.lock().map_err(|_| "Sessão indisponível.")?;
    if session.chat_messages.len() != session.analyzed_message_count {
        session.chat_analysis = twitch_chat::analyze_signals(&session.chat_messages);
        session.analyzed_message_count = session.chat_messages.len();
    }
    let query = query.unwrap_or_default().trim().to_lowercase();
    let filtered: Vec<_> = session
        .chat_messages
        .iter()
        .filter(|message| {
            start.is_none_or(|s| message.offset >= s)
                && end.is_none_or(|e| message.offset < e)
                && (!reactions_only.unwrap_or(false) || message.reaction)
                && (query.is_empty()
                    || message.user.to_lowercase().contains(&query)
                    || message.text.to_lowercase().contains(&query))
        })
        .collect();
    Ok(SessionSnapshot {
        clip_profile: session.clip_profile.clone(),
        provider: session.provider.clone(),
        legacy_youtube_analysis: if session.provider == "youtube" {
            session.video_analysis.clone()
        } else {
            None
        },
        video_analysis: session.video_analysis.clone(),
        clip_candidates: session.clip_candidates(),
        can_export: session.video_analysis.is_some() || !session.chat_messages.is_empty(),
        source: session.source.clone(),
        status: session.status.clone(),
        detail: session.detail.clone(),
        total: session.chat_messages.len(),
        matched: filtered.len(),
        position_seconds: session.position_seconds,
        elapsed: session
            .started
            .map(|t| {
                session
                    .finished
                    .unwrap_or_else(Instant::now)
                    .duration_since(t)
                    .as_secs_f64()
            })
            .unwrap_or(0.0),
        chat_messages: filtered
            .into_iter()
            .rev()
            .take(400)
            .cloned()
            .collect::<Vec<_>>()
            .into_iter()
            .rev()
            .collect(),
        chat_analysis: session.chat_analysis.clone(),
    })
}

#[tauri::command]
pub(crate) fn open_youtube_moment(
    start: f64,
    state: State<'_, SharedAnalysisSession>,
) -> Result<(), String> {
    let session = state.lock().map_err(|_| "Sessão indisponível.")?;
    let source = session
        .source
        .as_ref()
        .filter(|source| source.kind == "youtube")
        .ok_or("Seleciona um vídeo YouTube.")?;
    if !start.is_finite() || start < source.start || start >= source.end.unwrap_or(0.0) {
        return Err("O momento está fora do intervalo analisado.".into());
    }
    let url = source_links::youtube_timestamp_url(&source.id, start);
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        let launcher = std::env::var_os("SystemRoot")
            .map(std::path::PathBuf::from)
            .ok_or("Não foi possível localizar o navegador do Windows.")?
            .join("System32/rundll32.exe");
        std::process::Command::new(launcher)
            .args(["url.dll,FileProtocolHandler", &url])
            .creation_flags(0x08000000)
            .spawn()
            .map_err(|_| "Não foi possível abrir o navegador.")?;
    }
    #[cfg(not(windows))]
    return Err(format!("Abre no navegador: {url}"));
    #[cfg(windows)]
    Ok(())
}

#[tauri::command]
pub(crate) async fn pick_media_source() -> Result<Option<String>, String> {
    let selected = rfd::AsyncFileDialog::new()
        .set_title("Analisar vídeo local")
        .add_filter("Vídeo", &["mp4", "mkv", "mov", "webm", "m4v", "avi"])
        .pick_file()
        .await;
    selected
        .map(|file| {
            url::Url::from_file_path(file.path())
                .map(|url| url.to_string())
                .map_err(|_| "Ficheiro inválido.".into())
        })
        .transpose()
}
