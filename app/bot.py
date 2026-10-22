"""Telegram botu: ilan bildirimleri, butonlar ve komutlar.

Komutlar:
    /start   - Karşılama ve yardım
    /profil  - CV analizinin özeti
    /esik 70 - Bildirim için minimum uyum skorunu değiştirir
    /durum   - Agent'ın durumu
    /test    - Örnek bir ilan bildirimi gönderir
"""
from __future__ import annotations

import html
import json
import logging
from dataclasses import dataclass, field

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    filters,
)

from app.config import ROOT, env, settings

log = logging.getLogger(__name__)
STATE_FILE = ROOT / "data" / "state.json"


# ---------------------------------------------------------------- durum (state)
def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {}


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def min_score() -> int:
    return int(load_state().get("min_score", settings()["matching"]["min_score"]))


# ---------------------------------------------------------------- ilan kartı
@dataclass
class JobCard:
    job_id: str
    title: str
    company: str
    location: str
    url: str
    source: str
    score: int
    matched: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    reason: str = ""
    posted: str = ""


def format_job(job: JobCard) -> str:
    e = html.escape
    bar = "🟩" * (job.score // 20) + "⬜" * (5 - job.score // 20)
    lines = [
        f"💼 <b>{e(job.title)}</b>",
        f"🏢 {e(job.company)}  ·  📍 {e(job.location)}",
        f"📊 Uyum: <b>%{job.score}</b> {bar}",
    ]
    if job.posted:
        lines.append(f"🕒 Yayınlanma: <b>{e(job.posted)}</b>")
    if job.matched:
        lines.append(f"✅ Eşleşen: {e(', '.join(job.matched))}")
    if job.missing:
        lines.append(f"⚠️ Eksik: {e(', '.join(job.missing))}")
    if job.reason:
        lines.append(f"\n💬 <i>{e(job.reason)}</i>")
    lines.append(f"\n🔎 Kaynak: {e(job.source)}")
    return "\n".join(lines)


def job_buttons(job: JobCard) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🔗 İlana Git", url=job.url)],
            [
                InlineKeyboardButton("📝 CV'mi Düzenle", callback_data=f"tailor:{job.job_id}"),
                InlineKeyboardButton("❌ İlgilenmiyorum", callback_data=f"skip:{job.job_id}"),
            ],
        ]
    )


async def send_job(app: Application, job: JobCard) -> None:
    await app.bot.send_message(
        chat_id=int(env("TELEGRAM_CHAT_ID")),
        text=format_job(job),
        parse_mode=ParseMode.HTML,
        reply_markup=job_buttons(job),
        disable_web_page_preview=True,
    )


# ---------------------------------------------------------------- komutlar
HELP = (
    "👋 Merhaba! Ben <b>Emir İş Asistanı</b>.\n\n"
    "CV'ine uygun staj ilanlarını LinkedIn ve Kariyer.net'te otomatik tarayıp sana bildireceğim. "
    "Beğendiğin ilanda <b>📝 CV'mi Düzenle</b> butonuna basarsan o ilana özel PDF CV hazırlarım.\n\n"
    "<b>Komutlar</b>\n"
    "/ara - Şimdi yeni ilan tara\n"
    "/son - Son 1 haftada bulunan en uygun ilanları tekrar listele\n"
    "/modeller - Kullanılan Gemini modelleri ve kullanım sıklıkları\n"
    "/profil - CV analizimin özeti\n"
    "/esik 65 - Minimum uyum skorunu ayarla\n"
    "/durum - Agent durumu\n"
    "/test - Örnek ilan bildirimi"
)


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_html(HELP)


async def cmd_profil(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    from app.cv_parser import load_profile

    p = load_profile()
    e = html.escape
    skills = p.technical_skills + p.finance_skills
    text = (
        f"👤 <b>{e(p.full_name)}</b>\n\n"
        f"🛠 <b>Beceriler:</b> {e(', '.join(skills[:15]))}\n"
        f"🌐 <b>Diller:</b> {e(', '.join(p.languages))}\n"
        f"📜 <b>Sertifikalar:</b> {e(', '.join(p.certificates) or '-')}\n\n"
        f"💪 <b>Güçlü yönler</b>\n" + "\n".join(f"• {e(s)}" for s in p.strengths) + "\n\n"
        f"⚠️ <b>Geliştirilebilecekler</b>\n" + "\n".join(f"• {e(g)}" for g in p.gaps)
    )
    await update.message.reply_html(text)


async def cmd_esik(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not ctx.args or not ctx.args[0].isdigit() or not 0 <= int(ctx.args[0]) <= 100:
        await update.message.reply_html(
            f"Şu anki eşik: <b>%{min_score()}</b>\nDeğiştirmek için: <code>/esik 65</code> (0-100)"
        )
        return
    from app import storage
    from app.scanner import notify_pending

    new_val = int(ctx.args[0])
    state = load_state()
    state["min_score"] = new_val
    save_state(state)
    promoted = storage.reevaluate_threshold(new_val)
    await update.message.reply_html(f"✅ Artık uyum skoru <b>%{new_val}</b> ve üzeri ilanları bildireceğim.")
    if promoted:
        await notify_pending(ctx.application, force=True)


async def cmd_durum(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    from app import storage

    state = load_state()
    s = settings()
    st = storage.stats()
    text = (
        "🟢 <b>Agent çalışıyor</b>\n\n"
        f"📍 Konum: {html.escape(s['search']['location'])}\n"
        f"🎯 Eşik: %{min_score()}\n"
        f"⏱ Otomatik tarama: ~{s['scheduler']['interval_minutes']} dk'da bir\n"
        f"🕐 Son tarama: {state.get('last_scan', 'henüz yapılmadı')}\n\n"
        f"📦 Toplam incelenen (son 1 hafta): {sum(st.values())}\n"
        f"📨 Bildirilen: {st.get('notified', 0)}  ·  ⏳ Bekleyen: {st.get('scored', 0)}\n"
        f"📉 Eşik altı: {st.get('below', 0)}  ·  ❌ Gizlenen: {st.get('skipped', 0)}"
    )
    await update.message.reply_html(text)


async def cmd_ara(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    import asyncio
    from app import storage
    from app.scanner import _lock, notify_pending, run_scan

    loop = asyncio.get_running_loop()

    def live_report(msg: str) -> None:
        asyncio.run_coroutine_threadsafe(update.message.reply_text(msg), loop)

    if _lock.locked():
        await update.message.reply_text(
            "⏳ Şu an arka planda otomatik tarama zaten çalışıyor (LinkedIn ve Kariyer.net bekleme süreleriyle ~4-5 dk sürer). "
            "Bittiği anda sonuçları hemen göndereceğim..."
        )
        while _lock.locked():
            await asyncio.sleep(2)
        sent = await notify_pending(ctx.application, force=True)
        st = storage.stats()
        await update.message.reply_html(
            f"✅ Arka plandaki tarama tamamlandı! ({sent} yeni uygun ilan gönderildi, toplam {sum(st.values())} ilan kayıtlı).\n"
            "💡 Son 1 haftada bulunan en uygun ilanların tamamını görmek için <code>/son</code> yazabilirsin."
        )
        return

    await update.message.reply_text("🔎 Son 3 günlük ve anlık yeni ilanlar taranıyor, yaşanan her durumu anlık bildireceğim...")
    new, sent = await run_scan(ctx.application, force_notify=True, on_issue=live_report)
    st = storage.stats()
    if sent == 0:
        await update.message.reply_html(
            f"✅ Tarama bitti ({new} yeni ilan incelendi, toplam {sum(st.values())} ilan kayıtlı).\n"
            f"Son taramadan beri <b>%{min_score()}</b> eşiğini geçen <i>daha önce gönderilmemiş</i> yeni bir ilan çıkmadı.\n\n"
            "💡 Son 3 günde bulunan en uygun ilanları tekrar görmek için <code>/son</code> yazabilirsin."
        )
    else:
        await update.message.reply_text(f"✅ Tarama bitti. {new} yeni ilan incelendi, {sent} tanesini gönderdim.")


async def cmd_son(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    import asyncio
    from app import storage
    from app.scanner import _card

    limit = int(ctx.args[0]) if (ctx.args and ctx.args[0].isdigit()) else 10
    rows = storage.top_jobs(min_sc=60, limit=min(limit, 15))
    if not rows:
        await update.message.reply_text("Son 3 günde kayıtlı uygun ilan yok. /ara ile tarama başlatabilirsin.")
        return
    await update.message.reply_html(
        f"📋 <b>Son 3 günde bulunan en yüksek puanlı {len(rows)} taze staj ilanı:</b>"
    )
    for row in rows:
        await send_job(ctx.application, _card(row, json.loads(row["match_json"])))
        await asyncio.sleep(0.6)


async def cmd_test(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    demo = JobCard(
        job_id="demo",
        title="Yatırım Analizi Stajyeri (6 Ay, Yarı Zamanlı)",
        company="Örnek Portföy Yönetimi A.Ş.",
        location="İstanbul (Hibrit)",
        url="https://www.linkedin.com/jobs/",
        source="LinkedIn (örnek)",
        score=84,
        matched=["Python", "Mali Tablo Analizi", "Temel Analiz"],
        missing=["Bloomberg Terminal"],
        reason="Finans altyapın ve Python ile yaptığın analiz projeleri ilandaki gereksinimlerle güçlü şekilde örtüşüyor.",
    )
    await send_job(ctx.application, demo)


# ---------------------------------------------------------------- butonlar
async def on_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    action, job_id = query.data.split(":", 1)

    if action == "skip":
        await query.answer("Tamam, bu ilanı gizledim.")
        await query.edit_message_reply_markup(reply_markup=None)
        from app import storage

        storage.set_status(job_id, "skipped")
    elif action == "tailor":
        await query.answer("CV hazırlanıyor...")
        import asyncio
        from app import storage
        from app.cv_parser import load_profile
        from app.pdf_render import render_cv_pdf
        from app.tailor import tailor_cv

        if job_id == "demo":
            job = {
                "id": "demo",
                "title": "Yatırım Analizi Stajyeri (6 Ay, Yarı Zamanlı)",
                "company": "Örnek Portföy Yönetimi A.Ş.",
                "location": "İstanbul (Hibrit)",
                "description": (
                    "Portföy yönetimi ve yatırım araştırmaları ekibimizde 6 ay boyunca haftada en az 3 gün görev alacak "
                    "stajyer arıyoruz. Mali tablo analizi, temel ve teknik analiz süreçlerine destek olmak, Python ve Excel "
                    "ile finansal veri analizi ve raporlama yapmak, piyasa bültenlerinin hazırlanmasına katkıda bulunmak."
                ),
            }
        else:
            job = storage.get(job_id)

        if not job:
            await query.message.reply_text("❌ Bu ilanın detayı veritabanında bulunamadı.")
            return

        wait_msg = await query.message.reply_text(
            f"⏳ <b>{html.escape(job['title'])}</b> ({html.escape(job['company'])}) ilanı için CV'n uyarlanıyor, "
            "15-20 saniye sürebilir...",
            parse_mode=ParseMode.HTML,
        )
        loop = asyncio.get_running_loop()

        def live_report(msg: str) -> None:
            asyncio.run_coroutine_threadsafe(query.message.reply_text(msg), loop)

        try:
            profile = await asyncio.to_thread(load_profile)
            tailored = await asyncio.to_thread(tailor_cv, profile, job, live_report)
            pdf_path = await asyncio.to_thread(render_cv_pdf, profile, tailored, job)
        except Exception as exc:  # noqa: BLE001
            log.exception("CV uyarlama hatası")
            await wait_msg.edit_text(f"❌ CV hazırlanırken hata oluştu:\n{exc}")
            return

        e = html.escape
        notes = "\n".join(f"• {e(n)}" for n in tailored.tailoring_notes)
        short_caption = f"📄 <b>{e(job['company'])} — {e(job['title'])}</b> için uyarlanmış CV'n hazır!"
        details_msg = (
            f"🔧 <b>CV'de Neler Öne Çıkarıldı:</b>\n{notes}\n\n"
            f"✉️ <b>Ön Yazı Önerisi:</b>\n<i>{e(tailored.cover_note)}</i>"
        )
        with open(pdf_path, "rb") as f:
            await query.message.reply_document(
                document=f,
                filename=f"{profile.full_name} CV.pdf",
                caption=short_caption[:1024],
                parse_mode=ParseMode.HTML,
            )
        await query.message.reply_html(details_msg[:4096])
        await wait_msg.delete()


async def cmd_modeller(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    from app import usage

    cfg = settings()["gemini"]
    chain = [cfg["model"], *cfg.get("fallback_models", [])]
    header = "🤖 <b>Aktif Model Zinciri (Sırasıyla):</b>\n" + "\n".join(
        f"{i}. <code>{m}</code>" + (" <i>(Ana Model)</i>" if i == 1 else " <i>(Yedek)</i>")
        for i, m in enumerate(chain, 1)
    )
    await update.message.reply_html(header + "\n\n" + usage.summary_text())


_bg_net_errors = 0


async def on_error(update: object, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Ciddi hataları ve kullanıcı işlemlerindeki tüm sorunları Telegram'a bildirir;
    yalnızca boşta beklerken (update=None) yaşanan tekil 1 saniyelik soket yenilemelerini susturur.
    """
    global _bg_net_errors
    err = ctx.error
    err_str = f"{type(err).__name__}: {err}" if err else "Bilinmeyen hata"
    is_transient_net = any(
        k in err_str for k in ("ReadError", "ConnectError", "RemoteProtocolError", "TimedOut", "NetworkError")
    )

    # Boşta beklerken (kullanıcı komutu yokken) tekil soket yenilenmesi olduysa:
    if update is None and is_transient_net:
        _bg_net_errors += 1
        log.info("Anlık arka plan bağlantı yenilenmesi (%d): %s", _bg_net_errors, err_str)
        if _bg_net_errors < 3:
            return  # 1-2 kerelik anlık yenilenmede rahatsız etme; 3 kez üst üste olursa ciddi sayıp bildir!
    else:
        _bg_net_errors = 0

    log.error("Ciddi/işlem hatası:", exc_info=err)
    try:
        await ctx.application.bot.send_message(
            chat_id=int(env("TELEGRAM_CHAT_ID")),
            text=f"❌ İşlem sırasında beklenmeyen bir sorun oluştu:\n{err_str}",
        )
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------- uygulama
def build_app() -> Application:
    app = Application.builder().token(env("TELEGRAM_BOT_TOKEN")).build()
    only_me = filters.Chat(chat_id=int(env("TELEGRAM_CHAT_ID")))  # Başkaları botu kullanamaz

    app.add_handler(CommandHandler(["start", "yardim", "help"], cmd_start, filters=only_me))
    app.add_handler(CommandHandler("profil", cmd_profil, filters=only_me))
    app.add_handler(CommandHandler("esik", cmd_esik, filters=only_me))
    app.add_handler(CommandHandler("durum", cmd_durum, filters=only_me))
    app.add_handler(CommandHandler("modeller", cmd_modeller, filters=only_me))
    app.add_handler(CommandHandler("test", cmd_test, filters=only_me))
    app.add_handler(CommandHandler("son", cmd_son, filters=only_me))
    app.add_handler(CommandHandler("ara", cmd_ara, filters=only_me, block=False))
    app.add_handler(CallbackQueryHandler(on_button, block=False))
    app.add_error_handler(on_error)
    return app
