# Caption languages: PT → EN first

Proposed clip titles are English. Generated subtitles default to English; the
profile can represent English or Portuguese output. The implementation priority
is PT → EN. PT speech can also keep Portuguese captions. EN → PT is prepared as
an extension point and has no active translation provider yet.

```mermaid
flowchart LR
  M[Local master from any MediaSource] --> C[CaptionService: bounded audio]
  P[CaptionProfile: source / target / model] --> C
  C --> W[Transcriber adapter]
  W --> T[TimedTranscript: actual output language]
  T --> S[SRT + JSON provenance]
  S --> R[FFmpegRenderer]
  R --> V[Captioned MP4]
```

`caption_models.py` contains `CaptionProfile`, `SubtitleCue` and `TimedTranscript`.
`speech_transcriber.py` contains the `Transcriber` interface and current
`WhisperTranscriber` adapter. `caption_service.py` handles audio extraction,
timing validation, readable line lengths and subtitle artifacts. The renderer
accepts an injected service; the service accepts an injected provider. A future
provider can combine ASR and a separate text translator while returning the same
`TimedTranscript`, without changing the renderer or source adapters.
`transcript_translation.py` defines `TranscriptTranslator.supports(source, target)`
and `translate(transcript, target)`. The service accepts these adapters through
dependency injection; no EN → PT implementation or external service is configured.

## Current backend and configuration

Whisper's multilingual models translate speech directly to English with
`task="translate"`. `language=None` detects the spoken language; `language="pt"`
explicitly identifies Portuguese input. Explicit English input uses
`task="transcribe"`. Forcing `language="en"` on Portuguese speech is not translation.

```json
{
  "renderProfile": {
    "aspect": "9:16", "fit": "pad", "captions": true,
    "captionProfile": {
      "sourceLanguage": "auto", "targetLanguage": "en", "model": "small"
    }
  }
}
```

Older requests with only `captions: true` receive these English defaults. Rust
omits the default nested profile when serializing, preserving the old JSON shape.
The UI has **Legendas**, audio detection/PT/EN and an English/Portuguese output
choice. Portuguese is labelled for PT audio; selecting English input disables
that unsupported EN → PT direction.

Targets are `en` and `pt`; other targets fail validation. Whisper translates into
English or transcribes the original speech. Its result records the actual text
language. If Portuguese output needs an unavailable translator, the service fails
explicitly instead of labelling English text as Portuguese. The model defaults to
multilingual `small`; `tiny`, `base`, `medium` and `large-v3` are also accepted.
English-only `.en` models and `turbo` are rejected for this translation workflow.
Additional translation directions need a capable adapter. Only the requested
model is downloaded, and the current setup caches multilingual `small`.

Install with `Setup-Media.ps1 -Captions`. Model weights are downloaded once and
cached locally; inference runs on the local CPU. Optional requirements constrain
PyAV below 19 because faster-whisper 1.2.x calls the `metadata_errors` argument
removed in PyAV 19, as verified in a real model test.

Primary references: [Whisper speech translation](https://github.com/openai/whisper#command-line-usage)
and [faster-whisper options](https://github.com/SYSTRAN/faster-whisper/blob/master/faster_whisper/transcribe.py).

## Timing, provenance and limits

SRT timestamps are relative to the clip. JSON stores the detected source language
separately from the output language, provider/model/task, input media file and
input-file interval. The production manifest retains the source URL and absolute
cut interval, plus paths to the caption artifacts.

Cues stay inside the clip and do not overlap. Text wraps at 42 characters, with
at most two lines per cue. Longer model segments are divided proportionally and
that timing method is recorded; this is not word-level alignment. Silence returns
`no_speech`; a video without audio returns `no_audio`. Provider errors fail that
clip and remain visible for retry. Translation quality varies with noise, accents
and overlapping speakers; human review is still needed.

Titles in the daily review are currently editorial metadata prepared by the
workflow, not an automatic app title generator. Keep them in English. A future
`TitleGenerator` should consume a `TimedTranscript` plus an explicit
`titleLanguage="en"`, independently of the caption target. A Portuguese
transcript may need translation before drafting an English title. Keep title
generation separate from rendering and source adapters.

Timed source subtitles/transcripts used to **select moments** remain separate
work in [issue #3](https://github.com/TomasPedreira/ChatScope/issues/3). English
output captions for an already selected clip do not implement that detector.
