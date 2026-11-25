//! One bounded subprocess boundary for all media adapters. Rust owns editorial policy
//! and lifecycle; Python owns extraction/FFmpeg integration, never uploads.
use crate::{
    clips::{ClipProfile, TimeRange},
    detectors::{AudioEnergyDetector, HeatmapDetector, MomentDetector},
    scope::{Moment, Source, VideoAnalysis},
};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::{
    path::{Path, PathBuf},
    process::Stdio,
    sync::{
        Arc, Mutex,
        atomic::{AtomicBool, AtomicU64, Ordering},
    },
    time::Duration,
};
use tokio::io::AsyncWriteExt;

static NEXT: AtomicU64 = AtomicU64::new(0);
pub fn id() -> String {
    format!(
        "{}-{}",
        chrono::Utc::now().format("%Y%m%dT%H%M%S%f"),
        NEXT.fetch_add(1, Ordering::Relaxed)
    )
}

pub fn root() -> PathBuf {
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

pub fn atomic_json(path: &Path, value: &Value) -> Result<(), String> {
    std::fs::create_dir_all(path.parent().ok_or("Destino inválido.")?)
        .map_err(|e| e.to_string())?;
    let temporary = path.with_extension("rust-tmp");
    std::fs::write(
        &temporary,
        serde_json::to_vec_pretty(value).map_err(|e| e.to_string())?,
    )
    .map_err(|e| e.to_string())?;
    for attempt in 0..12 {
        match std::fs::rename(&temporary, path) {
            Ok(()) => return Ok(()),
            Err(error) if error.kind() == std::io::ErrorKind::PermissionDenied && attempt < 11 => {
                std::thread::sleep(Duration::from_millis(25 * (attempt + 1)));
            }
            Err(error) => return Err(error.to_string()),
        }
    }
    Err("Não foi possível guardar o estado.".into())
}

fn runtime(root: &Path) -> Result<PathBuf, String> {
    let files = [
        ("__init__.py", include_str!("../../pipeline/__init__.py")),
        ("tools.py", include_str!("../../pipeline/tools.py")),
        ("providers.py", include_str!("../../pipeline/providers.py")),
        ("kick.py", include_str!("../../pipeline/kick.py")),
        ("signals.py", include_str!("../../pipeline/signals.py")),
        ("render.py", include_str!("../../pipeline/render.py")),
        ("captions.py", include_str!("../../pipeline/captions.py")),
        ("worker.py", include_str!("../../pipeline/worker.py")),
    ];
    use std::hash::{Hash, Hasher};
    let mut hash = std::collections::hash_map::DefaultHasher::new();
    for (_, content) in files {
        content.hash(&mut hash);
    }
    let folder = root.join("runtime").join(format!("{:x}", hash.finish()));
    let package = folder.join("pipeline");
    std::fs::create_dir_all(&package).map_err(|e| e.to_string())?;
    for (name, content) in files {
        let destination = package.join(name);
        if std::fs::read_to_string(&destination).ok().as_deref() != Some(content) {
            std::fs::write(destination, content).map_err(|e| e.to_string())?;
        }
    }
    Ok(folder)
}

// Windows closes the Job Object even if the desktop process itself exits.
// All descendants (including FFmpeg/Whisper subprocesses) die with the worker.
struct ProcessTree(isize);
impl ProcessTree {
    fn bind(pid: u32) -> Result<Self, String> {
        #[cfg(windows)]
        unsafe {
            use windows_sys::Win32::{
                Foundation::CloseHandle,
                System::{JobObjects::*, Threading::*},
            };
            let job = CreateJobObjectW(std::ptr::null(), std::ptr::null());
            if job.is_null() {
                return Err(std::io::Error::last_os_error().to_string());
            }
            let mut info: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = std::mem::zeroed();
            info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
            let process = OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, 0, pid);
            let configured = SetInformationJobObject(
                job,
                JobObjectExtendedLimitInformation,
                &info as *const _ as *const _,
                std::mem::size_of_val(&info) as u32,
            ) != 0;
            let assigned =
                !process.is_null() && configured && AssignProcessToJobObject(job, process) != 0;
            let error = std::io::Error::last_os_error();
            if !process.is_null() {
                CloseHandle(process);
            }
            if !assigned {
                CloseHandle(job);
                return Err(format!(
                    "Não foi possível isolar os processos de vídeo: {error}"
                ));
            }
            Ok(Self(job as isize))
        }
        #[cfg(not(windows))]
        {
            let _ = pid;
            Ok(Self(0))
        }
    }
}
impl Drop for ProcessTree {
    fn drop(&mut self) {
        #[cfg(windows)]
        unsafe {
            windows_sys::Win32::Foundation::CloseHandle(self.0 as *mut _);
        }
    }
}

pub async fn call(request: &Value, cancel: Arc<AtomicBool>, timeout: u64) -> Result<Value, String> {
    let path = PathBuf::from(
        request["root"]
            .as_str()
            .ok_or("Falta a pasta de produção.")?,
    );
    let runtime = runtime(&path)?;
    let mut command = tokio::process::Command::new(python_command());
    command.args(["-I", "-X", "utf8", "-u", "-c",
        "import runpy,sys;sys.path.insert(0,sys.argv[1]);runpy.run_module('pipeline.worker',run_name='__main__')"])
        .arg(runtime).stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::piped()).kill_on_drop(true);
    #[cfg(windows)]
    command.creation_flags(0x08000000);
    let mut child = command
        .spawn()
        .map_err(|_| "Não foi possível iniciar o worker. Executa Setup-Media.ps1.")?;
    let _tree = ProcessTree::bind(child.id().ok_or("Worker sem PID.")?)?;
    let mut input = child.stdin.take().ok_or("Worker sem entrada.")?;
    input
        .write_all(&serde_json::to_vec(request).map_err(|e| e.to_string())?)
        .await
        .map_err(|e| e.to_string())?;
    drop(input);
    let output = tokio::select! {
        result = tokio::time::timeout(Duration::from_secs(timeout), child.wait_with_output()) => {
            result.map_err(|_| "A operação excedeu o tempo limite; os clips concluídos foram preservados.")?
                .map_err(|e| e.to_string())?
        },
        _ = async { while !cancel.load(Ordering::Relaxed) { tokio::time::sleep(Duration::from_millis(100)).await; } } => {
            return Err("Operação cancelada; os clips concluídos foram preservados.".into());
        }
    };
    if !output.status.success() {
        return Err(String::from_utf8_lossy(&output.stderr)
            .chars()
            .take(2400)
            .collect::<String>());
    }
    if output.stdout.len() > 4_000_000 {
        return Err("Resposta do worker demasiado grande.".into());
    }
    serde_json::from_slice(&output.stdout).map_err(|_| "O worker devolveu dados inválidos.".into())
}

pub async fn analyze(
    url: &str,
    start: Option<f64>,
    end: Option<f64>,
    profile: &ClipProfile,
    capture_seconds: u32,
    cancel: Arc<AtomicBool>,
) -> Result<(Source, VideoAnalysis), String> {
    analyze_at(url, start, end, profile, capture_seconds, cancel, root()).await
}

pub async fn analyze_at(
    url: &str,
    start: Option<f64>,
    end: Option<f64>,
    profile: &ClipProfile,
    capture_seconds: u32,
    cancel: Arc<AtomicBool>,
    output_root: PathBuf,
) -> Result<(Source, VideoAnalysis), String> {
    let request = json!({"action":"analyze", "id":id(), "root":output_root, "url":url,
        "start":start,"end":end,"clipProfile":profile,"captureSeconds":capture_seconds});
    let result = call(&request, cancel, 1000).await?;
    let source: Source =
        serde_json::from_value(result["source"].clone()).map_err(|e| e.to_string())?;
    let mut analysis: VideoAnalysis =
        serde_json::from_value(result["analysis"].clone()).map_err(|e| e.to_string())?;
    let bounds = TimeRange {
        start: source.start,
        end: source.end.ok_or("Falta o fim do intervalo.")?,
    };
    analysis.moments = match analysis.signal.as_str() {
        "audio_energy" => AudioEnergyDetector.detect(&analysis.points, bounds, profile),
        "youtube_heatmap" => HeatmapDetector.detect(&analysis.points, bounds, profile),
        _ => return Err("O adapter devolveu um tipo de sinal não suportado.".into()),
    };
    Ok((source, analysis))
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields, rename_all = "camelCase")]
pub struct RenderProfile {
    pub aspect: String,
    pub fit: String,
    pub captions: bool,
}
impl Default for RenderProfile {
    fn default() -> Self {
        Self {
            aspect: "9:16".into(),
            fit: "pad".into(),
            captions: false,
        }
    }
}
impl RenderProfile {
    pub fn validate(&self) -> Result<(), String> {
        if !["9:16", "16:9", "1:1"].contains(&self.aspect.as_str())
            || !["pad", "crop"].contains(&self.fit.as_str())
        {
            return Err("Formato ou enquadramento inválido.".into());
        }
        Ok(())
    }
}

pub struct Production {
    pub busy: bool,
    pub cancel: Arc<AtomicBool>,
    pub root: PathBuf,
    lease: Option<std::fs::File>,
}
pub type SharedProduction = Arc<Mutex<Production>>;
impl Production {
    fn lease(root: &Path) -> Option<std::fs::File> {
        std::fs::create_dir_all(root).ok()?;
        let mut options = std::fs::OpenOptions::new();
        options.read(true).write(true).create(true).truncate(false);
        #[cfg(windows)]
        {
            use std::os::windows::fs::OpenOptionsExt;
            options.share_mode(0);
        }
        options.open(root.join("production.lock")).ok()
    }
    pub fn writable(&self) -> bool {
        self.lease.is_some() || Self::lease(&self.root).is_some()
    }
    pub fn reserve(&mut self) -> Result<(), String> {
        if self.lease.is_none() {
            self.lease = Self::lease(&self.root);
        }
        if self.lease.is_none() {
            return Err("Outra produção está em curso nesta pasta.".into());
        }
        Ok(())
    }
    pub fn new(root: PathBuf) -> Self {
        let lease = Self::lease(&root);
        let mut manager = Self {
            busy: false,
            cancel: Arc::new(AtomicBool::new(false)),
            root,
            lease,
        };
        let mut value = manager.snapshot();
        if manager.writable() && value["status"] == "running" {
            mark_incomplete(
                &mut value,
                "interrupted",
                "A aplicação foi fechada durante a produção. Podes retomar os incompletos.",
            );
            let _ = manager.save(&value);
        }
        manager.lease = None;
        manager
    }
    pub fn snapshot(&self) -> Value {
        let mut value = std::fs::read(self.root.join("current.json"))
            .ok()
            .and_then(|b| serde_json::from_slice::<Value>(&b).ok())
            .unwrap_or(json!({"status":"idle","clips":[]}));
        value["busy"] = json!(self.busy || !self.writable());
        value["writable"] = json!(self.writable());
        if !self.writable() {
            value["detail"] =
                json!("Outra produção está em curso nesta pasta. Aguarda que termine.");
        }
        value["outputRoot"] = json!(self.root);
        value
    }
    fn save(&self, value: &Value) -> Result<(), String> {
        atomic_json(&self.root.join("current.json"), value)?;
        if let Some(folder) = value["folder"].as_str() {
            let folder = PathBuf::from(folder);
            let inside = folder
                .canonicalize()
                .ok()
                .zip(self.root.canonicalize().ok())
                .is_some_and(|(folder, root)| folder.starts_with(root));
            if inside {
                atomic_json(&folder.join("job.json"), value)?;
            }
        }
        Ok(())
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

pub fn request(
    source: &Source,
    analysis: Option<&VideoAnalysis>,
    moments: Vec<Moment>,
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
    if moments.is_empty()
        || moments.len() > 30
        || moments.iter().any(|m| {
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
        json!({"action":"render","id":id(),"root":root(),"source":source,"moments":moments,
        "clipProfile":clip_profile,"renderProfile":render_profile,"topic":topic,
        "localMedia":analysis.and_then(|a|a.local_media.clone()),"mediaOrigin":analysis.map_or(0.0,|a|a.media_origin)}),
    )
}

pub fn start(shared: SharedProduction, mut request: Value) -> Result<(), String> {
    let cancel = {
        let mut manager = shared.lock().map_err(|_| "Produção indisponível.")?;
        if manager.busy {
            return Err("Já existe uma produção em curso.".into());
        }
        manager.reserve()?;
        request["root"] = json!(manager.root);
        atomic_json(
            &manager.root.join("requests").join(format!(
                "{}.json",
                request["id"].as_str().ok_or("Job inválido.")?
            )),
            &request,
        )?;
        manager.save(&json!({"id":request["id"],"status":"running","clips":[],"detail":"A preparar a produção local…"}))?;
        manager.busy = true;
        manager.cancel = Arc::new(AtomicBool::new(false));
        manager.cancel.clone()
    };
    tauri::async_runtime::spawn(async move {
        let outcome = call(&request, cancel.clone(), 21600).await;
        if let Ok(mut manager) = shared.lock() {
            let mut value = manager.snapshot();
            if let Err(error) = outcome {
                mark_incomplete(
                    &mut value,
                    if cancel.load(Ordering::Relaxed) {
                        "cancelled"
                    } else {
                        "error"
                    },
                    &error,
                );
                let _ = manager.save(&value);
            }
            manager.busy = false;
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
        let root = std::env::temp_dir().join(id());
        atomic_json(&root.join("current.json"), &json!({"status":"running","clips":[{"status":"ready","path":"keep.mp4"},{"status":"rendering"}]})).unwrap();
        let manager = Production::new(root);
        let value = manager.snapshot();
        assert_eq!(value["status"], "interrupted");
        assert_eq!(value["clips"][0]["path"], "keep.mp4");
        assert_eq!(value["clips"][1]["status"], "interrupted");
    }
    #[test]
    fn render_profile_rejects_unknown_layouts() {
        let profile = RenderProfile {
            aspect: "arbitrary".into(),
            ..Default::default()
        };
        assert!(profile.validate().is_err());
    }
    #[test]
    #[cfg(windows)]
    fn another_instance_cannot_take_over_running_production() {
        let root = std::env::temp_dir().join(id());
        let mut first = Production::new(root.clone());
        first.reserve().unwrap();
        first.save(&json!({"status":"running","clips":[]})).unwrap();
        let second = Production::new(root.clone());
        assert!(!second.writable());
        assert_eq!(second.snapshot()["status"], "running");
        drop(second);
        drop(first);
        let recovered = Production::new(root);
        assert!(recovered.writable());
        assert_eq!(recovered.snapshot()["status"], "interrupted");
    }
}

pub fn python_command() -> PathBuf {
    let mut roots = vec![];
    if let Ok(executable) = std::env::current_exe() {
        if let Some(parent) = executable.parent() {
            roots.push(parent.to_path_buf());
            if let Some(parent) = parent.parent() {
                roots.push(parent.to_path_buf());
            }
        }
    }
    roots.push(
        PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .unwrap()
            .to_path_buf(),
    );
    for root in roots {
        let candidate = root.join(".venv-youtube").join(if cfg!(windows) {
            "Scripts/python.exe"
        } else {
            "bin/python"
        });
        if candidate.is_file() {
            return candidate;
        }
    }
    PathBuf::from(if cfg!(windows) {
        "python.exe"
    } else {
        "python3"
    })
}
