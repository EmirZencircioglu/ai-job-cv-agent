"""Gemini istemcisi için ortak yardımcılar (akıllı bekleme ve sessiz yedek model geçişli)."""
from __future__ import annotations

import logging
import time
from functools import lru_cache
from typing import TypeVar

from google import genai
from google.genai import types
from pydantic import BaseModel

from app import usage
from app.config import env, settings
from app.progress import ProgressFn, noop

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)

# Model bazlı geçici bekleme süreleri (model_adı -> unix_timestamp)
# 429 (kota) alan model 2 saat, 503 (yoğunluk) alan model 15 dakika dinlendirilir.
_cooldown_until: dict[str, float] = {}


@lru_cache
def client() -> genai.Client:
    return genai.Client(api_key=env("GEMINI_API_KEY"))


def _candidate_models() -> list[str]:
    cfg = settings()["gemini"]
    primary = cfg["model"]
    fallbacks = cfg.get("fallback_models", [])
    all_models = [primary, *[m for m in fallbacks if m != primary]]
    now = time.time()
    # Önce bekleme süresi (cooldown) olmayan modelleri dene
    active = [m for m in all_models if _cooldown_until.get(m, 0) <= now]
    if not active:
        # Hepsi beklemedeyse en erken açılacak olandan başlayarak sırala
        return sorted(all_models, key=lambda m: _cooldown_until.get(m, 0))
    return active


def generate_structured(
    contents: list,
    schema: type[T],
    system: str | None = None,
    on_issue: ProgressFn = noop,
) -> T:
    """Gemini'den verilen Pydantic şemasına uygun JSON yanıt alır.
    Bir model 429 (kota) veya 503 (yoğunluk) verirse Telegram'ı mesaj yağmuruna tutmadan
    sessizce sıradaki çalışan yedek modele geçer ve sorunlu modeli dinlenmeye alır.
    """
    last_err: Exception | None = None
    for model_name in _candidate_models():
        try:
            response = client().models.generate_content(
                model=model_name,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    response_mime_type="application/json",
                    response_schema=schema,
                    temperature=0.2,
                ),
            )
            usage.record(model_name, "ok")
            _cooldown_until.pop(model_name, None)
            if response.parsed is not None:
                return response.parsed
            return schema.model_validate_json(response.text)
        except Exception as e:  # noqa: BLE001
            last_err = e
            msg = str(e)
            if "429" in msg or "RESOURCE_EXHAUSTED" in msg or "404" in msg or "NOT_FOUND" in msg:
                log.info("Gemini %s kotası doldu (2 saat dinlendiriliyor), yedek modele geçiliyor...", model_name)
                usage.record(model_name, "quota")
                _cooldown_until[model_name] = time.time() + 7200
                continue
            if "503" in msg or "UNAVAILABLE" in msg:
                log.info("Gemini %s şu an yoğun (15 dk dinlendiriliyor), yedek modele geçiliyor...", model_name)
                usage.record(model_name, "busy")
                _cooldown_until[model_name] = time.time() + 900
                continue
            usage.record(model_name, "error")
            raise
    raise last_err  # type: ignore[misc]
