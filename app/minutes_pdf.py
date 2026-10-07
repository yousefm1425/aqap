"""توليد PDF عربي لمحضر الاجتماع (WeasyPrint: تشكيل عربي سليم واتجاه RTL عبر Pango/HarfBuzz)."""
from __future__ import annotations

from datetime import date, datetime
from html import escape

DAYS = ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]
FU_LABEL = {"done": "مُنفذ", "partial": "مُنفذ جزئي", "not_done": "لم يُنفذ"}
ORDINAL = ["الأول", "الثاني", "الثالث", "الرابع", "الخامس", "السادس", "السابع", "الثامن", "التاسع", "العاشر"]


def hijri(d: date | datetime | None) -> str:
    if d is None:
        return "—"
    from hijridate import Gregorian

    h = Gregorian(d.year, d.month, d.day).to_hijri()
    return f"{h.year}/{h.month:02d}/{h.day:02d}هـ"


def gregorian(d: date | datetime | None) -> str:
    return "—" if d is None else f"{d.year}/{d.month:02d}/{d.day:02d}م"


def _e(v) -> str:
    return escape(str(v)) if v not in (None, "") else "—"


CSS = """
@page { size: A4; margin: 16mm 14mm 18mm 14mm;
        @bottom-center { content: "صفحة " counter(page) " من " counter(pages); font: 9pt 'Noto Sans Arabic'; color: #6b7a77; }
        @bottom-left { content: string(ref); font: 8pt 'Noto Sans Arabic'; color: #6b7a77; } }
* { box-sizing: border-box; }
body { font-family: 'Noto Naskh Arabic', 'Noto Sans Arabic', serif; font-size: 11pt; line-height: 1.65; color: #17302b;
       direction: rtl; text-align: right; margin: 0; }
.ref { string-set: ref content(); font-size: 0; height: 0; }
header.doc { display: flex; justify-content: space-between; align-items: flex-start; border-bottom: 2.5pt solid #0e5a47;
             padding-bottom: 6pt; margin-bottom: 10pt; }
header.doc .org { font-family: 'Noto Sans Arabic'; font-size: 10pt; line-height: 1.5; }
header.doc .org b { font-size: 11.5pt; }
header.doc .stamp { font-family: 'Noto Sans Arabic'; font-size: 9pt; text-align: left; color: #4e625d; }
h1 { font-family: 'Noto Kufi Arabic', 'Noto Sans Arabic'; font-size: 16pt; margin: 4pt 0 2pt; color: #0e5a47; }
.req { font-family: 'Noto Sans Arabic'; font-size: 9.5pt; color: #4e625d; margin-bottom: 8pt; }
table { width: 100%; border-collapse: collapse; margin: 4pt 0 10pt; page-break-inside: auto; }
th, td { border: 0.6pt solid #b9c6c2; padding: 4pt 6pt; vertical-align: top; }
th { background: #e3efeb; font-family: 'Noto Sans Arabic'; font-weight: 600; font-size: 9.5pt; }
tr { page-break-inside: avoid; }
.info td { width: 16.6%; }
.info .k { background: #f4f6f5; font-family: 'Noto Sans Arabic'; font-size: 9.5pt; color: #4e625d; }
h2 { font-family: 'Noto Sans Arabic'; font-size: 12pt; margin: 12pt 0 4pt; color: #0e5a47; page-break-after: avoid; }
h3 { font-family: 'Noto Sans Arabic'; font-size: 11pt; margin: 8pt 0 2pt; page-break-after: avoid; }
ol.agenda { margin: 0 18pt 8pt 0; padding: 0; }
.num { width: 26pt; text-align: center; font-family: 'Noto Sans Arabic'; }
.muted { color: #6b7a77; }
.fu-done { color: #2f7a4f; font-weight: 600; } .fu-partial { color: #9a6c12; font-weight: 600; } .fu-not_done { color: #a63a32; font-weight: 600; }
.approval { margin-top: 12pt; border: 1.2pt solid #0e5a47; padding: 8pt 10pt; page-break-inside: avoid; }
.approval .row { display: flex; gap: 18pt; flex-wrap: wrap; font-size: 10.5pt; }
.approval .seal { margin-top: 6pt; font-family: 'Noto Sans Arabic'; font-size: 9pt; color: #0e5a47; }
.draft { position: fixed; top: 40%; left: 10%; font: 700 64pt 'Noto Kufi Arabic'; color: rgba(194,70,61,.12);
         transform: rotate(-24deg); }
.summary { font-family: 'Noto Sans Arabic'; font-size: 10pt; margin: 2pt 0 6pt; }
"""


def render_html(doc: dict) -> str:
    m = doc
    md = m.get("meeting_date")
    day = DAYS[md.weekday()] if md else "—"
    status_note = "" if m["status"] == "approved" else '<div class="draft">غير معتمد</div>'
    ref = f"AQAP-M-{m['id']}" + (f" · اعتُمد {gregorian(m['approved_at'])}" if m.get("approved_at") else "")

    parts = [f"""<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><style>{CSS}</style></head><body>
{status_note}<div class="ref">{escape(ref)}</div>
<header class="doc">
  <div class="org"><b>{_e(m['institution_name'])}</b><br>القسم التدريبي: {_e(m['department_name'])}<br>
  العام التدريبي {_e(m['academic_year'])}هـ — الفصل التدريبي {_e(m['semester'])}</div>
  <div class="stamp">نظام جودة التدريب — المستوى الثاني<br>المرجع: AQAP-M-{m['id']}</div>
</header>
<h1>محضر {escape(m['title_ar'])}</h1>
<div class="req">المتطلب {escape(m['requirement_code'])}: {_e(m.get('requirement_text'))}</div>
<table class="info">
  <tr><td class="k">رقم الاجتماع</td><td>{m['meeting_no']}</td><td class="k">اليوم</td><td>{day}</td>
      <td class="k">التاريخ</td><td>{hijri(md)}<br><span class="muted">{gregorian(md)}</span></td></tr>
  <tr><td class="k">الوقت</td><td>{_e(m.get('start_time'))}</td><td class="k">المكان</td><td colspan="3">{_e(m.get('location_ar'))}</td></tr>
</table>
<h2>محاور الاجتماع</h2><ol class="agenda">"""]
    parts += [f"<li>{escape(a['title_ar'])}</li>" for a in m["agenda"]]
    parts.append("</ol><h2>التوصيات</h2>")

    has_fu = any(r.get("fu_status") for a in m["agenda"] for r in a["recommendations"])
    for i, a in enumerate(m["agenda"]):
        label = ORDINAL[i] if i < len(ORDINAL) else str(i + 1)
        parts.append(f"<h3>المحور {label}: {escape(a['title_ar'])}</h3><table><thead><tr>"
                     "<th class='num'>رقم</th><th>التوصية</th><th style='width:22%'>مسؤول التنفيذ</th>"
                     "<th style='width:16%'>فترة التنفيذ</th></tr></thead><tbody>")
        for j, r in enumerate(a["recommendations"], 1):
            parts.append(f"<tr><td class='num'>{j}.{i + 1}</td><td>{escape(r['text_ar'])}</td>"
                         f"<td>{_e(r.get('responsible_ar'))}</td><td>{_e(r.get('period_ar'))}</td></tr>")
        parts.append("</tbody></table>")

    if has_fu:
        s = m["summary"]
        parts.append(f"""<h2>متابعة تنفيذ التوصيات</h2>
<div class="summary">مسؤول المتابعة: {_e(m.get('follow_up_owner'))} — نسبة التوصيات المنفذة: <b>{_e(s.get('completion_pct'))}%</b>
 (مُنفذ {s['rec_done']}، مُنفذ جزئي {s['rec_partial']}، لم يُنفذ {s['rec_not_done']}، لم تُتابع {s['rec_pending']})</div>
<table><thead><tr><th class='num'>رقم</th><th style='width:30%'>التوصية</th><th style='width:13%'>حالة التنفيذ</th>
<th>المعوقات والتحديات</th><th>الحلول المقترحة</th></tr></thead><tbody>""")
        for i, a in enumerate(m["agenda"]):
            for j, r in enumerate(a["recommendations"], 1):
                st = r.get("fu_status")
                parts.append(f"<tr><td class='num'>{j}.{i + 1}</td><td>{escape(r['text_ar'])}</td>"
                             f"<td class='fu-{st or ''}'>{FU_LABEL.get(st, '—')}</td>"
                             f"<td>{_e(r.get('fu_obstacles'))}</td><td>{_e(r.get('fu_solutions'))}</td></tr>")
        parts.append("</tbody></table>")

    parts.append("<h2>حضر الاجتماع</h2><table><thead><tr><th class='num'>م</th><th>الاسم</th><th style='width:26%'>المهمة</th>"
                 "<th style='width:30%'>التوقيع</th></tr></thead><tbody>")
    for k, at in enumerate(m["attendees"], 1):
        sig = (f"<span class='muted'>أكّد حضوره إلكترونياً {hijri(at['confirmed_at'])}</span>"
               if at.get("confirmed_at") else "")
        parts.append(f"<tr><td class='num'>{k}</td><td>{escape(at['name_ar'])}</td><td>{_e(at.get('role_ar'))}</td>"
                     f"<td style='height:24pt'>{sig}</td></tr>")
    parts.append("</tbody></table>")

    if m["status"] == "approved":
        parts.append(f"""<div class="approval"><b>اعتماد</b>
<div class="row"><span>القسم التدريبي: {_e(m['department_name'])}</span><span>المعتمِد: {_e(m.get('approved_by_name'))}</span>
<span>التاريخ: {hijri(m['approved_at'])} ({gregorian(m['approved_at'])})</span></div>
<div class="seal">اعتُمد إلكترونياً عبر منصة الجودة والاعتماد (AQAP) — المرجع AQAP-M-{m['id']}؛ النسخة الإلكترونية هي المرجع.</div></div>""")
    else:
        parts.append(f"<div class='approval'><b>اعتماد</b><div class='row'><span>القسم التدريبي: {_e(m['department_name'])}</span>"
                     "<span>اسم رئيس القسم: ……………………</span><span>التاريخ: ……………</span><span>التوقيع: ……………</span></div></div>")
    parts.append("</body></html>")
    return "".join(parts)


def render_pdf(doc: dict) -> bytes:
    from weasyprint import HTML

    return HTML(string=render_html(doc)).write_pdf()
