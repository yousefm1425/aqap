"""محرّك النماذج الإلكترونية: تحقق البيانات حسب القالب، ودمج التخطيط بالمتابعة، وحساب الصيغ.

تخزين بيانات النموذج:
- plan_data:   {section: ...} لما مرحلته «تخطيط».
    جدول: [{"id": "...", <أعمدة التخطيط>}]   حقول: {key: value}   نص: "..."
- follow_data: {section: ...} لما مرحلته «متابعة».
    جدول بمرحلة مختلطة: {row_id: {<أعمدة المتابعة>}}   جدول متابعة كامل: [{"id", ...}]   حقول/نص كما سبق.
الجداول ذات الصفوف الثابتة (fixed_rows) تُنشأ من القالب ولا تُضاف صفوفها أو تُحذف.

الصيغ نفسها منفّذة في frontend/js/formcalc.js، واختبار التطابق في tests/test_forms.py.
"""
from __future__ import annotations

import math
import re
import uuid
from typing import Any

SRC_RE = re.compile(r"^[a-z0-9_]{1,40}:[A-Za-z0-9_-]{1,40}$")
ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,24}$")
MAX_TEXT = 4000
DONE, PARTIAL, NOT_DONE = "مُنفذ", "مُنفذ جزئي", "لم يُنفذ"
REMOVED_OPTIONS = {"مؤجل / ملغى بقرار"}           # خيار أُلغي: يُعامل كفارغ إن وُجد في بيانات محفوظة
REASON_KEYS = ("obstacles", "reasons", "challenges", "notes")      # أعمدة سبب عدم التنفيذ أو المسوّغ


class FormError(ValueError):
    """خطأ في بيانات النموذج برسالة عربية تُعرض للمستخدم."""


# ---------------------------------------------------------------------------
# أدوات القالب
# ---------------------------------------------------------------------------
def table_phase(section: dict) -> str:
    """'follow' إن كان الجدول كله متابعة (صفوفه تُضاف بعد الاعتماد)، وإلا 'mixed'."""
    return "follow" if section.get("phase") == "follow" else "mixed"


def input_cols(section: dict) -> list[dict]:
    return [c for c in section["columns"] if c["type"] != "computed"]


def _num(v: Any) -> float | None:
    if v is None or v == "" or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v) if math.isfinite(v) else None
    try:
        f = float(str(v).strip().replace("٫", ".").replace(",", "").translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")))
        return f if math.isfinite(f) else None
    except ValueError:
        return None


def _empty(v: Any) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


def _clean_value(c: dict, v: Any, where: str) -> Any:
    if _empty(v):
        return None
    t = c["type"]
    if t == "number":
        n = _num(v)
        if n is None:
            raise FormError(f"{where}: «{c['label']}» يجب أن يكون رقماً")
        if "min" in c and n < c["min"] or "max" in c and n > c["max"]:
            raise FormError(f"{where}: «{c['label']}» خارج المدى المسموح ({c.get('min', '')}–{c.get('max', '')})")
        return int(n) if n.is_integer() else n
    s = str(v).strip()
    if len(s) > MAX_TEXT:
        raise FormError(f"{where}: «{c['label']}» أطول من المسموح")
    if t == "select" and s in REMOVED_OPTIONS:
        return None
    if t == "select" and s not in c["options"]:
        raise FormError(f"{where}: قيمة غير مسموحة في «{c['label']}»")
    if t == "url" and not re.match(r"^https?://\S+$", s):
        raise FormError(f"{where}: «{c['label']}» يجب أن يكون رابطاً يبدأ بـ https://")
    return s


def _row_id(r: dict) -> str:
    rid = r.get("id")
    if isinstance(rid, str) and ID_RE.match(rid):
        return rid
    return uuid.uuid4().hex[:10]


def _clean_rows(section: dict, rows: Any, phase: str, title: str) -> list[dict]:
    if rows is None:
        rows = []
    if not isinstance(rows, list):
        raise FormError(f"«{title}»: صيغة الجدول غير صحيحة")
    if len(rows) > section.get("max_rows", 100):
        raise FormError(f"«{title}»: تجاوز الحد الأعلى للصفوف ({section.get('max_rows', 100)})")
    cols = [c for c in input_cols(section) if c["phase"] == phase and not c.get("fixed")]
    out, seen = [], set()
    for i, r in enumerate(rows, 1):
        if not isinstance(r, dict):
            raise FormError(f"«{title}»: صف غير صالح")
        rid = _row_id(r)
        if rid in seen:
            rid = uuid.uuid4().hex[:10]
        seen.add(rid)
        clean = {"id": rid}
        if isinstance(r.get("_src"), str) and SRC_RE.match(r["_src"]):
            clean["_src"] = r["_src"]                     # صف خطة تحسين مولّد من مهمة غير منفذة
        for c in cols:
            clean[c["key"]] = _clean_value(c, r.get(c["key"]), f"«{title}» صف {i}")
        out.append(clean)
    return out


def _fixed_plan_rows(section: dict) -> list[dict]:
    return [{"id": fr["id"]} for fr in section["fixed_rows"]]


# ---------------------------------------------------------------------------
# التحقق
# ---------------------------------------------------------------------------
def clean_plan(schema: dict, plan: Any) -> dict:
    plan = plan if isinstance(plan, dict) else {}
    out: dict = {}
    for s in schema["sections"]:
        k, t, title = s["key"], s["type"], s.get("title", s["key"])
        if t == "table" and table_phase(s) == "mixed":
            if s.get("fixed_rows"):
                given = {r.get("id"): r for r in (plan.get(k) or []) if isinstance(r, dict)}
                rows = [{**given.get(fr["id"], {}), "id": fr["id"]} for fr in s["fixed_rows"]]
                out[k] = _clean_rows(s, rows, "plan", title)
            else:
                out[k] = _clean_rows(s, plan.get(k), "plan", title)
        elif t == "fields":
            vals = plan.get(k) if isinstance(plan.get(k), dict) else {}
            out[k] = {c["key"]: _clean_value(c, vals.get(c["key"]), f"«{title}»") for c in s["fields"] if c["phase"] == "plan"}
        elif t == "text" and s.get("phase", "plan") == "plan":
            out[k] = _clean_value({"type": "longtext", "label": title}, plan.get(k), f"«{title}»")
    return out


def clean_follow(schema: dict, plan: dict, follow: Any) -> dict:
    follow = follow if isinstance(follow, dict) else {}
    out: dict = {}
    for s in schema["sections"]:
        k, t, title = s["key"], s["type"], s.get("title", s["key"])
        if t == "table" and table_phase(s) == "follow":
            out[k] = _clean_rows(s, follow.get(k), "follow", title)
        elif t == "table":
            fcols = [c for c in input_cols(s) if c["phase"] == "follow"]
            if not fcols:
                continue
            given = follow.get(k) if isinstance(follow.get(k), dict) else {}
            ids = [r["id"] for r in plan.get(k, [])] or [fr["id"] for fr in s.get("fixed_rows", [])]
            out[k] = {}
            for i, rid in enumerate(ids, 1):
                vals = given.get(rid) if isinstance(given.get(rid), dict) else {}
                row = {c["key"]: _clean_value(c, vals.get(c["key"]), f"«{title}» صف {i}") for c in fcols}
                if any(v is not None for v in row.values()):
                    out[k][rid] = row
        elif t == "fields":
            vals = follow.get(k) if isinstance(follow.get(k), dict) else {}
            fields = [c for c in s["fields"] if c["phase"] == "follow"]
            if fields:
                out[k] = {c["key"]: _clean_value(c, vals.get(c["key"]), f"«{title}»") for c in fields}
        elif t == "text" and s.get("phase") == "follow":
            out[k] = _clean_value({"type": "longtext", "label": title}, follow.get(k), f"«{title}»")
    sync_improvements(schema, plan, out)
    return out


# ---------------------------------------------------------------------------
# خطط التحسين التلقائية: كل مهمة «لم يُنفذ» أو «مُنفذ جزئي» تظهر في «التوصيات وخطط التحسين»
# ---------------------------------------------------------------------------
NEEDS_PLAN = (NOT_DONE, PARTIAL)          # حالتا التنفيذ اللتان تولّدان خطة تحسين
LABEL_KEYS = ("task", "initiative", "item", "activity", "title", "program", "name", "course", "workshop", "subject")
_AUTO_FILLED = ("action", "date", "owner", "evidence", "status", "obstacles", "solutions")


def _status_col(section: dict) -> dict | None:
    return next((c for c in section.get("columns", []) if c["type"] == "select" and set(NEEDS_PLAN) <= set(c.get("options", []))), None)


def _label(section: dict, row: dict) -> str:
    cols = [c for c in section["columns"] if c["type"] in ("longtext", "text") and c["key"] not in ("owner", "date", "mechanism")]
    for k in LABEL_KEYS + tuple(c["key"] for c in cols):
        v = row.get(k)
        if not _empty(v):
            return " ".join(str(v).split())[:220]
    return "مهمة بلا عنوان"


def sync_improvements(schema: dict, plan: dict, follow: dict) -> None:
    imp = next((s for s in schema["sections"] if s["key"] == "improvements"), None)
    if imp is None:
        return
    pending: dict[str, str] = {}                                   # _src → نص التوصية
    for s in schema["sections"]:
        if s["type"] != "table" or s["key"] == "improvements":
            continue
        sc = _status_col(s)
        if sc is None:
            continue
        for row in merged_rows(s, plan, follow):
            st = row.get(sc["key"])
            if st in NEEDS_PLAN:
                why = next((" ".join(str(row[k]).split()) for k in REASON_KEYS if not _empty(row.get(k))), None)
                pending[f"{s['key']}:{row['id']}"] = (f"استكمال تنفيذ ({st}): {_label(s, row)} — "
                                                      + (f"سبب عدم التنفيذ: {why[:200]}" if why else "حدّد سبب عدم التنفيذ ثم الإجراء التصحيحي الذي يعالجه"))
    rows = follow.get("improvements") or []
    have = {r.get("_src") for r in rows if r.get("_src")}
    kept = []
    for r in rows:
        src = r.get("_src")
        untouched = all(_empty(r.get(k)) for k in _AUTO_FILLED)
        if src and src not in pending and untouched:
            continue                                               # نُفذت المهمة ولم يُعمل على التوصية: تُزال
        if src and src in pending and untouched:
            r["recommendation"] = pending[src]                     # تحديث النص إن تغيّرت الحالة أو المهمة
        kept.append(r)
    for src, text in pending.items():
        if src not in have and len(kept) < imp.get("max_rows", 30):
            kept.append({"id": uuid.uuid4().hex[:10], "_src": src, "recommendation": text,
                         **{c["key"]: None for c in input_cols(imp) if c["key"] != "recommendation"}})
    follow["improvements"] = kept


def empty_plan(schema: dict) -> dict:
    out: dict = {}
    for s in schema["sections"]:
        if s["type"] == "table" and table_phase(s) == "mixed":
            out[s["key"]] = _fixed_plan_rows(s) if s.get("fixed_rows") else []
    return clean_plan(schema, out)


def missing_for_submit(schema: dict, plan: dict, follow: dict) -> list[str]:
    """ما ينقص النموذج قبل رفعه للاعتماد (حقول التخطيط الإلزامية والحد الأدنى للصفوف)."""
    msgs: list[str] = []
    for s in schema["sections"]:
        title = s.get("title", s["key"])
        if s["type"] == "table":
            rows = merged_rows(s, plan, follow)
            if len(rows) < s.get("min_rows", 0):
                msgs.append(f"«{title}»: أضف صفاً واحداً على الأقل")
            req = [c for c in input_cols(s) if c.get("required") and not c.get("fixed")
                   and (c["phase"] == "plan" or table_phase(s) == "follow")]
            for i, r in enumerate(rows, 1):
                miss = [c["label"] for c in req if _empty(r.get(c["key"]))]
                if miss:
                    msgs.append(f"«{title}» صف {i}: أكمل {('، '.join(miss))}")
        elif s["type"] == "fields":
            vals = plan.get(s["key"], {})
            miss = [c["label"] for c in s["fields"] if c.get("required") and c["phase"] == "plan" and _empty(vals.get(c["key"]))]
            if miss:
                msgs.append(f"«{title}»: أكمل {('، '.join(miss))}")
    return msgs[:12]


# ---------------------------------------------------------------------------
# الدمج والحساب
# ---------------------------------------------------------------------------
def merged_rows(section: dict, plan: dict, follow: dict) -> list[dict]:
    k = section["key"]
    if table_phase(section) == "follow":
        return [dict(r) for r in (follow.get(k) or [])]
    fixed = {fr["id"]: fr for fr in section.get("fixed_rows", [])}
    fmap = follow.get(k) or {}
    rows = []
    for r in plan.get(k) or []:
        row = {**fixed.get(r["id"], {}), **r, **(fmap.get(r["id"]) or {})}
        rows.append(row)
    return rows


def _round_half_up(x: float) -> int:
    return int(math.floor(x + 0.5)) if x >= 0 else -int(math.floor(-x + 0.5))


def eval_row(expr: dict, row: dict) -> Any:
    op = expr["op"]
    if op == "ratio":
        a, b = _num(row.get(expr["a"])), _num(row.get(expr["b"]))
        return None if a is None or not b else a / b
    if op == "sumratio":
        nums = [_num(row.get(x)) for x in expr["num"]]
        dens = [_num(row.get(x)) for x in expr["den"]]
        if all(n is None for n in nums):
            return None
        d = sum(x for x in dens if x is not None)
        return None if not d else sum(x for x in nums if x is not None) / d
    if op == "mul":
        m = expr.get("map")
        vals = [_num(m.get(row.get(x)) if m else row.get(x)) for x in expr["of"]]
        if any(v is None for v in vals):
            return None
        out = 1.0
        for v in vals:
            out *= v
        return out
    if op == "add":
        vals = [n for n in (_num(row.get(x)) for x in expr["of"]) if n is not None]
        return sum(vals) if vals else None
    if op == "sub":
        a, b = _num(row.get(expr["a"])), _num(row.get(expr["b"]))
        return None if a is None or b is None else a - b
    if op == "avg":
        vals = [n for n in (_num(row.get(x)) for x in expr["of"]) if n is not None]
        return sum(vals) / len(vals) if vals else None
    if op == "band":
        v = _num(row.get(expr["of"]))
        if v is None:
            return None
        if expr.get("trunc"):
            v = float(math.trunc(v))
        for lo, hi, label in expr["bands"]:
            if v >= lo and (hi is None or v < hi):
                return label
        return None
    if op == "map":
        return expr["map"].get(row.get(expr["of"]))
    raise FormError(f"صيغة غير معروفة: {op}")


def _match(row: dict, cond: dict) -> bool:
    for k, v in cond.items():
        if isinstance(v, list):
            if row.get(k) not in v:
                return False
        elif row.get(k) != v:
            return False
    return True


def eval_summary(expr: dict, rows: list[dict], tables: dict | None = None) -> Any:
    op = expr["op"]
    if op == "count_filled_any":
        return sum(1 for r in rows if any(not _empty(r.get(c)) for c in expr["cols"]))
    if op == "ratio_filled":
        den = [r for r in rows if any(not _empty(r.get(c)) for c in expr["den"])]
        return None if not den else sum(1 for r in den if not _empty(r.get(expr["num"]))) / len(den)
    if op == "avg_cells":
        vals = [n for n in (_num(r.get(c)) for r in rows for c in expr["cols"]) if n is not None]
        return None if not vals else sum(vals) / len(vals) * expr.get("scale", 1)
    if op == "band_of":
        v = eval_summary(expr["of"], rows, tables)
        if v is None:
            return None
        for lo, hi, label in expr["bands"]:
            if v >= lo and (hi is None or v < hi):
                return label
        return None
    if op == "count_match":
        return sum(1 for r in rows if _match(r, expr["match"]))
    if op == "ratio_match":
        den = sum(1 for r in rows if _match(r, expr["den"]))
        return None if not den else sum(1 for r in rows if _match(r, expr["num"])) / den
    if op in ("per_lookup", "per_sum"):
        n = sum(1 for r in rows if _match(r, expr["match"]))
        other = (tables or {}).get(expr["table"], [])
        if op == "per_sum":
            d = sum(x for x in (_num(r.get(expr["col"])) for r in other) if x is not None)
        else:
            hit = next((r for r in other if (r.get(expr["key"]) or "").strip() == expr["_group"]), None)
            d = _num(hit.get(expr["col"])) if hit else None
        return None if not d else n / d
    if op == "status_pct":
        col = expr["col"]
        done = sum(1 for r in rows if r.get(col) == DONE)
        part = sum(1 for r in rows if r.get(col) == PARTIAL)
        nd = sum(1 for r in rows if r.get(col) == NOT_DONE)
        den = len(rows) if expr.get("denominator") == "rows" else done + part + nd
        return None if not den else (done + 0.5 * part) / den
    if op == "sum":
        vals = [n for n in (_num(r.get(expr["col"])) for r in rows) if n is not None]
        return sum(vals) if vals else None
    if op == "ratio_sums":
        if expr.get("where"):
            rows = [r for r in rows if r.get(expr["where"]) in expr["in"]]
        nums = [n for n in (_num(r.get(expr["num"])) for r in rows) if n is not None]
        d = sum(n for n in (_num(r.get(expr["den"])) for r in rows) if n is not None)
        return None if not nums or not d else sum(nums) / d
    if op == "avg":
        vals = [n for n in (_num(r.get(expr["col"])) for r in rows) if n is not None]
        return sum(vals) / len(vals) if vals else None
    if op == "count":
        return len(rows)
    if op == "count_eq":
        return sum(1 for r in rows if r.get(expr["col"]) == expr["eq"])
    if op == "share_eq":
        cells = [r.get(c) for r in rows for c in expr["cols"]]
        if expr.get("denominator") == "filled":
            cells = [v for v in cells if not _empty(v)]
        return None if not cells else sum(1 for v in cells if v == expr["eq"]) / len(cells)
    if op == "share_nonempty":
        return None if not rows else sum(1 for r in rows if not _empty(r.get(expr["col"]))) / len(rows)
    if op == "avg_where":
        sel = [r for r in rows if r.get(expr["where"]) in expr["in"]]
        return None if not sel else sum(_num(r.get(expr["col"])) or 0 for r in sel) / len(sel)
    raise FormError(f"صيغة غير معروفة: {op}")


def _pivot(section: dict, tables: dict[str, list[dict]]) -> list[dict]:
    src = tables.get(section["source"], [])
    key = section["group_by"]
    order: list[str] = []
    groups: dict[str, list[dict]] = {}
    for r in src:
        g = (r.get(key) or "").strip() if isinstance(r.get(key), str) else r.get(key)
        if _empty(g):
            continue
        if g not in groups:
            order.append(g)
            groups[g] = []
        groups[g].append(r)
    out = []
    for g in order:
        rows = groups[g]
        vals: dict = {}
        for c in section["columns"]:
            e = c["expr"]
            if c.get("requires") and all(_empty(r.get(c["requires"])) for r in rows):
                vals[c["key"]] = None                       # لا بيانات لهذا الفصل بعد
            elif e["op"] == "per_ratio":
                other = next((r for r in tables.get(e["table"], []) if (r.get(e["key"]) or "").strip() == g), None)
                n = _num(other.get(e["col"])) if other else None
                vals[c["key"]] = None if n is None else f"1 : {_round_half_up(n / len(rows))}"
            else:
                vals[c["key"]] = eval_summary({**e, "_group": g} if e["op"] == "per_lookup" else e, rows, tables)
        out.append({"group": g, "count": len(rows), "values": vals})
    return out


def compute(schema: dict, plan: dict, follow: dict) -> dict:
    """الحسابات كاملة: صفوف الجداول مدموجة مع أعمدتها المحسوبة، وملخصات الجداول، والجداول المحورية، ومؤشر التقدم."""
    tables: dict[str, list[dict]] = {}
    summaries: dict[str, dict] = {}
    for s in schema["sections"]:
        if s["type"] != "table":
            continue
        rows = merged_rows(s, plan, follow)
        for r in rows:
            for c in s["columns"]:
                if c["type"] == "computed":
                    r[c["key"]] = eval_row(c["expr"], r)
        tables[s["key"]] = rows
    for s in schema["sections"]:                         # الملخصات بعد اكتمال الجداول (قد تشير إلى جدول آخر)
        if s["type"] == "table" and s.get("summary"):
            summaries[s["key"]] = {m["key"]: eval_summary(m["expr"], tables[s["key"]], tables) for m in s["summary"]}
    pivots = {s["key"]: _pivot(s, tables) for s in schema["sections"] if s["type"] == "pivot"}
    prog = schema.get("progress")
    progress = summaries.get(prog["section"], {}).get(prog["summary"]) if prog else None
    imp = summaries.get("improvements", {}).get("improvement_pct")
    return {"tables": tables, "summaries": summaries, "pivots": pivots,
            "progress": progress, "improvement_pct": imp,
            "rows": sum(len(v) for k, v in tables.items() if k != "improvements"),
            "improvements": len(tables.get("improvements", []))}


def summary_record(result: dict) -> dict:
    """ما يُحفظ في form_record.summary للقوائم واللوحات."""
    return {"progress": result["progress"], "improvement_pct": result["improvement_pct"],
            "rows": result["rows"], "improvements": result["improvements"]}
