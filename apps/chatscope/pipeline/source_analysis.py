"""Acquire source evidence; editorial ranking stays in Rust."""

from pathlib import Path
import math
from .media_sources import MediaSourceRegistry
from .audio_signals import extract_audio_energy_signal
from .media_tools import probe_video
from .job_storage import write_json_atomically
from .request_validation import validate_clip_profile, validate_heatmap_points


def analyze_media_request(request):
    clip_profile = request["clipProfile"]
    validate_clip_profile(clip_profile)
    provider_id, source_adapter = MediaSourceRegistry().resolve(request["url"])
    extracted_metadata = source_adapter.metadata()
    is_live_recording = bool(extracted_metadata.get("is_live"))
    source_duration_seconds = float(extracted_metadata.get("duration") or 0)
    analysis_start_seconds = float(request.get("start") or 0)
    analysis_end_seconds = request.get("end")
    if is_live_recording:
        if analysis_start_seconds or analysis_end_seconds is not None:
            raise ValueError(
                "Num direto, deixa o intervalo vazio e escolhe a duração da captura."
            )
        analysis_end_seconds = float(request.get("captureSeconds", 120))
        if not 30 <= analysis_end_seconds <= 600:
            raise ValueError(
                "A captura de um direto deve durar entre 30 e 600 segundos."
            )
    else:
        analysis_end_seconds = (
            source_duration_seconds
            if analysis_end_seconds is None
            else float(analysis_end_seconds)
        )
    if (
        not all(
            math.isfinite(v) for v in (analysis_start_seconds, analysis_end_seconds)
        )
        or not 0 <= analysis_start_seconds < analysis_end_seconds
        or (not is_live_recording and analysis_end_seconds > source_duration_seconds)
    ):
        raise ValueError("O intervalo tem de ficar dentro da duração do vídeo.")
    replay_heatmap = extracted_metadata.get("heatmap") or []
    validate_heatmap_points(replay_heatmap, source_duration_seconds)
    replay_heatmap = [
        {
            **p,
            "start_time": max(analysis_start_seconds, p["start_time"]),
            "end_time": min(analysis_end_seconds, p["end_time"]),
        }
        for p in replay_heatmap
        if p["end_time"] > analysis_start_seconds
        and p["start_time"] < analysis_end_seconds
    ]
    local_master_path, master_source_offset_seconds = None, 0.0
    signal_kind, signal_points = "youtube_heatmap", replay_heatmap
    availability = "available" if replay_heatmap else "unavailable"
    if not replay_heatmap:
        # Bounded fallback prevents an accidental multi-hour download/analysis.
        if analysis_end_seconds - analysis_start_seconds > 600:
            raise ValueError(
                "Sem heatmap: escolhe um intervalo até 10 minutos para analisar o áudio."
            )
        analysis_cache_folder = Path(request["root"]) / "cache" / request["id"]
        local_master_path, master_source_offset_seconds = source_adapter.acquire(
            analysis_start_seconds, analysis_end_seconds, analysis_cache_folder
        )
        master_metadata = probe_video(local_master_path)
        if is_live_recording:
            source_duration_seconds = analysis_end_seconds = master_metadata["duration"]
        else:
            analysis_end_seconds = min(
                analysis_end_seconds,
                master_source_offset_seconds + master_metadata["duration"],
            )
        signal_points = (
            extract_audio_energy_signal(
                local_master_path,
                analysis_start_seconds,
                analysis_end_seconds,
                master_source_offset_seconds,
            )
            if master_metadata["audio"]
            else []
        )
        signal_kind = "audio_energy"
        availability = "available" if signal_points else "unavailable"
    from yt_dlp.version import __version__

    source_descriptor = {
        "url": request["url"],
        "kind": f"{provider_id}_live" if is_live_recording else provider_id,
        "id": str(extracted_metadata["id"]),
        "title": extracted_metadata.get("title") or str(extracted_metadata["id"]),
        "channel": extracted_metadata.get("channel")
        or extracted_metadata.get("uploader")
        or provider_id,
        "duration": source_duration_seconds,
        "start": analysis_start_seconds,
        "end": analysis_end_seconds,
    }
    video_analysis = {
        "clipProfile": clip_profile,
        "availability": availability,
        "heatmap": replay_heatmap,
        "points": signal_points,
        "signal": signal_kind,
        "timeOrigin": "recording" if is_live_recording else "source",
        "moments": [],
        "extractorVersion": __version__,
        "localMedia": str(local_master_path.resolve()) if local_master_path else None,
        "mediaOrigin": master_source_offset_seconds,
    }
    analysis_result = {"source": source_descriptor, "analysis": video_analysis}
    write_json_atomically(
        Path(request["root"]) / "cache" / request["id"] / "analysis.json",
        analysis_result,
    )
    return analysis_result
