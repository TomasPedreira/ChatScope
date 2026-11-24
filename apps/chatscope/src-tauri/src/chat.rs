use chrono::Utc;
use futures_util::{SinkExt, StreamExt};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::{
    collections::{HashMap, HashSet},
    sync::{
        Arc,
        atomic::{AtomicBool, Ordering},
    },
    time::{Duration, Instant},
};
use tokio_tungstenite::{connect_async, tungstenite::Message};
use url::Url;

// Public client identifier used by TwitchDownloader; this is not a user token.
const CLIENT_ID: &str = "kd1unb4b3q4t58fwlpcbzcbnm76a8fp";
const COMMENTS_HASH: &str = "b70a3591ff0f4e0313d126c6a1502d79a1c02baebb288227c582044aa76adf6a";
pub const MAX_MESSAGES: usize = 250_000;

pub use crate::scope::Source;

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ChatMessage {
    pub id: String,
    pub offset: f64,
    pub timestamp: String,
    pub user: String,
    pub text: String,
    pub color: String,
    pub reaction: bool,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Highlight {
    pub start: f64,
    pub end: f64,
    pub messages: usize,
    pub reactions: usize,
    pub users: usize,
    pub score: u32,
    pub reason: String,
}

#[derive(Clone, Debug, Default, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Analysis {
    pub users: usize,
    pub reactions: usize,
    pub bins: Vec<Bin>,
    pub highlights: Vec<Highlight>,
}

#[derive(Clone, Debug, Serialize)]
pub struct Bin {
    pub start: f64,
    pub messages: usize,
    pub reactions: usize,
}

pub enum Update {
    Source(Source),
    Messages(Vec<ChatMessage>, f64),
    Status(String, String),
}

fn valid_id(id: &str) -> bool {
    !id.is_empty() && id.len() <= 24 && id.bytes().all(|c| c.is_ascii_digit())
}
fn valid_login(id: &str) -> bool {
    !id.is_empty() && id.len() <= 25 && id.bytes().all(|c| c.is_ascii_alphanumeric() || c == b'_')
}

pub fn parse_time(input: &str) -> Result<f64, String> {
    let input = input.trim();
    if input.is_empty() {
        return Ok(0.0);
    }
    if let Ok(n) = input.parse::<f64>() {
        return if n.is_finite() && (0.0..=604800.0).contains(&n) {
            Ok(n)
        } else {
            Err("Tempo inválido.".into())
        };
    }
    if input.contains(':') {
        let parts: Vec<_> = input.split(':').collect();
        if !(2..=3).contains(&parts.len()) {
            return Err("Usa HH:MM:SS ou segundos.".into());
        }
        let mut total = 0.0;
        for (i, part) in parts.iter().enumerate() {
            let n: f64 = part.parse().map_err(|_| "Tempo inválido.")?;
            if !n.is_finite() || n < 0.0 || (i > 0 && n >= 60.0) {
                return Err("Tempo inválido.".into());
            }
            total = total * 60.0 + n;
        }
        return if total <= 604800.0 {
            Ok(total)
        } else {
            Err("Intervalo demasiado longo.".into())
        };
    }
    let mut total = 0u32;
    let mut digits = String::new();
    for c in input.chars() {
        if c.is_ascii_digit() {
            digits.push(c);
            continue;
        }
        let multiplier = match c {
            'h' => 3600,
            'm' => 60,
            's' => 1,
            _ => return Err("Tempo inválido.".into()),
        };
        let n: u32 = digits.parse().map_err(|_| "Tempo inválido.")?;
        total = total
            .checked_add(n.checked_mul(multiplier).ok_or("Tempo inválido.")?)
            .ok_or("Tempo inválido.")?;
        digits.clear();
    }
    if !digits.is_empty() || total > 604800 {
        return Err("Tempo inválido.".into());
    }
    Ok(total as f64)
}

pub fn parse_source(input: &str) -> Result<Source, String> {
    let raw = input.trim();
    let normalized = if raw.starts_with("twitch.tv/")
        || raw.starts_with("www.twitch.tv/")
        || raw.starts_with("clips.twitch.tv/")
    {
        format!("https://{raw}")
    } else {
        raw.to_owned()
    };
    let url = Url::parse(&normalized).map_err(|_| "Cola um URL da Twitch válido.")?;
    if url.scheme() != "https"
        || !url.username().is_empty()
        || url.password().is_some()
        || url.port().is_some()
    {
        return Err("Usa um URL HTTPS da Twitch.".into());
    }
    let host = url.host_str().unwrap_or("");
    if ![
        "twitch.tv",
        "www.twitch.tv",
        "m.twitch.tv",
        "clips.twitch.tv",
    ]
    .contains(&host)
    {
        return Err("O URL tem de pertencer a twitch.tv.".into());
    }
    let path: Vec<_> = url
        .path_segments()
        .unwrap_or_else(|| unreachable!())
        .filter(|s| !s.is_empty())
        .collect();
    let (kind, id) = match path.as_slice() {
        ["videos", id] if host != "clips.twitch.tv" && valid_id(id) => ("vod", id.to_string()),
        [slug] if host == "clips.twitch.tv" => ("clip", slug.to_string()),
        [_, "clip", slug] if host != "clips.twitch.tv" => ("clip", slug.to_string()),
        [login]
            if host != "clips.twitch.tv"
                && valid_login(login)
                && ![
                    "directory",
                    "downloads",
                    "settings",
                    "videos",
                    "subscriptions",
                    "search",
                    "wallet",
                    "inventory",
                ]
                .contains(login) =>
        {
            ("live", login.to_lowercase())
        }
        _ => return Err("Usa twitch.tv/canal, twitch.tv/videos/ID ou um URL de clip.".into()),
    };
    if kind == "clip"
        && (id.len() > 200
            || !id
                .bytes()
                .all(|c| c.is_ascii_alphanumeric() || c == b'_' || c == b'-'))
    {
        return Err("Identificador de clip inválido.".into());
    }
    let start = url
        .query_pairs()
        .find(|(k, _)| k == "t")
        .map(|(_, v)| parse_time(&v))
        .transpose()?
        .unwrap_or(0.0);
    Ok(Source {
        url: normalized,
        kind: kind.into(),
        id,
        channel: String::new(),
        title: String::new(),
        duration: None,
        start,
        end: None,
    })
}

fn client() -> Result<reqwest::Client, String> {
    reqwest::Client::builder()
        .timeout(Duration::from_secs(25))
        .user_agent("ChatScope/0.1")
        .build()
        .map_err(|e| e.to_string())
}

async fn gql(client: &reqwest::Client, body: Value) -> Result<Value, String> {
    let mut last_error = String::new();
    for attempt in 0..3u64 {
        let response = client
            .post("https://gql.twitch.tv/gql")
            .header("Client-ID", CLIENT_ID)
            .json(&body)
            .send()
            .await;
        match response {
            Ok(response) if response.status().is_success() => {
                let data: Value = response
                    .json()
                    .await
                    .map_err(|e| format!("Resposta Twitch inválida: {e}"))?;
                if let Some(errors) = data.get("errors") {
                    return Err(format!("A Twitch recusou o pedido: {}", errors));
                }
                return Ok(data);
            }
            Ok(response) => {
                let status = response.status();
                if !status.is_server_error() && status.as_u16() != 429 {
                    return Err(format!(
                        "Twitch HTTP {status}. O conteúdo pode estar indisponível."
                    ));
                }
                last_error = format!("Twitch HTTP {status}");
            }
            Err(e) => last_error = format!("Não foi possível contactar a Twitch: {e}"),
        }
        if attempt < 2 {
            tokio::time::sleep(Duration::from_secs((attempt + 1) * 2)).await;
        }
    }
    Err(last_error)
}

pub async fn example_vod() -> Result<Value, String> {
    let data = gql(&client()?, json!({"query":"{ user(login: \"xqc\") { videos(first: 1, type: ARCHIVE, sort: TIME) { edges { node { id lengthSeconds } } } } }"})).await?;
    let video = &data["data"]["user"]["videos"]["edges"][0]["node"];
    let id = video["id"]
        .as_str()
        .ok_or("Não foi encontrado um VOD recente. Cola um URL à tua escolha.")?;
    let duration = video["lengthSeconds"].as_f64().unwrap_or(300.0);
    let start: f64 = if duration > 900.0 { 600.0 } else { 0.0 };
    Ok(
        json!({"url":format!("https://www.twitch.tv/videos/{id}"),"start":start,"end":(start + 300.0).min(duration)}),
    )
}

pub async fn resolve(input: &str, start: Option<f64>, end: Option<f64>) -> Result<Source, String> {
    let mut source = parse_source(input)?;
    let http = client()?;
    if source.kind == "live" {
        let data = gql(&http, json!({"query":"query($login: String!) { user(login: $login) { displayName stream { title } } }", "variables":{"login":source.id}})).await?;
        let user = &data["data"]["user"];
        if user.is_null() {
            return Err("Este canal não existe.".into());
        }
        source.channel = user["displayName"].as_str().unwrap_or(&source.id).into();
        source.title = user["stream"]["title"]
            .as_str()
            .unwrap_or("Chat do canal · o canal pode estar offline")
            .into();
        source.start = 0.0;
        source.end = None;
        return Ok(source);
    }
    if source.kind == "clip" {
        let data = gql(&http, json!({"query":"query($slug: ID!) { clip(slug: $slug) { title durationSeconds videoOffsetSeconds broadcaster { displayName } video { id lengthSeconds } } }", "variables":{"slug":source.id}})).await?;
        let clip = &data["data"]["clip"];
        if clip.is_null() {
            return Err("Clip não encontrado.".into());
        }
        let video_id = clip["video"]["id"].as_str().ok_or(
            "O VOD de origem deste clip já não está disponível; o chat não pode ser recuperado.",
        )?;
        source.id = video_id.into();
        source.start = clip["videoOffsetSeconds"]
            .as_f64()
            .ok_or("Este clip não tem posição no VOD.")?;
        source.end = Some(source.start + clip["durationSeconds"].as_f64().unwrap_or(30.0));
        source.title = clip["title"].as_str().unwrap_or("Clip Twitch").into();
        source.channel = clip["broadcaster"]["displayName"]
            .as_str()
            .unwrap_or("")
            .into();
        source.duration = clip["video"]["lengthSeconds"].as_f64();
    } else {
        let data = gql(&http, json!({"query":"query($id: ID!) { video(id: $id) { title lengthSeconds owner { displayName } } }", "variables":{"id":source.id}})).await?;
        let video = &data["data"]["video"];
        if video.is_null() {
            return Err("VOD não encontrado, expirado ou privado.".into());
        }
        source.title = video["title"].as_str().unwrap_or("VOD Twitch").into();
        source.channel = video["owner"]["displayName"].as_str().unwrap_or("").into();
        source.duration = video["lengthSeconds"].as_f64();
    }
    if let Some(value) = start {
        source.start = value;
    }
    if let Some(value) = end {
        source.end = Some(value);
    }
    if source.end.is_none() {
        source.end = source.duration;
    }
    if !source.start.is_finite()
        || source.start < 0.0
        || source.duration.is_some_and(|d| source.start >= d)
    {
        return Err("O início está fora da duração do VOD.".into());
    }
    if source.end.is_some_and(|e| {
        !e.is_finite() || e <= source.start || source.duration.is_some_and(|d| e > d + 1.0)
    }) {
        return Err("O fim tem de ser posterior ao início e estar dentro do VOD.".into());
    }
    Ok(source)
}

pub fn is_reaction(text: &str) -> bool {
    text.split(|c: char| !c.is_alphanumeric())
        .filter(|s| !s.is_empty())
        .any(|token| {
            let t = token.to_lowercase();
            matches!(
                t.as_str(),
                "lul"
                    | "lulw"
                    | "omegalul"
                    | "lol"
                    | "lmao"
                    | "lmfao"
                    | "kekw"
                    | "kekl"
                    | "pog"
                    | "pogchamp"
                    | "poggers"
                    | "haha"
                    | "hahaha"
                    | "hahahaha"
                    | "ahah"
                    | "ahahah"
                    | "ri"
                    | "riso"
                    | "😂"
                    | "🤣"
            ) || (t.len() >= 3 && t.bytes().all(|c| c == b'k'))
        })
        || text.contains('😂')
        || text.contains('🤣')
}

fn unescape_tag(text: &str) -> String {
    let mut result = String::new();
    let mut chars = text.chars();
    while let Some(c) = chars.next() {
        if c == '\\' {
            match chars.next() {
                Some('s') => result.push(' '),
                Some(':') => result.push(';'),
                Some('r') => result.push('\r'),
                Some('n') => result.push('\n'),
                Some(c) => result.push(c),
                None => {}
            }
        } else {
            result.push(c);
        }
    }
    result
}

pub fn parse_irc(line: &str, elapsed: f64) -> Option<ChatMessage> {
    let (tags, rest) = if let Some(tagged) = line.strip_prefix('@') {
        tagged.split_once(' ')?
    } else {
        ("", line)
    };
    let (prefix, rest) = rest.strip_prefix(':')?.split_once(' ')?;
    let (command, rest) = rest.split_once(' ')?;
    if command != "PRIVMSG" {
        return None;
    }
    let (_, text) = rest.split_once(" :")?;
    let mut fields = HashMap::new();
    for field in tags.split(';') {
        if let Some((key, value)) = field.split_once('=') {
            fields.insert(key, value);
        }
    }
    let user = fields
        .get("display-name")
        .filter(|s| !s.is_empty())
        .map(|s| unescape_tag(s))
        .unwrap_or_else(|| prefix.split('!').next().unwrap_or("unknown").into());
    let timestamp = fields
        .get("tmi-sent-ts")
        .and_then(|s| s.parse::<i64>().ok())
        .and_then(chrono::DateTime::from_timestamp_millis)
        .map(|t| t.to_rfc3339())
        .unwrap_or_else(|| Utc::now().to_rfc3339());
    let text = text
        .trim_start_matches("\u{1}ACTION ")
        .trim_end_matches('\u{1}')
        .to_string();
    Some(ChatMessage {
        id: fields
            .get("id")
            .map(|s| s.to_string())
            .unwrap_or_else(|| format!("{prefix}-{timestamp}-{elapsed}")),
        offset: elapsed,
        timestamp,
        user,
        reaction: is_reaction(&text),
        text,
        color: fields.get("color").unwrap_or(&"").to_string(),
    })
}

pub async fn capture<F>(
    source: Source,
    cancel: Arc<AtomicBool>,
    mut notify: F,
) -> Result<(), String>
where
    F: FnMut(Update) + Send,
{
    notify(Update::Source(source.clone()));
    if source.kind == "live" {
        capture_live(&source, cancel, &mut notify).await
    } else {
        capture_vod(&source, cancel, &mut notify).await
    }
}

async fn capture_live<F: FnMut(Update) + Send>(
    source: &Source,
    cancel: Arc<AtomicBool>,
    notify: &mut F,
) -> Result<(), String> {
    let started = Instant::now();
    let mut count = 0usize;
    let mut seen = HashSet::new();
    let mut failures = 0;
    loop {
        if cancel.load(Ordering::Relaxed) {
            return Ok(());
        }
        notify(Update::Status(
            "connecting".into(),
            if failures > 0 {
                "A restabelecer a ligação…"
            } else {
                "A ligar ao chat público…"
            }
            .into(),
        ));
        let connection = tokio::time::timeout(
            Duration::from_secs(20),
            connect_async("wss://irc-ws.chat.twitch.tv:443"),
        )
        .await;
        let (mut socket, _) = match connection {
            Ok(Ok(socket)) => socket,
            _ => {
                failures += 1;
                if failures >= 4 {
                    return Err("Não foi possível ligar ao chat após 4 tentativas.".into());
                }
                tokio::time::sleep(Duration::from_secs(2)).await;
                continue;
            }
        };
        let nick = format!(
            "justinfan{}",
            Utc::now().timestamp_millis().unsigned_abs() % 90_000_000 + 10_000_000
        );
        for command in [
            "CAP REQ :twitch.tv/tags twitch.tv/commands".to_string(),
            "PASS SCHMOOPIIE".to_string(),
            format!("NICK {nick}"),
            format!("JOIN #{}", source.id),
        ] {
            socket
                .send(Message::Text(format!("{command}\r\n").into()))
                .await
                .map_err(|e| e.to_string())?;
        }
        let mut ticker = tokio::time::interval(Duration::from_millis(250));
        let mut joined = false;
        let mut last_received = Instant::now();
        loop {
            tokio::select! {
                _ = ticker.tick() => {
                    if cancel.load(Ordering::Relaxed) { let _ = socket.close(None).await; return Ok(()); }
                    if last_received.elapsed() > Duration::from_secs(300) || (!joined && last_received.elapsed() > Duration::from_secs(20)) { break; }
                }
                frame = socket.next() => {
                    match frame {
                        Some(Ok(Message::Text(text))) => {
                            last_received = Instant::now();
                            let mut batch = Vec::new();
                            let mut reconnect = false;
                            for line in text.split("\r\n").filter(|s| !s.is_empty()) {
                                if line.starts_with("PING") { socket.send(Message::Text(line.replacen("PING", "PONG", 1).into())).await.map_err(|e| e.to_string())?; }
                                if line.contains(" RECONNECT") { reconnect = true; break; }
                                if (line.contains(" 366 ") || line.contains(" ROOMSTATE ")) && !joined {
                                    notify(Update::Status("live".into(), "Ligado · a receber mensagens reais".into())); joined = true; failures = 0;
                                }
                                if line.contains("Login authentication failed") || line.contains("Improperly formatted auth") { return Err("A Twitch recusou a leitura anónima do chat.".into()); }
                                if let Some(message) = parse_irc(line, started.elapsed().as_secs_f64()) && seen.insert(message.id.clone()) {
                                    batch.push(message); count += 1;
                                }
                            }
                            if !batch.is_empty() { notify(Update::Messages(batch, started.elapsed().as_secs_f64())); }
                            if count >= MAX_MESSAGES { return Err("Limite de 250 000 mensagens atingido. Exporta esta sessão e inicia outra.".into()); }
                            if reconnect { break; }
                        }
                        Some(Ok(Message::Ping(data))) => { let _ = socket.send(Message::Pong(data)).await; }
                        Some(Ok(Message::Close(_))) | None | Some(Err(_)) => break,
                        _ => {}
                    }
                }
            }
        }
        failures += 1;
        if failures >= 4 {
            return Err("A ligação ao chat foi interrompida. As mensagens capturadas continuam disponíveis.".into());
        }
        tokio::time::sleep(Duration::from_secs(2)).await;
    }
}

async fn capture_vod<F: FnMut(Update) + Send>(
    source: &Source,
    cancel: Arc<AtomicBool>,
    notify: &mut F,
) -> Result<(), String> {
    let http = client()?;
    let mut cursor: Option<String> = None;
    let mut seen = HashSet::new();
    let mut cursors = HashSet::new();
    notify(Update::Status(
        "downloading".into(),
        "A extrair o replay do chat…".into(),
    ));
    loop {
        if cancel.load(Ordering::Relaxed) {
            return Ok(());
        }
        let variables = match &cursor {
            Some(c) => json!({"videoID":source.id, "cursor":c}),
            None => {
                json!({"videoID":source.id, "contentOffsetSeconds":source.start.floor() as u64})
            }
        };
        let data = tokio::select! {
            result = gql(&http, json!({"operationName":"VideoCommentsByOffsetOrCursor", "variables":variables, "extensions":{"persistedQuery":{"version":1,"sha256Hash":COMMENTS_HASH}}})) => result?,
            _ = async { while !cancel.load(Ordering::Relaxed) { tokio::time::sleep(Duration::from_millis(200)).await; } } => return Ok(()),
        };
        let comments = &data["data"]["video"]["comments"];
        if comments.is_null() {
            return Err("O replay do chat não está disponível para este VOD.".into());
        }
        let edges = comments["edges"]
            .as_array()
            .ok_or("A Twitch devolveu um formato de chat inesperado.")?;
        let mut batch = Vec::new();
        let mut latest = source.start;
        let mut reached_end = false;
        for edge in edges {
            let node = &edge["node"];
            let offset = node["contentOffsetSeconds"]
                .as_f64()
                .ok_or("Mensagem sem timestamp no VOD.")?;
            latest = latest.max(offset);
            if source.end.is_some_and(|end| offset >= end) {
                reached_end = true;
                continue;
            }
            if offset < source.start {
                continue;
            }
            let id = node["id"].as_str().ok_or("Mensagem sem identificador.")?;
            if !seen.insert(id.to_owned()) {
                continue;
            }
            let text: String = node["message"]["fragments"]
                .as_array()
                .map(|a| a.iter().filter_map(|f| f["text"].as_str()).collect())
                .unwrap_or_default();
            batch.push(ChatMessage {
                id: id.into(),
                offset,
                timestamp: node["createdAt"].as_str().unwrap_or("").into(),
                user: node["commenter"]["displayName"]
                    .as_str()
                    .unwrap_or("[utilizador removido]")
                    .into(),
                reaction: is_reaction(&text),
                text,
                color: node["message"]["userColor"].as_str().unwrap_or("").into(),
            });
        }
        notify(Update::Messages(
            batch,
            source.end.map(|e| latest.min(e)).unwrap_or(latest),
        ));
        if seen.len() >= MAX_MESSAGES {
            return Err("Limite de 250 000 mensagens atingido. Exporta esta sessão e seleciona um intervalo menor.".into());
        }
        if reached_end
            || !comments["pageInfo"]["hasNextPage"]
                .as_bool()
                .unwrap_or(false)
        {
            break;
        }
        let next = edges
            .last()
            .and_then(|e| e["cursor"].as_str())
            .ok_or("Paginação do chat incompleta.")?
            .to_string();
        if !cursors.insert(next.clone()) {
            return Err("A Twitch repetiu uma página; extração interrompida para evitar omissões silenciosas.".into());
        }
        cursor = Some(next);
        tokio::time::sleep(Duration::from_millis(120)).await;
    }
    Ok(())
}

pub fn analyze(messages: &[ChatMessage]) -> Analysis {
    analyze_internal(messages, true)
}

pub fn analyze_signals(messages: &[ChatMessage]) -> Analysis {
    analyze_internal(messages, false)
}

fn analyze_internal(messages: &[ChatMessage], select_legacy_highlights: bool) -> Analysis {
    let mut analysis = Analysis::default();
    if messages.is_empty() {
        return analysis;
    }
    let users: HashSet<_> = messages.iter().map(|m| m.user.to_lowercase()).collect();
    analysis.users = users.len();
    analysis.reactions = messages.iter().filter(|m| m.reaction).count();
    let first = (messages.first().unwrap().offset / 10.0).floor() as usize;
    let last = (messages.last().unwrap().offset / 10.0).floor() as usize;
    let mut buckets: HashMap<usize, Vec<&ChatMessage>> = HashMap::new();
    for message in messages {
        buckets
            .entry((message.offset / 10.0).floor() as usize)
            .or_default()
            .push(message);
    }
    let baseline = messages.len() as f64 / (last - first + 1) as f64;
    for index in first..=last {
        let bucket = buckets.get(&index);
        let count = bucket.map_or(0, |b| b.len());
        let reactions = bucket.map_or(0, |b| b.iter().filter(|m| m.reaction).count());
        analysis.bins.push(Bin {
            start: index as f64 * 10.0,
            messages: count,
            reactions,
        });
        if let Some(bucket) = bucket {
            let unique = bucket
                .iter()
                .map(|m| m.user.to_lowercase())
                .collect::<HashSet<_>>()
                .len();
            if count >= 4 && reactions >= 2 && unique >= 3 {
                let ratio = reactions as f64 / count as f64;
                let boost = (count as f64 / baseline.max(1.0)).min(4.0);
                let score = ((ratio * 65.0 + boost * 8.0 + unique.min(20) as f64) as u32).min(100);
                analysis.highlights.push(Highlight { start: (index as f64 * 10.0 - 10.0).max(0.0), end: (index + 1) as f64 * 10.0, messages: count, reactions, users: unique, score, reason: format!("{reactions} reações de riso/entusiasmo · {unique} participantes · {boost:.1}× atividade média") });
            }
        }
    }
    analysis
        .highlights
        .sort_by_key(|h| std::cmp::Reverse(h.score));
    if select_legacy_highlights {
    let mut selected: Vec<Highlight> = Vec::new();
    for candidate in analysis.highlights.drain(..) {
        if selected
            .iter()
            .all(|h| candidate.end <= h.start || candidate.start >= h.end)
        {
            selected.push(candidate);
        }
        if selected.len() == 8 {
            break;
        }
    }
    analysis.highlights = selected;
    }
    // Keep the chart bounded even for very long VODs, including zero-activity gaps.
    if analysis.bins.len() > 80 {
        let size = analysis.bins.len().div_ceil(80);
        analysis.bins = analysis
            .bins
            .chunks(size)
            .map(|chunk| Bin {
                start: chunk[0].start,
                messages: chunk.iter().map(|b| b.messages).sum(),
                reactions: chunk.iter().map(|b| b.reactions).sum(),
            })
            .collect();
    }
    analysis
}

pub(crate) fn csv_cell(value: &str) -> String {
    let safe = if value.starts_with(['=', '+', '-', '@', '\t', '\r', '\n']) {
        format!("'{value}")
    } else {
        value.into()
    };
    format!("\"{}\"", safe.replace('"', "\"\""))
}

pub fn export_csv(messages: &[ChatMessage]) -> String {
    let mut csv = String::from("\u{feff}offset_seconds,timestamp,user,message,reaction\r\n");
    for message in messages {
        csv.push_str(&format!(
            "{:.3},{},{},{},{}\r\n",
            message.offset,
            csv_cell(&message.timestamp),
            csv_cell(&message.user),
            csv_cell(&message.text),
            message.reaction
        ));
    }
    csv
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn urls_and_time_ranges() {
        assert_eq!(
            parse_source("https://www.twitch.tv/videos/123?t=1h2m3s")
                .unwrap()
                .start,
            3723.0
        );
        assert_eq!(
            parse_source("twitch.tv/TwitchPlaysPokemon").unwrap().id,
            "twitchplayspokemon"
        );
        assert_eq!(
            parse_source("https://clips.twitch.tv/Good-Slug")
                .unwrap()
                .kind,
            "clip"
        );
        for url in [
            "https://twitch.tv.evil.com/foo",
            "http://twitch.tv/foo",
            "https://user:pass@twitch.tv/foo",
            "https://twitch.tv:444/foo",
            "https://twitch.tv/directory",
            "https://twitch.tv/videos/nope",
            "file:///etc/passwd",
        ] {
            assert!(parse_source(url).is_err(), "{url}");
        }
        assert_eq!(parse_time("1:02:03").unwrap(), 3723.0);
        assert!(parse_time("00:90").is_err());
        assert!(parse_time("NaN").is_err());
    }
    #[test]
    fn irc_unicode_tags_and_reactions() {
        let m = parse_irc("@display-name=João\\sP;id=abc;color=#00FF00;tmi-sent-ts=1700000000000 :joao!joao@joao PRIVMSG #canal :KEKW 😂 olá", 2.5).unwrap();
        assert_eq!(m.user, "João P");
        assert_eq!(m.text, "KEKW 😂 olá");
        assert!(m.reaction);
        assert_eq!(m.offset, 2.5);
        assert!(parse_irc("PING :tmi.twitch.tv", 0.0).is_none());
        assert!(!is_reaction("o gololo chegou"));
    }
    #[test]
    fn highlights_require_several_people_and_export_is_safe() {
        let messages: Vec<_> = (0..6)
            .map(|n| ChatMessage {
                id: n.to_string(),
                offset: 20.0 + n as f64,
                timestamp: String::new(),
                user: format!("user{n}"),
                text: "=1+1,\"olá\"\nKEKW".into(),
                color: String::new(),
                reaction: true,
            })
            .collect();
        let result = analyze(&messages);
        assert_eq!(result.highlights.len(), 1);
        assert_eq!(result.users, 6);
        let mut spam = messages.clone();
        for m in &mut spam {
            m.user = "one".into();
        }
        assert!(analyze(&spam).highlights.is_empty());
        assert!(export_csv(&messages).contains("\"'=1+1,\"\"olá\"\"\nKEKW\""));
    }
}
