use serde_json::{Value, json};
use std::{path::Path, time::Duration};
pub fn write_json_atomically(path: &Path, value: &Value) -> Result<(), String> {
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

pub fn load_production_state(output_root: &Path) -> Value {
    std::fs::read(output_root.join("current.json"))
        .ok()
        .and_then(|bytes| serde_json::from_slice(&bytes).ok())
        .unwrap_or(json!({"status":"idle","clips":[]}))
}
pub fn save_production_state(output_root: &Path, state: &Value) -> Result<(), String> {
    write_json_atomically(&output_root.join("current.json"), state)?;
    if let Some(folder) = state["folder"].as_str() {
        let folder = std::path::PathBuf::from(folder);
        let inside = folder
            .canonicalize()
            .ok()
            .zip(output_root.canonicalize().ok())
            .is_some_and(|(folder, root)| folder.starts_with(root));
        if inside {
            write_json_atomically(&folder.join("job.json"), state)?;
        }
    }
    Ok(())
}
