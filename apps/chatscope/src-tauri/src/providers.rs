//! Register an adapter here; UI, detectors and clip profiles use common contracts.
use crate::{
    chat,
    clips::ClipProfile,
    scope::{Input, Source},
    youtube,
};
use serde::Serialize;
use std::{
    future::Future,
    pin::Pin,
    sync::{Arc, atomic::AtomicBool},
};
use url::Url;

pub enum PreparedSource {
    Chat(Source),
    Video(Source, youtube::Analysis),
}
type Preparation<'a> = Pin<Box<dyn Future<Output = Result<PreparedSource, String>> + Send + 'a>>;

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Capabilities {
    pub provider: &'static str,
    pub live_chat: bool,
    pub replay_chat: bool,
    pub replay_heatmap: bool,
}

pub trait SourceProvider: Send + Sync {
    fn id(&self) -> &'static str;
    fn accepts(&self, host: &str) -> bool;
    fn normalize(&self, input: &str, url: &Url) -> Result<Input, String>;
    fn capabilities(&self) -> Capabilities;
    fn prepare<'a>(
        &'a self,
        url: &'a str,
        start: Option<f64>,
        end: Option<f64>,
        profile: &'a ClipProfile,
        cancel: Arc<AtomicBool>,
    ) -> Preparation<'a>;
}

pub struct TwitchProvider;
impl SourceProvider for TwitchProvider {
    fn id(&self) -> &'static str {
        "twitch"
    }
    fn accepts(&self, host: &str) -> bool {
        matches!(
            host,
            "twitch.tv" | "www.twitch.tv" | "m.twitch.tv" | "clips.twitch.tv"
        )
    }
    fn normalize(&self, input: &str, _url: &Url) -> Result<Input, String> {
        chat::parse_source(input)?;
        Ok(Input {
            provider: self.id(),
            url: input.trim().to_owned(),
        })
    }
    fn capabilities(&self) -> Capabilities {
        Capabilities {
            provider: self.id(),
            live_chat: true,
            replay_chat: true,
            replay_heatmap: false,
        }
    }
    fn prepare<'a>(
        &'a self,
        url: &'a str,
        start: Option<f64>,
        end: Option<f64>,
        _profile: &'a ClipProfile,
        _cancel: Arc<AtomicBool>,
    ) -> Preparation<'a> {
        Box::pin(async move { Ok(PreparedSource::Chat(chat::resolve(url, start, end).await?)) })
    }
}

pub struct YouTubeProvider;
impl SourceProvider for YouTubeProvider {
    fn id(&self) -> &'static str {
        "youtube"
    }
    fn accepts(&self, host: &str) -> bool {
        matches!(
            host,
            "youtube.com" | "www.youtube.com" | "m.youtube.com" | "youtu.be" | "www.youtu.be"
        )
    }
    fn normalize(&self, _input: &str, url: &Url) -> Result<Input, String> {
        if url.scheme() != "https"
            || !url.username().is_empty()
            || url.password().is_some()
            || url.port().is_some_and(|port| port != 443)
        {
            return Err("Usa um URL HTTPS de youtube.com ou youtu.be, sem credenciais ou portas alternativas.".into());
        }
        let parts: Vec<_> = url
            .path_segments()
            .map(|parts| parts.collect())
            .unwrap_or_default();
        let id = if matches!(url.host_str(), Some("youtu.be" | "www.youtu.be")) && parts.len() == 1
        {
            Some(parts[0].to_owned())
        } else if url.path() == "/watch" {
            url.query_pairs()
                .find(|(key, _)| key == "v")
                .map(|(_, value)| value.into_owned())
        } else if parts.len() == 2 && matches!(parts[0], "shorts" | "embed" | "live") {
            Some(parts[1].to_owned())
        } else {
            None
        };
        let id = id
            .filter(|id| {
                id.len() == 11
                    && id
                        .bytes()
                        .all(|b| b.is_ascii_alphanumeric() || b == b'-' || b == b'_')
            })
            .ok_or("Usa o URL de um vídeo YouTube; canais e playlists não são suportados.")?;
        Ok(Input {
            provider: self.id(),
            url: format!("https://www.youtube.com/watch?v={id}"),
        })
    }
    fn capabilities(&self) -> Capabilities {
        Capabilities {
            provider: self.id(),
            live_chat: false,
            replay_chat: false,
            replay_heatmap: true,
        }
    }
    fn prepare<'a>(
        &'a self,
        url: &'a str,
        start: Option<f64>,
        end: Option<f64>,
        profile: &'a ClipProfile,
        cancel: Arc<AtomicBool>,
    ) -> Preparation<'a> {
        Box::pin(async move {
            let info = youtube::extract(url, cancel).await?;
            let (source, analysis) = youtube::analyze_with_profile(info, start, end, profile)?;
            Ok(PreparedSource::Video(source, analysis))
        })
    }
}

pub struct ProviderRegistry {
    providers: Vec<Box<dyn SourceProvider>>,
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn registry_reports_only_implemented_acquisition_modes() {
        let registry = ProviderRegistry::default();
        let capabilities = registry.capabilities();
        assert_eq!(capabilities.len(), 2);
        assert!(
            capabilities
                .iter()
                .find(|item| item.provider == "twitch")
                .unwrap()
                .live_chat
        );
        let youtube = capabilities
            .iter()
            .find(|item| item.provider == "youtube")
            .unwrap();
        assert!(youtube.replay_heatmap);
        assert!(!youtube.live_chat);
        assert!(registry.resolve("https://kick.com/example").is_err());
    }
}
impl Default for ProviderRegistry {
    fn default() -> Self {
        Self {
            providers: vec![Box::new(TwitchProvider), Box::new(YouTubeProvider)],
        }
    }
}
impl ProviderRegistry {
    pub fn resolve(&self, input: &str) -> Result<Input, String> {
        let url = Url::parse(input.trim())
            .map_err(|_| "Introduz um URL HTTPS da Twitch ou do YouTube.")?;
        let host = url.host_str().unwrap_or("");
        let provider=self.providers.iter().find(|provider|provider.accepts(host))
            .ok_or("Origem ainda não suportada. Usa twitch.tv, clips.twitch.tv, youtube.com ou youtu.be.")?;
        provider.normalize(input, &url)
    }
    pub fn capabilities(&self) -> Vec<Capabilities> {
        self.providers
            .iter()
            .map(|provider| provider.capabilities())
            .collect()
    }
    pub async fn prepare(
        &self,
        input: &Input,
        start: Option<f64>,
        end: Option<f64>,
        profile: &ClipProfile,
        cancel: Arc<AtomicBool>,
    ) -> Result<PreparedSource, String> {
        let provider = self
            .providers
            .iter()
            .find(|provider| provider.id() == input.provider())
            .ok_or("Adapter indisponível.")?;
        let url = input.url.as_str();
        provider.prepare(url, start, end, profile, cancel).await
    }
}
