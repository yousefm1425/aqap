"""توليد PDF عربي لمحضر الاجتماع (WeasyPrint: تشكيل عربي سليم واتجاه RTL عبر Pango/HarfBuzz)."""
from __future__ import annotations

from datetime import date, datetime
from html import escape

from .pdf_brand import evidence_rows, header, meta_table, page_css, req_box, signatures, to_pdf

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


CSS = page_css(landscape=False, base_pt=10.5) + """
ol.agenda { margin: 0 18pt 8pt 0; padding: 0; }
td.num, th.num { width: 26pt; text-align: center; }
.fu-done { color: #18794e; font-weight: 700; } .fu-partial { color: #9a6c12; font-weight: 700; } .fu-not_done { color: #b42318; font-weight: 700; }
.summary { font-size: 10pt; margin: 2pt 0 6pt; }
"""


def render_html(doc: dict) -> str:
    m = doc
    md = m.get("meeting_date")
    day = DAYS[md.weekday()] if md else "—"

    approved = m["status"] == "approved"
    parts = [f"""<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><style>{CSS}</style></head><body>
{header("محضر اجتماع", f"AQAP-M-{m['id']}", approved)}
<h1>محضر {escape(m['title_ar'])}</h1>
{req_box(m['requirement_code'], m.get('requirement_text'))}
{meta_table([("القسم التدريبي", m['department_name']), ("العام التدريبي", f"{m['academic_year']}هـ"),
             ("الفصل التدريبي", m.get('semester')), ("رقم الاجتماع", m['meeting_no']), ("اليوم", day),
             ("التاريخ", f"{hijri(md)} — {gregorian(md)}" if md else None), ("الوقت", m.get('start_time')),
             ("المكان", m.get('location_ar'))])}
<h2>محاور الاجتماع</h2><ol class="agenda">"""]
    parts += [f"<li>{escape(a['title_ar'])}</li>" for a in m["agenda"]]
    parts.append("</ol><h2>التوصيات</h2>")

    has_fu = any(r.get("fu_status") for a in m["agenda"] for r in a["recommendations"])
    for i, a in enumerate(m["agenda"]):
        label = ORDINAL[i] if i < len(ORDINAL) else str(i + 1)
        parts.append(f"<h3>المحور {label}: {escape(a['title_ar'])}</h3><table class='grid'><thead><tr>"
                     "<th class='num'>رقم</th><th>التوصية</th><th style='width:22%'>مسؤول التنفيذ</th>"
                     "<th style='width:16%'>فترة التنفيذ</th></tr></thead><tbody>")
        for j, r in enumerate(a["recommendations"], 1):
            parts.append(f"<tr><td class='num'>{j}.{i + 1}</td><td>{escape(r['text_ar'])}</td>"
                         f"<td>{_e(r.get('responsible_ar'))}</td><td>{_e(r.get('period_ar'))}</td></tr>")
        if not a["recommendations"]:
            parts.append("<tr><td colspan='4' class='muted'>لم تُسجل توصيات لهذا المحور.</td></tr>")
        parts.append("</tbody></table>")

    if has_fu:
        s = m["summary"]
        parts.append(f"""<h2>متابعة تنفيذ التوصيات</h2>
<div class="summary">مسؤول المتابعة: {_e(m.get('follow_up_owner'))} — نسبة التوصيات المنفذة: <b>{_e(s.get('completion_pct'))}%</b>
 (مُنفذ {s['rec_done']}، مُنفذ جزئي {s['rec_partial']}، لم يُنفذ {s['rec_not_done']}، لم تُتابع {s['rec_pending']})</div>
<table class='grid'><thead><tr><th class='num'>رقم</th><th style='width:30%'>التوصية</th><th style='width:13%'>حالة التنفيذ</th>
<th>المعوقات والتحديات</th><th>الحلول المقترحة</th></tr></thead><tbody>""")
        for i, a in enumerate(m["agenda"]):
            for j, r in enumerate(a["recommendations"], 1):
                st = r.get("fu_status")
                parts.append(f"<tr><td class='num'>{j}.{i + 1}</td><td>{escape(r['text_ar'])}</td>"
                             f"<td class='fu-{st or ''}'>{FU_LABEL.get(st, '—')}</td>"
                             f"<td>{_e(r.get('fu_obstacles'))}</td><td>{_e(r.get('fu_solutions'))}</td></tr>")
        parts.append("</tbody></table>")

    atts = m.get("attachments") or []
    if atts:
        parts.append("<h2>الشواهد والتقارير الداعمة</h2>" + evidence_rows(atts, m["requirement_code"]))

    parts.append("<h2>حضر الاجتماع</h2><table class='grid'><thead><tr><th class='num'>م</th><th>الاسم</th><th style='width:26%'>المهمة</th>"
                 "<th style='width:30%'>التوقيع</th></tr></thead><tbody>")
    for k, at in enumerate(m["attendees"], 1):
        sig = (f"<span class='muted'>أكّد حضوره إلكترونياً {hijri(at['confirmed_at'])}</span>"
               if at.get("confirmed_at") else "")
        parts.append(f"<tr><td class='num'>{k}</td><td>{escape(at['name_ar'])}</td><td>{_e(at.get('role_ar'))}</td>"
                     f"<td style='height:24pt'>{sig}</td></tr>")
    parts.append("</tbody></table>")

    if approved:
        parts.append(signatures([("أعدّه (منسق الجودة بالقسم)", m.get("submitted_by_name") or ""),
                                 ("اعتمده", m.get("approved_by_name") or ""),
                                 ("تاريخ الاعتماد", f"{hijri(m['approved_at'])} — {gregorian(m['approved_at'])}")],
                                f"اعتُمد إلكترونياً عبر منصة الجودة والاعتماد — المرجع AQAP-M-{m['id']}؛ النسخة الإلكترونية هي المرجع."))
    else:
        parts.append(signatures([("أعدّه (منسق الجودة بالقسم)", ""), ("اعتمده (رئيس القسم)", ""), ("اطّلع عليه (وكالة الجودة)", "")]))
    parts.append("</body></html>")
    return "".join(parts)


def render_pdf(doc: dict) -> bytes:
    return to_pdf(render_html(doc))
