"""Index continuous video blocks for editorial review without using chat."""

import argparse
import json
from pathlib import Path
import re
from statistics import median
import subprocess


def measurement(source, stream):
    if stream == "video":
        filters = ("fps=5,scale=320:-2,blackdetect=d=1:pix_th=0.10,"
                   "scdet=t=8,metadata=print:key=lavfi.scd.score:file=-")
        selection = ["-an", "-vf", filters]
    else:
        filters = ("aformat=sample_rates=16000:channel_layouts=mono,asetnsamples=n=16000,"
                   "astats=metadata=1:reset=1,ametadata=print:key=lavfi.astats.Overall.RMS_level:file=-")
        selection = ["-vn", "-af", filters]
    return subprocess.run(
        ["ffmpeg", "-nostdin", "-hide_banner", "-v", "info", "-i", str(source), *selection, "-f", "null", "-"],
        check=True, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
    )


def time_series(output, key):
    values = re.findall(r"pts_time:([\d.]+)\n" + re.escape(key) + r"=([^\s]+)", output)
    return [(round(float(at), 2), float(value)) for at, value in values]


def strongest(values, limit=8):
    chosen = []
    for at, magnitude in sorted(values, key=lambda value: value[1], reverse=True):
        if all(abs(at - point["seconds"]) >= 6 for point in chosen):
            chosen.append({"seconds": at, "change": round(magnitude, 2)})
        if len(chosen) == limit:
            break
    return sorted(chosen, key=lambda point: point["seconds"])


def loudness_peaks(output):
    rms = [(at, max(-70, value))
           for at, value in time_series(output, "lavfi.astats.Overall.RMS_level")]
    peaks = []
    for index in range(6, len(rms)):
        at, level = rms[index]
        reference = median(value for _, value in rms[max(0, index - 12):index])
        if level > -36 and level - reference >= 8:
            peaks.append((at, level - reference))
    return strongest(peaks)


def sheets(source, destination, period):
    windows_font = Path("C:/Windows/Fonts/arial.ttf")
    font = "fontfile='C\\:/Windows/Fonts/arial.ttf':" if windows_font.is_file() else ""
    filters = (f"fps=1/{period}:start_time=0:round=up,scale=192:-2,"
               f"drawtext={font}text='%{{pts\\:hms}}':x=5:y=5:"
               "fontsize=15:fontcolor=white:box=1:boxcolor=black@0.7,tile=6x5:padding=2")
    subprocess.run(
        ["ffmpeg", "-y", "-nostdin", "-hide_banner", "-v", "error", "-i", str(source),
         "-an", "-vf", filters, "-fps_mode", "passthrough", str(destination / "frames-%03d.jpg")],
        check=True, timeout=120,
    )


def scan(source, destination, period, model):
    visual = measurement(source, "video")
    has_audio = bool(subprocess.check_output(
        ["ffprobe", "-v", "error", "-select_streams", "a:0",
         "-show_entries", "stream=index", "-of", "csv=p=0", str(source)], timeout=15,
    ).strip())
    audio = measurement(source, "audio") if has_audio else None
    record = {
        "source": str(source),
        "frameInterval": period,
        "sceneChanges": strongest(
            [(at, value) for at, value in time_series(visual.stdout, "lavfi.scd.score") if value >= 8]
        ),
        "blackIntervals": [[float(start), float(end)] for start, end in re.findall(
            r"black_start:([\d.]+) black_end:([\d.]+)", visual.stderr
        )],
        "audioAvailable": has_audio,
        "audioRisesDb": loudness_peaks(audio.stdout) if audio else [],
    }
    sheets(source, destination, period)
    if model and has_audio:
        segments, _ = model.transcribe(str(source), language="en", beam_size=3,
                                       condition_on_previous_text=False, vad_filter=True)
        record["transcript"] = [[round(row.start, 2), round(row.end, 2), row.text.strip()]
                                for row in segments if row.no_speech_prob < 0.65]
    (destination / "index.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n",
                                            encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destino", type=Path)
    parser.add_argument("videos", type=Path, nargs="+")
    parser.add_argument("--intervalo", type=int, default=6)
    parser.add_argument("--transcrever", action="store_true")
    args = parser.parse_args()
    if args.intervalo < 1 or len({video.stem for video in args.videos}) != len(args.videos):
        parser.error("Usa um intervalo positivo e ficheiros com nomes distintos.")
    model = None
    if args.transcrever:
        from faster_whisper import WhisperModel

        model = WhisperModel("small", device="cpu", compute_type="int8", local_files_only=True)
    for source in args.videos:
        destination = args.destino / source.stem
        destination.mkdir(parents=True, exist_ok=True)
        scan(source.resolve(strict=True), destination, args.intervalo, model)
        print(destination, flush=True)


if __name__ == "__main__":
    main()
