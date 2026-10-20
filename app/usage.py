"""Gemini model kullanım istatistikleri (günlük, kalıcı).

Her model için: ok (başarılı), quota (kota doldu 429), busy (yoğun 503), error (diğer hata).
"""
from __future__ import annotations

import json
import threading
from datetime import date

from app.config import ROOT

_FILE = ROOT / "data" / "model_usage.json"
_lock = threading.Lock()
KINDS = ("ok", "quota", "busy", "error")


def _load() -> dict:
    if _FILE.exists():
        try:
            return json.loads(_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def record(model: str, kind: str) -> None:
    with _lock:
        data = _load()
        day = data.setdefault(date.today().isoformat(), {})
        counts = day.setdefault(model, {k: 0 for k in KINDS})
        counts[kind] = counts.get(kind, 0) + 1
        _FILE.parent.mkdir(parents=True, exist_ok=True)
        _FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def summary_text(days: int = 3) -> str:
    """Telegram (HTML) için son N günün model kullanım özeti."""
    data = _load()
    if not data:
        return "Henüz kayıtlı model kullanımı yok. Bir tarama veya CV düzenleme sonrası tekrar dene."
    lines = ["📊 <b>Gemini model kullanımı</b>"]
    for day in sorted(data, reverse=True)[:days]:
        lines.append(f"\n📅 <b>{day}</b>")
        models = sorted(data[day].items(), key=lambda kv: -kv[1].get("ok", 0))
        for model, c in models:
            lines.append(
                f"• <code>{model}</code>: ✅ {c.get('ok', 0)} başarılı"
                f" · 🚫 {c.get('quota', 0)} kota"
                f" · ⏳ {c.get('busy', 0)} yoğun"
                f" · ❌ {c.get('error', 0)} hata"
            )
    lines.append("\nℹ️ Ücretsiz planda her modelin günlük ~20 istek kotası ayrıdır.")
    return "\n".join(lines)
