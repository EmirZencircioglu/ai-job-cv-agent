"""İlan ↔ CV uyum puanlaması (Gemini — tekli ve toplu puanlama destekli)."""
from __future__ import annotations

import json
import logging

from pydantic import BaseModel, Field

from app.config import settings
from app.cv_parser import CVProfile
from app.llm import generate_structured
from app.progress import ProgressFn, noop

log = logging.getLogger(__name__)


class MatchResult(BaseModel):
    score: int = Field(description="0-100 arası genel uyum skoru")
    is_internship: bool = Field(description="İlan gerçekten bir staj / stajyer ilanı mı?")
    duration_months: int | None = Field(None, description="İlanda belirtilen staj süresi (ay), yoksa null")
    project_based: bool = Field(False, description="Proje bazlı staj mı?")
    work_model: str = Field("", description="Ofis / Hibrit / Uzaktan / belirtilmemiş")
    matched_skills: list[str] = Field(default_factory=list, description="En fazla 5, kısa")
    missing_skills: list[str] = Field(default_factory=list, description="En fazla 3, kısa")
    reason: str = Field(description="Adaya hitaben 1-2 cümlelik Türkçe gerekçe")


class BatchItemMatch(MatchResult):
    job_id: str = Field(description="İlanın verilen ID değeri (birebir aynı olmalı)")


class BatchMatchResult(BaseModel):
    results: list[BatchItemMatch]


SYSTEM = """Sen bir işe alım uzmanısın. Adayın profilini ve iş ilan(lar)ını karşılaştırıp uyum skoru ver.

Puanlama kuralları:
- Rol uyumu (veri analizi, finans, yatırım, portföy) ve beceri örtüşmesi skorun ana belirleyicisidir.
- İlan staj DEĞİLSE (deneyimli pozisyon) skor en fazla 30 olsun ve is_internship=false olsun.
- İlan alakasız bir alandaysa (ör. hukuk, yazılım geliştirme, İK, satış, tasarım, mimarlık, kimya) skor en fazla 40 olsun.
- Aday tercihi: {prefs}. Bunlara uyan ilanlara +5-10 puan ekle.
- Zorunlu (okul) stajı arayan ve adayın durumuna uymayan ilanları düşür.
- Gerekçe adayın gerçek profiline dayansın; abartma, uydurma."""


def _profile_summary(p: CVProfile) -> str:
    return json.dumps(
        {
            "eğitim": [f"{e.school} - {e.degree} {e.field} ({e.start}-{e.end})" for e in p.education],
            "deneyim": [f"{x.title} @ {x.company}" for x in p.experience],
            "projeler": [f"{x.name}: {x.description[:150]}" for x in p.projects],
            "teknik": p.technical_skills,
            "finans": p.finance_skills,
            "diller": p.languages,
            "sertifikalar": p.certificates,
        },
        ensure_ascii=False,
    )


def _prefs_text() -> str:
    pref = settings()["search"]["internship_preferences"]
    return (
        f"{'/'.join(map(str, pref['durations_months']))} aylık uzun dönem stajlar"
        f"{', proje bazlı stajlar' if pref['project_based'] else ''}"
        f"{', yarı zamanlı uygun' if pref['part_time_ok'] else ''}; konum İstanbul"
    )


def score_job(profile: CVProfile, job: dict, on_issue: ProgressFn = noop) -> MatchResult:
    extra = job.get("extra") or "{}"
    job_text = (
        f"BAŞLIK: {job['title']}\nŞİRKET: {job['company']}\nKONUM: {job['location']}\n"
        f"EK BİLGİ: {extra}\n\nAÇIKLAMA:\n{(job.get('description') or '')[:5000]}"
    )
    return generate_structured(
        contents=[f"ADAY PROFİLİ:\n{_profile_summary(profile)}\n\nİLAN:\n{job_text}"],
        schema=MatchResult,
        system=SYSTEM.format(prefs=_prefs_text()),
        on_issue=on_issue,
    )


def score_jobs_batch(profile: CVProfile, jobs: list[dict], on_issue: ProgressFn = noop) -> dict[str, MatchResult]:
    """Birden fazla ilanı TEK Gemini API isteğinde puanlar (kota tüketimini %85+ azaltır)."""
    if not jobs:
        return {}
    if len(jobs) == 1:
        j = jobs[0]
        return {j["id"]: score_job(profile, j, on_issue=on_issue)}

    blocks = []
    for j in jobs:
        extra = j.get("extra") or "{}"
        blocks.append(
            f"=== İLAN ID: {j['id']} ===\n"
            f"BAŞLIK: {j['title']}\nŞİRKET: {j['company']}\nKONUM: {j['location']}\n"
            f"EK BİLGİ: {extra}\nAÇIKLAMA:\n{(j.get('description') or '')[:2500]}"
        )
    prompt = (
        f"ADAY PROFİLİ:\n{_profile_summary(profile)}\n\n"
        f"Aşağıdaki {len(jobs)} ilanın HER BİRİ için `results` listesinde ilgili `job_id` ile puanlama üret:\n\n"
        + "\n\n".join(blocks)
    )
    res = generate_structured(
        contents=[prompt],
        schema=BatchMatchResult,
        system=SYSTEM.format(prefs=_prefs_text()),
        on_issue=on_issue,
    )
    return {item.job_id: item for item in res.results}
