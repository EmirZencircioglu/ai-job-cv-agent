"""Agent'ı başlatır (Telegram polling + bulut sağlık sunucusu).

Kullanım:
    python -m app.main
"""
from __future__ import annotations

import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
from telegram import BotCommand

from app.bot import build_app
from app.config import env
from app.scanner import schedule_next

logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("fontTools").setLevel(logging.WARNING)
log = logging.getLogger(__name__)


class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(b'{"status":"ok","service":"emir-is-asistani"}')

    def do_HEAD(self) -> None:  # noqa: N802
        self.send_response(200)
        self.end_headers()

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        return  # Sağlık kontrolü istekleriyle logları kirletme


def start_health_server() -> None:
    """Render / Koyeb gibi bulut servisleri için arka planda /health HTTP sunucusu başlatır."""
    port = int(os.getenv("PORT", "10000"))
    try:
        server = ThreadingHTTPServer(("0.0.0.0", port), _HealthHandler)
    except OSError as e:
        log.warning("Sağlık sunucusu port %d üzerinde başlatılamadı (zaten kullanımda olabilir): %s", port, e)
        return
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    log.info("Bulut sağlık sunucusu aktif: http://0.0.0.0:%d/health", port)


async def _self_ping(ctx) -> None:
    url = os.getenv("RENDER_EXTERNAL_URL")
    if not url:
        return
    target = url.rstrip("/") + "/health"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.get(target)
    except Exception:  # noqa: BLE001
        pass


async def post_init(app) -> None:
    await app.bot.set_my_commands(
        [
            BotCommand("ara", "Şimdi ilan tara"),
            BotCommand("son", "Son 1 haftanın en uygun ilanları"),
            BotCommand("modeller", "Gemini model kullanım istatistikleri"),
            BotCommand("durum", "Agent durumu"),
            BotCommand("profil", "CV analizinin özeti"),
            BotCommand("esik", "Minimum uyum skorunu ayarla"),
            BotCommand("test", "Örnek ilan bildirimi"),
            BotCommand("yardim", "Yardım"),
        ]
    )
    await app.bot.send_message(
        chat_id=int(env("TELEGRAM_CHAT_ID")),
        text="🟢 Emir İş Asistanı çalışmaya başladı! /yardim yazarak komutları görebilirsin.",
    )
    from app.scanner import notify_pending

    await notify_pending(app)
    schedule_next(app, first=True)
    if os.getenv("RENDER_EXTERNAL_URL"):
        app.job_queue.run_repeating(_self_ping, interval=600, first=300, name="self_ping")


def main() -> None:
    start_health_server()
    app = build_app()
    app.post_init = post_init
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
