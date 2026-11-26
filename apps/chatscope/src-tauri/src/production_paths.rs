use std::{
    path::PathBuf,
    sync::atomic::{AtomicU64, Ordering},
};
static JOB_SEQUENCE: AtomicU64 = AtomicU64::new(0);
pub fn generate_job_id() -> String {
    format!(
        "{}-{}",
        chrono::Utc::now().format("%Y%m%dT%H%M%S%f"),
        JOB_SEQUENCE.fetch_add(1, Ordering::Relaxed)
    )
}

pub fn daily_output_root() -> PathBuf {
    if std::env::args().any(|arg| arg == "--isolated-test") {
        return PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../artifacts/media-native");
    }
    if let Ok(executable) = std::env::current_exe() {
        for candidate in executable.ancestors().skip(1).take(7) {
            if candidate.join("apps/chatscope").is_dir() {
                return candidate.join("media/daily");
            }
        }
    }
    // A portable dist lives inside apps/chatscope. CLI and installed copies use
    // the build's workspace, falling back to app-local storage when unavailable.
    let project = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../..");
    if project.join("apps/chatscope").is_dir() {
        return project.join("media/daily");
    }
    std::env::var_os("LOCALAPPDATA")
        .map(PathBuf::from)
        .unwrap_or_else(std::env::temp_dir)
        .join("ChatScope/media/daily")
}
