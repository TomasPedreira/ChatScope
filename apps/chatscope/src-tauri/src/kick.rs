//! Kick owns URL policy only. Acquisition and rendering use the shared pipeline.
use crate::{
    clips::ClipProfile,
    providers::{Capabilities, CaptureOptions, Preparation, PreparedSource, SourceProvider},
    scope::Input,
};
use std::sync::{Arc, atomic::AtomicBool};
use url::Url;

pub struct KickProvider;
fn slug(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 64
        && value
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-')
}
fn uuid(value: &str) -> bool {
    value.len() == 36
        && value.bytes().enumerate().all(|(i, b)| {
            if [8, 13, 18, 23].contains(&i) {
                b == b'-'
            } else {
                b.is_ascii_hexdigit()
            }
        })
}
impl SourceProvider for KickProvider {
    fn id(&self) -> &'static str {
        "kick"
    }
    fn accepts(&self, host: &str) -> bool {
        matches!(host, "kick.com" | "www.kick.com")
    }
    fn normalize(&self, _input: &str, url: &Url) -> Result<Input, String> {
        if url.scheme() != "https"
            || !url.username().is_empty()
            || url.password().is_some()
            || url.port().is_some_and(|p| p != 443)
        {
            return Err("Usa um URL HTTPS Kick, sem credenciais ou portas alternativas.".into());
        }
        let path = url.path().trim_matches('/');
        let parts: Vec<_> = path.split('/').collect();
        let channel = parts[0].to_ascii_lowercase();
        if !slug(&channel)
            || [
                "categories",
                "search",
                "auth",
                "video",
                "videos",
                "clips",
                "settings",
                "following",
            ]
            .contains(&channel.as_str())
        {
            return Err("Indica um canal, VOD ou clip Kick.".into());
        }
        let normalized = if parts.len() == 3 && parts[1] == "videos" && uuid(parts[2]) {
            format!(
                "https://kick.com/{channel}/videos/{}",
                parts[2].to_ascii_lowercase()
            )
        } else {
            let clip = if parts.len() == 3 && parts[1] == "clips" {
                Some(parts[2].to_owned())
            } else if parts.len() == 1 {
                url.query_pairs()
                    .find(|(key, _)| key == "clip")
                    .map(|(_, value)| value.into_owned())
            } else {
                return Err(
                    "Usa um VOD específico; listas de vídeos e clips não são suportadas.".into(),
                );
            };
            if let Some(clip) = clip {
                if !clip.starts_with("clip_")
                    || clip.len() > 128
                    || !slug(clip.trim_start_matches("clip_"))
                {
                    return Err("Identificador de clip Kick inválido.".into());
                }
                format!("https://kick.com/{channel}/clips/{clip}")
            } else {
                format!("https://kick.com/{channel}")
            }
        };
        Ok(Input {
            provider: self.id(),
            url: normalized,
        })
    }
    fn capabilities(&self) -> Capabilities {
        Capabilities {
            provider: self.id(),
            live_chat: false,
            replay_chat: false,
            replay_heatmap: false,
            media_capture: true,
        }
    }
    fn prepare<'a>(
        &'a self,
        url: &'a str,
        start: Option<f64>,
        end: Option<f64>,
        profile: &'a ClipProfile,
        options: CaptureOptions,
        cancel: Arc<AtomicBool>,
    ) -> Preparation<'a> {
        Box::pin(async move {
            let (source, analysis) =
                crate::media::analyze(url, start, end, profile, options.capture_seconds, cancel)
                    .await?;
            Ok(PreparedSource::Video(source, analysis))
        })
    }
}

#[cfg(test)]
mod tests {
    use crate::scope::parse_input;
    #[test]
    fn kick_normalizes_supported_sources_and_discards_tracking() {
        for (input, expected) in [
            (
                "https://www.kick.com/XQC/?utm_source=test",
                "https://kick.com/xqc",
            ),
            (
                "https://kick.com/xqc/videos/01a214cb-42f8-75cd-b00f-f083ea893dfd?t=20",
                "https://kick.com/xqc/videos/01a214cb-42f8-75cd-b00f-f083ea893dfd",
            ),
            (
                "https://kick.com/mxddy?clip=clip_01GYXVB5Y8PWAPWCWMSBCFB05X",
                "https://kick.com/mxddy/clips/clip_01GYXVB5Y8PWAPWCWMSBCFB05X",
            ),
        ] {
            let result = parse_input(input).unwrap();
            assert_eq!(result.provider(), "kick");
            assert_eq!(result.url, expected);
        }
    }
    #[test]
    fn kick_rejects_ambiguous_or_untrusted_sources() {
        for url in [
            "https://kick.com.evil.org/xqc",
            "http://kick.com/xqc",
            "https://user@kick.com/xqc",
            "https://kick.com:8000/xqc",
            "https://kick.com/xqc/videos",
            "https://kick.com/xqc/videos/not-an-id",
            "https://kick.com/search",
            "https://kick.com/xqc?clip=../../bad",
            "https://kick.com/xqc/other/path",
        ] {
            assert!(parse_input(url).is_err(), "accepted {url}");
        }
    }
}
