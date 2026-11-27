"""Restyle an approved transcript and its audio without rerunning recognition."""

from hashlib import sha256
from pathlib import Path
import json
import shutil

from .caption_models import CaptionProfile, SubtitleCue
from .caption_styling import CaptionStyler


class SavedCaptionService:
    def __init__(self, transcript_path, srt_path, audio_path, caption_styler=None):
        self.transcript_path, self.srt_path, self.audio_path = map(
            Path, (transcript_path, srt_path, audio_path)
        )
        self.caption_styler = caption_styler or CaptionStyler()

    def generate(
        self,
        source_path,
        start_seconds,
        end_seconds,
        folder,
        profile=None,
        canvas_size=(1080, 1920),
    ):
        profile = CaptionProfile.from_dict({} if profile is None else profile)
        transcript_bytes = self.transcript_path.read_bytes()
        transcript = json.loads(transcript_bytes)
        if (
            Path(transcript["inputMedia"]).resolve() != Path(source_path).resolve()
            or abs(transcript["inputStartSeconds"] - start_seconds) > 0.001
            or abs(transcript["inputEndSeconds"] - end_seconds) > 0.001
            or transcript["language"] != profile.target_language
        ):
            raise ValueError(
                "A transcrição aprovada pertence a outro ficheiro, corte ou língua."
            )
        cues = [
            SubtitleCue(cue["start"], cue["end"], cue["text"])
            for cue in transcript["segments"]
        ]
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        srt_path, transcript_path = folder / "captions.srt", folder / "transcript.json"
        if srt_path.exists() or transcript_path.exists():
            raise ValueError("O destino de legendas já existe; usa um novo trabalho.")
        shutil.copyfile(self.srt_path, srt_path)
        shutil.copyfile(self.transcript_path, transcript_path)
        style_metadata = (
            self.caption_styler.write(
                self.audio_path,
                cues,
                transcript,
                folder,
                profile,
                end_seconds - start_seconds,
                canvas_size,
            )
            if cues
            else {"style": profile.style}
        )
        return {
            **style_metadata,
            "status": "ready" if cues else "no_speech",
            "language": transcript["language"],
            "sourceLanguage": transcript["sourceLanguage"],
            "provider": transcript["provider"],
            "model": transcript["model"],
            "task": transcript["task"],
            "cueCount": len(cues),
            "srtPath": str(srt_path.resolve()),
            "transcriptPath": str(transcript_path.resolve()),
            "transcriptReused": True,
            "approvedTranscriptSha256": sha256(transcript_bytes).hexdigest(),
        }
