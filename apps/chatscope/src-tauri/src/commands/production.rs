use crate::{
    analysis_session::SharedAnalysisSession, clip_production, clip_profiles, domain_models,
    production_paths, twitch_chat,
};
use std::sync::atomic::Ordering;
use tauri::State;
#[tauri::command]
pub(crate) fn create_clips(
    start: Option<String>,
    end: Option<String>,
    all: Option<bool>,
    render_profile: Option<clip_profiles::RenderProfile>,
    topic: Option<String>,
    state: State<'_, SharedAnalysisSession>,
    production: State<'_, clip_production::SharedClipProduction>,
) -> Result<(), String> {
    let request = {
        let session = state.lock().map_err(|_| "Sessão indisponível.")?;
        let source = session
            .source
            .as_ref()
            .ok_or("Analisa primeiro uma origem.")?;
        let clip_candidates = if all.unwrap_or(false) {
            session.clip_candidates()
        } else {
            let start = twitch_chat::parse_time(&start.ok_or("Seleciona o início do corte.")?)?;
            let end = twitch_chat::parse_time(&end.ok_or("Seleciona o fim do corte.")?)?;
            let suggested = session.clip_candidates().into_iter().find(|moment| {
                (moment.start - start).abs() < 0.001 && (moment.end - end).abs() < 0.001
            });
            vec![suggested.unwrap_or(domain_models::ClipCandidate {
                start,
                end,
                peak: (start + end) / 2.0,
                strength: 0.0,
                signal: "manual".into(),
                reason: "Intervalo escolhido para revisão".into(),
            })]
        };
        clip_production::build_render_job_request(
            source,
            session.video_analysis.as_ref(),
            clip_candidates,
            &session.clip_profile,
            render_profile.unwrap_or_default(),
            &topic.unwrap_or_else(|| "geral".into()),
        )?
    };
    clip_production::start_clip_production(production.inner().clone(), request)
}

#[tauri::command]
pub(crate) fn get_production(
    production: State<'_, clip_production::SharedClipProduction>,
) -> Result<serde_json::Value, String> {
    Ok(production
        .lock()
        .map_err(|_| "Produção indisponível.")?
        .snapshot())
}

#[tauri::command]
pub(crate) fn cancel_production(
    production: State<'_, clip_production::SharedClipProduction>,
) -> Result<(), String> {
    production
        .lock()
        .map_err(|_| "Produção indisponível.")?
        .cancellation_requested
        .store(true, Ordering::Relaxed);
    Ok(())
}

#[tauri::command]
pub(crate) fn retry_production(
    production: State<'_, clip_production::SharedClipProduction>,
) -> Result<(), String> {
    let request = {
        let manager = production.lock().map_err(|_| "Produção indisponível.")?;
        if manager.is_running {
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
            &std::fs::read(
                manager
                    .output_root
                    .join("requests")
                    .join(format!("{id}.json")),
            )
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
        request["id"] = serde_json::json!(production_paths::generate_job_id());
        request
    };
    clip_production::start_clip_production(production.inner().clone(), request)
}

#[tauri::command]
pub(crate) fn open_media_output(
    index: Option<usize>,
    production: State<'_, clip_production::SharedClipProduction>,
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
        if !path.starts_with(
            manager
                .output_root
                .canonicalize()
                .map_err(|e| e.to_string())?,
        ) || !path.is_file()
        {
            return Err("Clip inválido.".into());
        }
        path
    } else {
        std::fs::create_dir_all(&manager.output_root).map_err(|e| e.to_string())?;
        manager.output_root.clone()
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
