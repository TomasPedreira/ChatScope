# Caption appearance and fixed-text alignment

The default style is the original Shorts template: short uppercase phrases,
bold Arial, dark outline/shadow, a small entrance animation and exactly one
active word highlighted in yellow (`#FFD548`). SRT remains available as a text
sidecar; ASS carries the appearance and word events burned into the MP4.

The template originally existed in
[`study/shorts_style.py` at 2b05f1e](https://github.com/TomasPedreira/ChatScope/blob/2b05f1e/apps/chatscope/study/shorts_style.py).
The common desktop renderer introduced in
[`bd74d7d`](https://github.com/TomasPedreira/ChatScope/blob/bd74d7d/apps/chatscope/pipeline/render.py)
used plain SRT and did not integrate that template. Both paths now share
`pipeline/caption_style.py`; the legacy module re-exports the same implementation.

```text
Fixed transcript + clip audio
  → WordAligner (Whisper cross-attention; no speech recognition)
  → TimedWord + short phrase groups
  → CaptionStyler → ASS → FFmpegRenderer
```

`CaptionProfile.style` defaults to `word_highlight`; choose `plain` for the simple
SRT appearance. The UI exposes both. The classic 1080×1920 position, font, colour
and animation are retained; the template scales to the other output sizes.

`WhisperWordAligner` supplies already approved text as tokens to the model's
alignment API. It never calls `transcribe`. Punctuation and words are checked
against the fixed text before styling. Timing is quantized to centiseconds,
with a minimum visible duration for zero-duration model tokens. A mismatched
alignment fails explicitly instead of dropping or replacing text.

`SavedCaptionService` reuses an approved transcript, SRT and extracted audio.
It verifies the source file, interval and output language, copies transcript/SRT
bytes unchanged and records their approved hash. Restyling therefore does not
rerun recognition or alter the approved wording. Previous MP4s remain preserved.

New artifacts include `captions.ass` and `word-timing.json`, with the fixed-text
hash, word intervals, phrase groups and alignment method. Translated English
words over Portuguese audio use translation cross-attention: word correspondence
can be approximate across languages and needs review. English speech with English
captions uses same-language alignment. Translation scope remains PT → EN, with
EN → PT prepared as a future adapter; appearance does not change language routing.

The optional faster-whisper version is pinned because this alignment adapter uses
its model alignment API. No additional model weights or translation service are
needed beyond the existing multilingual model.
