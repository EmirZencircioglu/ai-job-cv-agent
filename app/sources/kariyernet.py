"""Kariyer.net çok kanallı (Cloudflare 403 engeline takılmayan, son 3 gün & anlık yeni ilan odaklı) arama modülü.

Kullanılan kanallar:
1. Doğrudan SSR Staj Arama (`https://www.kariyer.net/is-ilanlari/stajyer?ct=34,82&kw=...`) — Kart üzerindeki `time` değerini kontrol ederek 3 günden eski ilanları kesin olarak eler.
2. Arama Motoru Köprüsü (`ddgs` indeksi `site:kariyer.net/is-ilani`) — Bulut IP'si 403 alırsa son günlerin indeksinden (`timelimit="w"`) taze ilanları bulur, eski tarihli olanları eler.
3. Detay 403 Yedeği — Detay sayfası 403 döndürürse arama motorundan gelen özet açıklama (snippet) ile devam eder.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime

import httpx
from bs4 import BeautifulSoup
from ddgs import DDGS

from app.models import Job, polite_sleep, random_headers
from app.progress import ProgressFn, noop

log = logging.getLogger(__name__)

BASE = "https://www.kariyer.net"


def _text(el) -> str:
    return el.get_text(" ", strip=True) if el else ""


def _browser_headers() -> dict[str, str]:
    h = random_headers()
    h.update(
        {
            "Referer": "https://www.google.com.tr/",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "cross-site",
            "Upgrade-Insecure-Requests": "1",
        }
    )
    return h


def _is_fresh_kariyer(time_str: str, max_days: int = 3) -> bool:
    """Kariyer.net kartındaki 'time' değerinin son `max_days` (3 gün) içinde olup olmadığını kontrol eder."""
    if not time_str:
        return True
    low = time_str.strip().lower()
    if any(k in low for k in ("bugün", "dün", "saat", "dakika", "sn", "yeni", "az önce")):
        return True
    if any(k in low for k in ("hafta", "ay", "yıl")):
        return False
    m = re.search(r"(\d+)\s*gün", low)
    if m:
        return int(m.group(1)) <= max_days
    return False


def _is_fresh_bridge_text(raw_title: str, body: str, max_days: int = 3) -> tuple[bool, str]:
    """Arama motoru köprüsünden gelen ilanın başlık/özetindeki tarihi kontrol eder."""
    combined = f"{raw_title} {body}"
    today = date.today()
    for dm in re.finditer(r"\b(\d{2})\.(\d{2})\.(\d{4})\b", combined):
        try:
            d = date(int(dm.group(3)), int(dm.group(2)), int(dm.group(1)))
            diff = (today - d).days
            if diff > max_days:
                return False, ""
            return True, f"{dm.group(0)} ({diff} gün önce)" if diff > 0 else f"Bugün ({dm.group(0)})"
        except ValueError:
            continue
    low = combined.lower()
    if any(w in low for w in ("week", "hafta", "month", "ay önce", "year", "yıl")):
        return False, ""
    m = re.search(r"(\d+)\s*(?:day|gün)", low)
    if m and int(m.group(1)) > max_days:
        return False, ""
    return True, f"Son {max_days} gün içinde"


def _parse_bridge_item(raw_title: str, body: str) -> tuple[str, str]:
    """Arama motoru sonucundan (başlık ve özet) şirket ve pozisyon adını ayrıştırır."""
    m = re.search(r"Kariyer\.net'teki\s+(.+?)\s+firmasına\s+ait\s+(.+?)\s+iş\s+ilanını", body, re.I)
    if m:
        return m.group(2).strip(), m.group(1).strip()

    clean = re.sub(r"\s*[-|]\s*Kariyer\.net.*$", "", raw_title, flags=re.I).strip()
    clean = re.sub(r"\s*[-|]\s*\d{2}\.\d{2}\.\d{4}.*$", "", clean).strip()
    clean = re.sub(r"\s+İş\s+İlanı.*$", "", clean, flags=re.I).strip()

    m2 = re.match(
        r"^(.+?)\s+((?:Uzun Dönem\s+|Üniversite\s+|Zorunlu\s+)?(?:[\wÇĞİÖŞÜçğıöşü]+\s+){0,2}Stajyer[i]?.*)$",
        clean,
        re.I,
    )
    if m2:
        return m2.group(2).strip(), m2.group(1).strip()
    return clean, "Kariyer.net İlanı"


def _search_via_bridge(jobs: dict[str, Job], max_days: int = 3) -> int:
    """Bulut IP'si 403 aldığında arama motoru köprüsü üzerinden son 3 günün Kariyer.net staj ilanlarını çeker."""
    queries = [
        "site:kariyer.net/is-ilani stajyer istanbul finans",
        "site:kariyer.net/is-ilani stajyer istanbul yatırım OR portföy",
        "site:kariyer.net/is-ilani stajyer istanbul veri analizi OR analist",
        "site:kariyer.net/is-ilani uzun dönem stajyer istanbul finans OR banka",
    ]
    added = 0
    for q in queries:
        try:
            results = DDGS().text(q, region="tr-tr", timelimit="w", max_results=10, backend="yahoo")
            for item in results:
                href = item.get("href", "")
                m = re.search(r"kariyer\.net(/is-ilani/[^?#\s\"'<>]+-(\d{6,10}))", href)
                if not m:
                    continue
                path_part, jid = m.group(1), m.group(2)
                if jid in jobs:
                    continue

                raw_title = item.get("title", "")
                body = item.get("body", "")
                is_fresh, label = _is_fresh_bridge_text(raw_title, body, max_days=max_days)
                if not is_fresh:
                    continue

                title, company = _parse_bridge_item(raw_title, body)
                if "staj" not in title.lower() and "intern" not in title.lower():
                    title = f"{title} (Stajyer)"

                jobs[jid] = Job(
                    source="Kariyer.net",
                    native_id=jid,
                    title=title,
                    company=company,
                    location="İstanbul",
                    url=BASE + path_part,
                    posted=label,
                    description=body or f"{title} — {company} (İstanbul)",
                    extra={"Pozisyon": "Stajyer", "Yayınlanma": label},
                )
                added += 1
        except Exception as e:  # noqa: BLE001
            log.debug("Kariyer.net köprü araması hatası (%s): %s", q, e)
        polite_sleep(1.0, 2.0)
    return added


def search(
    client: httpx.Client,
    queries: list[str],
    city_slug: str = "istanbul",
    on_issue: ProgressFn = noop,
    max_days: int = 3,
) -> list[Job]:
    jobs: dict[str, Job] = {}
    direct_blocked = False

    # 1. Kanal: Doğrudan Kariyer.net İstanbul Stajyer araması (ct=34,82 -> İstanbul Avrupa & Anadolu)
    for q in queries:
        kw = q.replace("-stajyer", "").replace("-", " ")
        try:
            r = client.get(
                f"{BASE}/is-ilanlari/stajyer",
                params={"ct": "34,82", "kw": kw},
                headers=_browser_headers(),
                timeout=12.0,
            )
            if r.status_code in (403, 429):
                log.info("Kariyer.net doğrudan kanal %d döndü, arama motoru köprüsüne geçiliyor...", r.status_code)
                direct_blocked = True
                break
            r.raise_for_status()
        except httpx.HTTPError as e:
            log.info("Kariyer.net doğrudan kanal erişilemedi (%s): %s; köprüye geçiliyor...", q, e)
            direct_blocked = True
            break

        soup = BeautifulSoup(r.text, "html.parser")
        for card in soup.find_all("div", attrs={"data-test": "ad-card"}):
            time_str = card.get("time", "")
            if not _is_fresh_kariyer(time_str, max_days=max_days):
                continue
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
                title=_text(card.find(attrs={"data-test": "ad-card-title"})),
                company=_text(card.find(attrs={"data-test": "subtitle"})),
                location=card.get("cityname", "İstanbul"),
                url=BASE + href,
                posted=time_str or "Yeni",
                extra={
                    "Pozisyon": card.get("positionname", "Stajyer"),
                    "Çalışma şekli": card.get("worktypetext", ""),
                    "Çalışma modeli": card.get("workmodeltext", ""),
                    "Sektör": card.get("sectorname", ""),
                    "Yayınlanma": time_str or "Yeni",
                },
            )
        polite_sleep()

    # 2. Kanal: Doğrudan kanal 403 aldıysa Arama Motoru Köprüsü
    if direct_blocked:
        bridge_count = _search_via_bridge(jobs, max_days=max_days)
        if bridge_count:
            log.info("Kariyer.net (arama motoru köprüsü): %d taze ilan bulundu", bridge_count)

    log.info("Kariyer.net (son %d gün): toplam %d taze ilan bulundu", max_days, len(jobs))
    return list(jobs.values())


def fetch_detail(client: httpx.Client, job: Job) -> Job:
    """Detay sayfasını dener; 403/hata alırsa arama motorundan gelen özet açıklama ile devam eder."""
    try:
        r = client.get(job.url, headers=_browser_headers(), timeout=10.0)
        if r.status_code not in (403, 429):
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            desc = _text(soup.find(attrs={"data-test": "qualifications-and-job-description"}))
            if desc:
                job.description = desc
            if not job.title:
                job.title = _text(soup.select_one("h1"))
            if not job.company or job.company == "Kariyer.net İlanı":
                c = _text(soup.select_one('[data-test="job-detail-company-card-large-detail"] a, .company-name'))
                if c:
                    job.company = c
            return job
    except httpx.HTTPError as e:
        log.debug("Kariyer.net detay 403/hata (%s), özet açıklamayla devam ediliyor: %s", job.native_id, e)

    if not job.description and job.title:
        job.description = f"{job.title} — {job.company} ({job.location})"
    return job


def job_from_url(url: str) -> Job | None:
    """E-postadaki bir kariyer.net ilan linkinden boş bir Job oluşturur."""
    m = re.search(r"(/is-ilani/[^?#\s\"']+-(\d+))", url)
    if not m:
        return None
    return Job(
        source="Kariyer.net",
        native_id=m.group(2),
        title="",
        company="",
        location="",
        url=BASE + m.group(1),
    )
