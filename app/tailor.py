"""İlana özel CV uyarlama (Gemini).

ÖNEMLİ: Asla uydurma bilgi eklemez. Mevcut deneyimleri ve projeleri ilan diline
(Türkçe veya İngilizce) ve ilandaki anahtar kelimelere göre yeniden ifade eder ve sıralar.
"""
from __future__ import annotations

import json
import logging

from pydantic import BaseModel, Field

from app.cv_parser import CVProfile, Education, Experience, Project
from app.llm import generate_structured
from app.progress import ProgressFn, noop

log = logging.getLogger(__name__)


class TailoredCV(BaseModel):
    language: str = Field(description="'tr' veya 'en' — ilanın diline göre")
    target_headline: str = Field(description="İlana uygun kısa başlık (örn. 'Finance & Data Analytics Intern Candidate')")
    summary: str = Field(description="İlana göre uyarlanmış 3-4 cümlelik profesyonel özet")
    education: list[Education] = Field(default_factory=list)
    experience: list[Experience] = Field(
        default_factory=list,
        description="En alakalı deneyimden başlayarak sıralanmış ve maddeleri ilana göre güçlendirilmiş deneyim listesi",
    )
    projects: list[Project] = Field(
        default_factory=list,
        description="En alakalı projeden başlayarak sıralanmış proje listesi",
    )
    technical_skills: list[str] = Field(default_factory=list, description="İlanla en alakalı olanlar başta")
    finance_skills: list[str] = Field(default_factory=list, description="İlanla en alakalı olanlar başta")
    soft_skills: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    certificates: list[str] = Field(default_factory=list)
    cover_note: str = Field(
        description="Başvuruda veya İK'ya mesaj atarken kullanılabilecek 3-4 cümlelik samimi, profesyonel ön yazı"
    )
    tailoring_notes: list[str] = Field(
        default_factory=list,
        description="Kullanıcıya bilgi: CV'de bu ilan için neleri öne çıkardık / değiştirdik (3-4 madde, Türkçe)",
    )


SYSTEM = """Sen kıdemli bir kariyer danışmanı ve ATS (Aday Takip Sistemi) uzmanısın.
Görevin, adayın mevcut CV profilini hedef iş ilanına göre uyarlamak.

KESİN KURALLAR:
1. ASLA uydurma deneyim, şirket, tarih, sertifika, araç veya beceri ekleme! Adayın bilmediği bir programı (örn. Bloomberg, Power BI) biliyormuş gibi gösterme.
2. İlan Türkçe ise çıktıyı (summary, experience bullets, projects, skills, cover_note) TÜRKÇE üret. İlan İngilizce ise İNGİLİZCE üret. (tailoring_notes her zaman Türkçe olsun).
3. Deneyim (experience) içinde unvan ve şirket adı karışmışsa düzelt (örneğin 'Stock Market and Investment Club' şirket/kurum, 'Event Organizer' unvan olmalı).
4. Deneyimleri ve projeleri ilanla en alakalı olandan başlayarak sırala.
5. Deneyim maddelerini (bullets) ve proje açıklamalarını ilandaki anahtar kelimelerle (ATS uyumu için) doğal biçimde örtüşecek şekilde güçlendir, ama gerçeğe sadık kal.
6. Becerileri (technical_skills, finance_skills) ilanda geçenleri en başa alarak sırala."""


def tailor_cv(profile: CVProfile, job: dict, on_issue: ProgressFn = noop) -> TailoredCV:
    job_text = (
        f"BAŞLIK: {job['title']}\n"
        f"ŞİRKET: {job['company']}\n"
        f"KONUM: {job['location']}\n"
        f"AÇIKLAMA:\n{(job.get('description') or '')[:6000]}"
    )
    prompt = (
        f"ADAYIN MEVCUT PROFİLİ (JSON):\n{json.dumps(profile.model_dump(), ensure_ascii=False, indent=2)}\n\n"
        f"HEDEF İLAN:\n{job_text}\n\n"
        "Bu profili ilana göre uyarla."
    )
    return generate_structured(
        contents=[prompt],
        schema=TailoredCV,
        system=SYSTEM,
        on_issue=on_issue,
    )
