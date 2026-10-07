"""استيراد "نموذج العمل الشامل لنظام جودة التدريب – المستوى الثاني" (.xlsb) إلى AQAP.

يقرأ ورقة "م2-معايير المنهجية" (48 متطلباً × 8 أقسام) وورقة "بيانات المنشأة التدريبية"،
ويستورد على ثلاث درجات، كل درجة اختيارية بعد الأولى:

  1) الإطار: 6 معايير و18 معياراً فرعياً و48 متطلباً بنصوصها الرسمية (دائماً).
  2) الأقسام: أسماء الأقسام وأعداد المدربين والمتدربين           (--institution-id).
  3) التقديرات: الذاتي والخارجي والتوصيات وملاءمة الإجراءات       (--cycle-id و --actor-id).

أمثلة:
  python scripts/import_xlsb.py model.xlsb --dsn postgresql://aqap:aqap@localhost/aqap --dry-run
  python scripts/import_xlsb.py model.xlsb --dsn ... --institution-id 1
  python scripts/import_xlsb.py model.xlsb --dsn ... --institution-id 1 --cycle-id 1 --actor-id 4
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field

FRAMEWORK_CODE = "TVTC-TQ-L2"
SHEET_METHOD = "م2-معايير المنهجية"
SHEET_INST = "بيانات المنشأة التدريبية"
REQS_PER_DEPT = 48
MAX_DEPTS = 8

ORDINALS = {"الأول": 1, "الثاني": 2, "الثالث": 3, "الرابع": 4, "الخامس": 5, "السادس": 6}

# أعمدة ورقة المنهجية (صفر-مبدئي)
C_DEPT, C_STD_ORD, C_STD_TITLE, C_SUB, C_REQ, C_SELF, C_EXT, C_REC = 2, 3, 4, 5, 6, 7, 8, 9

SELF_MAP = {"متحقق": "met", "متحقق جزئي": "partial", "متحقق جزئيا": "partial", "متحقق جزئياً": "partial",
            "غير متحقق": "not_met", "لا ينطبق": "na"}
# التقييم الخارجي في النموذج حكم على صحة التقييم الذاتي، والمنصة تخزنه بالقيم نفسها
VERDICT_MAP = {"منطبق": "conforms", "غير منطبق": "not_conforming", "غير كافٍ": "insufficient", "غير كاف": "insufficient"}
GENERAL_STUDIES = "الدراسات العامة"

STAR_NOTES = {
    "**": "غير مطلوب من بعض الأقسام ومن قسم الدراسات العامة؛ يُقيَّم ذاتياً «لا ينطبق» ويؤكد المقيّم الخارجي انطباق ذلك.",
    "*": "غير مطلوب من قسم الدراسات العامة فقط؛ يُقيَّم ذاتياً «لا ينطبق» ويؤكد المقيّم الخارجي انطباق ذلك.",
}
REQ_RE = re.compile(r"^\s*(\d+-\d+-\d+)\s+(.*?)\s*$", re.S)
SUB_RE = re.compile(r"^\s*(\d+-\d+)\s*\n?\s*(.*?)\s*$", re.S)
PLACEHOLDERS = {"", "0", "0.0", "اكتب اسم القسم", "اسم المنشأة التدريبية"}


def clean(v) -> str | None:
    if v is None:
        return None
    if isinstance(v, float) and v == 0:
        return None
    s = re.sub(r"[ \t]+", " ", str(v)).strip()
    return None if s in PLACEHOLDERS else s


@dataclass
class Requirement:
    std_no: int
    std_title: str
    sub_code: str
    sub_title: str
    code: str
    text: str
    note: str | None
    order: int
    na_scope: int = 0


@dataclass
class Rating:
    dept_index: int
    dept_name: str
    code: str
    self_rating: str | None
    ext_verdict: str | None
    recommendation: str | None


@dataclass
class Department:
    index: int
    name: str
    trainers: int | None = None
    trainees: int | None = None


@dataclass
class Parsed:
    requirements: list[Requirement] = field(default_factory=list)
    departments: list[Department] = field(default_factory=list)
    ratings: list[Rating] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _rows(wb, name):
    with wb.get_sheet(name) as sh:
        return [{c.c: c.v for c in r if c.v is not None} for r in sh.rows()]


def _int(v) -> int | None:
    try:
        n = int(float(v))
        return n if n > 0 else None
    except (TypeError, ValueError):
        return None


def parse(path: str) -> Parsed:
    from pyxlsb import open_workbook

    out = Parsed()
    with open_workbook(path) as wb:
        if SHEET_METHOD not in wb.sheets:
            raise SystemExit(f"الملف لا يحتوي ورقة «{SHEET_METHOD}» — تأكد أنه نموذج المستوى الثاني")
        method = _rows(wb, SHEET_METHOD)
        inst = _rows(wb, SHEET_INST) if SHEET_INST in wb.sheets else []

    body = [r for r in method[1:] if clean(r.get(C_REQ))]
    expected = REQS_PER_DEPT * MAX_DEPTS
    if len(body) != expected:
        out.warnings.append(f"عدد صفوف المنهجية {len(body)} والمتوقع {expected}")

    # 1) الإطار من كتلة القسم الأول
    for i, r in enumerate(body[:REQS_PER_DEPT], 1):
        m_req = REQ_RE.match(str(r[C_REQ]))
        m_sub = SUB_RE.match(str(r.get(C_SUB, "")))
        std_no = ORDINALS.get(clean(r.get(C_STD_ORD)) or "")
        if not (m_req and m_sub and std_no):
            raise SystemExit(f"تعذّر تحليل الصف {i}: {str(r.get(C_REQ))[:60]}")
        code, text = m_req.groups()
        star = "**" if text.endswith("**") else "*" if text.endswith("*") else None
        out.requirements.append(Requirement(
            std_no=std_no, std_title=clean(r[C_STD_TITLE]), sub_code=m_sub.group(1), sub_title=m_sub.group(2).strip(),
            code=code, text=text.rstrip("*").strip(), note=STAR_NOTES.get(star), order=i,
            na_scope={"*": 1, "**": 2}.get(star, 0)))

    codes = [q.code for q in out.requirements]
    if len(set(codes)) != REQS_PER_DEPT:
        raise SystemExit("رموز المتطلبات مكررة أو ناقصة في كتلة القسم الأول")
    subs = {q.sub_code for q in out.requirements}
    stds = {q.std_no for q in out.requirements}
    if (len(stds), len(subs)) != (6, 18):
        out.warnings.append(f"البنية: {len(stds)} معايير و{len(subs)} معياراً فرعياً (المتوقع 6 و18)")

    # 2) الأقسام: ورقة بيانات المنشأة أولاً (الأسماء والأعداد)، ثم أسماء ورقة المنهجية
    names_by_index: dict[int, Department] = {}
    for k, row_no in enumerate(range(20, 20 + 2 * MAX_DEPTS, 2), 1):
        r = inst[row_no] if row_no < len(inst) else {}
        name = clean(r.get(4))
        if name:
            names_by_index[k] = Department(k, name, _int(r.get(16)), _int(r.get(23)))
    for k in range(1, MAX_DEPTS + 1):
        block = body[(k - 1) * REQS_PER_DEPT: k * REQS_PER_DEPT]
        name = clean(block[0].get(C_DEPT)) if block else None
        if name and k not in names_by_index:
            names_by_index[k] = Department(k, name)
    out.departments = [names_by_index[k] for k in sorted(names_by_index)]

    # 3) التقديرات
    for dept in out.departments:
        block = body[(dept.index - 1) * REQS_PER_DEPT: dept.index * REQS_PER_DEPT]
        for r in block:
            m = REQ_RE.match(str(r[C_REQ]))
            if not m:
                continue
            code = m.group(1)
            raw_self, raw_ext = clean(r.get(C_SELF)), clean(r.get(C_EXT))
            self_r = SELF_MAP.get(raw_self) if raw_self else None
            verdict = VERDICT_MAP.get(raw_ext) if raw_ext else None
            for raw, val, label in ((raw_self, self_r, "ذاتي"), (raw_ext, verdict, "خارجي")):
                if raw and val is None:
                    out.warnings.append(f"{dept.name} {code}: قيمة {label} غير معروفة «{raw}» — تم تجاهلها")
            rec = clean(r.get(C_REC))
            if any((self_r, verdict, rec)):
                out.ratings.append(Rating(dept.index, dept.name, code, self_r, verdict, rec))
    return out


# ---------------------------------------------------------------------------
def apply(conn, data: Parsed, institution_id: int | None, cycle_id: int | None, actor_id: int | None) -> dict:
    """يكتب البيانات المحللة في معاملة واحدة. يُعيد ملخصاً بالأعداد."""
    summary: dict = {}
    conn.execute("SET search_path = aqap, public")

    fw = conn.execute("SELECT id FROM framework WHERE code = %s", (FRAMEWORK_CODE,)).fetchone()
    if fw is None:
        raise SystemExit(f"الإطار {FRAMEWORK_CODE} غير موجود — طبّق db/schema.sql أولاً")
    fw_id = fw[0]

    with conn.cursor() as cur:
        cur.execute("TRUNCATE import_requirement_staging")
        cur.executemany(
            "INSERT INTO import_requirement_staging VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'department',true,%s)",
            [(str(q.std_no), q.std_title, q.std_no, q.sub_code, q.sub_title,
              int(q.sub_code.split("-")[1]), q.code, q.text, q.order, q.na_scope) for q in data.requirements])
    conn.execute("SELECT import_framework_from_staging(%s)", (FRAMEWORK_CODE,))
    for q in data.requirements:
        conn.execute("""UPDATE requirement r SET guidance_ar = %s
                          FROM sub_standard ss JOIN standard s ON s.id = ss.standard_id
                         WHERE r.sub_standard_id = ss.id AND s.framework_id = %s AND r.code = %s""",
                     (q.note, fw_id, q.code))
    # إزالة معايير البذرة القديمة الخالية (مثل S1..S6) إن وُجدت
    conn.execute("""DELETE FROM standard s WHERE s.framework_id = %s
                      AND NOT EXISTS (SELECT 1 FROM sub_standard ss WHERE ss.standard_id = s.id)""", (fw_id,))
    summary["requirements"] = conn.execute(
        """SELECT count(*) FROM requirement r JOIN sub_standard ss ON ss.id = r.sub_standard_id
             JOIN standard s ON s.id = ss.standard_id WHERE s.framework_id = %s""", (fw_id,)).fetchone()[0]

    if institution_id is None:
        return summary

    dept_ids: dict[int, int] = {}
    created = 0
    for d in data.departments:
        row = conn.execute("SELECT id FROM department WHERE institution_id = %s AND name_ar = %s",
                           (institution_id, d.name)).fetchone()
        if row is None:
            code = f"D{d.index}"
            if conn.execute("SELECT 1 FROM department WHERE institution_id = %s AND code = %s",
                            (institution_id, code)).fetchone():
                code = f"D{d.index}-{abs(hash(d.name)) % 1000}"
            row = conn.execute("""INSERT INTO department (institution_id, code, name_ar, trainer_count, trainee_count)
                                  VALUES (%s, %s, %s, %s, %s) RETURNING id""",
                               (institution_id, code, d.name, d.trainers, d.trainees)).fetchone()
            created += 1
        else:
            conn.execute("""UPDATE department SET trainer_count = COALESCE(%s, trainer_count),
                                   trainee_count = COALESCE(%s, trainee_count) WHERE id = %s""",
                         (d.trainers, d.trainees, row[0]))
        dept_ids[d.index] = row[0]
        # الخانة الأولى في القالب ثابتة لقسم الدراسات العامة، وتنطبق عليها متطلبات النجمة الواحدة
        conn.execute("UPDATE department SET is_general_studies = %s WHERE id = %s",
                     (d.index == 1 or d.name == GENERAL_STUDIES, row[0]))
    summary["departments"] = len(dept_ids)
    summary["departments_created"] = created

    if cycle_id is None:
        return summary
    if actor_id is None:
        raise SystemExit("استيراد التقديرات يتطلب --actor-id (يُسجَّل في سجل التدقيق ومسار الاعتماد)")

    cyc = conn.execute("SELECT status, framework_id, institution_id FROM assessment_cycle WHERE id = %s",
                       (cycle_id,)).fetchone()
    if cyc is None:
        raise SystemExit(f"الدورة {cycle_id} غير موجودة")
    if cyc[0] in ("closed", "archived"):
        raise SystemExit("الدورة مغلقة؛ لا يمكن الاستيراد إليها")
    if cyc[1] != fw_id or cyc[2] != institution_id:
        raise SystemExit("الدورة لا تتبع هذا الإطار أو هذه المنشأة")

    with conn.cursor() as cur:
        cur.executemany("INSERT INTO cycle_department VALUES (%s, %s) ON CONFLICT DO NOTHING",
                        [(cycle_id, i) for i in dept_ids.values()])
    conn.execute("SELECT generate_cycle_assessments(%s)", (cycle_id,))

    conn.execute("SELECT set_config('aqap.user_id', %s, true)", (str(actor_id),))
    conn.execute("SELECT set_config('aqap.system_op', 'on', true)")
    updated = moved = 0
    for r in data.ratings:
        a = conn.execute(
            """SELECT a.id, a.status FROM assessment a JOIN requirement q ON q.id = a.requirement_id
                 JOIN sub_standard ss ON ss.id = q.sub_standard_id JOIN standard s ON s.id = ss.standard_id
                WHERE a.cycle_id = %s AND a.department_id = %s AND q.code = %s AND s.framework_id = %s""",
            (cycle_id, dept_ids[r.dept_index], r.code, fw_id)).fetchone()
        if a is None:
            data.warnings.append(f"{r.dept_name} {r.code}: لا يوجد سجل تقدير في الدورة")
            continue
        conn.execute("""UPDATE assessment SET self_rating = COALESCE(%s, self_rating),
                               ext_verdict = COALESCE(%s, ext_verdict),
                               ext_recommendation = COALESCE(%s, ext_recommendation)
                         WHERE id = %s""",
                     (r.self_rating, r.ext_verdict, r.recommendation, a[0]))
        updated += 1
        # ما قيّمه المقيّم الخارجي يدخل مرحلة "مُدقَّق" ليعتمده وكيل الجودة؛ والباقي يبقى مسودة لمراجعة القسم
        target = "audited" if r.ext_verdict else None
        if target and a[1] != target:
            conn.execute("UPDATE assessment SET status = %s WHERE id = %s", (target, a[0]))
            conn.execute("""INSERT INTO assessment_transition (assessment_id, from_status, to_status, actor_id, comment)
                            VALUES (%s, %s, %s, %s, 'استيراد من ملف نموذج العمل الشامل')""",
                         (a[0], a[1], target, actor_id))
            moved += 1
    conn.execute("SELECT set_config('aqap.system_op', 'off', true)")
    summary["assessments_updated"] = updated
    summary["moved_to_audited"] = moved
    return summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("xlsb")
    ap.add_argument("--dsn", help="اتصال PostgreSQL (غير مطلوب مع --dry-run)")
    ap.add_argument("--institution-id", type=int)
    ap.add_argument("--cycle-id", type=int)
    ap.add_argument("--actor-id", type=int)
    ap.add_argument("--dry-run", action="store_true", help="تحليل الملف وعرض الملخص دون كتابة")
    args = ap.parse_args(argv)
    if args.cycle_id and not args.institution_id:
        ap.error("--cycle-id يتطلب --institution-id")

    data = parse(args.xlsb)
    stds = sorted({(q.std_no, q.std_title) for q in data.requirements})
    print(f"الإطار: {len(stds)} معايير، {len({q.sub_code for q in data.requirements})} معياراً فرعياً، "
          f"{len(data.requirements)} متطلباً")
    for no, title in stds:
        n = sum(1 for q in data.requirements if q.std_no == no)
        print(f"  {no}. {title} — {n} متطلباً")
    starred = [q.code for q in data.requirements if q.note]
    print(f"متطلبات بشرط انطباق (*/**): {len(starred)} — {', '.join(starred)}")
    print("الأقسام في الملف: " + ("، ".join(f"{d.name}" + (f" ({d.trainers} مدرب، {d.trainees} متدرب)" if d.trainers else "")
                                        for d in data.departments) or "لا يوجد"))
    print(f"تقديرات معبأة: {len(data.ratings)}")
    for w in data.warnings:
        print(f"تنبيه: {w}")
    if args.dry_run:
        return 0
    if not args.dsn:
        ap.error("--dsn مطلوب للكتابة")

    import psycopg
    seen = len(data.warnings)
    with psycopg.connect(args.dsn) as conn:
        with conn.transaction():
            summary = apply(conn, data, args.institution_id, args.cycle_id, args.actor_id)
    print("تم الاستيراد:", ", ".join(f"{k}={v}" for k, v in summary.items()))
    for w in data.warnings[seen:]:
        print(f"تنبيه: {w}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
