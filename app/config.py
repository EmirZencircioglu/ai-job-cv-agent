"""config.yaml ve .env dosyalarını yükler."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


@lru_cache
def settings() -> dict:
    with open(ROOT / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def path(key: str) -> Path:
    """config.yaml içindeki `paths` anahtarını mutlak yola çevirir."""
    p = ROOT / settings()["paths"][key]
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def env(name: str, required: bool = True) -> str | None:
    value = os.getenv(name)
    if required and not value:
        raise RuntimeError(
            f"'{name}' tanımlı değil. .env.example dosyasını .env olarak kopyalayıp doldurun."
        )
    return value
