"""LinkedIn çok kanallı (429 hız sınırına takılmayan) ilan arama ve detay çekme modülü.

Kullanılan 3 alternatif kanal:
1. Ana SSR Arama Sayfası (`https://www.linkedin.com/jobs/search`) — Tek istekte ~60 ilan döner, API kotasına takılmaz.
2. Yedek Guest API (`https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search`) — 1. kanal başarısız olursa devreye girer.
3. Arama Motoru Köprüsü (DuckDuckGo `site:linkedin.com/jobs/view`) — LinkedIn sunucularına hiç istek atmadan indeks üzerinden ilan bulur.

Detay çekme için de önce doğrudan web ilan sayfası (`tr.linkedin.com/jobs/view/<id>`), yedek olarak Guest API kullanılır.
"""
from __future__ import annotations

import logging
import re
import urllib.parse

import httpx
from bs4 import BeautifulSoup

from app.models import Job, polite_sleep, random_headers
from app.progress import ProgressFn, noop

log = logging.getLogger(__name__)

SSR_SEARCH_URL = "https://www.linkedin.com/jobs/search"
API_SEARCH_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
WEB_DETAIL_URL = "https://tr.linkedin.com/jobs/view/{id}"
API_DETAIL_URL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{id}"
DDG_HTML_URL = "https://html.duckduckgo.com/html/"


def _text(el) -> str:
    return el.get_text(" ", strip=True) if el else ""


def _parse_cards(html_text: str, jobs: dict[str, Job]) -> int:
    soup = BeautifulSoup(html_text, "html.parser")
    added = 0
    for card in soup.select("div.base-card"):
        m = re.search(r"jobPosting:(\d+)", card.get("data-entity-urn", ""))
        if not m:
            continue
        jid = m.group(1)
        link = card.select_one("a.base-card__full-link")
        time_el = card.select_one("time")
        jobs[jid] = Job(
            source="LinkedIn",
            native_id=jid,
            title=_text(card.select_one(".base-search-card__title")),
            company=_text(card.select_one(".base-search-card__subtitle")),
            location=_text(card.select_one(".job-search-card__location")),
            url=(link["href"].split("?")[0] if link else f"https://www.linkedin.com/jobs/view/{jid}"),
            posted=time_el.get("datetime", "") if time_el else "",
        )
        added += 1
    return added


def _search_via_ddg(client: httpx.Client, jobs: dict[str, Job]) -> int:
    """LinkedIn'e hiç dokunmadan arama motoru köprüsü üzerinden yeni LinkedIn staj ilanlarını bulur."""
    from ddgs import DDGS

    queries = [
        "site:linkedin.com/jobs/view (Finans OR Finance OR Yatırım OR Investment OR Portföy) (Stajyer OR Intern) Istanbul",
        "site:linkedin.com/jobs/view (Data Analyst OR Veri Analizi OR Business Intelligence) (Stajyer OR Intern) Istanbul",
    ]
    added = 0
    ddgs = DDGS()
    for q in queries:
        try:
            for res in ddgs.text(q, region="tr-tr", max_results=10, backend="yahoo"):
                href = urllib.parse.unquote(res.get("href", ""))
                m = re.search(r"linkedin\.com/jobs/view/[^\"<>?\s]*?(\d{8,12})", href)
                if not m:
                    continue
                jid = m.group(1)
                if jid in jobs:
                    continue
                raw_title = res.get("title", "")
                snippet = res.get("body", "")
                title, company = raw_title, "LinkedIn İlanı"
                hm = re.match(r"^(.+?)\s+hiring\s+(.+?)(?:\s+in\s+|\s*\|\s*LinkedIn|$)", raw_title, re.I)
                if hm:
                    company, title = hm.group(1).strip(), hm.group(2).strip()
                else:
                    title = re.sub(r"\s*[-|]\s*LinkedIn.*$", "", raw_title, flags=re.I).strip()
                jobs[jid] = Job(
                    source="LinkedIn",
                    native_id=jid,
                    title=title,
                    company=company,
                    location="Istanbul, Turkey",
                    url=f"https://www.linkedin.com/jobs/view/{jid}",
                    description=snippet,
                )
                added += 1
        except Exception as e:  # noqa: BLE001
            log.debug("DDG LinkedIn yedek arama hatası: %s", e)
        polite_sleep(1.0, 2.0)
    return added


def search(
    client: httpx.Client,
    keywords: list[str],
    location: str,
    days: int,
    on_issue: ProgressFn = noop,
) -> list[Job]:
    jobs: dict[str, Job] = {}

    # 1. Kanal: Ana SSR Web Arama Sayfası (tek istekte ~60 ilan döner, 429'a takılmaz)
    # 2. Kanal: Eğer SSR 429/hata verirse otomatik Guest API'ye düşer
    for kw in keywords:
        params = {
            "keywords": kw,
            "location": location,
            "f_E": "1",                       # Deneyim seviyesi: Staj
            "f_TPR": f"r{days * 86400}",      # Son N gün
            "position": "1",
            "pageNum": "0",
        }
        fetched = False
        for endpoint_name, url in [("SSR", SSR_SEARCH_URL), ("GuestAPI", API_SEARCH_URL)]:
            try:
                r = client.get(url, params=params, headers=random_headers())
                if r.status_code == 429:
                    log.info("LinkedIn %s 429 döndü, alternatif kanala geçiliyor...", endpoint_name)
                    continue
                r.raise_for_status()
                count = _parse_cards(r.text, jobs)
                if count > 0:
                    fetched = True
                    break
            except httpx.HTTPError as e:
                log.debug("LinkedIn %s hatası (%s): %s", endpoint_name, kw, e)
                continue

        if not fetched:
            log.info("LinkedIn doğrudan kanallar '%s' için yanıt vermedi, arama motoru köprüsü kullanılacak.", kw)
        polite_sleep(2.5, 4.5)

    # 3. Kanal: Arama Motoru Köprüsü (DuckDuckGo) — her zaman ek/yedek kaynak olarak çalıştırılır
    ddg_added = _search_via_ddg(client, jobs)
    if ddg_added:
        log.info("DuckDuckGo köprüsünden %d ek LinkedIn ilanı bulundu", ddg_added)

    if not jobs:
        on_issue("⚠️ LinkedIn tüm kanallarda hız sınırına takıldı; sonraki saat tekrar denenecek.")

    log.info("LinkedIn (çok kanallı): toplam %d benzersiz ilan bulundu", len(jobs))
    return list(jobs.values())


def fetch_detail(client: httpx.Client, job: Job) -> Job:
    """Önce hızlı Guest Detail API'sini, 429 alırsa doğrudan web sayfasını dener.
    İkisi de 429/zaman aşımı verirse arama motorundan gelen özet veya başlıkla devam eder."""
    for url_tpl in (API_DETAIL_URL, WEB_DETAIL_URL):
        try:
            r = client.get(url_tpl.format(id=job.native_id), headers=random_headers(), timeout=10.0)
            if r.status_code == 429:
                polite_sleep(1.5, 3.0)
                continue
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            desc = _text(soup.select_one(".show-more-less-html__markup, .description__text"))
            if desc:
                job.description = desc
                for item in soup.select(".description__job-criteria-item"):
                    key = _text(item.select_one(".description__job-criteria-subheader"))
                    val = _text(item.select_one(".description__job-criteria-text"))
                    if key:
                        job.extra[key] = val
                if not job.title or job.company == "LinkedIn İlanı":
                    t = _text(soup.select_one(".top-card-layout__title, h1, h2"))
                    c = _text(soup.select_one(".topcard__org-name-link, .top-card-layout__second-subline a"))
                    if t:
                        job.title = t
                    if c:
                        job.company = c
                if not job.location:
                    job.location = _text(soup.select_one(".topcard__flavor--bullet"))
                return job
        except httpx.HTTPError as e:
            log.debug("LinkedIn detay alternatif kanal hatası (%s): %s", job.native_id, e)
            continue

    # Her iki detay kanalı da 429 verdiyse ama elimizde başlık/şirket varsa ilanı kaybetmemek için başlığı açıklama yap
    if not job.description and job.title:
        job.description = f"{job.title} — {job.company} ({job.location})"
    return job
