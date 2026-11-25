//! Source routing and data contracts shared by the platform-specific adapters.
use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Source {
    pub url: String,
    pub kind: String,
    pub id: String,
    pub channel: String,
    pub title: String,
    pub duration: Option<f64>,
    pub start: f64,
    pub end: Option<f64>,
}

pub struct Input {
    pub provider: &'static str,
    pub url: String,
}
impl Input {
    pub fn provider(&self) -> &'static str {
        self.provider
    }
}
pub fn parse_input(input: &str) -> Result<Input, String> {
    crate::providers::ProviderRegistry::default().resolve(input)
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct SignalPoint {
    pub start_time: f64,
    pub end_time: f64,
    pub value: f64,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Moment {
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
    pub clip_profile: crate::clips::ClipProfile,
    pub availability: String,
    #[serde(default)]
    pub heatmap: Vec<SignalPoint>,
    #[serde(default)]
    pub points: Vec<SignalPoint>,
    #[serde(default)]
    pub signal: String,
    #[serde(default)]
    pub time_origin: String,
    pub moments: Vec<Moment>,
    pub extractor_version: String,
    #[serde(default, skip_serializing)]
    pub local_media: Option<String>,
    #[serde(default, skip_serializing)]
    pub media_origin: f64,
}

pub fn youtube_url(id: &str, start: f64) -> String {
    format!(
        "https://www.youtube.com/watch?v={id}&t={}s",
        start.floor() as u64
    )
}

pub fn export_moments_csv(source: &Source, moments: &[Moment]) -> String {
    let mut output =
        "\u{feff}video_id,title,start,end,peak,strength,signal,reason,url\r\n".to_owned();
    for moment in moments {
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
                youtube_url(&source.id, moment.start)
            } else {
                source.url.clone()
            },
        ];
        output.push_str(
            &values
                .iter()
                .map(|value| crate::chat::csv_cell(value))
                .collect::<Vec<_>>()
                .join(","),
        );
        output.push_str("\r\n");
    }
    output
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn normalizes_video_urls_and_discards_playlist_parameters() {
        for url in [
            "https://youtu.be/YE7VzlLtp-4?t=20",
            "https://www.youtube.com/watch?v=YE7VzlLtp-4&list=whatever",
            "https://m.youtube.com/shorts/YE7VzlLtp-4",
            "https://youtube.com/live/YE7VzlLtp-4",
        ] {
            assert!(
                parse_input(url).is_ok_and(|request| request.provider() == "youtube"
                    && request.url == "https://www.youtube.com/watch?v=YE7VzlLtp-4")
            );
        }
    }

    #[test]
    fn rejects_other_hosts_credentials_ports_and_non_video_urls() {
        for url in [
            "https://youtube.com.evil.org/watch?v=YE7VzlLtp-4",
            "http://youtube.com/watch?v=YE7VzlLtp-4",
            "https://user@youtube.com/watch?v=YE7VzlLtp-4",
            "https://youtube.com:8000/watch?v=YE7VzlLtp-4",
            "https://youtube.com/playlist?list=foo",
            "https://youtube.com/@Blender",
            "https://youtu.be/../../anything",
            "https://youtube.com/watch?v=bad",
            "https://twitch.tv.evil.org/foo",
        ] {
            assert!(parse_input(url).is_err(), "accepted {url}");
        }
    }
}
