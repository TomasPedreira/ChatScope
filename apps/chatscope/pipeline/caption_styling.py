"""Caption presentation consumes fixed text and audio; it never calls transcription."""

from hashlib import sha256
from pathlib import Path
import json

from .caption_style import highlight_cues, timed_captions
from .job_storage import write_json_atomically, write_text_atomically
from .word_alignment import WhisperWordAligner


class CaptionStyler:
    def __init__(self, word_aligner=None):
        self.word_aligner = word_aligner or WhisperWordAligner()

    def write(
        self,
        audio_path,
        cues,
        transcript,
        folder,
        profile,
        duration,
        canvas_size=(1080, 1920),
    ):
        if profile.style == "plain":
            return {"style": "plain", "renderFile": "captions.srt"}
        words = self.word_aligner.align(
            audio_path,
            cues,
            transcript["sourceLanguage"],
            transcript["task"],
            profile.model,
        )
        if [word.text for word in words] != [
            word for cue in cues for word in cue.text.split()
        ]:
            raise ValueError("O estilo não pode alterar as palavras da transcrição.")
        groups = highlight_cues(words, duration)
        ass_path, timing_path = (
            Path(folder) / "captions.ass",
            Path(folder) / "word-timing.json",
        )
        write_text_atomically(
            ass_path,
            timed_captions(
                json.dumps(groups, ensure_ascii=False), duration, *canvas_size
            ),
        )
        text_digest = sha256(
            " ".join(" ".join(cue.text.split()) for cue in cues).encode("utf-8")
        ).hexdigest()
        method = (
            "whisper_cross_attention_translation"
            if transcript["task"] == "translate"
            else "whisper_cross_attention"
        )
        write_json_atomically(
            timing_path,
            {
                "schemaVersion": 1,
                "timeOrigin": "clip",
                "textSha256": text_digest,
                "method": method,
                "model": profile.model,
                "sourceLanguage": transcript["sourceLanguage"],
                "language": transcript["language"],
                "words": [
                    {
                        "text": word.text,
                        "start": word.start_seconds,
                        "end": word.end_seconds,
                    }
                    for word in words
                ],
                "groups": groups,
            },
        )
        return {
            "style": "word_highlight",
            "renderFile": "captions.ass",
            "assPath": str(ass_path.resolve()),
            "wordTimingPath": str(timing_path.resolve()),
            "wordCount": len(words),
            "alignmentMethod": method,
            "textSha256": text_digest,
        }
