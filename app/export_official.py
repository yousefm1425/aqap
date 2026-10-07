"""تصدير دورة تقييم إلى قالب «نموذج العمل الشامل» الرسمي.

مطابقة القيم مع القالب:
- التقييم الذاتي: متحقق / متحقق جزئي / غير متحقق / لا ينطبق (كما هي).
- التقييم الخارجي: حكم المقيّم كما هو (منطبق / غير منطبق / غير كافٍ) — المنصة تخزنه بالقيم نفسها.
- ملاءمة الإجراءات في ورقة التحسين: مناسب / غير مناسب / غير كافٍ، والخطة المغلقة بعد التحقق ← «متحقق».
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from psycopg import AsyncConnection

SELF_LABEL = {"met": "متحقق", "partial": "متحقق جزئي", "not_met": "غير متحقق", "na": "لا ينطبق"}
ADEQ_LABEL = {"suitable": "مناسب", "unsuitable": "غير مناسب", "insufficient": "غير كافٍ"}
GENERAL_STUDIES = "الدراسات العامة"
MAX_SLOTS = 8


class ExportError(Exception):
    pass


VERDICT_LABEL = {"conforms": "منطبق", "not_conforming": "غير منطبق", "insufficient": "غير كافٍ"}


async def build_payload(conn: AsyncConnection, cycle_id: int) -> dict:
    cur = await conn.execute(
        """SELECT c.id, c.framework_id, c.academic_year, i.name_ar AS institution_name
             FROM assessment_cycle c JOIN institution i ON i.id = c.institution_id WHERE c.id = %s""", (cycle_id,))
    cycle = await cur.fetchone()
    if cycle is None:
        raise ExportError("الدورة غير موجودة")

    cur = await conn.execute(
        """SELECT r.code FROM requirement r JOIN sub_standard ss ON ss.id = r.sub_standard_id
             JOIN standard s ON s.id = ss.standard_id WHERE s.framework_id = %s AND r.is_active""",
        (cycle["framework_id"],))
    codes = [r["code"] for r in await cur.fetchall()]
    if not codes or not all(c.count("-") == 2 and c.replace("-", "").isdigit() for c in codes):
        raise ExportError("إطار الدورة ليس النموذج الرسمي المستورد؛ استورد ملف نموذج العمل أولاً")

    cur = await conn.execute(
        """SELECT d.id, d.name_ar, d.code, d.trainer_count, d.trainee_count
             FROM cycle_department cd JOIN department d ON d.id = cd.department_id
            WHERE cd.cycle_id = %s ORDER BY (d.name_ar = %s) DESC, d.code""", (cycle_id, GENERAL_STUDIES))
    depts = await cur.fetchall()
    if len(depts) > MAX_SLOTS:
        raise ExportError(f"القالب الرسمي يتسع لـ{MAX_SLOTS} أقسام والدورة فيها {len(depts)}")

    out = []
    for slot, d in enumerate(depts, 1):
        cur = await conn.execute(
            """SELECT r.code, a.self_rating, a.ext_verdict, a.ext_recommendation
                 FROM assessment a JOIN requirement r ON r.id = a.requirement_id
                WHERE a.cycle_id = %s AND a.department_id = %s""", (cycle_id, d["id"]))
        ratings = {}
        for a in await cur.fetchall():
            entry = {"self": SELF_LABEL.get(a["self_rating"]),
                     "ext": VERDICT_LABEL.get(a["ext_verdict"]),
                     "recommendation": a["ext_recommendation"]}
            if any(entry.values()):
                ratings[a["code"]] = entry
        cur = await conn.execute(
            """SELECT r.code, ia.action_ar, ia.owner_label, u.full_name_ar AS owner_name, ia.due_date, ia.status,
                      ia.adequacy, ia.reviewer_notes, ia.verification_note, e.title_ar AS evidence_title
                 FROM improvement_action ia
                 JOIN assessment a ON a.id = ia.assessment_id JOIN requirement r ON r.id = a.requirement_id
                 LEFT JOIN app_user u ON u.id = ia.owner_id
                 LEFT JOIN evidence e ON e.id = ia.completion_evidence_id
                WHERE ia.cycle_id = %s AND ia.department_id = %s AND ia.status <> 'cancelled'
                ORDER BY ia.id""", (cycle_id, d["id"]))
        plans = {}
        for p in await cur.fetchall():
            if p["code"] in plans:          # القالب صف واحد لكل متطلب: نضم الخطط الإضافية للنص
                prev = plans[p["code"]]
                prev["action"] = "\n".join(filter(None, [prev["action"], p["action_ar"]]))
                continue
            plans[p["code"]] = {
                "action": p["action_ar"],
                "owner": p["owner_label"] or p["owner_name"],
                "due_date": p["due_date"].isoformat() if p["due_date"] else None,
                "evidence": p["evidence_title"],
                "adequacy": "متحقق" if p["status"] == "verified" else ADEQ_LABEL.get(p["adequacy"]),
                "notes": p["verification_note"] or p["reviewer_notes"],
            }
        out.append({"slot": slot, "name": d["name_ar"], "trainers": d["trainer_count"],
                    "trainees": d["trainee_count"], "ratings": ratings, "plans": plans})
    return {"cycle_id": cycle_id, "academic_year": cycle["academic_year"],
            "institution_name": cycle["institution_name"], "departments": out, "requirement_codes": codes}


def run_filler(payload: dict, template: str, out_path: str, timeout: int = 300, verify: bool = False) -> dict:
    if not Path(template).is_file():
        raise ExportError("ملف القالب الرسمي غير موجود؛ اضبط AQAP_OFFICIAL_TEMPLATE")
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
        payload_path = f.name
    try:
        proc = subprocess.run([sys.executable, "-m", "app.export_filler", payload_path, template, out_path]
                              + (["--verify"] if verify else []),
                              capture_output=True, text=True, timeout=timeout,
                              cwd=str(Path(__file__).resolve().parents[1]))
    finally:
        Path(payload_path).unlink(missing_ok=True)
    if proc.returncode != 0 or not Path(out_path).is_file():
        raise ExportError(f"فشل توليد الملف: {(proc.stderr or proc.stdout).strip()[-400:]}")
    return json.loads(proc.stdout.strip().splitlines()[-1])
