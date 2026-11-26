"""Execute local clip batches from explicit candidate intervals."""

from pathlib import Path
import math
import re
from .media_sources import MediaSourceRegistry
from .video_renderer import FFmpegRenderer
from .media_tools import probe_video
from .job_storage import save_production_manifest, current_lisbon_date
from .request_validation import validate_clip_profile, validate_render_profile
from .review_index import build_review_index


def render_clip_batch(request):
    render_profile = request["renderProfile"]
    validate_render_profile(render_profile)
    validate_clip_profile(request["clipProfile"])
    output_root = Path(request["root"]).resolve()
    job_folder = output_root / current_lisbon_date() / "jobs" / request["id"]
    job_folder.mkdir(parents=True, exist_ok=False)
    clip_candidates = request["moments"]
    if not 1 <= len(clip_candidates) <= 30:
        raise ValueError("Escolhe entre 1 e 30 momentos.")
    topic = request.get("topic", "geral")
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,48}", topic):
        raise ValueError("O tema só pode conter letras, números, _ e -.")
    manifest = {
        "schemaVersion": 1,
        "id": request["id"],
        "status": "running",
        "folder": str(job_folder),
        "source": request["source"],
        "clipProfile": request["clipProfile"],
        "renderProfile": render_profile,
        "clips": [
            {"index": i, "moment": item, "status": "queued"}
            for i, item in enumerate(clip_candidates)
        ],
    }
    save_production_manifest(job_folder, output_root, manifest)
    source_url = request["source"]["url"]
    if request["source"]["kind"] == "clip":
        # Twitch chat offsets for clips refer to their parent VOD.
        source_url = f"https://www.twitch.tv/videos/{request['source']['id']}"
    _, source_adapter = MediaSourceRegistry().resolve(source_url)
    day_folder = job_folder.parent.parent
    try:
        for clip in manifest["clips"]:
            try:
                clip["status"] = "acquiring"
                save_production_manifest(job_folder, output_root, manifest)
                clip_candidate = clip["moment"]
                clip_start_seconds, clip_end_seconds = float(
                    clip_candidate["start"]
                ), float(clip_candidate["end"])
                bounds = request["source"]
                if (
                    not all(
                        math.isfinite(t) for t in (clip_start_seconds, clip_end_seconds)
                    )
                    or not 0 <= clip_start_seconds < clip_end_seconds
                    or clip_end_seconds - clip_start_seconds > 180.001
                    or clip_start_seconds < bounds["start"] - 0.001
                    or clip_end_seconds > bounds["end"] + 0.001
                ):
                    raise ValueError("Momento fora do intervalo da origem.")
                clip_folder = job_folder / str(clip["index"] + 1)
                clip_folder.mkdir()
                local_master_path = request.get("localMedia")
                if local_master_path:
                    local_master_path = Path(local_master_path).resolve(strict=True)
                    if bounds[
                        "kind"
                    ] != "local" and not local_master_path.is_relative_to(
                        output_root / "cache"
                    ):
                        raise ValueError(
                            "O master não pertence à cache desta aplicação."
                        )
                    master_source_offset_seconds = request.get("mediaOrigin", 0)
                else:
                    if bounds["kind"].endswith("_live") or bounds["kind"] == "live":
                        raise ValueError(
                            "Este direto não tem vídeo capturado. Usa o modo Vídeo/áudio."
                        )
                    local_master_path, master_source_offset_seconds = (
                        source_adapter.acquire(
                            clip_start_seconds, clip_end_seconds, clip_folder / "master"
                        )
                    )
                clip["status"] = "rendering"
                save_production_manifest(job_folder, output_root, manifest)
                output_folder = day_folder / "clips" / topic
                output_folder.mkdir(parents=True, exist_ok=True)
                final_clip_path = (
                    output_folder / f"{request['id']}-{clip['index'] + 1:02}.mp4"
                )
                rendered_clip_path = clip_folder / "draft.mp4"
                rendered_metadata = FFmpegRenderer().render(
                    local_master_path,
                    rendered_clip_path,
                    clip_start_seconds - master_source_offset_seconds,
                    clip_end_seconds - master_source_offset_seconds,
                    render_profile,
                )
                with rendered_clip_path.open("rb") as stream:
                    from hashlib import sha256

                    hasher = sha256()
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        hasher.update(chunk)
                    digest = hasher.hexdigest()
                if final_clip_path.exists():
                    raise ValueError(
                        "O destino já existe; o clip anterior foi preservado."
                    )
                rendered_clip_path.rename(final_clip_path)
                clip.update(
                    status="ready",
                    path=str(final_clip_path),
                    sha256=digest,
                    media=str(local_master_path),
                    mediaOrigin=master_source_offset_seconds,
                    duration=rendered_metadata["duration"],
                    dimensions=[
                        rendered_metadata["width"],
                        rendered_metadata["height"],
                    ],
                )
            except Exception as error:
                clip.update(status="error", error=str(error)[:1800])
            save_production_manifest(job_folder, output_root, manifest)
            build_review_index(day_folder)
        ready = sum(item["status"] == "ready" for item in manifest["clips"])
        manifest["status"] = (
            "complete"
            if ready == len(clip_candidates)
            else "partial" if ready else "error"
        )
    finally:
        save_production_manifest(job_folder, output_root, manifest)
        build_review_index(day_folder)
    return manifest
