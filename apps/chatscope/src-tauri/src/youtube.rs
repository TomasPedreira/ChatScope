//! Public replay signals are optional. Missing data is not a network/extractor failure.
use crate::{
    chat::Source,
    clips::{ClipProfile, TimeRange},
    detectors::{HeatmapDetector, MomentDetector},
    scope::Moment,
};
use serde::{Deserialize, Serialize};
use std::{
    path::PathBuf,
    process::Stdio,
    sync::{
        Arc,
        atomic::{AtomicBool, Ordering},
    },
    time::Duration,
};

pub use crate::scope::SignalPoint as HeatPoint;

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct VideoInfo {
    id: String,
    title: String,
    channel: String,
    duration: f64,
    #[serde(default)]
    heatmap: Option<Vec<HeatPoint>>,
    extractor_version: String,
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Analysis {
    pub clip_profile: ClipProfile,
    pub availability: String,
    pub heatmap: Vec<HeatPoint>,
    pub moments: Vec<Moment>,
    pub extractor_version: String,
}

pub fn export_document(source: &Source, analysis: &Analysis, status: &str) -> serde_json::Value {
    serde_json::json!({"schemaVersion":2,"provider":"youtube",
        "exportedAt":chrono::Utc::now().to_rfc3339(),"status":status,"source":source,
        "signal":"youtube_heatmap","availability":analysis.availability,"clipProfile":analysis.clip_profile,
        "extractorVersion":analysis.extractor_version,"heatmap":analysis.heatmap,"moments":analysis.moments})
}

#[cfg(test)]
pub fn analyze(
    info: VideoInfo,
    start: Option<f64>,
    end: Option<f64>,
) -> Result<(Source, Analysis), String> {
    analyze_with_profile(info, start, end, &ClipProfile::default())
}

pub fn analyze_with_profile(
    info: VideoInfo,
    start: Option<f64>,
    end: Option<f64>,
    profile: &ClipProfile,
) -> Result<(Source, Analysis), String> {
    profile.validate()?;
    if !info.duration.is_finite()
        || info.duration <= 0.0
        || info.id.len() != 11
        || !info
            .id
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b == b'-' || b == b'_')
    {
        return Err("O YouTube devolveu metadados de vídeo inválidos.".into());
    }
    let start = start.unwrap_or(0.0);
    let end = end.unwrap_or(info.duration);
    if !start.is_finite() || !end.is_finite() || start < 0.0 || start >= end || end > info.duration
    {
        return Err("O intervalo tem de ficar dentro da duração do vídeo.".into());
    }
    let source = Source {
        url: format!("https://www.youtube.com/watch?v={}", info.id),
        kind: "youtube".into(),
        id: info.id,
        title: info.title,
        channel: info.channel,
        duration: Some(info.duration),
        start,
        end: Some(end),
    };
    let mut heatmap = info.heatmap.unwrap_or_default();
    if heatmap.len() > 10_000
        || heatmap.iter().any(|point| {
            !point.start_time.is_finite()
                || !point.end_time.is_finite()
                || !point.value.is_finite()
                || point.start_time < 0.0
                || point.start_time >= point.end_time
                || point.end_time > info.duration + 1.0
                || !(0.0..=1.0).contains(&point.value)
        })
    {
        return Err("O YouTube devolveu um heatmap num formato inválido.".into());
    }
    heatmap.sort_by(|a, b| a.start_time.total_cmp(&b.start_time));
    if heatmap
        .windows(2)
        .any(|pair| pair[0].end_time > pair[1].start_time + 0.001)
    {
        return Err("O heatmap contém intervalos sobrepostos.".into());
    }
    let available = !heatmap.is_empty();
    heatmap.retain(|point| point.end_time > start && point.start_time < end);
    for point in &mut heatmap {
        point.start_time = point.start_time.max(start);
        point.end_time = point.end_time.min(end);
    }
    let moments = HeatmapDetector.detect(heatmap.as_slice(), TimeRange { start, end }, profile);
    Ok((
        source,
        Analysis {
            clip_profile: profile.clone(),
            availability: if available {
                "available"
            } else {
                "unavailable"
            }
            .into(),
            heatmap,
            moments,
            extractor_version: info.extractor_version,
        },
    ))
}

fn python_command() -> PathBuf {
    let mut roots = vec![];
    if let Ok(executable) = std::env::current_exe() {
        if let Some(parent) = executable.parent() {
            roots.push(parent.to_path_buf());
            if let Some(parent) = parent.parent() {
                roots.push(parent.to_path_buf());
            }
        }
    }
    roots.push(
        PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .unwrap()
            .to_path_buf(),
    );
    for root in roots {
        let candidate = root.join(".venv-youtube").join(if cfg!(windows) {
            "Scripts/python.exe"
        } else {
            "bin/python"
        });
        if candidate.is_file() {
            return candidate;
        }
    }
    PathBuf::from(if cfg!(windows) {
        "python.exe"
    } else {
        "python3"
    })
}

pub async fn extract(url: &str, cancel: Arc<AtomicBool>) -> Result<VideoInfo, String> {
    let mut command = tokio::process::Command::new(python_command());
    command
        .args([
            "-I",
            "-X",
            "utf8",
            "-u",
            "-c",
            include_str!("../../providers/youtube.py"),
            url,
        ])
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .kill_on_drop(true);
    #[cfg(windows)]
    command.creation_flags(0x08000000);
    let child = command.spawn().map_err(|_| "Não foi possível iniciar o suporte YouTube. Executa Setup-YouTube.ps1 na pasta apps/chatscope.")?;
    let output = tokio::select! {
        result = tokio::time::timeout(Duration::from_secs(50), child.wait_with_output()) => {
            result.map_err(|_| "O YouTube não respondeu a tempo. Volta a tentar.")?
                .map_err(|_| "Falhou o processo de análise do YouTube.")?
        },
        _ = async { while !cancel.load(Ordering::Relaxed) { tokio::time::sleep(Duration::from_millis(100)).await; } } => {
            return Err("Análise cancelada.".into());
        }
    };
    if !output.status.success() {
        let error = String::from_utf8_lossy(&output.stderr);
        return Err(format!(
            "YouTube: {}",
            error.chars().take(1200).collect::<String>().trim()
        ));
    }
    serde_json::from_slice(&output.stdout)
        .map_err(|_| "O extractor YouTube devolveu dados inválidos.".into())
}

#[cfg(test)]
mod tests {
    use super::*;
    fn info(values: &[f64]) -> VideoInfo {
        VideoInfo {
            id: "YE7VzlLtp-4".into(),
            title: "=unsafe title".into(),
            channel: "Blender".into(),
            duration: 100.0,
            extractor_version: "test".into(),
            heatmap: Some(
                values
                    .iter()
                    .enumerate()
                    .map(|(i, value)| HeatPoint {
                        start_time: i as f64 * 10.0,
                        end_time: (i + 1) as f64 * 10.0,
                        value: *value,
                    })
                    .collect(),
            ),
        }
    }
    #[test]
    fn missing_and_flat_heatmaps_do_not_invent_moments() {
        let mut video = info(&[]);
        video.heatmap = None;
        let (_, analysis) = analyze(video, None, None).unwrap();
        assert_eq!(analysis.availability, "unavailable");
        assert!(analysis.moments.is_empty());
        let (_, analysis) = analyze(info(&[0.5; 10]), None, None).unwrap();
        assert_eq!(analysis.availability, "available");
        assert!(analysis.moments.is_empty());
    }
    #[test]
    fn plateau_is_one_peak_and_candidates_are_ranked_non_overlapping_and_bounded() {
        let (_, analysis) = analyze(
            info(&[0.1, 0.1, 0.9, 0.9, 0.1, 0.1, 0.2, 1.0, 0.1, 0.1]),
            None,
            None,
        )
        .unwrap();
        assert_eq!(analysis.moments.len(), 2);
        assert_eq!(analysis.moments[0].peak, 75.0);
        assert_eq!(analysis.moments[1].peak, 30.0);
        for point in &analysis.moments {
            assert!(point.start >= 0.0 && point.end <= 100.0);
        }
    }
    #[test]
    fn range_clips_heatmap_and_context_and_rejects_invalid_data() {
        let (_, analysis) =
            analyze(info(&[0.1, 0.1, 0.9, 0.1, 0.1]), Some(20.0), Some(45.0)).unwrap();
        assert_eq!(analysis.heatmap[0].start_time, 20.0);
        assert!(
            analysis
                .moments
                .iter()
                .all(|point| point.start >= 20.0 && point.end <= 45.0)
        );
        assert!(analyze(info(&[f64::NAN]), None, None).is_err());
        assert!(analyze(info(&[1.1]), None, None).is_err());
        assert!(analyze(info(&[0.1]), Some(80.0), Some(110.0)).is_err());
    }
    #[test]
    fn exported_csv_keeps_timestamps_and_neutralizes_titles() {
        let (source, analysis) = analyze(info(&[0.1, 0.1, 0.9, 0.1]), None, None).unwrap();
        let csv = crate::scope::export_moments_csv(&source, &analysis.moments);
        assert!(csv.contains("'=unsafe title"));
        assert!(csv.contains("youtube_heatmap"));
        assert!(csv.contains("&t=5s"));
    }
    #[test]
    fn real_recorded_heatmap_produces_review_candidates() {
        let video: VideoInfo =
            serde_json::from_str(include_str!("../../tests/fixtures/youtube.json")).unwrap();
        let (source, analysis) = analyze(video, None, None).unwrap();
        assert_eq!(source.duration, Some(597.0));
        assert_eq!(analysis.heatmap.len(), 100);
        assert!(!analysis.moments.is_empty());
        assert!(
            analysis
                .moments
                .windows(2)
                .all(|pair| pair[0].strength >= pair[1].strength)
        );
        for (index, moment) in analysis.moments.iter().enumerate() {
            assert!(
                moment.start >= 0.0
                    && moment.start <= moment.peak
                    && moment.peak < moment.end
                    && moment.end <= 597.0
            );
            assert!(
                analysis.moments[index + 1..]
                    .iter()
                    .all(|other| moment.end <= other.start || moment.start >= other.end)
            );
        }
    }
}
