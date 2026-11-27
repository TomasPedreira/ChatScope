//! Normalize worker evidence and rank clip candidates with the shared detectors.
use crate::{
    clip_profiles::{ClipProfile, TimeRange},
    domain_models::{MediaSource, VideoAnalysis},
    media_worker_client::run_media_worker,
    moment_detectors::{AudioEnergyDetector, HeatmapDetector, MomentDetector},
    production_paths::{daily_output_root, generate_job_id},
};
use serde_json::json;
use std::{
    path::PathBuf,
    sync::{Arc, atomic::AtomicBool},
};
pub async fn analyze_media_source(
    url: &str,
    start: Option<f64>,
    end: Option<f64>,
    profile: &ClipProfile,
    capture_seconds: u32,
    cancel: Arc<AtomicBool>,
) -> Result<(MediaSource, VideoAnalysis), String> {
    analyze_media_source_in(
        url,
        start,
        end,
        profile,
        capture_seconds,
        cancel,
        daily_output_root(),
    )
    .await
}

pub async fn analyze_media_source_in(
    url: &str,
    start: Option<f64>,
    end: Option<f64>,
    profile: &ClipProfile,
    capture_seconds: u32,
    cancel: Arc<AtomicBool>,
    output_root: PathBuf,
) -> Result<(MediaSource, VideoAnalysis), String> {
    let request = json!({"action":"analyze", "id":generate_job_id(), "root":output_root, "url":url,
        "start":start,"end":end,"clipProfile":profile,"captureSeconds":capture_seconds});
    let result = run_media_worker(&request, cancel, 1000).await?;
    let source: MediaSource =
        serde_json::from_value(result["source"].clone()).map_err(|e| e.to_string())?;
    let mut analysis: VideoAnalysis =
        serde_json::from_value(result["analysis"].clone()).map_err(|e| e.to_string())?;
    let bounds = TimeRange {
        start: source.start,
        end: source.end.ok_or("Falta o fim do intervalo.")?,
    };
    analysis.clip_candidates = match analysis.signal.as_str() {
        "audio_energy" => AudioEnergyDetector.detect(&analysis.points, bounds, profile),
        "youtube_heatmap" => HeatmapDetector.detect(&analysis.points, bounds, profile),
        _ => return Err("O adapter devolveu um tipo de sinal não suportado.".into()),
    };
    Ok((source, analysis))
}
