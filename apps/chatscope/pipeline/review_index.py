"""Build the generated local review index without overwriting human review notes."""

from pathlib import Path
import json
from .job_storage import write_text_atomically


def build_review_index(day_folder):
    # Own index: preserve any human-maintained review.md.
    lines = [
        "# Clips locais",
        "",
        "Gerado automaticamente; confirma vídeo e áudio antes de publicar.",
        "",
    ]
    for file in sorted(day_folder.glob("jobs/*/job.json")):
        job = json.loads(file.read_text(encoding="utf-8"))
        title = (
            job["source"]["title"]
            .replace("\n", " ")
            .replace("[", "(")
            .replace("]", ")")
        )
        for clip in job["clips"]:
            if clip["status"] == "ready":
                relative = Path(clip["path"]).relative_to(day_folder).as_posix()
                moment = clip["moment"]
                lines.append(
                    f"- [{title} · {clip['duration']:.1f} s](<{relative}>) — {moment['reason']} · {moment['start']:.2f}–{moment['end']:.2f} s"
                )
    write_text_atomically(day_folder / "clips-index.md", "\n".join(lines) + "\n")
