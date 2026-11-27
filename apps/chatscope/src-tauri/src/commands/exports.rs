use crate::{analysis_session::SharedAnalysisSession, session_exports, twitch_chat};
use tauri::State;
#[tauri::command]
pub(crate) async fn export_chat(
    format: String,
    state: State<'_, SharedAnalysisSession>,
) -> Result<Option<String>, String> {
    if !["json", "csv"].contains(&format.as_str()) {
        return Err("Formato inválido.".into());
    }
    // SessionSnapshot before the dialog: capture may continue while the user chooses a file.
    let (source, messages, status, video_analysis, clip_profile, clip_candidates) = {
        let session = state.lock().map_err(|_| "Sessão indisponível.")?;
        if session.chat_messages.is_empty() && session.video_analysis.is_none() {
            return Err("Ainda não há dados para exportar.".into());
        }
        (
            session.source.clone(),
            session.chat_messages.clone(),
            session.status.clone(),
            session.video_analysis.clone(),
            session.clip_profile.clone(),
            session.clip_candidates(),
        )
    };
    let name = format!(
        "chatscope-{}-{}.{}",
        source.as_ref().map(|s| s.id.as_str()).unwrap_or("chat"),
        chrono::Local::now().format("%Y%m%d-%H%M%S"),
        format
    );
    let path = rfd::AsyncFileDialog::new()
        .set_title("Exportar sessão ChatScope")
        .set_file_name(name)
        .add_filter(format.to_uppercase(), &[format.as_str()])
        .save_file()
        .await;
    let Some(file) = path else {
        return Ok(None);
    };
    let content = if let Some(analysis) = video_analysis {
        let source = source.ok_or("Sessão sem origem.")?;
        if format == "csv" {
            session_exports::export_clip_candidates_csv(&source, &analysis.clip_candidates)
                .into_bytes()
        } else {
            serde_json::to_vec_pretty(&serde_json::json!({"schemaVersion":3,"status":status,"source":source,"video":analysis,"clipProfile":clip_profile,"moments":clip_candidates}))
                .map_err(|error| error.to_string())?
        }
    } else if format == "csv" {
        twitch_chat::export_csv(&messages).into_bytes()
    } else {
        serde_json::to_vec_pretty(&serde_json::json!({"schemaVersion":1,"exportedAt":chrono::Utc::now().to_rfc3339(),"status":status,"source":source,"messageCount":messages.len(),"analysis":twitch_chat::analyze(&messages),"messages":messages,"clipProfile":clip_profile,"moments":clip_candidates})).map_err(|e| e.to_string())?
    };
    file.write(&content)
        .await
        .map_err(|e| format!("Não foi possível guardar: {e}"))?;
    Ok(Some(file.path().display().to_string()))
}
