"""Validate shared request profiles and public replay data at the worker boundary."""

import math


def validate_clip_profile(profile):
    duration, before, count = (
        profile[key] for key in ("duration", "beforePeak", "maxMoments")
    )
    if (
        not all(
            isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
            for v in (duration, before, count)
        )
        or not 5 <= duration <= 180
        or not 0 <= before <= duration
        or not isinstance(count, int)
        or not 1 <= count <= 30
    ):
        raise ValueError("Perfil de clip inválido.")


def validate_render_profile(profile):
    if (
        set(profile) - {"aspect", "fit", "captions"}
        or profile.get("aspect", "9:16") not in ("9:16", "16:9", "1:1")
        or profile.get("fit", "pad") not in ("pad", "crop")
        or not isinstance(profile.get("captions", False), bool)
    ):
        raise ValueError("Perfil de rendering inválido.")


def validate_heatmap_points(points, duration):
    if len(points) > 10000:
        raise ValueError("Demasiados pontos no heatmap.")
    previous = 0.0
    for item in sorted(points, key=lambda p: p["start_time"]):
        start, end, value = (item[key] for key in ("start_time", "end_time", "value"))
        if (
            not all(math.isfinite(v) for v in (start, end, value))
            or start < previous - 0.001
            or not 0 <= start < end <= duration + 1
            or not 0 <= value <= 1
        ):
            raise ValueError("Heatmap inválido.")
        previous = end
