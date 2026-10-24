"""تقويم الإنجاز: مواعيد المعايير الفرعية والمتطلبات يرفعها وكيل الجودة، ويتابع كل قسم إنجازه عليها.

الإنجاز = تقديرات النطاق التي رُفعت من القسم (مرفوع فما بعده) ÷ تقديرات النطاق.
الموعد الأخص يغلب: المتطلب على المعيار الفرعي، والقسم المحدد على «كل الأقسام».
"""
import csv
import io
import re
import zipfile
from datetime import date, timedelta
from xml.etree import ElementTree as ET

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import Response
from psycopg import AsyncConnection
from pydantic import BaseModel, Field

from ..security import CurrentUser, current_user, forbid, get_conn, load_cycle, not_found

router = APIRouter(tags=["تقويم الإنجاز"])
MANAGERS = ("quality_dean", "system_admin")
DONE = ("submitted", "hod_approved", "under_audit", "audited", "final")
SOON_DAYS = 7


class DeadlineIn(BaseModel):
    target_code: str = Field(min_length=1, max_length=20)     # رمز معيار فرعي (1-2) أو متطلب (1-2-3)
    department_id: int | None = None
    starts_on: date | None = None
    due_on: date
    note_ar: str | None = Field(None, max_length=500)


def _status(done: int, total: int, due: date, today: date) -> str:
    if total and done >= total:
        return "done"
    if due < today:
        return "overdue"
    if (due - today).days <= SOON_DAYS:
        return "soon"
    return "upcoming"


@router.get("/cycles/{cycle_id}/calendar")
async def calendar(cycle_id: int, department_id: int | None = None, user: CurrentUser = Depends(current_user),
                   conn: AsyncConnection = Depends(get_conn, scope="function")):
    await load_cycle(conn, user, cycle_id)
    all_depts, depts = user.scope(cycle_id)
    cur = await conn.execute(
        """SELECT cd.id, cd.department_id, cd.starts_on, cd.due_on, cd.note_ar,
                   COALESCE(ss.code, r.code) AS target_code,
                   COALESCE(ss.title_ar, r.text_ar) AS target_title,
                   CASE WHEN cd.requirement_id IS NULL THEN 'sub_standard' ELSE 'requirement' END AS target_kind,
                   COALESCE(ss2.code, ss.code) AS sub_standard_code, COALESCE(ss2.title_ar, ss.title_ar) AS sub_standard_title,
                   d.name_ar AS department_name,
                   count(ad.assessment_id) AS total,
                   count(ad.assessment_id) FILTER (WHERE ad.status = ANY(%(done)s)) AS done
              FROM cycle_deadline cd
              LEFT JOIN sub_standard ss ON ss.id = cd.sub_standard_id
              LEFT JOIN requirement r   ON r.id = cd.requirement_id
              LEFT JOIN sub_standard ss2 ON ss2.id = r.sub_standard_id
              LEFT JOIN department d    ON d.id = cd.department_id
              LEFT JOIN v_assessment_deadline ad ON ad.deadline_id = cd.id
                   AND ad.department_id IS NOT NULL
                   AND (%(all)s OR ad.department_id = ANY(%(depts)s))
                   AND (%(dept)s::bigint IS NULL OR ad.department_id = %(dept)s)
             WHERE cd.cycle_id = %(c)s
               AND (cd.department_id IS NULL OR %(all)s OR cd.department_id = ANY(%(depts)s))
               AND (%(dept)s::bigint IS NULL OR cd.department_id IS NULL OR cd.department_id = %(dept)s)
             GROUP BY cd.id, ss.code, r.code, ss.title_ar, r.text_ar, ss2.code, ss2.title_ar, d.name_ar
             ORDER BY cd.due_on, target_code""",
        {"c": cycle_id, "all": all_depts, "depts": depts, "dept": department_id, "done": list(DONE)})
    rows = await cur.fetchall()
    today = date.today()
    for r in rows:
        r["status"] = _status(r["done"], r["total"], r["due_on"], today)
        r["days_left"] = (r["due_on"] - today).days
    return {"can_edit": user.has(*MANAGERS), "today": today, "deadlines": rows}


async def _resolve(conn, cycle: dict, code: str) -> tuple[int | None, int | None]:
    code = code.strip().replace("–", "-").replace("ـ", "-")
    cur = await conn.execute(
        """SELECT ss.id FROM sub_standard ss JOIN standard s ON s.id = ss.standard_id
            WHERE s.framework_id = %s AND ss.code = %s""", (cycle["framework_id"], code))
    row = await cur.fetchone()
    if row:
        return row["id"], None
    cur = await conn.execute(
        """SELECT r.id FROM requirement r JOIN sub_standard ss ON ss.id = r.sub_standard_id
             JOIN standard s ON s.id = ss.standard_id WHERE s.framework_id = %s AND r.code = %s""",
        (cycle["framework_id"], code))
    row = await cur.fetchone()
    if row:
        return None, row["id"]
    raise not_found(f"الرمز {code} ليس معياراً فرعياً ولا متطلباً في إطار الدورة")


async def _upsert(conn, user: CurrentUser, cycle: dict, body: DeadlineIn) -> int:
    if body.starts_on and body.starts_on > body.due_on:
        raise forbid("تاريخ البدء بعد تاريخ الانتهاء")
    sub_id, req_id = await _resolve(conn, cycle, body.target_code)
    if body.department_id is not None:
        cur = await conn.execute("SELECT 1 FROM department WHERE id = %s AND institution_id = %s",
                                 (body.department_id, user.institution_id))
        if await cur.fetchone() is None:
            raise not_found("القسم غير موجود")
    await conn.execute("SELECT set_config('aqap.user_id', %s, true)", (str(user.id),))
    cur = await conn.execute(
        """INSERT INTO cycle_deadline (cycle_id, sub_standard_id, requirement_id, department_id, starts_on, due_on, note_ar, created_by)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
           ON CONFLICT (cycle_id, COALESCE(sub_standard_id, 0), COALESCE(requirement_id, 0), COALESCE(department_id, 0))
           DO UPDATE SET starts_on = EXCLUDED.starts_on, due_on = EXCLUDED.due_on, note_ar = EXCLUDED.note_ar, updated_at = now()
           RETURNING id""",
        (cycle["id"], sub_id, req_id, body.department_id, body.starts_on, body.due_on, body.note_ar, user.id))
    return (await cur.fetchone())["id"]


def _manager(user: CurrentUser, cycle_id: int) -> None:
    if not user.has(*MANAGERS, cycle_id=cycle_id):
        raise forbid("رفع التقويم من صلاحية وكيل الجودة")


@router.post("/cycles/{cycle_id}/calendar", status_code=201)
async def add_deadline(cycle_id: int, body: DeadlineIn, user: CurrentUser = Depends(current_user),
                       conn: AsyncConnection = Depends(get_conn, scope="function")):
    cycle = await load_cycle(conn, user, cycle_id)
    _manager(user, cycle_id)
    return {"id": await _upsert(conn, user, cycle, body)}


@router.delete("/calendar/{deadline_id}")
async def delete_deadline(deadline_id: int, user: CurrentUser = Depends(current_user),
                          conn: AsyncConnection = Depends(get_conn, scope="function")):
    cur = await conn.execute("SELECT cycle_id FROM cycle_deadline WHERE id = %s", (deadline_id,))
    row = await cur.fetchone()
    if row is None:
        raise not_found("الموعد غير موجود")
    await load_cycle(conn, user, row["cycle_id"])
    _manager(user, row["cycle_id"])
    await conn.execute("SELECT set_config('aqap.user_id', %s, true)", (str(user.id),))
    await conn.execute("DELETE FROM cycle_deadline WHERE id = %s", (deadline_id,))
    return {"deleted": True}


# ---------------------------------------------------------------- القالب والاستيراد
HEADERS = ["الرمز (معيار فرعي أو متطلب)", "الاسم (للاسترشاد)", "تاريخ البدء", "تاريخ الانتهاء", "رمز القسم (فارغ = كل الأقسام)", "ملاحظات"]


@router.get("/cycles/{cycle_id}/calendar/template")
async def template(cycle_id: int, user: CurrentUser = Depends(current_user), conn: AsyncConnection = Depends(get_conn, scope="function")):
    """قالب CSV يفتح في Excel: صف لكل معيار فرعي، ويمكن إضافة صفوف لمتطلبات بعينها أو لقسم بعينه."""
    cycle = await load_cycle(conn, user, cycle_id)
    cur = await conn.execute(
        """SELECT ss.code, ss.title_ar, cd.starts_on, cd.due_on, cd.note_ar FROM sub_standard ss
             JOIN standard s ON s.id = ss.standard_id
             LEFT JOIN cycle_deadline cd ON cd.sub_standard_id = ss.id AND cd.cycle_id = %s AND cd.department_id IS NULL
            WHERE s.framework_id = %s ORDER BY s.sort_order, ss.sort_order""", (cycle_id, cycle["framework_id"]))
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(HEADERS)
    for r in await cur.fetchall():
        w.writerow([r["code"], r["title_ar"], r["starts_on"] or "", r["due_on"] or "", "", r["note_ar"] or ""])
    data = ("﻿" + buf.getvalue()).encode("utf-8")
    return Response(data, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": "attachment; filename*=UTF-8''calendar_template.csv"})


def _xlsx_rows(raw: bytes) -> list[list[str]]:
    """قارئ xlsx مبسّط (الورقة الأولى) دون مكتبات إضافية."""
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", ns):
                shared.append("".join(t.text or "" for t in si.iter(f"{{{ns['m']}}}t")))
        sheet = sorted(n for n in z.namelist() if n.startswith("xl/worksheets/sheet"))[0]
        rows = []
        for row in ET.fromstring(z.read(sheet)).iter(f"{{{ns['m']}}}row"):
            cells = {}
            for c in row.findall("m:c", ns):
                col = re.match(r"[A-Z]+", c.get("r", "A")).group(0)
                idx = 0
                for ch in col:
                    idx = idx * 26 + ord(ch) - 64
                v = c.find("m:v", ns)
                t = c.get("t")
                if t == "s" and v is not None:
                    val = shared[int(v.text)]
                elif t == "inlineStr":
                    val = "".join(x.text or "" for x in c.iter(f"{{{ns['m']}}}t"))
                else:
                    val = v.text if v is not None else ""
                cells[idx - 1] = val or ""
            rows.append([cells.get(i, "") for i in range(max(cells, default=-1) + 1)])
        return rows


def _date(v: str) -> date | None:
    v = (v or "").strip()
    if not v:
        return None
    if re.fullmatch(r"\d+(\.0+)?", v) and 20000 < float(v) < 80000:          # رقم تسلسلي من Excel
        return date(1899, 12, 30) + timedelta(days=int(float(v)))
    m = re.fullmatch(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", v)
    if m:
        return date(int(m[1]), int(m[2]), int(m[3]))
    m = re.fullmatch(r"(\d{1,2})[-/](\d{1,2})[-/](\d{4})", v)
    if m:
        return date(int(m[3]), int(m[2]), int(m[1]))
    raise ValueError(f"تاريخ غير مفهوم: {v} (استخدم 2026-11-30 أو 30/11/2026 بالتاريخ الميلادي)")


@router.post("/cycles/{cycle_id}/calendar/import")
async def import_calendar(cycle_id: int, file: UploadFile = File(...), user: CurrentUser = Depends(current_user),
                          conn: AsyncConnection = Depends(get_conn, scope="function")):
    cycle = await load_cycle(conn, user, cycle_id)
    _manager(user, cycle_id)
    raw = await file.read()
    if raw[:2] == b"PK":
        rows = _xlsx_rows(raw)
    else:
        text = raw.decode("utf-8-sig", errors="replace")
        rows = list(csv.reader(io.StringIO(text)))
    cur = await conn.execute("SELECT id, code FROM department WHERE institution_id = %s", (user.institution_id,))
    dept_by_code = {r["code"].upper(): r["id"] for r in await cur.fetchall()}
    imported, skipped, errors = 0, 0, []
    for n, row in enumerate(rows[1:], start=2):
        row = (row + [""] * 6)[:6]
        code, _, start, due, dept, note = (str(x).strip() for x in row)
        if not code or not due:
            skipped += 1
            continue
        try:
            dept_id = None
            if dept:
                dept_id = dept_by_code.get(dept.upper())
                if dept_id is None:
                    raise ValueError(f"رمز القسم {dept} غير معروف")
            body = DeadlineIn(target_code=code, department_id=dept_id, starts_on=_date(start), due_on=_date(due),
                              note_ar=note or None)
            async with conn.transaction():
                await _upsert(conn, user, cycle, body)
            imported += 1
        except Exception as ex:          # نجمع أخطاء الصفوف ونكمل البقية
            msg = getattr(ex, "detail", None) or str(ex)
            errors.append({"row": n, "code": code, "error": msg})
    return {"imported": imported, "skipped": skipped, "errors": errors}
