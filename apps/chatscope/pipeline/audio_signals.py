"""Decode audio to a normalized, timed energy signal."""

from array import array
import math
import sys
from .media_tools import resolve_ffmpeg_executable, run_media_command


def extract_audio_energy_signal(
    media_path,
    interval_start_seconds,
    interval_end_seconds,
    master_source_offset_seconds=0,
):
    pcm = run_media_command(
        [
            resolve_ffmpeg_executable(),
            "-v",
            "error",
            "-nostdin",
            "-ss",
            str(interval_start_seconds - master_source_offset_seconds),
            "-i",
            str(media_path),
            "-t",
            str(interval_end_seconds - interval_start_seconds),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "8000",
            "-f",
            "s16le",
            "pipe:1",
        ],
        timeout=max(60, interval_end_seconds - interval_start_seconds + 30),
    )
    samples = array("h")
    samples.frombytes(pcm)
    if sys.byteorder != "little":
        samples.byteswap()
    audio_levels_db = []
    for sample_offset in range(0, len(samples), 8000):
        chunk = samples[sample_offset : sample_offset + 8000]
        if not chunk:
            continue
        rms = math.sqrt(sum(v * v for v in chunk) / len(chunk)) / 32768
        audio_levels_db.append(20 * math.log10(max(rms, 1e-6)))
    if not audio_levels_db:
        return []
    # Fixed dB scale preserves silence and does not amplify barely audible noise.
    return [
        {
            "start_time": interval_start_seconds + i,
            "end_time": min(interval_end_seconds, interval_start_seconds + i + 1),
            "value": max(0.0, min(1.0, (db + 60) / 60)),
        }
        for i, db in enumerate(audio_levels_db)
    ]
