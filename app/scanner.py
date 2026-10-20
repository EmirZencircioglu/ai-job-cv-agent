"""Tarama döngüsü: topla → puanla → bildir."""
from __future__ import annotations

import asyncio
import logging
import random
import time
from datetime import datetime

from telegram.ext import Application, ContextTypes

from app import storage
from app.bot import JobCard, load_state, min_score, save_state, send_job
from app.collector import collect
from app.config import settings
from app.cv_parser import load_profile
from app.matcher import score_job, score_jobs_batch
from app.progress import ProgressFn, noop

log = logging.getLogger(__name__)
_lock = asyncio.Lock()


def _quiet_now() -> bool:
    start, end = settings()["scheduler"]["quiet_hours"]
    h = datetime.now().hour
    return h >= start or h < end if start > end else start <= h < end


def _card(row: dict, m: dict) -> JobCard:
    extras = []
    if m.get("duration_months"):
        extras.append(f"{m['duration_months']} ay")
    if m.get("project_based"):
        extras.append("proje bazlı")
    if m.get("work_model"):
        extras.append(m["work_model"])
    loc = row["location"] + (f" · {', '.join(extras)}" if extras else "")
    return JobCard(
        job_id=row["id"], title=row["title"], company=row["company"], location=loc,
        url=row["url"], source=row["source"], score=int(m["score"]),
        matched=m.get("matched_skills", []), missing=m.get("missing_skills", []),
        reason=m.get("reason", ""),
    )


def _score_new(on_issue: ProgressFn = noop) -> None:
    """'new' durumundaki ilanları 6'lı paketler halinde topluca puanlar (kota tüketimini %85 azaltır)."""
    profile = load_profile()
    threshold = min_score()
    pending = storage.by_status("new")
    if not pending:
        return

    batch_size = 6
    on_issue(f"🧠 {len(pending)} yeni ilan toplu paket halinde Gemini ile puanlanıyor...")
    for i in range(0, len(pending), batch_size):
        chunk = pending[i : i + batch_size]
        try:
            mapped = score_jobs_batch(profile, chunk, on_issue=on_issue)
        except Exception as e:  # noqa: BLE001
            log.warning("Toplu puanlama hatası: %s", e)
            msg_str = str(e)
            if "429" in msg_str or "RESOURCE_EXHAUSTED" in msg_str or "503" in msg_str or "UNAVAILABLE" in msg_str:
                msg = "⚠️ Tüm Gemini modelleri şu an kota/yoğunluk sınırında; kalan ilanlar sonraki saat puanlanacak."
                log.warning(msg)
                on_issue(msg)
                break
            on_issue(f"⚠️ Puanlama sırasında hata: {msg_str[:120]}")
            continue

        for row in chunk:
            m = mapped.get(row["id"])
            if m is None:
                continue
            status = "scored" if (m.score >= threshold and m.is_internship) else "below"
            storage.set_match(row["id"], m.score, m.model_dump(), status)
            log.info("%3d  %s — %s", m.score, row["title"], row["company"])
        time.sleep(2)


async def notify_pending(app: Application, force: bool = False) -> int:
    """Eşik üstü, henüz bildirilmemiş ilanları gönderir."""
    if not force and _quiet_now():
        log.info("Sessiz saatler aktif; eşik üstü ilanlar sabah gönderilmek üzere bekletiliyor.")
        return 0
    import json

    rows = sorted(storage.by_status("scored"), key=lambda r: r["score"] or 0, reverse=True)
    for row in rows:
        await send_job(app, _card(row, json.loads(row["match_json"])))
        storage.set_status(row["id"], "notified")
        await asyncio.sleep(1)
    if rows:
        state = load_state()
        state["notified_count"] = state.get("notified_count", 0) + len(rows)
        save_state(state)
    return len(rows)


async def run_scan(app: Application, force_notify: bool = False, on_issue: ProgressFn = noop) -> tuple[int, int]:
    """Bir tam tarama turu. (yeni ilan sayısı, bildirilen sayısı) döner."""
    if _lock.locked():
        return (-1, 0)
    async with _lock:
        new_jobs = await asyncio.to_thread(collect, on_issue)
        await asyncio.to_thread(_score_new, on_issue)
        sent = await notify_pending(app, force=force_notify)
        state = load_state()
        state["last_scan"] = datetime.now().strftime("%d.%m.%Y %H:%M")
        save_state(state)
        log.info("Tarama bitti: %d yeni, %d bildirildi", len(new_jobs), sent)
        return (len(new_jobs), sent)


async def scheduled_scan(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    from app.config import env

    loop = asyncio.get_running_loop()
    chat_id = int(env("TELEGRAM_CHAT_ID"))

    def report(msg: str) -> None:
        # Otomatik arka plan taramasında sadece uyarı/hata (⚠️/❌) mesajlarını gönder
        if msg.startswith(("⚠️", "❌")):
            asyncio.run_coroutine_threadsafe(
                ctx.application.bot.send_message(chat_id=chat_id, text=msg),
                loop,
            )

    try:
        await run_scan(ctx.application, on_issue=report)
    except Exception as exc:  # noqa: BLE001
        log.exception("Zamanlanmış tarama başarısız")
        await ctx.application.bot.send_message(
            chat_id=chat_id,
            text=f"❌ Otomatik tarama sırasında beklenmeyen hata oluştu:\n{exc}",
        )
    finally:
        schedule_next(ctx.application)


def schedule_next(app: Application, first: bool = False) -> None:
    sch = settings()["scheduler"]
    delay = 30 if first else 60 * (sch["interval_minutes"] + random.randint(-sch["jitter_minutes"], sch["jitter_minutes"]))
    app.job_queue.run_once(scheduled_scan, when=delay, name="scan")
    log.info("Sonraki tarama %d dk sonra", delay // 60)
