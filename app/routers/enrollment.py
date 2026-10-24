"""المتدربون المستمرون والبرامج: تقرير ST06 من رايات، قسم داخل صفحة «سير العملية التدريبية».

- يقرأ المتصفح ملف CSV (صف لكل قسم/برنامج/فترة) ويرسل الأعداد فقط.
- لقطتان لكل فصل: «بداية الفصل» تُحفظ عند أول رفع ولا تتغير إلا بطلب صريح، و«الأحدث» يستبدلها كل رفع — فيظهر الاستمرار/التسرب.
- الأقسام تُطابق بالاسم عند القراءة (رايات: «الحاسب وتقنية المعلومات» ↔ المنصة: «تقنية الحاسب»)، فإضافة قسم لاحقاً تنعكس فوراً.
- ST06 مصدر عدد المتدربين: زر يحدّث department.trainee_count بدل الإدخال اليدوي.
"""
import re

from fastapi import APIRouter, Depends
from psycopg import AsyncConnection
from pydantic import BaseModel, Field

from ..security import CurrentUser, current_user, forbid, get_conn, load_cycle

router = APIRouter(tags=["سير العملية التدريبية"])
MANAGERS = ("quality_dean", "system_admin")
STOP = {"تقنيه", "قسم", "و", "في", "تطبيقي"}


def tokens(name: str) -> set[str]:
    t = re.sub("[أإآ]", "ا", name or "").replace("ة", "ه")
    out = set()
    for w in re.findall(r"[؀-ۿ]+", t):
        if w.startswith("و") and len(w) > 4:
            w = w[1:]
        if w.startswith("ال") and len(w) > 4:
            w = w[2:]
        if w not in STOP and len(w) > 2:
            out.add(w)
    return out


def match_dept(raw: str, depts: list[dict]) -> int | None:
    """القسم الأكثر تطابقاً في الكلمات (بعد حذف «التقنية» و«ال»)."""
    rt = tokens(raw)
    best, score = None, 0
    for d in depts:
        n = len(rt & tokens(d["name_ar"]))
        if n > score:
            best, score = d["id"], n
    return best


class RowIn(BaseModel):
    dept_name: str = Field(min_length=1, max_length=200)
    program: str = Field(min_length=1, max_length=300)
    stage: str | None = Field(default=None, max_length=60)
    shift: str | None = Field(default=None, max_length=60)
    trainees: int = Field(ge=0, le=100000)


class UploadIn(BaseModel):
    term_label: str | None = Field(default=None, max_length=120)
    file_name: str | None = Field(default=None, max_length=300)
    as_baseline: bool = False          # اعتبار هذا الملف «بداية الفصل» أيضاً
    rows: list[RowIn] = Field(min_length=1, max_length=2000)


def _manager(user: CurrentUser) -> None:
    if not user.has(*MANAGERS):
        raise forbid("رفع تقارير رايات من صلاحية وكيل الجودة")


async def _save(conn, cycle_id: int, slot: str, body: UploadIn, user_id: int) -> None:
    await conn.execute("DELETE FROM enrollment_upload WHERE cycle_id = %s AND slot = %s", (cycle_id, slot))
    cur = await conn.execute("""INSERT INTO enrollment_upload (cycle_id, slot, term_label, file_name, uploaded_by)
                                VALUES (%s, %s, %s, %s, %s) RETURNING id""",
                             (cycle_id, slot, body.term_label, body.file_name, user_id))
    uid = (await cur.fetchone())["id"]
    async with conn.cursor() as c:
        await c.executemany("INSERT INTO enrollment_row (upload_id, dept_name, program, stage, shift, trainees) VALUES (%s, %s, %s, %s, %s, %s)",
                            [(uid, " ".join(r.dept_name.split()), " ".join(r.program.split()), r.stage, r.shift, r.trainees) for r in body.rows])


@router.post("/cycles/{cycle_id}/enrollment", status_code=201)
async def upload(cycle_id: int, body: UploadIn, user: CurrentUser = Depends(current_user), conn: AsyncConnection = Depends(get_conn, scope="function")):
    cycle = await load_cycle(conn, user, cycle_id)
    _manager(user)
    await conn.execute("SELECT set_config('aqap.user_id', %s, true)", (str(user.id),))
    cur = await conn.execute("SELECT 1 FROM enrollment_upload WHERE cycle_id = %s AND slot = 'baseline'", (cycle_id,))
    first = await cur.fetchone() is None
    await _save(conn, cycle_id, "latest", body, user.id)
    if first or body.as_baseline:
        await _save(conn, cycle_id, "baseline", body, user.id)
    cur = await conn.execute("SELECT id, name_ar FROM department WHERE institution_id = %s", (cycle["institution_id"],))
    depts = await cur.fetchall()
    unmatched = sorted({r.dept_name for r in body.rows if match_dept(r.dept_name, depts) is None})
    return {"rows": len(body.rows), "trainees": sum(r.trainees for r in body.rows), "baseline": first or body.as_baseline,
            "unmatched": unmatched}


@router.delete("/cycles/{cycle_id}/enrollment")
async def clear(cycle_id: int, user: CurrentUser = Depends(current_user), conn: AsyncConnection = Depends(get_conn, scope="function")):
    await load_cycle(conn, user, cycle_id)
    _manager(user)
    await conn.execute("SELECT set_config('aqap.user_id', %s, true)", (str(user.id),))
    await conn.execute("DELETE FROM enrollment_upload WHERE cycle_id = %s", (cycle_id,))
    return {"deleted": True}


async def _summary(conn, user: CurrentUser, cycle: dict) -> dict:
    all_depts, scope = user.scope(cycle["id"])
    cur = await conn.execute("SELECT id, name_ar, trainee_count FROM department WHERE institution_id = %s ORDER BY code",
                             (cycle["institution_id"],))
    depts = await cur.fetchall()
    cur = await conn.execute("SELECT id, slot, term_label, file_name, uploaded_at FROM enrollment_upload WHERE cycle_id = %s",
                             (cycle["id"],))
    ups = {u["slot"]: u for u in await cur.fetchall()}
    base = {"can_edit": user.has(*MANAGERS), "latest": ups.get("latest"), "baseline": ups.get("baseline")}
    if "latest" not in ups:
        return base

    async def rows(slot):
        if slot not in ups:
            return []
        c = await conn.execute("SELECT dept_name, program, stage, shift, trainees FROM enrollment_row WHERE upload_id = %s ORDER BY id",
                               (ups[slot]["id"],))
        out = []
        for r in await c.fetchall():
            r["department_id"] = match_dept(r["dept_name"], depts)
            if all_depts or r["department_id"] in scope:
                out.append(r)
        return out
    latest, baseline = await rows("latest"), await rows("baseline")
    same = not baseline or ups["baseline"]["uploaded_at"] == ups["latest"]["uploaded_at"]
    key = lambda r: (r["department_id"], r["dept_name"], r["program"], r["shift"])
    base_map = {key(r): r["trainees"] for r in baseline}
    # المدربون لكل قسم من آخر أسبوع SO09 (لنسبة المتدربين/المدرب)
    cur = await conn.execute(
        """SELECT td.department_id, count(DISTINCT s.trainer_no) AS n
             FROM attendance_section s JOIN attendance_upload u ON u.id = s.upload_id
             JOIN trainer_department td ON td.institution_id = %s AND td.trainer_no = s.trainer_no
            WHERE u.cycle_id = %s AND u.week_no = (SELECT max(week_no) FROM attendance_upload WHERE cycle_id = %s)
            GROUP BY td.department_id""", (cycle["institution_id"], cycle["id"], cycle["id"]))
    trainers = {r["department_id"]: r["n"] for r in await cur.fetchall()}
    names = {d["id"]: d["name_ar"] for d in depts}
    by_dept: dict = {}
    for r in latest:
        k = r["department_id"] if r["department_id"] is not None else f"? {r['dept_name']}"
        d = by_dept.setdefault(k, {"department_id": r["department_id"], "name": names.get(r["department_id"], r["dept_name"]),
                                   "raw_name": r["dept_name"], "trainees": 0, "baseline": 0, "programs": []})
        b = base_map.get(key(r))
        d["trainees"] += r["trainees"]
        d["baseline"] += b if b is not None else r["trainees"]
        d["programs"].append({"program": r["program"], "shift": r["shift"], "stage": r["stage"], "trainees": r["trainees"], "baseline": b})
    for d in by_dept.values():
        t = trainers.get(d["department_id"])
        d["trainers"] = t
        d["per_trainer"] = round(d["trainees"] / t, 1) if t else None
        d["platform_count"] = next((x["trainee_count"] for x in depts if x["id"] == d["department_id"]), None)
    shifts: dict[str, int] = {}
    for r in latest:
        shifts[r["shift"] or "—"] = shifts.get(r["shift"] or "—", 0) + r["trainees"]
    total = sum(r["trainees"] for r in latest)
    btotal = sum(r["trainees"] for r in baseline) if baseline else total
    return {**base, "same_snapshot": same, "total": total, "baseline_total": btotal,
            "programs": len({(r["dept_name"], r["program"]) for r in latest}), "departments": len(by_dept),
            "by_shift": shifts, "by_department": sorted(by_dept.values(), key=lambda d: -d["trainees"]),
            "unmatched": sorted({d["raw_name"] for d in by_dept.values() if d["department_id"] is None})}


@router.get("/cycles/{cycle_id}/enrollment")
async def summary(cycle_id: int, user: CurrentUser = Depends(current_user), conn: AsyncConnection = Depends(get_conn, scope="function")):
    cycle = await load_cycle(conn, user, cycle_id)
    return await _summary(conn, user, cycle)


@router.post("/cycles/{cycle_id}/enrollment/apply-counts")
async def apply_counts(cycle_id: int, user: CurrentUser = Depends(current_user), conn: AsyncConnection = Depends(get_conn, scope="function")):
    """اعتماد أعداد ST06 الأحدث عدداً لمتدربي كل قسم في المنصة (بدل الإدخال اليدوي)."""
    cycle = await load_cycle(conn, user, cycle_id)
    _manager(user)
    await conn.execute("SELECT set_config('aqap.user_id', %s, true)", (str(user.id),))
    s = await _summary(conn, user, cycle)
    updated = []
    for d in s.get("by_department", []):
        if d["department_id"] is not None:
            await conn.execute("UPDATE department SET trainee_count = %s, updated_at = now() WHERE id = %s", (d["trainees"], d["department_id"]))
            updated.append(d["name"])
    return {"updated": updated}
