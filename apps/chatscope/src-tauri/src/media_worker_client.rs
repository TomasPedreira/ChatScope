//! Subprocess/runtime boundary; no clip ranking or production persistence.
use serde_json::Value;
use std::{
    path::{Path, PathBuf},
    process::Stdio,
    sync::{
        Arc,
        atomic::{AtomicBool, Ordering},
    },
    time::Duration,
};
use tokio::io::AsyncWriteExt;
fn prepare_worker_runtime(root: &Path) -> Result<PathBuf, String> {
    let files = [
        ("__init__.py", include_str!("../../pipeline/__init__.py")),
        (
            "caption_models.py",
            include_str!("../../pipeline/caption_models.py"),
        ),
        (
            "caption_service.py",
            include_str!("../../pipeline/caption_service.py"),
        ),
        (
            "audio_signals.py",
            include_str!("../../pipeline/audio_signals.py"),
        ),
        (
            "clip_production.py",
            include_str!("../../pipeline/clip_production.py"),
        ),
        (
            "job_storage.py",
            include_str!("../../pipeline/job_storage.py"),
        ),
        (
            "kick_source.py",
            include_str!("../../pipeline/kick_source.py"),
        ),
        (
            "media_sources.py",
            include_str!("../../pipeline/media_sources.py"),
        ),
        (
            "media_tools.py",
            include_str!("../../pipeline/media_tools.py"),
        ),
        (
            "request_validation.py",
            include_str!("../../pipeline/request_validation.py"),
        ),
        (
            "review_index.py",
            include_str!("../../pipeline/review_index.py"),
        ),
        (
            "source_analysis.py",
            include_str!("../../pipeline/source_analysis.py"),
        ),
        (
            "speech_transcriber.py",
            include_str!("../../pipeline/speech_transcriber.py"),
        ),
        (
            "video_renderer.py",
            include_str!("../../pipeline/video_renderer.py"),
        ),
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

pub async fn run_media_worker(
    request: &Value,
    cancel: Arc<AtomicBool>,
    timeout: u64,
) -> Result<Value, String> {
    let path = PathBuf::from(
        request["root"]
            .as_str()
            .ok_or("Falta a pasta de produção.")?,
    );
    let runtime = prepare_worker_runtime(&path)?;
    let mut command = tokio::process::Command::new(resolve_python_executable());
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

pub fn resolve_python_executable() -> PathBuf {
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
