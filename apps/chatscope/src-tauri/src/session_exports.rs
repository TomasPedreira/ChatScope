use crate::domain_models::{ClipCandidate, MediaSource, VideoAnalysis};
pub fn export_clip_candidates_csv(
    source: &MediaSource,
    clip_candidates: &[ClipCandidate],
) -> String {
    let mut output =
        "\u{feff}video_id,title,start,end,peak,strength,signal,reason,url\r\n".to_owned();
    for moment in clip_candidates {
        let values = [
            source.id.clone(),
            source.title.clone(),
            format!("{:.3}", moment.start),
            format!("{:.3}", moment.end),
            format!("{:.3}", moment.peak),
            format!("{:.6}", moment.strength),
            moment.signal.clone(),
            moment.reason.clone(),
            if source.kind == "youtube" {
                crate::source_links::youtube_timestamp_url(&source.id, moment.start)
            } else {
                source.url.clone()
            },
        ];
        output.push_str(
            &values
                .iter()
                .map(|value| crate::twitch_chat::csv_cell(value))
                .collect::<Vec<_>>()
                .join(","),
        );
        output.push_str("\r\n");
    }
    output
}

pub fn export_youtube_analysis(
    source: &crate::domain_models::MediaSource,
    analysis: &VideoAnalysis,
    status: &str,
) -> serde_json::Value {
    serde_json::json!({"schemaVersion":2,"provider":"youtube",
        "exportedAt":chrono::Utc::now().to_rfc3339(),"status":status,"source":source,
        "signal":analysis.signal,"points":analysis.points,"timeOrigin":analysis.time_origin,"availability":analysis.availability,"clipProfile":analysis.clip_profile,
        "extractorVersion":analysis.extractor_version,"heatmap":analysis.heatmap,"moments":analysis.clip_candidates})
}
