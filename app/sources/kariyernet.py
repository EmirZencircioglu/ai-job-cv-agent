"""Kariyer.net arama sayfaları (sunucu tarafında üretilen HTML)."""
from __future__ import annotations

import logging
import re

import httpx
from bs4 import BeautifulSoup

from app.models import Job, polite_sleep
from app.progress import ProgressFn, noop

log = logging.getLogger(__name__)

BASE = "https://www.kariyer.net"


def _text(el) -> str:
    return el.get_text(" ", strip=True) if el else ""


def search(
    client: httpx.Client,
    queries: list[str],
    city_slug: str = "istanbul",
    on_issue: ProgressFn = noop,
) -> list[Job]:
    jobs: dict[str, Job] = {}
    blocked_reported = False
    for q in queries:
        url = f"{BASE}/is-ilanlari/{city_slug}-{q}"
        try:
            r = client.get(url)
            r.raise_for_status()
        except httpx.HTTPError as e:
            log.warning("Kariyer.net arama hatası (%s): %s", q, e)
            if not blocked_reported:
                blocked_reported = True
                on_issue("⚠️ Kariyer.net geçici hız sınırı (403) uyguladı; erişilebilen ilanlarla devam ediliyor.")
            continue

        soup = BeautifulSoup(r.text, "html.parser")
        for card in soup.select('div[data-test="ad-card"]'):
            a = card.select_one("a[href*='/is-ilani/']")
            if not a:
                continue
            href = a["href"].split("?")[0]
            m = re.search(r"-(\d+)$", href)
            if not m:
                continue
            jid = m.group(1)
            jobs[jid] = Job(
                source="Kariyer.net",
                native_id=jid,
                title=_text(card.select_one('[data-test="ad-card-title"]')),
                company=_text(card.select_one('[data-test="subtitle"]')),
                location=card.get("cityname", ""),
                url=BASE + href,
                posted=card.get("time", ""),
                extra={
                    "Pozisyon": card.get("positionname", ""),
                    "Çalışma şekli": card.get("worktypetext", ""),
                    "Çalışma modeli": card.get("workmodeltext", ""),
                    "Sektör": card.get("sectorname", ""),
                },
            )
        polite_sleep()
    log.info("Kariyer.net: %d ilan bulundu", len(jobs))
    return list(jobs.values())


def fetch_detail(client: httpx.Client, job: Job) -> Job:
    try:
        r = client.get(job.url)
        r.raise_for_status()
    except httpx.HTTPError as e:
        log.warning("Kariyer.net detay hatası (%s): %s", job.native_id, e)
        return job
    soup = BeautifulSoup(r.text, "html.parser")
    job.description = _text(soup.select_one('[data-test="qualifications-and-job-description"]'))
    if not job.title:
        job.title = _text(soup.select_one("h1"))
    if not job.company:
        job.company = _text(soup.select_one('[data-test="job-detail-company-card-large-detail"] a, .company-name'))
    return job


def job_from_url(url: str) -> Job | None:
    """E-postadaki bir kariyer.net ilan linkinden boş bir Job oluşturur."""
    m = re.search(r"(/is-ilani/[^?#\s\"']+-(\d+))", url)
    if not m:
        return None
    return Job(source="Kariyer.net", native_id=m.group(2), title="", company="", location="",
               url=BASE + m.group(1))
