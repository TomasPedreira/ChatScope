//! In-memory analysis state and the compatibility-preserving IPC snapshot.
use crate::{
    clip_profiles, domain_models,
    moment_detectors::{self, MomentDetector},
    twitch_chat,
};
use serde::Serialize;
use std::{
    sync::{Arc, Mutex, atomic::AtomicBool},
    time::Instant,
};
use twitch_chat::{ChatMessage, MediaSource};
#[derive(Default)]
pub(crate) struct AnalysisSession {
    pub(crate) clip_profile: clip_profiles::ClipProfile,
    pub(crate) provider: String,
    pub(crate) video_analysis: Option<domain_models::VideoAnalysis>,
    pub(crate) generation: u64,
    pub(crate) source: Option<MediaSource>,
    pub(crate) chat_messages: Vec<ChatMessage>,
    pub(crate) status: String,
    pub(crate) detail: String,
    pub(crate) position_seconds: f64,
    pub(crate) cancellation_requested: Arc<AtomicBool>,
    pub(crate) started: Option<Instant>,
    pub(crate) finished: Option<Instant>,
    pub(crate) chat_analysis: twitch_chat::Analysis,
    pub(crate) analyzed_message_count: usize,
}

impl AnalysisSession {
    pub(crate) fn clip_candidates(&self) -> Vec<domain_models::ClipCandidate> {
        if let Some(analysis) = &self.video_analysis {
            return analysis.clip_candidates.clone();
        }
        let Some(source) = &self.source else {
            return vec![];
        };
        let bounds = clip_profiles::TimeRange {
            start: source.start,
            end: source
                .end
                .or(source.duration)
                .unwrap_or(self.position_seconds)
                .max(source.start),
        };
        let analysis = if self.analyzed_message_count == self.chat_messages.len() {
            self.chat_analysis.clone()
        } else {
            twitch_chat::analyze_signals(&self.chat_messages)
        };
        moment_detectors::ChatActivityDetector.detect(&analysis, bounds, &self.clip_profile)
    }
}

pub(crate) type SharedAnalysisSession = Arc<Mutex<AnalysisSession>>;

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct SessionSnapshot {
    pub(crate) clip_profile: clip_profiles::ClipProfile,
    pub(crate) provider: String,
    #[serde(rename = "youtube")]
    pub(crate) legacy_youtube_analysis: Option<domain_models::VideoAnalysis>,
    #[serde(rename = "video")]
    pub(crate) video_analysis: Option<domain_models::VideoAnalysis>,
    #[serde(rename = "moments")]
    pub(crate) clip_candidates: Vec<domain_models::ClipCandidate>,
    pub(crate) can_export: bool,
    pub(crate) source: Option<MediaSource>,
    pub(crate) status: String,
    pub(crate) detail: String,
    pub(crate) total: usize,
    pub(crate) matched: usize,
    #[serde(rename = "position")]
    pub(crate) position_seconds: f64,
    pub(crate) elapsed: f64,
    #[serde(rename = "messages")]
    pub(crate) chat_messages: Vec<ChatMessage>,
    #[serde(rename = "analysis")]
    pub(crate) chat_analysis: twitch_chat::Analysis,
}
