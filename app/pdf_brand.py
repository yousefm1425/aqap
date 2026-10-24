"""الهوية الموحّدة لملفات PDF في المنصة (المحاضر والخطط والتقارير وتقرير المتطلب).

كل صفحة تحمل ترويسة: شعار المؤسسة العامة للتدريب التقني والمهني وتحته «الكلية التقنية التطبيقية بينبع»،
ونوع الوثيقة ومرجعها؛ وتذييلاً باسم الجهة ورقم الصفحة. الخطوط مضمّنة (Tajawal للعناوين، IBM Plex Sans Arabic للنص)
فيُطبع الملف بالشكل نفسه على أي جهاز ويُرفع كما هو إلى منصات الاعتماد الأخرى.
"""
from __future__ import annotations

import base64
from datetime import date, datetime
from functools import lru_cache
from html import escape
from pathlib import Path

ROOT = Path(__file__).parent / "report_templates"
FONTS = ROOT / "fonts"
COLLEGE = "الكلية التقنية التطبيقية بينبع"
ORG = "المؤسسة العامة للتدريب التقني والمهني"
SYSTEM = "نظام جودة التدريب — المستوى الثاني"

INK, TEAL, TEAL_D, LINE, SOFT = "#1f2d2c", "#25AFA5", "#126C66", "#cfdedb", "#eef6f4"


@lru_cache(maxsize=1)
def logo_uri() -> str:
    p = ROOT / "tvtc-logo.png"
    return "data:image/png;base64," + base64.b64encode(p.read_bytes()).decode() if p.is_file() else ""


def _face(family: str, file: str, weight: int) -> str:
    f = FONTS / file
    return f"@font-face {{ font-family: '{family}'; src: url('{f.as_uri()}'); font-weight: {weight}; }}" if f.is_file() else ""


FONT_CSS = "\n".join(filter(None, [            # خط عربي وخط لاتيني منفصلان (الأرقام واللاتيني من الثاني)
    _face("Taj", "tajawal-arabic-500.ttf", 500), _face("Taj", "tajawal-arabic-700.ttf", 700),
    _face("TajL", "tajawal-latin-500.ttf", 500), _face("TajL", "tajawal-latin-700.ttf", 700),
    _face("Plex", "ibm-plex-sans-arabic-arabic-400.ttf", 400), _face("Plex", "ibm-plex-sans-arabic-arabic-500.ttf", 500),
    _face("Plex", "ibm-plex-sans-arabic-arabic-700.ttf", 700),
    _face("PlexL", "ibm-plex-sans-arabic-latin-400.ttf", 400), _face("PlexL", "ibm-plex-sans-arabic-latin-500.ttf", 500),
    _face("PlexL", "ibm-plex-sans-arabic-latin-700.ttf", 700),
]))


def page_css(landscape: bool = False, base_pt: float = 10) -> str:
    size = "A4 landscape" if landscape else "A4"
    return FONT_CSS + f"""
@page {{ size: {size}; margin: 47mm 13mm 18mm 13mm;
  @top-center {{ content: element(brand); width: 100%; vertical-align: bottom; }}
  @bottom-right {{ content: "{ORG} · {COLLEGE}"; font: 7.5pt 'Plex', 'PlexL', 'Noto Sans Arabic'; color: #6b7a77; }}
  @bottom-center {{ content: "صفحة " counter(page) " من " counter(pages); font: 7.5pt 'Plex', 'PlexL', 'Noto Sans Arabic'; color: #6b7a77; }}
  @bottom-left {{ content: string(ref); font: 7.5pt 'Plex', 'PlexL', 'Noto Sans Arabic'; color: #6b7a77; }} }}
* {{ box-sizing: border-box; }}
body {{ font-family: 'Plex', 'PlexL', 'Noto Sans Arabic', 'Noto Naskh Arabic', sans-serif; font-size: {base_pt}pt; line-height: 1.6; color: {INK};
       direction: rtl; text-align: right; margin: 0; }}
.ref {{ string-set: ref content(); font-size: 0; height: 0; }}
/* الترويسة المتكررة */
.brand {{ position: running(brand); width: 100%; border-collapse: collapse; border-bottom: 2.2pt solid {TEAL_D}; }}
.brand td {{ border: 0; padding: 0 0 4pt; vertical-align: bottom; }}
.brand .b-logo {{ width: 34%; text-align: right; }}
.brand .b-logo img {{ height: 21mm; display: block; margin: 0 0 1pt auto; }}
.brand .b-logo .college {{ font: 700 9.5pt 'Taj', 'TajL', 'Plex', 'PlexL'; color: {TEAL_D}; }}
.brand .b-mid {{ text-align: center; }}
.brand .b-mid .kind {{ font: 700 12pt 'Taj', 'TajL', 'Plex', 'PlexL'; color: {TEAL_D}; }}
.brand .b-mid .sys {{ font-size: 8pt; color: #5b6b68; }}
.brand .b-ref {{ width: 30%; text-align: left; font-size: 7.8pt; color: #4e625d; line-height: 1.55; }}
.brand .b-ref b {{ color: {INK}; font-weight: 700; }}
.chip {{ display: inline-block; padding: 0 6pt; border-radius: 6pt; font-size: 7.5pt; font-weight: 700; }}
.chip.ok {{ background: #e1f3e8; color: #18794e; }} .chip.draft {{ background: #fdeedd; color: #a45a10; }}
/* العنوان وبطاقة البيانات */
h1 {{ margin-top: 2pt; font: 700 15pt 'Taj', 'TajL', 'Plex', 'PlexL'; color: {TEAL_D}; margin: 3pt 0 4pt; }}
.reqbox {{ background: {SOFT}; border-right: 3pt solid {TEAL}; padding: 5pt 8pt; margin: 0 0 7pt; font-size: {base_pt - 0.5}pt; }}
.reqbox b {{ color: {TEAL_D}; }}
table.meta {{ width: 100%; border-collapse: collapse; margin: 0 0 9pt; font-size: {base_pt - 1}pt; }}
table.meta td {{ border: 0.6pt solid {LINE}; padding: 3pt 6pt; }}
table.meta td.k {{ background: #f5f8f7; color: #4e625d; width: 12%; white-space: nowrap; }}
h2 {{ font: 700 {base_pt + 1.5}pt 'Taj', 'TajL', 'Plex', 'PlexL'; color: {TEAL_D}; margin: 11pt 0 4pt; padding-bottom: 2pt;
      border-bottom: 0.8pt solid {LINE}; page-break-after: avoid; }}
h3 {{ font: 700 {base_pt + 0.5}pt 'Taj', 'TajL', 'Plex', 'PlexL'; margin: 7pt 0 3pt; page-break-after: avoid; }}
table.grid {{ width: 100%; border-collapse: collapse; margin: 3pt 0 7pt; }}
table.grid th, table.grid td {{ border: 0.5pt solid #b9c9c5; padding: 2.6pt 4pt; vertical-align: top; }}
table.grid th {{ background: {TEAL_D}; color: #fff; font-weight: 700; font-size: {base_pt - 1.5}pt; }}
table.grid th.grp {{ background: #2f8c84; text-align: center; }}
table.grid tbody tr:nth-child(even) td {{ background: #f7faf9; }}
table.grid tr {{ page-break-inside: avoid; }}
td.n {{ text-align: center; white-space: nowrap; font-variant-numeric: tabular-nums; }}
td.c {{ background: #eef5f3 !important; font-weight: 700; }}
.muted {{ color: #6b7a77; }}
a {{ color: #1d5fa8; text-decoration: none; }}
.st-done {{ color: #18794e; font-weight: 700; }} .st-part {{ color: #9a6c12; font-weight: 700; }} .st-not {{ color: #b42318; font-weight: 700; }}
.sum {{ font-size: {base_pt - 0.5}pt; margin: 0 0 7pt; }}
.sum span {{ display: inline-block; margin-left: 14pt; }} .sum b {{ color: {TEAL_D}; }}
.text {{ border: 0.5pt solid #b9c9c5; padding: 4pt 7pt; min-height: 16pt; white-space: pre-wrap; }}
/* الاعتماد والتواقيع */
table.sign {{ width: 100%; border-collapse: collapse; margin-top: 12pt; page-break-inside: avoid; }}
table.sign td {{ border: 0.8pt solid {TEAL_D}; padding: 5pt 7pt; width: 33.3%; vertical-align: top; font-size: {base_pt - 0.5}pt; height: 22mm; }}
table.sign td b {{ display: block; color: {TEAL_D}; margin-bottom: 2pt; }}
.eseal {{ margin-top: 5pt; font-size: {base_pt - 1.5}pt; color: {TEAL_D}; }}
.draftmark {{ position: fixed; top: 42%; left: 12%; font: 700 58pt 'Taj', 'TajL', 'Plex', 'PlexL'; color: rgba(194,70,61,.10); transform: rotate(-20deg); }}
"""


def _d(v) -> str:
    if v is None:
        return "—"
    if isinstance(v, (date, datetime)):
        return f"{v.year}/{v.month:02d}/{v.day:02d}م"
    return escape(str(v))


def header(kind: str, ref: str, approved: bool, issued: datetime | None = None) -> str:
    """ترويسة الصفحات + حقل المرجع للتذييل + علامة المسودة."""
    issued = issued or datetime.now()
    status = '<span class="chip ok">معتمد</span>' if approved else '<span class="chip draft">مسودة — غير معتمد</span>'
    return f"""<div class="ref">{escape(ref)}</div>{'' if approved else '<div class="draftmark">غير معتمد</div>'}
<table class="brand"><tr>
 <td class="b-logo"><img src="{logo_uri()}" alt="{ORG}"><div class="college">{COLLEGE}</div></td>
 <td class="b-mid"><div class="kind">{escape(kind)}</div><div class="sys">{SYSTEM}</div></td>
 <td class="b-ref">المرجع: <b>{escape(ref)}</b><br>تاريخ الإصدار: {_d(issued)}<br>{status}</td>
</tr></table>"""


def meta_table(pairs: list[tuple[str, object]], per_row: int = 3) -> str:
    """بطاقة بيانات الوثيقة: أزواج (البيان، القيمة) في صفوف."""
    pairs = [(k, v) for k, v in pairs if v not in (None, "")]
    rows = []
    for i in range(0, len(pairs), per_row):
        chunk = pairs[i:i + per_row]
        cells = "".join(f"<td class='k'>{escape(k)}</td><td>{_d(v)}</td>" for k, v in chunk)
        if len(chunk) < per_row:
            cells += f"<td colspan='{2 * (per_row - len(chunk))}'></td>"
        rows.append(f"<tr>{cells}</tr>")
    return f"<table class='meta'>{''.join(rows)}</table>"


def code(c: str) -> str:
    """رمز مثل 1-3-2 يُعرض من اليسار لليمين داخل النص العربي (لا ينقلب إلى 2-3-1)."""
    return f"<bdo dir='ltr'>{escape(str(c))}</bdo>"


def req_box(code_: str, text: str | None, standard: str | None = None, sub: str | None = None) -> str:
    where = " · ".join(x for x in (standard, sub) if x)
    return (f"<div class='reqbox'><b>المتطلب {code(code_)}</b>{(' — ' + escape(where)) if where else ''}"
            f"<br>{escape(text or '')}</div>")


def evidence_rows(items: list[dict], req: str) -> str:
    """جدول الشواهد: الروابط قابلة للنقر حتى يفتحها المقيّم من الملف المرفوع على أي منصة."""
    out = ["<table class='grid'><thead><tr><th style='width:5%'>م</th><th style='width:11%'>رمز الشاهد</th><th>بيان الشاهد</th>"
           "<th style='width:9%'>النوع</th><th style='width:24%'>الوصول</th></tr></thead><tbody>"]
    for i, a in enumerate(items, 1):
        url = a.get("url")
        access = (f"<a href='{escape(url)}'>فتح الشاهد ↗</a>" if url
                  else f"<span class='muted'>بنك الشواهد: AQAP-E-{a.get('evidence_id') or a.get('id')}</span>")
        note = f"<br><span class='muted'>{escape(a['note'])}</span>" if a.get("note") else ""
        out.append(f"<tr><td class='n'>{i}</td><td class='n'>{code(req)}</td><td>{escape(a.get('title_ar') or '')}{note}</td>"
                   f"<td>{'رابط' if a.get('kind') == 'link' else 'ملف'}</td><td>{access}</td></tr>")
    out.append("</tbody></table>")
    return "".join(out)


def signatures(boxes: list[tuple[str, str]], eseal: str | None = None) -> str:
    """صف التواقيع: (الصفة، الاسم أو سطر فارغ)."""
    cells = "".join(f"<td><b>{escape(t)}</b>{escape(n) if n else 'الاسم: ……………………'}<br><br>التوقيع: ……………………</td>"
                    for t, n in boxes)
    seal = f"<div class='eseal'>{escape(eseal)}</div>" if eseal else ""
    return f"<table class='sign'><tr>{cells}</tr></table>{seal}"


def to_pdf(html: str) -> bytes:
    from weasyprint import HTML

    return HTML(string=html, base_url=str(ROOT)).write_pdf()
