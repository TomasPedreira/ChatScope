"""Public replay data or audio energy: evidence for review, not semantic judgement."""
from array import array
import math

import sys

from .tools import ffmpeg, run


def audio_energy(path, start, end, origin=0):
    pcm = run([ffmpeg(), "-v", "error", "-nostdin", "-ss", str(start - origin),
               "-i", str(path), "-t", str(end - start), "-vn", "-ac", "1", "-ar", "8000",
               "-f", "s16le", "pipe:1"], timeout=max(60, end - start + 30))
    samples = array("h")
    samples.frombytes(pcm)
    if sys.byteorder != "little":
        samples.byteswap()
    values = []
    for offset in range(0, len(samples), 8000):
        chunk = samples[offset:offset + 8000]
        if not chunk:
            continue
        rms = math.sqrt(sum(v * v for v in chunk) / len(chunk)) / 32768
        values.append(20 * math.log10(max(rms, 1e-6)))
    if not values:
        return []
    # Fixed dB scale preserves silence and does not amplify barely audible noise.
    return [{"start_time": start + i, "end_time": min(end, start + i + 1),
             "value": max(0.0, min(1.0, (db + 60) / 60))} for i, db in enumerate(values)]


def validate_profile(profile):
    duration, before, count = (profile[key] for key in ("duration", "beforePeak", "maxMoments"))
    if (not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
                for v in (duration, before, count)) or not 5 <= duration <= 180
            or not 0 <= before <= duration or not isinstance(count, int) or not 1 <= count <= 30):
        raise ValueError("Perfil de clip inválido.")
