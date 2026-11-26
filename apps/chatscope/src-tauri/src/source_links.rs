pub fn youtube_timestamp_url(id: &str, start: f64) -> String {
    format!(
        "https://www.youtube.com/watch?v={id}&t={}s",
        start.floor() as u64
    )
}
