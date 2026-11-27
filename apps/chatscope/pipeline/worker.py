"""Thin JSON transport entrypoint; analysis, production and storage live in services."""

import json
import re
import sys
from .source_analysis import analyze_media_request
from .clip_production import render_clip_batch


def main():
    request = json.load(sys.stdin)
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", request.get("id", "")):
        raise ValueError("Identificador de job inválido.")
    action = request["action"]
    result = (
        analyze_media_request(request)
        if action == "analyze"
        else render_clip_batch(request) if action == "render" else None
    )
    if result is None:
        raise ValueError("Operação desconhecida.")
    print(json.dumps(result, ensure_ascii=True, allow_nan=False), flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
