"""PDF عربي لأي نموذج (خطة أو تقرير) من قالبه وبياناته المحسوبة — أفقي A4 لأن جداول النماذج الرسمية عريضة."""
from __future__ import annotations

from html import escape

from .minutes_pdf import gregorian, hijri
from .pdf_brand import evidence_rows, header, meta_table, page_css, req_box, signatures, to_pdf

CSS = page_css(landscape=True, base_pt=8.6)


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
    kind = "خطة" if doc.get("kind") == "plan" else "تقرير"
    approved = doc["status"] == "approved"
    out = [f"""<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><style>{CSS}</style></head><body>
{header(kind, f"AQAP-F-{doc['id']}", approved)}
<h1>{escape(doc['title_ar'])}</h1>
{req_box(doc['requirement_code'], doc.get('requirement_text'))}
{meta_table([("القسم التدريبي", doc['department_name']), ("العام التدريبي", f"{doc['academic_year']}هـ"),
             ("نوع الوثيقة", kind), ("أعدّه", doc.get('submitted_by_name')),
             ("اعتمده", doc.get('approved_by_name')), ("تاريخ الاعتماد", gregorian(doc['approved_at']) if doc.get('approved_at') else None)])}"""]

    for s in schema["sections"]:
        k, title = s["key"], s.get("title", s["key"])
        if s["type"] == "table":
            rows = calc["tables"].get(k, [])
            if k == "improvements" and not rows:
                continue
            cols = s["columns"]
            out.append(f"<h2>{escape(title)}</h2><table class='grid'><thead>{_group_row(cols)}<tr><th>م</th>"
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
            out.append(f"<h2>{escape(title)}</h2><table class='grid'><thead>{_group_row(cols)}<tr><th>{escape(s.get('group_label', 'التخصص'))}</th>"
                       + "".join(f"<th>{escape(c['label'])}</th>" for c in cols) + "</tr></thead><tbody>")
            for g in groups:
                out.append(f"<tr><td>{escape(str(g['group']))} <span class='muted'>({g['count']})</span></td>"
                           + "".join(f"<td class='n c'>{escape(fmt(g['values'].get(c['key']), c.get('format')))}</td>" for c in cols)
                           + "</tr>")
            out.append("</tbody></table>")
        elif s["type"] == "fields":
            vals = {**(plan.get(k) or {}), **(follow.get(k) or {})}
            out.append(f"<h2>{escape(title)}</h2><table class='grid'><tr>" + "".join(
                f"<th>{escape(c['label'])}</th><td>{escape(fmt(vals.get(c['key']), None))}</td>" for c in s["fields"]) + "</tr></table>")
        elif s["type"] == "text":
            v = (follow if s.get("phase") == "follow" else plan).get(k)
            out.append(f"<h2>{escape(title)}</h2><div class='text'>{escape(v or '')}</div>")

    atts = doc.get("attachments") or []
    if atts:
        out.append("<h2>الشواهد والتقارير الداعمة</h2>" + evidence_rows(atts, doc["requirement_code"]))

    if approved:
        out.append(signatures([("أعدّه (منسق الجودة بالقسم)", doc.get("submitted_by_name") or ""),
                               ("اعتمده (رئيس القسم)", doc.get("approved_by_name") or ""),
                               ("تاريخ الاعتماد", f"{hijri(doc['approved_at'])} — {gregorian(doc['approved_at'])}")],
                              f"اعتُمد إلكترونياً عبر منصة الجودة والاعتماد — المرجع AQAP-F-{doc['id']}؛ النسخة الإلكترونية هي المرجع."))
    else:
        out.append(signatures([("أعدّه (منسق الجودة بالقسم)", ""), ("اعتمده (رئيس القسم)", ""), ("اطّلع عليه (وكالة الجودة)", "")]))
    out.append("</body></html>")
    return "".join(out)


def render_pdf(doc: dict) -> bytes:
    return to_pdf(render_html(doc))
