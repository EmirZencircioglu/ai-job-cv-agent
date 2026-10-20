"""Ortak veri modelleri ve HTTP yardımcıları."""
from __future__ import annotations

import random
import re
import time
from dataclasses import asdict, dataclass, field

import httpx

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:134.0) Gecko/20100101 Firefox/134.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
]


def random_headers() -> dict[str, str]:
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }


@dataclass
class Job:
    source: str                 # "LinkedIn" | "Kariyer.net"
    native_id: str              # Kaynağın kendi ilan numarası
    title: str
    company: str
    location: str
    url: str
    description: str = ""
    posted: str = ""
    extra: dict = field(default_factory=dict)  # çalışma tipi, model vb.

    @property
    def id(self) -> str:
        return f"{self.source}:{self.native_id}"

    @property
    def fingerprint(self) -> str:
        """Aynı ilanın farklı kaynaklarda tekrarını yakalamak için."""
        norm = lambda s: re.sub(r"[^a-z0-9çğıöşü]", "", s.lower())
        return f"{norm(self.title)}|{norm(self.company)}"

    def to_dict(self) -> dict:
        return asdict(self) | {"id": self.id}


def http_client() -> httpx.Client:
    return httpx.Client(headers=random_headers(), timeout=25, follow_redirects=True)


def polite_sleep(lo: float = 1.5, hi: float = 4.0) -> None:
    """Siteleri yormamak ve bot tespitini azaltmak için rastgele bekleme."""
    time.sleep(random.uniform(lo, hi))
