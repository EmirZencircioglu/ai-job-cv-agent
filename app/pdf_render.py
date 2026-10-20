"""Uyarlanmış CV'yi tek/iki sayfalık temiz, ATS uyumlu PDF'e dönüştürür (fpdf2)."""
from __future__ import annotations

import re
from pathlib import Path

from fpdf import FPDF

from app.config import path
from app.cv_parser import CVProfile
from app.tailor import TailoredCV

FONT_CANDIDATES = [
    # Windows
    (r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\arialbd.ttf", r"C:\Windows\Fonts\ariali.ttf"),
    (r"C:\Windows\Fonts\calibri.ttf", r"C:\Windows\Fonts\calibrib.ttf", r"C:\Windows\Fonts\calibrii.ttf"),
    # Linux (Debian/Ubuntu - fonts-dejavu-core)
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
     "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
     "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf"),
]

LABELS = {
    "tr": {
        "summary": "PROFESYONEL ÖZET",
        "education": "EĞİTİM",
        "experience": "DENEYİM & KULÜP ROLLERİ",
        "projects": "PROJELER",
        "skills": "YETKİNLİKLER",
        "tech": "Teknik & Araçlar",
        "fin": "Finans & Analiz",
        "soft": "Yetkinlikler",
        "certs": "SERTİFİKA & PROGRAMLAR",
        "langs": "YABANCI DİL",
    },
    "en": {
        "summary": "PROFESSIONAL SUMMARY",
        "education": "EDUCATION",
        "experience": "EXPERIENCE & LEADERSHIP",
        "projects": "PROJECTS",
        "skills": "SKILLS",
        "tech": "Technical & Tools",
        "fin": "Finance & Analytics",
        "soft": "Soft Skills",
        "certs": "CERTIFICATES & PROGRAMS",
        "langs": "LANGUAGES",
    },
}


def _find_fonts() -> tuple[str, str, str]:
    for reg, bold, ita in FONT_CANDIDATES:
        if Path(reg).exists() and Path(bold).exists():
            return reg, bold, (ita if Path(ita).exists() else reg)
    raise RuntimeError("Unicode TTF font bulunamadı (Arial veya DejaVuSans gerekli).")


class _CVPDF(FPDF):
    def __init__(self) -> None:
        super().__init__(orientation="P", unit="mm", format="A4")
        self.set_margins(14, 12, 14)
        self.set_auto_page_break(auto=True, margin=12)
        reg, bold, ita = _find_fonts()
        self.add_font("CVFont", "", reg)
        self.add_font("CVFont", "B", bold)
        self.add_font("CVFont", "I", ita)

    def section_title(self, title: str) -> None:
        self.ln(2)
        self.set_font("CVFont", "B", 10.5)
        self.set_text_color(25, 55, 109)
        self.cell(0, 6, title.upper(), new_x="LMARGIN", new_y="NEXT")
        y = self.get_y()
        self.set_draw_color(25, 55, 109)
        self.set_line_width(0.35)
        self.line(self.l_margin, y, self.w - self.r_margin, y)
        self.ln(1.8)
        self.set_text_color(30, 30, 30)

    def bullet(self, text: str) -> None:
        self.set_font("CVFont", "", 9.2)
        self.set_x(self.l_margin + 2)
        self.multi_cell(0, 4.4, f"•  {text}", new_x="LMARGIN", new_y="NEXT")


def render_cv_pdf(profile: CVProfile, tailored: TailoredCV, job: dict) -> Path:
    lang = "en" if tailored.language.lower().startswith("en") else "tr"
    L = LABELS[lang]

    pdf = _CVPDF()
    pdf.add_page()

    # --- Başlık (İsim & İletişim)
    pdf.set_font("CVFont", "B", 18)
    pdf.set_text_color(20, 35, 60)
    pdf.cell(0, 8, profile.full_name, new_x="LMARGIN", new_y="NEXT", align="C")

    if tailored.target_headline:
        pdf.set_font("CVFont", "I", 10.5)
        pdf.set_text_color(70, 90, 120)
        pdf.cell(0, 5.5, tailored.target_headline, new_x="LMARGIN", new_y="NEXT", align="C")

    contact_parts = [x for x in [profile.location, profile.phone, profile.email, *profile.links] if x]
    pdf.set_font("CVFont", "", 8.8)
    pdf.set_text_color(80, 80, 80)
    pdf.cell(0, 5, "  |  ".join(contact_parts), new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(1)

    # --- Özet
    if tailored.summary:
        pdf.section_title(L["summary"])
        pdf.set_font("CVFont", "", 9.3)
        pdf.multi_cell(0, 4.5, tailored.summary, new_x="LMARGIN", new_y="NEXT")

    # --- Eğitim
    if tailored.education:
        pdf.section_title(L["education"])
        for ed in tailored.education:
            pdf.set_font("CVFont", "B", 9.6)
            left = " — ".join(x for x in [ed.school, ed.degree, ed.field] if x)
            dates = " - ".join(x for x in [ed.start, ed.end] if x)
            pdf.cell(135, 5, left)
            pdf.set_font("CVFont", "I", 9)
            pdf.cell(0, 5, dates, new_x="LMARGIN", new_y="NEXT", align="R")
            for d in ed.details:
                pdf.bullet(d)

    # --- Deneyim
    if tailored.experience:
        pdf.section_title(L["experience"])
        for ex in tailored.experience:
            pdf.set_font("CVFont", "B", 9.6)
            head = " — ".join(x for x in [ex.title, ex.company] if x)
            dates = " - ".join(x for x in [ex.start, ex.end] if x)
            pdf.cell(135, 5, head)
            pdf.set_font("CVFont", "I", 8.8)
            pdf.cell(0, 5, dates, new_x="LMARGIN", new_y="NEXT", align="R")
            for b in ex.bullets:
                pdf.bullet(b)
            pdf.ln(1)

    # --- Projeler
    if tailored.projects:
        pdf.section_title(L["projects"])
        for pr in tailored.projects:
            pdf.set_font("CVFont", "B", 9.5)
            tech = f"  ({', '.join(pr.technologies)})" if pr.technologies else ""
            pdf.multi_cell(0, 4.8, f"{pr.name}{tech}", new_x="LMARGIN", new_y="NEXT")
            if pr.description:
                pdf.bullet(pr.description)
            pdf.ln(0.8)

    # --- Yetkinlikler
    pdf.section_title(L["skills"])
    for label, items in [
        (L["tech"], tailored.technical_skills),
        (L["fin"], tailored.finance_skills),
        (L["soft"], tailored.soft_skills),
    ]:
        if items:
            pdf.set_font("CVFont", "B", 9.2)
            pdf.write(4.6, f"{label}: ")
            pdf.set_font("CVFont", "", 9.2)
            pdf.multi_cell(0, 4.6, ", ".join(items), new_x="LMARGIN", new_y="NEXT")

    # --- Sertifikalar
    if tailored.certificates:
        pdf.section_title(L["certs"])
        for c in tailored.certificates:
            pdf.bullet(c)

    # --- Diller
    if tailored.languages:
        pdf.section_title(L["langs"])
        pdf.set_font("CVFont", "", 9.2)
        pdf.multi_cell(0, 4.6, "  •  ".join(tailored.languages), new_x="LMARGIN", new_y="NEXT")

    out_dir = path("output_dir")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{profile.full_name} CV.pdf"
    pdf.output(str(out_file))
    return out_file
