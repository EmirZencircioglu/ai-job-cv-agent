"""CV PDF'ini Gemini ile analiz edip yapılandırılmış profile.json üretir.

Kullanım:
    python -m app.cv_parser
"""
from __future__ import annotations

import json

from google.genai import types
from pydantic import BaseModel, Field

from app.config import path, settings
from app.llm import generate_structured


class Education(BaseModel):
    school: str
    degree: str = ""
    field: str = ""
    start: str = ""
    end: str = ""
    gpa: str = ""
    details: list[str] = Field(default_factory=list)


class Experience(BaseModel):
    title: str
    company: str
    location: str = ""
    start: str = ""
    end: str = ""
    bullets: list[str] = Field(default_factory=list)


class Project(BaseModel):
    name: str
    description: str = ""
    technologies: list[str] = Field(default_factory=list)


class CVProfile(BaseModel):
    full_name: str
    email: str = ""
    phone: str = ""
    location: str = ""
    links: list[str] = Field(default_factory=list, description="LinkedIn, GitHub, portfolyo vb.")
    summary: str = Field("", description="CV'deki özet/hakkımda metni")
    education: list[Education] = Field(default_factory=list)
    experience: list[Experience] = Field(default_factory=list)
    projects: list[Project] = Field(default_factory=list)
    technical_skills: list[str] = Field(default_factory=list, description="Excel, Python, SQL, Power BI vb.")
    finance_skills: list[str] = Field(default_factory=list, description="Finansal analiz, değerleme, portföy vb.")
    soft_skills: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list, description="Örn: 'İngilizce - C1'")
    certificates: list[str] = Field(default_factory=list, description="SPL, CFA, Bloomberg vb.")
    # Agent'ın çıkarımları (CV'de birebir yazmayabilir)
    target_roles: list[str] = Field(default_factory=list, description="Bu profile uygun staj pozisyonları")
    strengths: list[str] = Field(default_factory=list, description="İlanlarda öne çıkarılabilecek güçlü yönler")
    gaps: list[str] = Field(default_factory=list, description="Hedef pozisyonlar için eksik görünen beceriler")


SYSTEM_PROMPT = """Sen deneyimli bir İK uzmanı ve kariyer danışmanısın.
Verilen CV'yi eksiksiz ve SADECE CV'de yazan bilgilere dayanarak yapılandırılmış hale getir.
Hiçbir bilgi uydurma; CV'de olmayan alanları boş bırak. Metinleri CV'nin orijinal dilinde koru.
target_roles, strengths ve gaps alanlarını kullanıcının hedefleri doğrultusunda yorumla:
{goals}"""


def parse_cv() -> CVProfile:
    cv_path = path("cv_pdf")
    if not cv_path.exists():
        raise FileNotFoundError(f"CV bulunamadı: {cv_path}. PDF'ini bu konuma koy.")

    s = settings()["search"]
    goals = (
        f"Hedef: {s['location']} lokasyonunda {s['experience_level']} seviyesinde; "
        f"pozisyonlar: {', '.join(s['keywords'])}. "
        f"Tercih edilen staj süreleri: {s['internship_preferences']['durations_months']} ay, "
        f"proje bazlı stajlar da uygun."
    )

    pdf_part = types.Part.from_bytes(data=cv_path.read_bytes(), mime_type="application/pdf")
    profile = generate_structured(
        contents=[pdf_part, "Bu CV'yi analiz et."],
        schema=CVProfile,
        system=SYSTEM_PROMPT.format(goals=goals),
    )

    out = path("profile_json")
    out.write_text(json.dumps(profile.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8")
    return profile


def load_profile() -> CVProfile:
    from app.config import env

    p = path("profile_json")
    prof = parse_cv() if not p.exists() else CVProfile.model_validate_json(p.read_text(encoding="utf-8"))
    if env("CANDIDATE_EMAIL"):
        prof.email = env("CANDIDATE_EMAIL")
    if env("CANDIDATE_PHONE"):
        prof.phone = env("CANDIDATE_PHONE")
    if env("CANDIDATE_LOCATION"):
        prof.location = env("CANDIDATE_LOCATION")
    return prof


if __name__ == "__main__":
    prof = parse_cv()
    print(f"✅ Profil oluşturuldu: {path('profile_json')}\n")
    print(f"👤 {prof.full_name}")
    print(f"🎯 Uygun roller : {', '.join(prof.target_roles)}")
    print(f"💪 Güçlü yönler : {', '.join(prof.strengths)}")
    print(f"⚠️  Eksikler     : {', '.join(prof.gaps)}")
