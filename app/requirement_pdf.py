"""تقرير المتطلب PDF: التقييم الذاتي والخارجي، والشواهد (روابط قابلة للنقر)، والمحاضر والنماذج المرتبطة، وخطط التحسين، وسير الاعتماد.
يصلح للطباعة وللرفع كما هو إلى منصات الاعتماد الأخرى."""
from __future__ import annotations

from html import escape

from .minutes_pdf import gregorian, hijri
from .pdf_brand import code, evidence_rows, header, meta_table, page_css, req_box, signatures, to_pdf

RATING = {"met": "متحقق", "partial": "متحقق جزئياً", "not_met": "غير متحقق", "na": "لا ينطبق"}
ADEQ = {"suitable": "مناسب", "unsuitable": "غير مناسب", "insufficient": "غير كافٍ"}
VERDICT = {"conforms": "منطبق", "not_conforming": "غير منطبق", "insufficient": "غير كافٍ"}
STATUS = {"draft": "مسودة", "submitted": "مرفوع لرئيس القسم", "returned": "معاد للتعديل", "hod_approved": "معتمد من القسم",
          "under_audit": "قيد التدقيق", "audited": "مُدقَّق", "final": "نهائي"}
DOC_STATUS = {"draft": "مسودة", "submitted": "بانتظار الاعتماد", "returned": "معاد", "approved": "معتمد"}
ACTION = {"draft": "مسودة", "submitted": "مرفوعة", "revision": "معادة للتعديل", "approved": "معتمدة", "completed": "مكتملة",
          "verified": "مُتحقق منها", "cancelled": "ملغاة"}
CSS = page_css(landscape=False, base_pt=10) + ".rating { font-weight: 700; color: #126C66; }"


def render_html(d: dict) -> str:
    r = d["requirement"]
    final = d["status"] == "final"
    ref = f"AQAP-A-{d['id']}"
    out = [f"""<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><style>{CSS}</style></head><body>
{header("تقرير متطلب", ref, final)}
<h1>المتطلب {code(r['code'])} — {escape(d['department_name'] or 'متطلبات المنشأة')}</h1>
{req_box(r['code'], r['text_ar'], f"{r['standard_code']} {r['standard_title']}", f"{r['sub_standard_code']} {r['sub_standard_title']}")}
{meta_table([("القسم التدريبي", d['department_name'] or 'متطلبات المنشأة'), ("العام التدريبي", f"{d['academic_year']}هـ"),
             ("حالة المتطلب", STATUS.get(d['status'], d['status'])),
             ("التقييم الذاتي", RATING.get(d.get('self_rating'))), ("كفاية الإجراء", ADEQ.get(d.get('self_adequacy'))),
             ("الحكم الخارجي", VERDICT.get(d.get('ext_verdict'))), ("التقدير المعتمد", RATING.get(d.get('eff_rating'))),
             ("عدد الشواهد", len(d['evidence']))])}"""]
    if d.get("self_notes"):
        out.append(f"<h2>ملاحظات التقييم الذاتي</h2><div class='text'>{escape(d['self_notes'])}</div>")
    if d.get("ext_recommendation"):
        out.append(f"<h2>توصية المقيّم</h2><div class='text'>{escape(d['ext_recommendation'])}</div>")

    out.append("<h2>الشواهد</h2>" + (evidence_rows(d["evidence"], r["code"]) if d["evidence"]
                                      else "<p class='muted'>لم يُربط شاهد بهذا المتطلب بعد.</p>"))
    docs = d.get("documents") or []
    if docs:
        out.append("<h2>المحاضر والخطط والتقارير المرتبطة</h2><table class='grid'><thead><tr><th style='width:5%'>م</th>"
                   "<th style='width:14%'>النوع</th><th>العنوان</th><th style='width:14%'>الحالة</th><th style='width:16%'>المرجع</th>"
                   "</tr></thead><tbody>")
        for i, x in enumerate(docs, 1):
            out.append(f"<tr><td class='n'>{i}</td><td>{escape(x['kind'])}</td><td>{escape(x['title'])}</td>"
                       f"<td>{escape(DOC_STATUS.get(x['status'], x['status']))}</td><td class='n'>{escape(x['ref'])}</td></tr>")
        out.append("</tbody></table>")
    plans = d.get("plans") or []
    if plans:
        out.append("<h2>خطط التحسين</h2><table class='grid'><thead><tr><th style='width:5%'>م</th><th>الإجراء التحسيني</th>"
                   "<th style='width:16%'>المسؤول</th><th style='width:13%'>تاريخ الاكتمال</th><th style='width:10%'>الإنجاز</th>"
                   "<th style='width:13%'>الحالة</th></tr></thead><tbody>")
        for i, p in enumerate(plans, 1):
            out.append(f"<tr><td class='n'>{i}</td><td>{escape(p.get('action_ar') or p['title_ar'])}</td>"
                       f"<td>{escape(p.get('owner') or '—')}</td><td class='n'>{gregorian(p.get('due_date')) if p.get('due_date') else '—'}</td>"
                       f"<td class='n'>{p['progress_pct']}%</td><td>{escape(ACTION.get(p['status'], p['status']))}</td></tr>")
        out.append("</tbody></table>")
    hist = d.get("history") or []
    if hist:
        out.append("<h2>سير الاعتماد</h2><table class='grid'><thead><tr><th style='width:18%'>التاريخ</th><th style='width:22%'>الإجراء</th>"
                   "<th style='width:20%'>بواسطة</th><th>الملاحظة</th></tr></thead><tbody>")
        for h_ in hist:
            out.append(f"<tr><td class='n'>{hijri(h_['at'])}</td><td>{escape(STATUS.get(h_['to_status'], h_['to_status']))}</td>"
                       f"<td>{escape(h_.get('actor') or '')}</td><td>{escape(h_.get('comment') or '')}</td></tr>")
        out.append("</tbody></table>")
    out.append(signatures([("منسق الجودة بالقسم", ""), ("رئيس القسم", ""), ("المقيّم / المدقق", "")],
                          f"صدر من منصة الجودة والاعتماد — المرجع {ref}" + ("؛ المتطلب معتمد نهائياً." if final else ".")))
    out.append("</body></html>")
    return "".join(out)


def render_pdf(d: dict) -> bytes:
    return to_pdf(render_html(d))
