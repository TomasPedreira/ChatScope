#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]
mod analysis_session;
mod cli;
mod clip_production;
mod clip_profiles;
mod commands;
mod domain_models;
mod kick_provider;
mod media_analysis;
mod media_worker_client;
mod moment_detectors;
mod production_paths;
mod production_store;
mod session_exports;
mod source_links;
mod source_providers;
mod twitch_chat;
#[cfg(test)]
mod youtube_heatmap_tests;
use analysis_session::{AnalysisSession, SharedAnalysisSession};
use std::sync::{Arc, Mutex};
use tauri::Manager;
fn main() {
    let args: Vec<String> = std::env::args().collect();
    if args.get(1).is_some_and(|s| s == "--media-job") {
        let result = tokio::runtime::Runtime::new()
            .unwrap()
            .block_on(cli::run_media_job(&args));
        if let Err(error) = result {
            eprintln!("{error}");
            std::process::exit(1);
        }
        return;
    }
    if args.get(1).is_some_and(|s| s == "--scope-youtube") {
        let result = tokio::runtime::Runtime::new()
            .unwrap()
            .block_on(cli::run_youtube_scope(&args));
        if let Err(error) = result {
            eprintln!("{error}");
            std::process::exit(1);
        }
        return;
    }
    if args.get(1).is_some_and(|s| s == "--capture") {
        let result = tokio::runtime::Runtime::new()
            .unwrap()
            .block_on(cli::run_twitch_capture(&args));
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
        .manage(Arc::new(Mutex::new(AnalysisSession::default())) as SharedAnalysisSession)
        .manage(
            Arc::new(Mutex::new(clip_production::ClipProductionManager::new(
                production_paths::daily_output_root(),
            ))) as clip_production::SharedClipProduction,
        )
        .invoke_handler(tauri::generate_handler![
            commands::analysis::get_source_capabilities,
            commands::analysis::get_example_vod,
            commands::analysis::start_capture,
            commands::analysis::stop_capture,
            commands::analysis::get_snapshot,
            commands::exports::export_chat,
            commands::analysis::open_youtube_moment,
            commands::production::create_clips,
            commands::production::get_production,
            commands::production::cancel_production,
            commands::production::retry_production,
            commands::production::open_media_output,
            commands::analysis::pick_media_source
        ])
        .run(tauri::generate_context!())
        .expect("Não foi possível iniciar o ChatScope");
}
