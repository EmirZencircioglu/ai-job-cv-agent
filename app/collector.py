"""Tüm kaynaklardan ilanları toplar, ön filtreler, tekilleştirir ve veritabanına kaydeder.

Kullanım (test):
    python -m app.collector
"""
from __future__ import annotations

import logging
import re
from itertools import zip_longest

from app import storage
from app.config import settings
from app.models import Job, http_client, polite_sleep
from app.progress import ProgressFn, noop
from app.sources import gmail_alerts, kariyernet, linkedin

log = logging.getLogger(__name__)

INTERN_RE = re.compile(r"staj|intern|trainee|we plus|genç yetenek|young talent|öğrenci|student", re.I)
LOCATION_OK = ("istanbul", "turkiye", "turkey", "remote", "uzaktan")


def _norm(s: str) -> str:
    """Türkçe büyük harfleri doğru küçült ('İ'.lower() Python'da 'i̇' olur)."""
    return s.replace("İ", "i").replace("I", "ı").lower().replace("ı", "i").replace("ü", "u")


def _prefilter(job: Job, excludes: list[str]) -> bool:
    """LLM'e gitmeden önce bariz uyumsuz ilanları eler (maliyet ve hız için)."""
    title = _norm(job.title or "")
    if any(_norm(x) in title for x in excludes):
        return False
    if job.source == "Kariyer.net" and title:
        # Kariyer.net aramaları gevşek; sadece staj ilanlarını tut
        if not (INTERN_RE.search(title) or "staj" in _norm(job.extra.get("Pozisyon", ""))):
            return False
    loc = _norm(job.location or "")
    if loc and not any(x in loc for x in LOCATION_OK):
        return False
    return True


def collect(on_issue: ProgressFn = noop) -> list[Job]:
    cfg = settings()
    s, src = cfg["search"], cfg["sources"]
    found: list[Job] = []

    with http_client() as client:
        if src["linkedin"]["enabled"]:
            found += linkedin.search(
                client, s["keywords"], src["linkedin"]["location"],
                src["linkedin"]["posted_within_days"], on_issue=on_issue,
            )
        if src["kariyernet"]["enabled"]:
            found += kariyernet.search(client, src["kariyernet"]["queries"], on_issue=on_issue)
        if src["gmail"]["enabled"]:
            found += gmail_alerts.fetch(client, src["gmail"]["lookback_days"])

        new_jobs: list[Job] = []
        seen_fp: set[str] = set()
        for job in found:
            if storage.is_seen(job) or job.id in {j.id for j in new_jobs}:
                continue
            if job.title and job.fingerprint in seen_fp:
                continue
            if not _prefilter(job, s["exclude_keywords"]):
                continue
            new_jobs.append(job)
            if job.title:
                seen_fp.add(job.fingerprint)

        # Kaynakları sırayla karıştır ki limit bir kaynağı tamamen dışarıda bırakmasın
        by_src: dict[str, list[Job]] = {}
        for j in new_jobs:
            by_src.setdefault(j.source, []).append(j)
        mixed = [j for grp in zip_longest(*by_src.values()) for j in grp if j]

        limit = src["max_new_jobs_per_run"]
        if len(mixed) > limit:
            log.info("%d yeni ilan var, bu turda %d tanesi işlenecek (kalanlar sonraki turda).", len(mixed), limit)
            mixed = mixed[:limit]

        result = []
        failures: dict[str, int] = {}
        skipped_sources: set[str] = set()
        for job in mixed:
            if failures.get(job.source, 0) >= 2:
                if job.source not in skipped_sources:
                    skipped_sources.add(job.source)
                    on_issue(f"⚠️ {job.source} ilan detaylarında hız sınırı koydu; kalan {job.source} ilanları sonraki tura bırakıldı.")
                continue
            fetcher = linkedin.fetch_detail if job.source == "LinkedIn" else kariyernet.fetch_detail
            job = fetcher(client, job)
            polite_sleep(2.5, 6.0)
            if not job.description:
                failures[job.source] = failures.get(job.source, 0) + 1
                continue  # Kaydetme; sonraki turda tekrar denenecek
            failures[job.source] = 0
            # E-postadan gelen ilanlar başlık bilgisi şimdi geldiği için tekrar filtrelenir
            if not job.title or not _prefilter(job, s["exclude_keywords"]) or storage.is_seen(job):
                continue
            storage.add(job)
            result.append(job)

    log.info("Toplam %d yeni ilan kaydedildi.", len(result))
    return result


if __name__ == "__main__":
    logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    jobs = collect()
    print(f"\n✅ {len(jobs)} yeni ilan:\n")
    for j in jobs:
        print(f"[{j.source}] {j.title} — {j.company} ({j.location}) | açıklama: {len(j.description)} krk")
        print(f"   {j.url}")
