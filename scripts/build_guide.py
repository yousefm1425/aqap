"""يبني دليل الاستخدام PDF من docs/guide/guide.html (هوية المؤسسة العامة للتدريب التقني والمهني).
التشغيل: python scripts/build_guide.py  ← frontend/docs/aqap-user-guide.pdf
لتحديث لقطات الشاشة ضع الصور الجديدة في docs/guide/shots بنفس الأسماء ثم أعد البناء."""
from pathlib import Path

from weasyprint import HTML

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "docs" / "guide" / "guide.html"
OUT = ROOT / "frontend" / "docs" / "aqap-user-guide.pdf"

if __name__ == "__main__":
    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc = HTML(filename=str(SRC), base_url=str(SRC.parent)).render()
    doc.metadata.title = "دليل استخدام منصة الجودة والاعتماد"
    doc.metadata.authors = ["الكلية التقنية التطبيقية بينبع — وكالة الجودة"]
    doc.write_pdf(str(OUT))
    print(f"✓ {OUT.relative_to(ROOT)} — {len(doc.pages)} صفحة، {OUT.stat().st_size // 1024} ك.ب")
