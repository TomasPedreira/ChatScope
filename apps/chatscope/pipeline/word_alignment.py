"""Forced alignment of fixed caption text; this module never transcribes speech."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
import math
import re

from .speech_transcriber import load_whisper_model


@dataclass(frozen=True)
class TimedWord:
    text: str
    start_seconds: float
    end_seconds: float


class WordAligner(ABC):
    @abstractmethod
    def align(self, audio_path, cues, source_language, task, model_name):
        """Align the supplied words without replacing or regenerating their text."""


def preserve_words(cue, aligned, offset_seconds):
    expected = re.findall(r"\S+", cue.text)
    actual = "".join("".join(item["word"].split()) for item in aligned)
    if actual != "".join(expected):
        raise ValueError("O alinhamento não corresponde à transcrição aprovada.")
    spans, cursor = [], 0
    for item in aligned:
        end = cursor + len("".join(item["word"].split()))
        if end > cursor:
            spans.append((cursor, end, item))
        cursor = end
    lower, upper = math.ceil(cue.start_seconds * 100 - 1e-7), math.floor(
        cue.end_seconds * 100 + 1e-7
    )
    if upper - lower < len(expected):
        raise ValueError("A frase é demasiado curta para destacar todas as palavras.")
    starts, ends, cursor = [], [], 0
    for index, word in enumerate(expected):
        end = cursor + len(word)
        matching = [
            item for left, right, item in spans if left < end and right > cursor
        ]
        if not matching or any(
            not math.isfinite(item[key])
            for item in matching
            for key in ("start", "end")
        ):
            raise ValueError("O provider não alinhou todas as palavras.")
        start = round((offset_seconds + min(item["start"] for item in matching)) * 100)
        start = min(
            max(lower, start, starts[-1] + 1 if starts else lower),
            upper - (len(expected) - index),
        )
        starts.append(start)
        ends.append(
            round((offset_seconds + max(item["end"] for item in matching)) * 100)
        )
        cursor = end
    return [
        TimedWord(
            word,
            starts[index] / 100,
            max(
                starts[index] + 1,
                min(
                    ends[index], starts[index + 1] if index + 1 < len(starts) else upper
                ),
            )
            / 100,
        )
        for index, word in enumerate(expected)
    ]


class WhisperWordAligner(WordAligner):
    def align(self, audio_path, cues, source_language, task, model_name):
        from faster_whisper.audio import decode_audio, pad_or_trim
        from faster_whisper.tokenizer import Tokenizer

        if not cues:
            return []
        model = load_whisper_model(model_name)
        tokenizer = Tokenizer(
            model.hf_tokenizer,
            model.model.is_multilingual,
            task=task,
            language=source_language,
        )
        audio = decode_audio(str(audio_path), sampling_rate=16000)
        groups, group, token_count = [], [], 0
        for cue in cues:
            tokens = tokenizer.encode(" " + " ".join(cue.text.split()))
            if len(tokens) > 400 or cue.end_seconds - cue.start_seconds > 29.5:
                raise ValueError("A frase excede a janela do alinhador de palavras.")
            if group and (
                cue.end_seconds - group[0][0].start_seconds > 29.5
                or token_count + len(tokens) > 400
            ):
                groups.append(group)
                group, token_count = [], 0
            group.append((cue, tokens))
            token_count += len(tokens)
        if group:
            groups.append(group)
        words = []
        for group in groups:
            start = max(0.0, group[0][0].start_seconds - 0.05)
            end = min(len(audio) / 16000, group[-1][0].end_seconds + 0.05)
            features = model.feature_extractor(
                audio[round(start * 16000) : round(end * 16000)]
            )
            frames = features.shape[-1]
            encoder = model.encode(pad_or_trim(features))
            segments = [
                {
                    "seek": 0,
                    "start": cue.start_seconds - start,
                    "end": cue.end_seconds - start,
                    "tokens": tokens,
                }
                for cue, tokens in group
            ]
            model.add_word_timestamps(
                [segments],
                tokenizer,
                encoder,
                frames,
                "\"'“¿([{-",
                "\"'.。,，!！?？:：”)]}、",
                last_speech_timestamp=0,
            )
            for (cue, _), segment in zip(group, segments):
                words.extend(preserve_words(cue, segment.get("words", []), start))
        return words
