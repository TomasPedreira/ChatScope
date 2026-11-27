//! Command-line adapters use the same analysis/production services as the desktop.
use crate::{
    clip_production, clip_profiles, media_analysis, media_worker_client, production_paths,
    production_store, session_exports, source_providers, twitch_chat,
};
use std::sync::{
    Arc,
    atomic::{AtomicBool, Ordering},
};
use twitch_chat::Update;
pub(crate) async fn run_media_job(args: &[String]) -> Result<(), String> {
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
    let input = source_providers::parse_source_input(job["url"].as_str().ok_or("Falta url.")?)?;
    let profile: clip_profiles::ClipProfile = serde_json::from_value(
        job.get("clipProfile")
            .cloned()
            .unwrap_or(serde_json::json!({})),
    )
    .map_err(|e| e.to_string())?;
    profile.validate()?;
    let (source, analysis) = media_analysis::analyze_media_source_in(
        &input.url,
        job["start"].as_f64(),
        job["end"].as_f64(),
        &profile,
        capture_seconds as u32,
        Arc::new(AtomicBool::new(false)),
        job["outputRoot"]
            .as_str()
            .map(std::path::PathBuf::from)
            .unwrap_or_else(production_paths::daily_output_root),
    )
    .await?;
    let production = if job["produce"].as_bool().unwrap_or(false) {
        let mut manager = clip_production::ClipProductionManager::new(
            job["outputRoot"]
                .as_str()
                .map(std::path::PathBuf::from)
                .unwrap_or_else(production_paths::daily_output_root),
        );
        manager.reserve()?;
        let clip_candidates = if let Some(value) = job.get("moments") {
            serde_json::from_value(value.clone()).map_err(|e| e.to_string())?
        } else {
            analysis.clip_candidates.clone()
        };
        if clip_candidates.is_empty() && job.get("moments").is_none() {
            production_store::write_json_atomically(
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
        let mut request = clip_production::build_render_job_request(
            &source,
            Some(&analysis),
            clip_candidates,
            &profile,
            render_profile,
            job["topic"].as_str().unwrap_or("geral"),
        )?;
        if let Some(root) = job.get("outputRoot") {
            request["root"] = root.clone();
        }
        production_store::write_json_atomically(
            &manager
                .output_root
                .join("requests")
                .join(format!("{}.json", request["id"].as_str().unwrap())),
            &request,
        )?;
        Some(
            media_worker_client::run_media_worker(
                &request,
                Arc::new(AtomicBool::new(false)),
                21600,
            )
            .await?,
        )
    } else {
        None
    };
    production_store::write_json_atomically(
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

pub(crate) async fn run_youtube_scope(args: &[String]) -> Result<(), String> {
    let option = |key: &str| {
        args.iter()
            .position(|value| value == key)
            .and_then(|index| args.get(index + 1))
    };
    let url = args
        .get(2)
        .ok_or("Uso: chatscope --scope-youtube URL --output analise.json")?;
    let input = source_providers::parse_source_input(url)?;
    if input.provider() != "youtube" {
        return Err("Indica um vídeo YouTube.".into());
    }
    let profile = clip_profiles::ClipProfile {
        duration_seconds: option("--duration")
            .map(|v| v.parse::<f64>().map_err(|_| "Duração inválida."))
            .transpose()?
            .unwrap_or(30.0),
        seconds_before_peak: option("--before-peak")
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
    let prepared = source_providers::ProviderRegistry::default()
        .prepare(
            &input,
            option("--start")
                .map(|value| twitch_chat::parse_time(value))
                .transpose()?,
            option("--end")
                .map(|value| twitch_chat::parse_time(value))
                .transpose()?,
            &profile,
            source_providers::CaptureOptions {
                video_mode: false,
                capture_seconds: 120,
            },
            Arc::new(AtomicBool::new(false)),
        )
        .await?;
    let source_providers::PreparedSource::Video(source, analysis) = prepared else {
        return Err("Indica um vídeo YouTube.".into());
    };
    let output = option("--output").ok_or("Indica --output para guardar a análise.")?;
    let document = session_exports::export_youtube_analysis(&source, &analysis, "complete");
    std::fs::write(
        output,
        serde_json::to_vec_pretty(&document).map_err(|error| error.to_string())?,
    )
    .map_err(|error| error.to_string())?;
    println!(
        "{} intervalos · {} momentos · {}",
        analysis.heatmap.len(),
        analysis.clip_candidates.len(),
        analysis.availability
    );
    Ok(())
}

pub(crate) async fn run_twitch_capture(args: &[String]) -> Result<(), String> {
    let option = |key: &str| {
        args.iter()
            .position(|s| s == key)
            .and_then(|n| args.get(n + 1))
            .cloned()
    };
    let url = args.get(2).ok_or(
        "Uso: chatscope --capture URL --seconds 20 --output chat.json [--start 00:00 --end 05:00]",
    )?;
    let source = twitch_chat::resolve(
        url,
        option("--start")
            .map(|s| twitch_chat::parse_time(&s))
            .transpose()?,
        option("--end")
            .map(|s| twitch_chat::parse_time(&s))
            .transpose()?,
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
    twitch_chat::capture(source.clone(), cancel, |update| match update {
        Update::Messages(batch, _) => messages.extend(batch),
        Update::Status(status, detail) => eprintln!("{status}: {detail}"),
        _ => {}
    })
    .await?;
    let output = option("--output").ok_or("Indica --output para guardar o resultado.")?;
    let document = serde_json::json!({"schemaVersion":1,"exportedAt":chrono::Utc::now().to_rfc3339(),"source":source,"messageCount":messages.len(),"analysis":twitch_chat::analyze(&messages),"messages":messages});
    std::fs::write(&output, serde_json::to_vec_pretty(&document).unwrap())
        .map_err(|e| e.to_string())?;
    if let Some(csv) = option("--csv") {
        std::fs::write(csv, twitch_chat::export_csv(&messages)).map_err(|e| e.to_string())?;
    }
    println!("{} mensagens reais → {output}", messages.len());
    Ok(())
}
