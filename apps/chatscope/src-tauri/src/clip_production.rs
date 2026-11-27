//! Persistent clip-batch coordinator, ownership lease and restart recovery.
use crate::{
    clip_profiles::{ClipProfile, RenderProfile},
    domain_models::{ClipCandidate, MediaSource, VideoAnalysis},
    media_worker_client::run_media_worker,
    production_paths::{daily_output_root, generate_job_id},
    production_store::{load_production_state, save_production_state, write_json_atomically},
};
use serde_json::{Value, json};
use std::{
    path::{Path, PathBuf},
    sync::{
        Arc, Mutex,
        atomic::{AtomicBool, Ordering},
    },
};
pub struct ClipProductionManager {
    pub is_running: bool,
    pub cancellation_requested: Arc<AtomicBool>,
    pub output_root: PathBuf,
    lease: Option<std::fs::File>,
}
pub type SharedClipProduction = Arc<Mutex<ClipProductionManager>>;
impl ClipProductionManager {
    fn lease(output_root: &Path) -> Option<std::fs::File> {
        std::fs::create_dir_all(output_root).ok()?;
        let mut options = std::fs::OpenOptions::new();
        options.read(true).write(true).create(true).truncate(false);
        #[cfg(windows)]
        {
            use std::os::windows::fs::OpenOptionsExt;
            options.share_mode(0);
        }
        options.open(output_root.join("production.lock")).ok()
    }
    pub fn writable(&self) -> bool {
        self.lease.is_some() || Self::lease(&self.output_root).is_some()
    }
    pub fn reserve(&mut self) -> Result<(), String> {
        if self.lease.is_none() {
            self.lease = Self::lease(&self.output_root);
        }
        if self.lease.is_none() {
            return Err("Outra produção está em curso nesta pasta.".into());
        }
        Ok(())
    }
    pub fn new(output_root: PathBuf) -> Self {
        let lease = Self::lease(&output_root);
        let mut manager = Self {
            is_running: false,
            cancellation_requested: Arc::new(AtomicBool::new(false)),
            output_root,
            lease,
        };
        let mut value = manager.snapshot();
        if manager.writable() && value["status"] == "running" {
            mark_incomplete(
                &mut value,
                "interrupted",
                "A aplicação foi fechada durante a produção. Podes retomar os incompletos.",
            );
            let _ = manager.persist_state(&value);
        }
        manager.lease = None;
        manager
    }
    pub fn snapshot(&self) -> Value {
        let mut value = load_production_state(&self.output_root);
        value["busy"] = json!(self.is_running || !self.writable());
        value["writable"] = json!(self.writable());
        if !self.writable() {
            value["detail"] =
                json!("Outra produção está em curso nesta pasta. Aguarda que termine.");
        }
        value["outputRoot"] = json!(self.output_root);
        value
    }
    fn persist_state(&self, state: &Value) -> Result<(), String> {
        save_production_state(&self.output_root, state)
    }
}
fn mark_incomplete(value: &mut Value, status: &str, detail: &str) {
    value["status"] = json!(status);
    value["detail"] = json!(detail);
    if let Some(clips) = value["clips"].as_array_mut() {
        for clip in clips {
            if clip["status"] != "ready" && clip["status"] != "error" {
                clip["status"] = json!(status);
            }
        }
    }
}

pub fn build_render_job_request(
    source: &MediaSource,
    analysis: Option<&VideoAnalysis>,
    clip_candidates: Vec<ClipCandidate>,
    clip_profile: &ClipProfile,
    render_profile: RenderProfile,
    topic: &str,
) -> Result<Value, String> {
    render_profile.validate()?;
    clip_profile.validate()?;
    if topic.is_empty()
        || topic.len() > 48
        || !topic
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-')
    {
        return Err("O tema só pode conter letras, números, _ e -.".into());
    }
    let end = source.end.or(source.duration).ok_or(
        "Este direto não tem um master. Usa o modo Vídeo/áudio para capturar e criar MP4.",
    )?;
    if clip_candidates.is_empty()
        || clip_candidates.len() > 30
        || clip_candidates.iter().any(|m| {
            !m.start.is_finite()
                || !m.end.is_finite()
                || m.start < source.start
                || m.end > end + 0.001
                || m.end <= m.start
                || m.end - m.start > 180.001
        })
    {
        return Err("Seleciona entre 1 e 30 intervalos válidos, com até 180 segundos.".into());
    }
    let mut source = source.clone();
    source.end = Some(end);
    Ok(
        json!({"action":"render","id":generate_job_id(),"root":daily_output_root(),"source":source,"moments":clip_candidates,
        "clipProfile":clip_profile,"renderProfile":render_profile,"topic":topic,
        "localMedia":analysis.and_then(|a|a.local_media.clone()),"mediaOrigin":analysis.map_or(0.0,|a|a.master_source_offset_seconds)}),
    )
}

pub fn start_clip_production(
    shared: SharedClipProduction,
    mut request: Value,
) -> Result<(), String> {
    let cancellation_requested = {
        let mut manager = shared.lock().map_err(|_| "Produção indisponível.")?;
        if manager.is_running {
            return Err("Já existe uma produção em curso.".into());
        }
        manager.reserve()?;
        request["root"] = json!(manager.output_root);
        write_json_atomically(
            &manager.output_root.join("requests").join(format!(
                "{}.json",
                request["id"].as_str().ok_or("Job inválido.")?
            )),
            &request,
        )?;
        manager.persist_state(&json!({"id":request["id"],"status":"running","clips":[],"detail":"A preparar a produção local…"}))?;
        manager.is_running = true;
        manager.cancellation_requested = Arc::new(AtomicBool::new(false));
        manager.cancellation_requested.clone()
    };
    tauri::async_runtime::spawn(async move {
        let outcome = run_media_worker(&request, cancellation_requested.clone(), 21600).await;
        if let Ok(mut manager) = shared.lock() {
            let mut value = manager.snapshot();
            if let Err(error) = outcome {
                mark_incomplete(
                    &mut value,
                    if cancellation_requested.load(Ordering::Relaxed) {
                        "cancelled"
                    } else {
                        "error"
                    },
                    &error,
                );
                let _ = manager.persist_state(&value);
            }
            manager.is_running = false;
            manager.lease = None;
        }
    });
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn recovery_preserves_completed_clips_and_marks_work_interrupted() {
        let output_root = std::env::temp_dir().join(generate_job_id());
        write_json_atomically(&output_root.join("current.json"), &json!({"status":"running","clips":[{"status":"ready","path":"keep.mp4"},{"status":"rendering"}]})).unwrap();
        let manager = ClipProductionManager::new(output_root);
        let value = manager.snapshot();
        assert_eq!(value["status"], "interrupted");
        assert_eq!(value["clips"][0]["path"], "keep.mp4");
        assert_eq!(value["clips"][1]["status"], "interrupted");
    }
    #[test]
    fn render_profile_rejects_unknown_layouts() {
        let profile = RenderProfile {
            aspect_ratio: "arbitrary".into(),
            ..Default::default()
        };
        assert!(profile.validate().is_err());
    }
    #[test]
    #[cfg(windows)]
    fn another_instance_cannot_take_over_running_production() {
        let output_root = std::env::temp_dir().join(generate_job_id());
        let mut first = ClipProductionManager::new(output_root.clone());
        first.reserve().unwrap();
        first
            .persist_state(&json!({"status":"running","clips":[]}))
            .unwrap();
        let second = ClipProductionManager::new(output_root.clone());
        assert!(!second.writable());
        assert_eq!(second.snapshot()["status"], "running");
        drop(second);
        drop(first);
        let recovered = ClipProductionManager::new(output_root);
        assert!(recovered.writable());
        assert_eq!(recovered.snapshot()["status"], "interrupted");
    }
}
