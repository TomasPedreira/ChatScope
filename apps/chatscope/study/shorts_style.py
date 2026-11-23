"""Visual style and metadata shared by the vertical review clips."""

import json
import math
import re


CAPTION_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes
WrapStyle: 0
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Main,Arial,69,&H00FFFFFF,&H0048D5FF,&H00151515,&H74000000,-1,0,0,0,100,100,0,0,1,6,3,5,60,60,0,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def ass_time(centiseconds):
    minutes, within_minute = divmod(centiseconds, 6000)
    seconds, hundredths = divmod(within_minute, 100)
    return f"0:{minutes:02}:{seconds:02}.{hundredths:02}"


def timed_captions(source, duration):
    cues = json.loads(source)
    if not isinstance(cues, list) or not cues:
        raise ValueError("As legendas precisam de uma lista de frases com os tempos de cada palavra.")
    events = []
    previous_end = 0
    for cue in cues:
        if (not isinstance(cue, dict) or not isinstance(cue.get("text"), str)
                or not isinstance(cue.get("times"), list)):
            raise ValueError("Cada legenda precisa de texto e de uma lista de tempos em segundos.")
        line = cue["text"]
        words = line.upper().split()
        times = cue["times"]
        if not words or len(times) != len(words) + 1 or re.search(r"[\\{}\r\n]", line):
            raise ValueError("Indica um tempo por palavra mais o fim da legenda, em texto simples.")
        if any(not isinstance(t, (int, float)) or not math.isfinite(t) or not 0 <= t <= duration for t in times):
            raise ValueError("As legendas têm de ficar dentro do corte.")
        ticks = [round(t * 100) for t in times]
        if ticks[0] < previous_end or any(a >= b for a, b in zip(ticks, ticks[1:])):
            raise ValueError("Os tempos das palavras têm de avançar sem sobrepor frases.")
        for index, (start, end) in enumerate(zip(ticks, ticks[1:])):
            active = words.copy()
            active[index] = r"{\1c&H48D5FF&}" + active[index] + r"{\1c&HFFFFFF&}"
            pop = r"\fscx105\fscy105\t(0,130,\fscx100\fscy100)" if index == 0 else ""
            style = r"{\an5\pos(540,1588)" + pop + "}"
            events.append(
                f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Main,,0,0,0,,{style}{' '.join(active)}"
            )
        previous_end = ticks[-1]
    return CAPTION_HEADER + "\n".join(events) + "\n"


def format_description(description, hashtags, twitch_url=None, youtube_url=None):
    credits = [f"{label}: {url}" for label, url in (("Twitch", twitch_url), ("YouTube", youtube_url)) if url]
    if credits:
        description = "\n\n".join(filter(None, (description.rstrip(), "\n".join(credits))))
    existing = {tag.casefold() for tag in re.findall(r"(?<![\w/])#(\w+)", description)}
    added = []
    for value in (*hashtags, "#Shorts"):
        tag = value.removeprefix("#")
        if not re.fullmatch(r"\w+", tag):
            raise ValueError(f"Hashtag inválida: {value}")
        if tag.casefold() not in existing:
            added.append(f"#{tag}")
            existing.add(tag.casefold())
    if not added:
        return description
    return (description.rstrip() + "\n\n" if description.strip() else "") + " ".join(added)
