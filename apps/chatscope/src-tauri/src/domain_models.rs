//! MediaSource routing and data contracts shared by the platform-specific adapters.
use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct MediaSource {
    pub url: String,
    pub kind: String,
    pub id: String,
    pub channel: String,
    pub title: String,
    pub duration: Option<f64>,
    pub start: f64,
    pub end: Option<f64>,
}

pub struct SourceInput {
    pub provider: &'static str,
    pub url: String,
}
impl SourceInput {
    pub fn provider(&self) -> &'static str {
        self.provider
    }
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct SignalPoint {
    pub start_time: f64,
    pub end_time: f64,
    pub value: f64,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ClipCandidate {
    pub start: f64,
    pub end: f64,
    pub peak: f64,
    /// Relative ranking signal, never a probability or an audience percentage.
    pub strength: f64,
    pub signal: String,
    pub reason: String,
}

/// Platform-neutral evidence plus the private local master needed for live cuts.
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct VideoAnalysis {
    pub clip_profile: crate::clip_profiles::ClipProfile,
    pub availability: String,
    #[serde(default)]
    pub heatmap: Vec<SignalPoint>,
    #[serde(default)]
    pub points: Vec<SignalPoint>,
    #[serde(default)]
    pub signal: String,
    #[serde(default)]
    pub time_origin: String,
    #[serde(rename = "moments")]
    pub clip_candidates: Vec<ClipCandidate>,
    pub extractor_version: String,
    #[serde(default, skip_serializing)]
    pub local_media: Option<String>,
    #[serde(default, skip_serializing)]
    #[serde(rename = "mediaOrigin")]
    pub master_source_offset_seconds: f64,
}
