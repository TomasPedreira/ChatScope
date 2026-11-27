"""Classic Shorts ASS style, shared by the desktop pipeline and legacy study CLI."""

import json
import math
import re


def caption_header(width=1080, height=1920):
    scale = min(width / 1080, height / 1920)
    size, outline, shadow, margin = (
        max(1, round(value * scale)) for value in (69, 6, 3, 60)
    )
    return f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
ScaledBorderAndShadow: yes
WrapStyle: 0
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Main,Arial,{size},&H00FFFFFF,&H0048D5FF,&H00151515,&H74000000,-1,0,0,0,100,100,0,0,1,{outline},{shadow},5,{margin},{margin},0,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


CAPTION_HEADER = caption_header()


def ass_time(centiseconds):
    minutes, within_minute = divmod(centiseconds, 6000)
    seconds, hundredths = divmod(within_minute, 100)
    return f"0:{minutes:02}:{seconds:02}.{hundredths:02}"


def timed_captions(source, duration, width=1080, height=1920):
    cues = json.loads(source)
    if not isinstance(cues, list) or not cues:
        raise ValueError(
            "As legendas precisam de uma lista de frases com os tempos de cada palavra."
        )
    events = []
    previous_end = 0
    for cue in cues:
        if (
            not isinstance(cue, dict)
            or not isinstance(cue.get("text"), str)
            or not isinstance(cue.get("times"), list)
        ):
            raise ValueError(
                "Cada legenda precisa de texto e de uma lista de tempos em segundos."
            )
        line, times = cue["text"], cue["times"]
        words = line.upper().split()
        if not words or len(times) != len(words) + 1 or re.search(r"[\\{}\r\n]", line):
            raise ValueError(
                "Indica um tempo por palavra mais o fim da legenda, em texto simples."
            )
        if any(
            not isinstance(t, (int, float))
            or isinstance(t, bool)
            or not math.isfinite(t)
            or not 0 <= t <= duration
            for t in times
        ):
            raise ValueError("As legendas têm de ficar dentro do corte.")
        ticks = [round(t * 100) for t in times]
        if ticks[0] < previous_end or any(a >= b for a, b in zip(ticks, ticks[1:])):
            raise ValueError(
                "Os tempos das palavras têm de avançar sem sobrepor frases."
            )
        for index, (start, end) in enumerate(zip(ticks, ticks[1:])):
            active = words.copy()
            active[index] = r"{\1c&H48D5FF&}" + active[index] + r"{\1c&HFFFFFF&}"
            pop = r"\fscx105\fscy105\t(0,130,\fscx100\fscy100)" if index == 0 else ""
            style = (
                r"{\an5\pos("
                + f"{round(width / 2)},{round(height * 1588 / 1920)}"
                + ")"
                + pop
                + "}"
            )
            events.append(
                f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Main,,0,0,0,,{style}{' '.join(active)}"
            )
        previous_end = ticks[-1]
    return caption_header(width, height) + "\n".join(events) + "\n"


def highlight_cues(words, duration):
    """Keep the classic five-word / short-phrase grouping without changing text."""
    groups, group = [], []
    for word in words:
        if group and (
            len(group) == 5
            or len(" ".join(item.text for item in group)) + len(word.text) >= 29
            or word.start_seconds - group[-1].end_seconds > 0.38
            or group[-1].text.endswith((".", "!", "?"))
        ):
            groups.append(group)
            group = []
        group.append(word)
    if group:
        groups.append(group)
    cues = []
    for index, group in enumerate(groups):
        boundary = (
            groups[index + 1][0].start_seconds
            if index + 1 < len(groups)
            else math.floor(duration * 100) / 100
        )
        finish = min(boundary, round((group[-1].end_seconds + 0.08) * 100) / 100)
        if finish <= group[-1].start_seconds:
            raise ValueError("Uma palavra alinhada não tem duração visível.")
        cues.append(
            {
                "text": " ".join(word.text for word in group),
                "times": [word.start_seconds for word in group] + [finish],
            }
        )
    return cues
