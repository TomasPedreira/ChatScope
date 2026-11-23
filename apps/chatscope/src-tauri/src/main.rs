#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]
mod chat;

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

type Shared = Arc<Mutex<Session>>;

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct Snapshot {
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
async fn get_example_vod() -> Result<serde_json::Value, String> {
    chat::example_vod().await
}

#[tauri::command]
fn start_capture(
    url: String,
    start: Option<String>,
    end: Option<String>,
    state: State<'_, Shared>,
) -> Result<(), String> {
    chat::parse_source(&url)?;
    let parse_optional = |s: Option<String>| {
        s.filter(|s| !s.trim().is_empty())
            .map(|s| chat::parse_time(&s))
            .transpose()
    };
    let start = parse_optional(start)?;
    let end = parse_optional(end)?;
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
            generation,
            status: "connecting".into(),
            detail: "A validar o URL na Twitch…".into(),
            started: Some(Instant::now()),
            ..Session::default()
        };
        (generation, session.cancel.clone())
    };
    tauri::async_runtime::spawn(async move {
        let result = async {
            let source = chat::resolve(&url, start, end).await?;
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
                Ok(()) => {
                    session.status = if cancel.load(Ordering::Relaxed) {
                        "stopped"
                    } else {
                        "complete"
                    }
                    .into();
                    session.detail = if session.messages.is_empty() {
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
        session.detail = "A terminar e preservar as mensagens…".into();
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
        session.analysis = chat::analyze(&session.messages);
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
    let (source, messages, status) = {
        let session = state.lock().map_err(|_| "Sessão indisponível.")?;
        if session.messages.is_empty() {
            return Err("Ainda não há mensagens para exportar.".into());
        }
        (
            session.source.clone(),
            session.messages.clone(),
            session.status.clone(),
        )
    };
    let name = format!(
        "chatscope-{}-{}.{}",
        source.as_ref().map(|s| s.id.as_str()).unwrap_or("chat"),
        chrono::Local::now().format("%Y%m%d-%H%M%S"),
        format
    );
    let path = rfd::AsyncFileDialog::new()
        .set_title("Exportar chat Twitch")
        .set_file_name(name)
        .add_filter(format.to_uppercase(), &[format.as_str()])
        .save_file()
        .await;
    let Some(file) = path else {
        return Ok(None);
    };
    let content = if format == "csv" {
        chat::export_csv(&messages).into_bytes()
    } else {
        serde_json::to_vec_pretty(&serde_json::json!({"schemaVersion":1,"exportedAt":chrono::Utc::now().to_rfc3339(),"status":status,"source":source,"messageCount":messages.len(),"analysis":chat::analyze(&messages),"messages":messages})).map_err(|e| e.to_string())?
    };
    file.write(&content)
        .await
        .map_err(|e| format!("Não foi possível guardar: {e}"))?;
    Ok(Some(file.path().display().to_string()))
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
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
        .invoke_handler(tauri::generate_handler![
            get_example_vod,
            start_capture,
            stop_capture,
            get_snapshot,
            export_chat
        ])
        .run(tauri::generate_context!())
        .expect("Não foi possível iniciar o ChatScope");
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
