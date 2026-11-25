"""Optional speech transcription is independent of source and rendering."""
from abc import ABC, abstractmethod
from functools import lru_cache

from .tools import ffmpeg, run


class Transcriber(ABC):
    @abstractmethod
    def captions(self, source, start, end, folder):
        pass


@lru_cache(maxsize=1)
def model():
    try:
        from faster_whisper import WhisperModel
    except ImportError as error:
        raise ValueError("As legendas exigem Setup-Media.ps1 -Captions.") from error
    return WhisperModel("small", device="cpu", compute_type="int8")


class WhisperTranscriber(Transcriber):
    def captions(self, source, start, end, folder):
        transcriber = model()
        speech = folder / "speech.wav"
        run([ffmpeg(), "-v", "error", "-nostdin", "-n", "-ss", str(start), "-i", str(source),
             "-t", str(end - start), "-vn", "-ar", "16000", "-ac", "1", str(speech)])
        segments, info = transcriber.transcribe(str(speech), vad_filter=True)
        cues = []
        transcript = []
        for segment in segments:
            begin, finish = max(0, segment.start), min(segment.end, end - start)
            text = segment.text.strip().replace("-->", "→").replace("\n", " ")
            if text and begin < finish:
                cues.append(f"{len(cues) + 1}\n{stamp(begin)} --> {stamp(finish)}\n{text}\n")
                transcript.append({"start":begin,"end":finish,"text":text})
        (folder / "captions.srt").write_text("\n".join(cues), encoding="utf-8")
        import json
        (folder / "transcript.json").write_text(json.dumps({"language": info.language, "segments":transcript}, ensure_ascii=False), encoding="utf-8")
        return bool(cues)


def stamp(seconds):
    ms = round(seconds * 1000)
    return f"{ms//3600000:02}:{ms//60000%60:02}:{ms//1000%60:02},{ms%1000:03}"
