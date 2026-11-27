"""Visual style and metadata shared by the vertical review clips."""

import re

# Both CLIs use one ASS implementation, restored from the original Shorts style.
from pathlib import Path
import sys

application_root = str(Path(__file__).resolve().parents[1])
if application_root not in sys.path:
    sys.path.insert(0, application_root)
from pipeline.caption_style import CAPTION_HEADER, ass_time, timed_captions


def format_description(description, hashtags, twitch_url=None, youtube_url=None):
    credits = [
        f"{label}: {url}"
        for label, url in (("Twitch", twitch_url), ("YouTube", youtube_url))
        if url
    ]
    if credits:
        description = "\n\n".join(
            filter(None, (description.rstrip(), "\n".join(credits)))
        )
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
    return (description.rstrip() + "\n\n" if description.strip() else "") + " ".join(
        added
    )
