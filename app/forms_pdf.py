"""PDF عربي لأي نموذج (خطة أو تقرير) من قالبه وبياناته المحسوبة — أفقي A4 لأن جداول النماذج الرسمية عريضة."""
from __future__ import annotations

from html import escape

from .minutes_pdf import gregorian, hijri

CSS = """
@page { size: A4 landscape; margin: 12mm 10mm 14mm 10mm;
        @bottom-center { content: "صفحة " counter(page) " من " counter(pages); font: 8pt 'Noto Sans Arabic'; color: #6b7a77; }
        @bottom-left { content: string(ref); font: 7.5pt 'Noto Sans Arabic'; color: #6b7a77; } }
* { box-sizing: border-box; }
body { font-family: 'Noto Sans Arabic', 'Noto Naskh Arabic', sans-serif; font-size: 8.5pt; line-height: 1.45; color: #17302b;
       direction: rtl; text-align: right; margin: 0; }
.ref { string-set: ref content(); font-size: 0; height: 0; }
header.doc { display: flex; justify-content: space-between; align-items: flex-start; border-bottom: 2pt solid #0e5a47;
             padding-bottom: 5pt; margin-bottom: 8pt; }
header.doc .org { font-size: 9pt; line-height: 1.5; } header.doc .org b { font-size: 10.5pt; }
header.doc .stamp { font-size: 8pt; text-align: left; color: #4e625d; }
h1 { font-family: 'Noto Kufi Arabic', 'Noto Sans Arabic'; font-size: 14pt; margin: 2pt 0; color: #0e5a47; }
.req { font-size: 8.5pt; color: #4e625d; margin-bottom: 6pt; }
h2 { font-size: 10.5pt; margin: 10pt 0 3pt; color: #0e5a47; page-break-after: avoid; }
table { width: 100%; border-collapse: collapse; margin: 3pt 0 6pt; }
th, td { border: 0.5pt solid #b9c6c2; padding: 2.5pt 3.5pt; vertical-align: top; }
th { background: #e3efeb; font-weight: 600; font-size: 7.5pt; }
th.grp { background: #cfe2dc; text-align: center; }
tr { page-break-inside: avoid; }
td.n { text-align: center; white-space: nowrap; font-variant-numeric: tabular-nums; }
td.c { background: #f4f7f6; }
.muted { color: #6b7a77; }
.st-done { color: #2f7a4f; font-weight: 600; } .st-part { color: #9a6c12; font-weight: 600; } .st-not { color: #a63a32; font-weight: 600; }
.sum { display: flex; flex-wrap: wrap; gap: 4pt 14pt; font-size: 8.5pt; margin: 0 0 6pt; }
.sum b { color: #0e5a47; }
.text { border: 0.5pt solid #b9c6c2; padding: 4pt 6pt; min-height: 16pt; white-space: pre-wrap; }
.approval { margin-top: 10pt; border: 1pt solid #0e5a47; padding: 6pt 8pt; page-break-inside: avoid; font-size: 9pt; }
.approval .row { display: flex; gap: 16pt; flex-wrap: wrap; }
.draft { position: fixed; top: 38%; left: 18%; font: 700 60pt 'Noto Kufi Arabic'; color: rgba(194,70,61,.11); transform: rotate(-18deg); }
"""

STATUS_CLASS = {"مُنفذ": "st-done", "مُنفذ جزئي": "st-part", "لم يُنفذ": "st-not"}


def fmt(v, f: str | None) -> str:
    if v is None or v == "":
        return "—"
    if f == "pct" and isinstance(v, (int, float)):
        return f"{v * 100:.1f}%".replace(".0%", "%")
    if isinstance(v, float):
        return f"{v:.2f}".rstrip("0").rstrip(".")
    return str(v)


def _cell(c: dict, v) -> str:
    f = c.get("format") if c["type"] == "computed" else ("num" if c["type"] == "number" else None)
    cls = "n" if c["type"] in ("number",) or f in ("pct", "num") else ""
    if c["type"] == "computed":
        cls += " c"
    st = STATUS_CLASS.get(v, "") if c["type"] == "select" else ""
    return f"<td class='{cls.strip()} {st}'>{escape(fmt(v, f))}</td>"


def _group_row(cols: list[dict]) -> str:
    if not any(c.get("group") for c in cols):
        return ""
    cells, prev, span = [], None, 0
    for c in cols + [{"group": object()}]:
        g = c.get("group")
        if span and g != prev:
            cells.append(f"<th class='grp' colspan='{span}'>{escape(prev) if isinstance(prev, str) else ''}</th>")
            span = 0
        prev = g
        span += 1
    return "<tr><th class='grp'></th>" + "".join(cells) + "</tr>"


def render_html(doc: dict) -> str:
    schema, calc = doc["schema"], doc["computed"]
    plan, follow = doc["plan_data"], doc["follow_data"]
    ref = f"AQAP-F-{doc['id']}" + (f" · اعتُمد {gregorian(doc['approved_at'])}" if doc.get("approved_at") else "")
    out = [f"""<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><style>{CSS}</style></head><body>
{'' if doc['status'] == 'approved' else '<div class="draft">غير معتمد</div>'}<div class="ref">{escape(ref)}</div>
<header class="doc"><div class="org"><b>{escape(doc['institution_name'])}</b><br>القسم التدريبي: {escape(doc['department_name'])}<br>
العام التدريبي {escape(str(doc['academic_year']))}هـ</div>
<div class="stamp">نظام جودة التدريب — المستوى الثاني<br>المرجع: AQAP-F-{doc['id']}</div></header>
<h1>{escape(doc['title_ar'])}</h1>
<div class="req">المتطلب {escape(doc['requirement_code'])}: {escape(doc.get('requirement_text') or '')}</div>"""]

    for s in schema["sections"]:
        k, title = s["key"], s.get("title", s["key"])
        if s["type"] == "table":
            rows = calc["tables"].get(k, [])
            if k == "improvements" and not rows:
                continue
            cols = s["columns"]
            out.append(f"<h2>{escape(title)}</h2><table><thead>{_group_row(cols)}<tr><th>م</th>"
                       + "".join(f"<th>{escape(c['label'])}</th>" for c in cols) + "</tr></thead><tbody>")
            for i, r in enumerate(rows, 1):
                out.append(f"<tr><td class='n'>{i}</td>" + "".join(_cell(c, r.get(c["key"])) for c in cols) + "</tr>")
            if not rows:
                out.append(f"<tr><td colspan='{len(cols) + 1}' class='muted'>لا توجد بيانات</td></tr>")
            out.append("</tbody></table>")
            sm = calc["summaries"].get(k)
            if sm:
                out.append("<div class='sum'>" + "".join(
                    f"<span>{escape(m['label'])}: <b>{escape(fmt(sm.get(m['key']), m.get('format')))}</b></span>"
                    for m in s["summary"]) + "</div>")
        elif s["type"] == "pivot":
            groups = calc["pivots"].get(k, [])
            cols = s["columns"]
            out.append(f"<h2>{escape(title)}</h2><table><thead>{_group_row(cols)}<tr><th>{escape(s.get('group_label', 'التخصص'))}</th>"
                       + "".join(f"<th>{escape(c['label'])}</th>" for c in cols) + "</tr></thead><tbody>")
            for g in groups:
                out.append(f"<tr><td>{escape(str(g['group']))} <span class='muted'>({g['count']})</span></td>"
                           + "".join(f"<td class='n c'>{escape(fmt(g['values'].get(c['key']), c.get('format')))}</td>" for c in cols)
                           + "</tr>")
            out.append("</tbody></table>")
        elif s["type"] == "fields":
            vals = {**(plan.get(k) or {}), **(follow.get(k) or {})}
            out.append(f"<h2>{escape(title)}</h2><table><tr>" + "".join(
                f"<th>{escape(c['label'])}</th><td>{escape(fmt(vals.get(c['key']), None))}</td>" for c in s["fields"]) + "</tr></table>")
        elif s["type"] == "text":
            v = (follow if s.get("phase") == "follow" else plan).get(k)
            out.append(f"<h2>{escape(title)}</h2><div class='text'>{escape(v or '')}</div>")

    atts = doc.get("attachments") or []
    if atts:
        out.append("<h2>الشواهد والتقارير الداعمة</h2><table><thead><tr><th>م</th><th>رمز الشاهد</th><th>بيان الشاهد</th>"
                   "<th>النوع</th><th>المرجع في بنك الشواهد</th></tr></thead><tbody>")
        for i, a in enumerate(atts, 1):
            out.append(f"<tr><td class='n'>{i}</td><td>{escape(doc['requirement_code'])}</td><td>{escape(a['title_ar'])}</td>"
                       f"<td>{'رابط' if a.get('kind') == 'link' else 'ملف'}</td><td class='muted'>AQAP-E-{a['evidence_id']}</td></tr>")
        out.append("</tbody></table>")

    if doc["status"] == "approved":
        out.append(f"""<div class="approval"><b>اعتماد</b><div class="row"><span>القسم التدريبي: {escape(doc['department_name'])}</span>
<span>رئيس القسم: {escape(doc.get('approved_by_name') or '')}</span><span>التاريخ: {hijri(doc['approved_at'])} ({gregorian(doc['approved_at'])})</span></div>
<div class="muted">اعتُمد إلكترونياً عبر منصة الجودة والاعتماد (AQAP) — المرجع AQAP-F-{doc['id']}؛ النسخة الإلكترونية هي المرجع.</div></div>""")
    else:
        out.append(f"<div class='approval'><b>اعتماد</b><div class='row'><span>القسم التدريبي: {escape(doc['department_name'])}</span>"
                   "<span>رئيس القسم: ……………………</span><span>التاريخ: ……………</span><span>التوقيع: ……………</span></div></div>")
    out.append("</body></html>")
    return "".join(out)


def render_pdf(doc: dict) -> bytes:
    from weasyprint import HTML

    return HTML(string=render_html(doc)).write_pdf()
