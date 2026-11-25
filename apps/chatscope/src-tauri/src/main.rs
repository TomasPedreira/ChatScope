#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]
mod chat;
mod clips;
mod detectors;
mod providers;
use detectors::MomentDetector;
mod media;
mod scope;
mod youtube;

use chat::{ChatMessage, Source, Update};
use serde::Serialize;
use std::{
    sync::{
        Arc, Mutex,
        atomic::{AtomicBool, Ordering},
    },
    time::Instant,
};
use tauri::{Manager, State};

#[derive(Default)]
struct Session {
    clip_profile: clips::ClipProfile,
    provider: String,
    youtube: Option<youtube::Analysis>,
    video: Option<scope::VideoAnalysis>,
    generation: u64,
    source: Option<Source>,
    messages: Vec<ChatMessage>,
    status: String,
    detail: String,
    position: f64,
    cancel: Arc<AtomicBool>,
    started: Option<Instant>,
    finished: Option<Instant>,
    analysis: chat::Analysis,
    analyzed_count: usize,
}

impl Session {
    fn moments(&self) -> Vec<scope::Moment> {
        if let Some(analysis) = &self.video {
            return analysis.moments.clone();
        }
        let Some(source) = &self.source else {
            return vec![];
        };
        let bounds = clips::TimeRange {
            start: source.start,
            end: source
                .end
                .or(source.duration)
                .unwrap_or(self.position)
                .max(source.start),
        };
        let analysis = if self.analyzed_count == self.messages.len() {
            self.analysis.clone()
        } else {
            chat::analyze_signals(&self.messages)
        };
        detectors::ChatActivityDetector.detect(&analysis, bounds, &self.clip_profile)
    }
}

type Shared = Arc<Mutex<Session>>;

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct Snapshot {
    clip_profile: clips::ClipProfile,
    provider: String,
    youtube: Option<youtube::Analysis>,
    video: Option<scope::VideoAnalysis>,
    moments: Vec<scope::Moment>,
    can_export: bool,
    source: Option<Source>,
    status: String,
    detail: String,
    total: usize,
    matched: usize,
    position: f64,
    elapsed: f64,
    messages: Vec<ChatMessage>,
    analysis: chat::Analysis,
}

#[tauri::command]
fn get_source_capabilities() -> Vec<providers::Capabilities> {
    providers::ProviderRegistry::default().capabilities()
}

#[tauri::command]
async fn get_example_vod() -> Result<serde_json::Value, String> {
    chat::example_vod().await
}

#[tauri::command]
fn start_capture(
    url: String,
    start: Option<String>,
    end: Option<String>,
    clip_profile: Option<clips::ClipProfile>,
    video_mode: Option<bool>,
    capture_seconds: Option<u32>,
    state: State<'_, Shared>,
) -> Result<(), String> {
    let input = scope::parse_input(&url)?;
    let clip_profile = clip_profile.unwrap_or_default();
    clip_profile.validate()?;
    let capture_seconds = capture_seconds.unwrap_or(120);
    if !(30..=600).contains(&capture_seconds) {
        return Err("A captura de um direto deve durar entre 30 e 600 segundos.".into());
    }
    let options = providers::CaptureOptions {
        video_mode: video_mode.unwrap_or(false),
        capture_seconds,
    };
    let parse_optional = |s: Option<String>| {
        s.filter(|s| !s.trim().is_empty())
            .map(|s| chat::parse_time(&s))
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
        session.cancel.store(true, Ordering::Relaxed);
        let generation = session.generation + 1;
        *session = Session {
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
            ..Session::default()
        };
        (generation, session.cancel.clone())
    };
    tauri::async_runtime::spawn(async move {
        let result = async {
            let prepared = providers::ProviderRegistry::default()
                .prepare(&input, start, end, &clip_profile, options, cancel.clone())
                .await?;
            let source = match prepared {
                providers::PreparedSource::Video(source, analysis) => {
                    if cancel.load(Ordering::Relaxed) {
                        return Ok(());
                    }
                    if let Ok(mut session) = shared.lock() {
                        if session.generation == generation {
                            session.position = source.end.unwrap_or(0.0);
                            session.source = Some(source);
                            if input.provider() == "youtube" {
                                session.youtube = Some(analysis.clone());
                            }
                            session.video = Some(analysis);
                        }
                    }
                    return Ok(());
                }
                providers::PreparedSource::Chat(source) => source,
            };
            if cancel.load(Ordering::Relaxed) {
                return Ok(());
            }
            let shared_update = shared.clone();
            chat::capture(source, cancel.clone(), move |update| {
                if let Ok(mut session) = shared_update.lock() {
                    if session.generation != generation {
                        return;
                    }
                    match update {
                        Update::Source(source) => {
                            session.position = source.start;
                            session.source = Some(source);
                        }
                        Update::Messages(messages, position) => {
                            session.messages.extend(messages);
                            session.position = position;
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
                    session.detail = if let Some(analysis) = &session.video {
                        if analysis.signal == "audio_energy" {
                            if analysis.moments.is_empty() { "Áudio analisado · sem picos distintos; podes definir um corte manual" }
                            else { "Análise de áudio concluída · momentos prontos para criar MP4 locais" }
                        } else {
                        if analysis.availability == "unavailable" {
                            "Vídeo consultado · o YouTube não disponibilizou um heatmap público"
                        } else if analysis.moments.is_empty() {
                            "Heatmap recebido · sem picos distintos no intervalo escolhido"
                        } else {
                            "Análise concluída · momentos prontos para rever e exportar"
                        }
                        }
                    } else if session.messages.is_empty() {
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
fn stop_capture(state: State<'_, Shared>) -> Result<(), String> {
    let mut session = state.lock().map_err(|_| "Sessão indisponível.")?;
    if matches!(
        session.status.as_str(),
        "connecting" | "downloading" | "live"
    ) {
        session.cancel.store(true, Ordering::Relaxed);
        session.status = "stopping".into();
        session.detail = "A terminar e preservar os resultados disponíveis…".into();
    }
    Ok(())
}

#[tauri::command]
fn get_snapshot(
    query: Option<String>,
    reactions_only: Option<bool>,
    start: Option<f64>,
    end: Option<f64>,
    state: State<'_, Shared>,
) -> Result<Snapshot, String> {
    if start.is_some_and(|s| !s.is_finite() || s < 0.0)
        || end.is_some_and(|e| !e.is_finite() || e <= start.unwrap_or(0.0))
    {
        return Err("Intervalo de consulta inválido.".into());
    }
    let mut session = state.lock().map_err(|_| "Sessão indisponível.")?;
    if session.messages.len() != session.analyzed_count {
        session.analysis = chat::analyze_signals(&session.messages);
        session.analyzed_count = session.messages.len();
    }
    let query = query.unwrap_or_default().trim().to_lowercase();
    let filtered: Vec<_> = session
        .messages
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
    Ok(Snapshot {
        clip_profile: session.clip_profile.clone(),
        provider: session.provider.clone(),
        youtube: session.youtube.clone(),
        video: session.video.clone(),
        moments: session.moments(),
        can_export: session.video.is_some() || !session.messages.is_empty(),
        source: session.source.clone(),
        status: session.status.clone(),
        detail: session.detail.clone(),
        total: session.messages.len(),
        matched: filtered.len(),
        position: session.position,
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
        messages: filtered
            .into_iter()
            .rev()
            .take(400)
            .cloned()
            .collect::<Vec<_>>()
            .into_iter()
            .rev()
            .collect(),
        analysis: session.analysis.clone(),
    })
}

#[tauri::command]
async fn export_chat(format: String, state: State<'_, Shared>) -> Result<Option<String>, String> {
    if !["json", "csv"].contains(&format.as_str()) {
        return Err("Formato inválido.".into());
    }
    // Snapshot before the dialog: capture may continue while the user chooses a file.
    let (source, messages, status, youtube, clip_profile, moments) = {
        let session = state.lock().map_err(|_| "Sessão indisponível.")?;
        if session.messages.is_empty() && session.video.is_none() {
            return Err("Ainda não há dados para exportar.".into());
        }
        (
            session.source.clone(),
            session.messages.clone(),
            session.status.clone(),
            session.video.clone(),
            session.clip_profile.clone(),
            session.moments(),
        )
    };
    let name = format!(
        "chatscope-{}-{}.{}",
        source.as_ref().map(|s| s.id.as_str()).unwrap_or("chat"),
        chrono::Local::now().format("%Y%m%d-%H%M%S"),
        format
    );
    let path = rfd::AsyncFileDialog::new()
        .set_title("Exportar sessão ChatScope")
        .set_file_name(name)
        .add_filter(format.to_uppercase(), &[format.as_str()])
        .save_file()
        .await;
    let Some(file) = path else {
        return Ok(None);
    };
    let content = if let Some(analysis) = youtube {
        let source = source.ok_or("Sessão sem origem.")?;
        if format == "csv" {
            scope::export_moments_csv(&source, &analysis.moments).into_bytes()
        } else {
            serde_json::to_vec_pretty(&serde_json::json!({"schemaVersion":3,"status":status,"source":source,"video":analysis,"clipProfile":clip_profile,"moments":moments}))
                .map_err(|error| error.to_string())?
        }
    } else if format == "csv" {
        chat::export_csv(&messages).into_bytes()
    } else {
        serde_json::to_vec_pretty(&serde_json::json!({"schemaVersion":1,"exportedAt":chrono::Utc::now().to_rfc3339(),"status":status,"source":source,"messageCount":messages.len(),"analysis":chat::analyze(&messages),"messages":messages,"clipProfile":clip_profile,"moments":moments})).map_err(|e| e.to_string())?
    };
    file.write(&content)
        .await
        .map_err(|e| format!("Não foi possível guardar: {e}"))?;
    Ok(Some(file.path().display().to_string()))
}

#[tauri::command]
fn open_youtube_moment(start: f64, state: State<'_, Shared>) -> Result<(), String> {
    let session = state.lock().map_err(|_| "Sessão indisponível.")?;
    let source = session
        .source
        .as_ref()
        .filter(|source| source.kind == "youtube")
        .ok_or("Seleciona um vídeo YouTube.")?;
    if !start.is_finite() || start < source.start || start >= source.end.unwrap_or(0.0) {
        return Err("O momento está fora do intervalo analisado.".into());
    }
    let url = scope::youtube_url(&source.id, start);
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
fn create_clips(
    start: Option<String>,
    end: Option<String>,
    all: Option<bool>,
    render_profile: Option<media::RenderProfile>,
    topic: Option<String>,
    state: State<'_, Shared>,
    production: State<'_, media::SharedProduction>,
) -> Result<(), String> {
    let request = {
        let session = state.lock().map_err(|_| "Sessão indisponível.")?;
        let source = session
            .source
            .as_ref()
            .ok_or("Analisa primeiro uma origem.")?;
        let moments = if all.unwrap_or(false) {
            session.moments()
        } else {
            let start = chat::parse_time(&start.ok_or("Seleciona o início do corte.")?)?;
            let end = chat::parse_time(&end.ok_or("Seleciona o fim do corte.")?)?;
            let suggested = session.moments().into_iter().find(|moment| {
                (moment.start - start).abs() < 0.001 && (moment.end - end).abs() < 0.001
            });
            vec![suggested.unwrap_or(scope::Moment {
                start,
                end,
                peak: (start + end) / 2.0,
                strength: 0.0,
                signal: "manual".into(),
                reason: "Intervalo escolhido para revisão".into(),
            })]
        };
        media::request(
            source,
            session.video.as_ref(),
            moments,
            &session.clip_profile,
            render_profile.unwrap_or_default(),
            &topic.unwrap_or_else(|| "geral".into()),
        )?
    };
    media::start(production.inner().clone(), request)
}

#[tauri::command]
fn get_production(
    production: State<'_, media::SharedProduction>,
) -> Result<serde_json::Value, String> {
    Ok(production
        .lock()
        .map_err(|_| "Produção indisponível.")?
        .snapshot())
}

#[tauri::command]
fn cancel_production(production: State<'_, media::SharedProduction>) -> Result<(), String> {
    production
        .lock()
        .map_err(|_| "Produção indisponível.")?
        .cancel
        .store(true, Ordering::Relaxed);
    Ok(())
}

#[tauri::command]
fn retry_production(production: State<'_, media::SharedProduction>) -> Result<(), String> {
    let request = {
        let manager = production.lock().map_err(|_| "Produção indisponível.")?;
        if manager.busy {
            return Err("Já existe uma produção em curso.".into());
        }
        let snapshot = manager.snapshot();
        let id = snapshot["id"]
            .as_str()
            .ok_or("Ainda não existe uma produção.")?;
        if !id
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-')
        {
            return Err("Job inválido.".into());
        }
        let mut request: serde_json::Value = serde_json::from_slice(
            &std::fs::read(manager.root.join("requests").join(format!("{id}.json")))
                .map_err(|e| e.to_string())?,
        )
        .map_err(|e| e.to_string())?;
        if let Some(clips) = snapshot["clips"]
            .as_array()
            .filter(|clips| !clips.is_empty())
        {
            request["moments"] = serde_json::json!(
                clips
                    .iter()
                    .filter(|clip| clip["status"] != "ready")
                    .map(|clip| clip["moment"].clone())
                    .collect::<Vec<_>>()
            );
        }
        if request["moments"].as_array().is_none_or(|m| m.is_empty()) {
            return Err("Todos os clips desta produção estão prontos.".into());
        }
        request["id"] = serde_json::json!(media::id());
        request
    };
    media::start(production.inner().clone(), request)
}

#[tauri::command]
fn open_media_output(
    index: Option<usize>,
    production: State<'_, media::SharedProduction>,
) -> Result<(), String> {
    let manager = production.lock().map_err(|_| "Produção indisponível.")?;
    let path = if let Some(index) = index {
        let snapshot = manager.snapshot();
        let path = snapshot["clips"][index]["path"]
            .as_str()
            .ok_or("O clip ainda não está pronto.")?
            .to_owned();
        let path = std::path::PathBuf::from(path)
            .canonicalize()
            .map_err(|e| e.to_string())?;
        if !path.starts_with(manager.root.canonicalize().map_err(|e| e.to_string())?)
            || !path.is_file()
        {
            return Err("Clip inválido.".into());
        }
        path
    } else {
        std::fs::create_dir_all(&manager.root).map_err(|e| e.to_string())?;
        manager.root.clone()
    };
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        let system = std::env::var_os("SystemRoot").ok_or("Windows indisponível.")?;
        let program = std::path::PathBuf::from(system).join(if index.is_some() {
            "System32/rundll32.exe"
        } else {
            "explorer.exe"
        });
        let mut command = std::process::Command::new(program);
        if index.is_some() {
            command.arg("url.dll,FileProtocolHandler");
        }
        command
            .arg(path)
            .creation_flags(0x08000000)
            .spawn()
            .map_err(|e| e.to_string())?;
    }
    Ok(())
}

#[tauri::command]
async fn pick_media_source() -> Result<Option<String>, String> {
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

async fn media_cli(args: &[String]) -> Result<(), String> {
    let file = args
        .get(2)
        .ok_or("Uso: ChatScope --media-job pedido.json")?;
    let job: serde_json::Value =
        serde_json::from_slice(&std::fs::read(file).map_err(|e| e.to_string())?)
            .map_err(|e| e.to_string())?;
    let output = job["output"]
        .as_str()
        .ok_or("Falta o caminho output para o resultado JSON.")?;
    for key in ["start", "end"] {
        if job
            .get(key)
            .is_some_and(|v| !v.is_null() && v.as_f64().is_none())
        {
            return Err(format!("{key} deve ser um número de segundos."));
        }
    }
    let capture_seconds = job["captureSeconds"].as_u64().unwrap_or(120);
    if !(30..=600).contains(&capture_seconds) {
        return Err("captureSeconds deve ficar entre 30 e 600.".into());
    }
    let input = scope::parse_input(job["url"].as_str().ok_or("Falta url.")?)?;
    let profile: clips::ClipProfile = serde_json::from_value(
        job.get("clipProfile")
            .cloned()
            .unwrap_or(serde_json::json!({})),
    )
    .map_err(|e| e.to_string())?;
    profile.validate()?;
    let (source, analysis) = media::analyze_at(
        &input.url,
        job["start"].as_f64(),
        job["end"].as_f64(),
        &profile,
        capture_seconds as u32,
        Arc::new(AtomicBool::new(false)),
        job["outputRoot"]
            .as_str()
            .map(std::path::PathBuf::from)
            .unwrap_or_else(media::root),
    )
    .await?;
    let production = if job["produce"].as_bool().unwrap_or(false) {
        let mut manager = media::Production::new(
            job["outputRoot"]
                .as_str()
                .map(std::path::PathBuf::from)
                .unwrap_or_else(media::root),
        );
        manager.reserve()?;
        let moments = if let Some(value) = job.get("moments") {
            serde_json::from_value(value.clone()).map_err(|e| e.to_string())?
        } else {
            analysis.moments.clone()
        };
        if moments.is_empty() && job.get("moments").is_none() {
            media::atomic_json(
                std::path::Path::new(output),
                &serde_json::json!({"source":source,"video":analysis,"production":{"status":"no_candidates","clips":[]}}),
            )?;
            return Ok(());
        }
        let render_profile = serde_json::from_value(
            job.get("renderProfile")
                .cloned()
                .unwrap_or(serde_json::json!({})),
        )
        .map_err(|e| e.to_string())?;
        let mut request = media::request(
            &source,
            Some(&analysis),
            moments,
            &profile,
            render_profile,
            job["topic"].as_str().unwrap_or("geral"),
        )?;
        if let Some(root) = job.get("outputRoot") {
            request["root"] = root.clone();
        }
        media::atomic_json(
            &manager
                .root
                .join("requests")
                .join(format!("{}.json", request["id"].as_str().unwrap())),
            &request,
        )?;
        Some(media::call(&request, Arc::new(AtomicBool::new(false)), 21600).await?)
    } else {
        None
    };
    media::atomic_json(
        std::path::Path::new(output),
        &serde_json::json!({"source":source,"video":analysis,"production":production}),
    )?;
    if production
        .as_ref()
        .is_some_and(|p| p["status"] != "complete")
    {
        return Err("Produção incompleta; consulta os erros no JSON de resultado.".into());
    }
    Ok(())
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    if args.get(1).is_some_and(|s| s == "--media-job") {
        let result = tokio::runtime::Runtime::new()
            .unwrap()
            .block_on(media_cli(&args));
        if let Err(error) = result {
            eprintln!("{error}");
            std::process::exit(1);
        }
        return;
    }
    if args.get(1).is_some_and(|s| s == "--scope-youtube") {
        let result = tokio::runtime::Runtime::new()
            .unwrap()
            .block_on(youtube_cli(&args));
        if let Err(error) = result {
            eprintln!("{error}");
            std::process::exit(1);
        }
        return;
    }
    if args.get(1).is_some_and(|s| s == "--capture") {
        let result = tokio::runtime::Runtime::new().unwrap().block_on(cli(&args));
        if let Err(error) = result {
            eprintln!("{error}");
            std::process::exit(1);
        }
        return;
    }
    tauri::Builder::default()
        .setup(|app| {
            // A separate hidden WebView2 instance can be tested over CDP without
            // injecting mouse/keyboard input or activating the user's desktop.
            if !std::env::args().any(|arg| arg == "--isolated-test") {
                let window = app
                    .get_webview_window("main")
                    .ok_or("Missing main window")?;
                window.show()?;
                window.set_focus()?;
            }
            Ok(())
        })
        .manage(Arc::new(Mutex::new(Session::default())) as Shared)
        .manage(
            Arc::new(Mutex::new(media::Production::new(media::root()))) as media::SharedProduction
        )
        .invoke_handler(tauri::generate_handler![
            get_source_capabilities,
            get_example_vod,
            start_capture,
            stop_capture,
            get_snapshot,
            export_chat,
            open_youtube_moment,
            create_clips,
            get_production,
            cancel_production,
            retry_production,
            open_media_output,
            pick_media_source
        ])
        .run(tauri::generate_context!())
        .expect("Não foi possível iniciar o ChatScope");
}

async fn youtube_cli(args: &[String]) -> Result<(), String> {
    let option = |key: &str| {
        args.iter()
            .position(|value| value == key)
            .and_then(|index| args.get(index + 1))
    };
    let url = args
        .get(2)
        .ok_or("Uso: chatscope --scope-youtube URL --output analise.json")?;
    let input = scope::parse_input(url)?;
    if input.provider() != "youtube" {
        return Err("Indica um vídeo YouTube.".into());
    }
    let profile = clips::ClipProfile {
        duration: option("--duration")
            .map(|v| v.parse::<f64>().map_err(|_| "Duração inválida."))
            .transpose()?
            .unwrap_or(30.0),
        before_peak: option("--before-peak")
            .map(|v| v.parse::<f64>().map_err(|_| "Contexto inválido."))
            .transpose()?
            .unwrap_or(20.0),
        max_moments: option("--max-moments")
            .map(|v| {
                v.parse::<usize>()
                    .map_err(|_| "Número de candidatos inválido.")
            })
            .transpose()?
            .unwrap_or(8),
    };
    profile.validate()?;
    let prepared = providers::ProviderRegistry::default()
        .prepare(
            &input,
            option("--start")
                .map(|value| chat::parse_time(value))
                .transpose()?,
            option("--end")
                .map(|value| chat::parse_time(value))
                .transpose()?,
            &profile,
            providers::CaptureOptions {
                video_mode: false,
                capture_seconds: 120,
            },
            Arc::new(AtomicBool::new(false)),
        )
        .await?;
    let providers::PreparedSource::Video(source, analysis) = prepared else {
        return Err("Indica um vídeo YouTube.".into());
    };
    let output = option("--output").ok_or("Indica --output para guardar a análise.")?;
    let document = youtube::export_document(&source, &analysis, "complete");
    std::fs::write(
        output,
        serde_json::to_vec_pretty(&document).map_err(|error| error.to_string())?,
    )
    .map_err(|error| error.to_string())?;
    println!(
        "{} intervalos · {} momentos · {}",
        analysis.heatmap.len(),
        analysis.moments.len(),
        analysis.availability
    );
    Ok(())
}

async fn cli(args: &[String]) -> Result<(), String> {
    let option = |key: &str| {
        args.iter()
            .position(|s| s == key)
            .and_then(|n| args.get(n + 1))
            .cloned()
    };
    let url = args.get(2).ok_or(
        "Uso: chatscope --capture URL --seconds 20 --output chat.json [--start 00:00 --end 05:00]",
    )?;
    let source = chat::resolve(
        url,
        option("--start")
            .map(|s| chat::parse_time(&s))
            .transpose()?,
        option("--end").map(|s| chat::parse_time(&s)).transpose()?,
    )
    .await?;
    let cancel = Arc::new(AtomicBool::new(false));
    if source.kind == "live" {
        let seconds: u64 = option("--seconds")
            .unwrap_or("20".into())
            .parse()
            .map_err(|_| "Duração inválida.")?;
        let stop = cancel.clone();
        tokio::spawn(async move {
            tokio::time::sleep(std::time::Duration::from_secs(seconds)).await;
            stop.store(true, Ordering::Relaxed);
        });
    }
    let mut messages = Vec::new();
    chat::capture(source.clone(), cancel, |update| match update {
        Update::Messages(batch, _) => messages.extend(batch),
        Update::Status(status, detail) => eprintln!("{status}: {detail}"),
        _ => {}
    })
    .await?;
    let output = option("--output").ok_or("Indica --output para guardar o resultado.")?;
    let document = serde_json::json!({"schemaVersion":1,"exportedAt":chrono::Utc::now().to_rfc3339(),"source":source,"messageCount":messages.len(),"analysis":chat::analyze(&messages),"messages":messages});
    std::fs::write(&output, serde_json::to_vec_pretty(&document).unwrap())
        .map_err(|e| e.to_string())?;
    if let Some(csv) = option("--csv") {
        std::fs::write(csv, chat::export_csv(&messages)).map_err(|e| e.to_string())?;
    }
    println!("{} mensagens reais → {output}", messages.len());
    Ok(())
}
