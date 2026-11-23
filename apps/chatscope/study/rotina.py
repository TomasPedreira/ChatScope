"""Queue one ChatScope review in the existing Codex conversation."""

import argparse
from datetime import datetime
import os
from pathlib import Path
import sqlite3
import subprocess
from uuid import UUID
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[3]
LISBON = ZoneInfo("Europe/Lisbon")
SCHEDULE = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "ChatScope" / "Schedule"
CODEX_QUEUE = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex") / "queue_1.sqlite"
PROMPT = (
    "Ronda automática da triagem de Clipping. Lê AGENTS.md, docs/triagem/README.md e "
    "apps/chatscope/study/SHORTS.md. Verifica a rotação e o estado da recolha. Se houver diretos elegíveis e ainda "
    "não houver recolha ativa, inicia o ChatScope em segundo plano por até duas horas dentro do horário "
    "diurno. Revê o material novo com vídeo original, áudio ou transcrição e chat, incluindo janelas fora "
    "da deteção inicial. Se não houver diretos, reavalia clips em reserva e trechos de VOD ainda por rever. "
    "Usa os registos anteriores para evitar repetir o trabalho. Verifica os cortes aprovados que já ficaram "
    "pendentes na fila de Shorts antes de escolher outro. Em caso de limite de uploads do YouTube, "
    "consulta no registo da ronda a data da próxima tentativa. Publica quando houver evidência da ação e "
    "do desfecho no corte e a fila permitir, com um máximo de uma publicação a cada 30 minutos. Escreve "
    "títulos em inglês com tensão e uma pista concreta do clip. Guarda o desfecho para o vídeo. "
    "Respeita a proibição de tomar o rato ou o teclado. Regista as decisões e partilha nesta conversa os "
    "resultados novos. Termina a ronda depois do trabalho disponível. A próxima ronda vem do agendamento."
)


def pending(thread):
    with sqlite3.connect(CODEX_QUEUE.resolve().as_uri() + "?mode=ro", uri=True, timeout=4) as db:
        return db.execute(
            "SELECT 1 FROM queued_items WHERE thread_id=? LIMIT 1", (thread,)
        ).fetchone() is not None


def codex(executable, *args):
    return subprocess.run(
        [str(executable), *args], cwd=ROOT, stdin=subprocess.DEVNULL, capture_output=True,
        text=True, encoding="utf-8", errors="replace", timeout=50,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


def run(executable, thread, now, log, last_slot):
    if not 8 <= now.hour < 22:
        return
    slot = now.replace(minute=now.minute // 30 * 30, second=0, microsecond=0).isoformat()
    if last_slot.is_file() and last_slot.read_text(encoding="ascii").strip() == slot:
        return
    if pending(thread):
        log.write(f"{now.isoformat(timespec='seconds')} · Já existe uma ronda ou mensagem na fila.\n")
        return
    service = codex(executable, "app-server", "daemon", "start")
    if service.returncode:
        raise RuntimeError(service.stderr.strip() or "Falhou o arranque do Codex.")
    result = codex(executable, "queue", "-C", str(ROOT), "--thread", thread, "--message", PROMPT, "--resume")
    log.write(f"{now.isoformat(timespec='seconds')} · {result.stdout.strip()} {result.stderr.strip()}\n")
    if result.returncode:
        raise RuntimeError("Falhou o pedido de retoma.")
    temporary = last_slot.with_suffix(".tmp")
    temporary.write_text(slot + "\n", encoding="ascii")
    temporary.replace(last_slot)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex", required=True, type=Path)
    parser.add_argument("--thread", required=True, type=UUID)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    thread = str(args.thread)
    now = datetime.now(LISBON)
    if args.check:
        args.codex.resolve(strict=True)
        print(f"Conversa {thread} · fila acessível · mensagem pendente: {pending(thread)}")
        return
    SCHEDULE.mkdir(parents=True, exist_ok=True)
    with (SCHEDULE / f"rotina-{now:%Y%m%d}.log").open("a", encoding="utf-8") as log:
        try:
            run(args.codex, thread, now, log, SCHEDULE / "rotina-ultima-ronda.txt")
        except (OSError, RuntimeError, sqlite3.Error, subprocess.SubprocessError) as error:
            log.write(f"{now.isoformat(timespec='seconds')} · {error}\n")
            raise SystemExit(1) from error


if __name__ == "__main__":
    main()
