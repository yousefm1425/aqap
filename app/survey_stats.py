"""قراءة ملف ردود Microsoft Forms المصدَّر (Excel أو CSV) وحساب إحصاءات الاستبيان.

- أعمدة التعريف في بداية الملف (المعرّف، أوقات البدء والإكمال، البريد، الاسم) تُقرأ منها هوية الرد ووقته فقط؛
  البريد والاسم لا يُحفظان أبداً، فتبقى الردود مجهولة الهوية في المنصة.
- نوع كل سؤال يُستنتج من إجاباته: مقياس (موافق بشدة… / ممتاز… / تقييم رقمي)، اختيار، اختيار متعدد، نص مفتوح.
- «نسبة الرضا» = نسبة الإجابات في أعلى درجتين من المقياس (4 و5 من 5)، و«المتوسط» من 5.
"""
from __future__ import annotations

import csv
import io
import re
from datetime import datetime

MAX_ROWS = 20000
MAX_COLS = 200
TEXT_SAMPLE = 40

_TASHKEEL = re.compile(r"[ؐ-ًؚ-ٰٟـ]")
_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)


def norm(s: str) -> str:
    s = _TASHKEEL.sub("", str(s)).strip().lower()
    s = re.sub("[أإآ]", "ا", s).replace("ى", "ي").replace("ة", "ه")
    s = _PUNCT.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


_SCALE_WORDS = {
    5: ["موافق بشده", "اوافق بشده", "ممتاز", "راض جدا", "راضي جدا", "راضيه جدا", "راض تماما", "راضي تماما", "دائما",
        "عالي جدا", "عاليه جدا", "مرتفع جدا", "كبير جدا", "بدرجه كبيره جدا", "strongly agree", "excellent", "very satisfied",
        "always", "very good"],
    4: ["موافق", "اوافق", "جيد جدا", "راض", "راضي", "راضيه", "غالبا", "عالي", "عاليه", "مرتفع", "كبير", "بدرجه كبيره",
        "agree", "satisfied", "often", "good"],
    3: ["محايد", "الي حد ما", "الى حد ما", "جيد", "احيانا", "متوسط", "متوسطه", "بدرجه متوسطه", "neutral", "sometimes",
        "somewhat", "average", "fair"],
    2: ["غير موافق", "لا اوافق", "مقبول", "غير راض", "غير راضي", "نادرا", "منخفض", "منخفضه", "قليل", "بدرجه قليله",
        "disagree", "dissatisfied", "rarely", "poor"],
    1: ["غير موافق بشده", "لا اوافق بشده", "ضعيف", "غير راض اطلاقا", "غير راضي اطلاقا", "غير راض جدا", "غير راضي جدا",
        "ابدا", "منخفض جدا", "منخفضه جدا", "قليل جدا", "بدرجه قليله جدا", "strongly disagree", "very dissatisfied", "never",
        "very poor"],
}
# «جيد» و«good» و«poor» متعارضة بين مقياسَي الرضا والجودة: الجودة (ممتاز/جيد جداً/جيد/مقبول/ضعيف) هي الأشيع في نماذج المؤسسة
SCALE: dict[str, int] = {}
for _score, _words in sorted(_SCALE_WORDS.items()):
    for _w in _words:
        SCALE.setdefault(norm(_w), _score)
SCALE[norm("جيد")] = 3
SCALE[norm("ضعيف")] = 1
SCALE[norm("مقبول")] = 2
SCALE["good"] = 3

# أعمدة التعريف في ملف Microsoft Forms (بالإنجليزية والعربية)
_META = {
    "id": ["id", "المعرف", "معرف", "رقم"],
    "start": ["start time", "وقت البدء", "وقت البدايه"],
    "end": ["completion time", "وقت الاكمال", "وقت الانتهاء", "وقت الاتمام"],
    "email": ["email", "البريد الالكتروني", "البريد", "e mail"],
    "name": ["name", "الاسم"],
    "modified": ["last modified time", "وقت اخر تعديل", "وقت التعديل الاخير", "اخر تعديل"],
}
_META_N = {k: {norm(x) for x in v} for k, v in _META.items()}
_SKIP_PREFIX = ("points ", "feedback ", "total points", "quiz feedback", "النقاط", "الملاحظات", "مجموع النقاط")


class SurveyFileError(ValueError):
    pass


def _rows_from_xlsx(data: bytes) -> list[list]:
    from openpyxl import load_workbook
    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as ex:   # noqa: BLE001 — أي ملف تالف يُرد برسالة واضحة
        raise SurveyFileError("تعذّرت قراءة ملف Excel؛ صدّر الردود من Microsoft Forms («فتح في Excel») وارفعه كما هو") from ex
    ws = wb.worksheets[0]
    out = []
    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if i > MAX_ROWS:
            raise SurveyFileError(f"الملف أكبر من المسموح ({MAX_ROWS} رد)")
        out.append(list(row[:MAX_COLS]))
    wb.close()
    return out


def _rows_from_csv(data: bytes) -> list[list]:
    for enc in ("utf-8-sig", "cp1256"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise SurveyFileError("ترميز ملف CSV غير معروف؛ احفظه بترميز UTF-8")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    rows = []
    for i, r in enumerate(csv.reader(io.StringIO(text), dialect)):
        if i > MAX_ROWS:
            raise SurveyFileError(f"الملف أكبر من المسموح ({MAX_ROWS} رد)")
        rows.append(r[:MAX_COLS])
    return rows


def _cell(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    if isinstance(v, datetime):
        return v.isoformat()
    return str(v).strip()


def _when(v) -> str | None:
    if isinstance(v, datetime):
        return v.isoformat()
    s = _cell(v)
    for fmt in ("%m/%d/%y %H:%M:%S", "%m/%d/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M:%S", "%m/%d/%y %H:%M",
                "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).isoformat()
        except ValueError:
            continue
    return None


def parse_responses(filename: str, data: bytes) -> tuple[list[str], list[dict]]:
    """يعيد (نصوص الأسئلة، الردود) حيث الرد = {ext_id, submitted_at, answers: [نص لكل سؤال]}."""
    name = (filename or "").lower()
    if name.endswith((".xlsx", ".xlsm")):
        rows = _rows_from_xlsx(data)
    elif name.endswith((".csv", ".txt")):
        rows = _rows_from_csv(data)
    else:
        raise SurveyFileError("ارفع ملف Excel (.xlsx) أو CSV مصدَّراً من Microsoft Forms")
    rows = [r for r in rows if any(_cell(c) for c in r)]
    if len(rows) < 1:
        raise SurveyFileError("الملف فارغ")
    header = [_cell(c) for c in rows[0]]
    roles: dict[int, str] = {}
    for i, hcell in enumerate(header[:8]):                 # أعمدة التعريف في بداية الملف فقط
        n = norm(hcell)
        for key, names in _META_N.items():
            if n in names and key not in roles.values():
                roles[i] = key
                break
    qcols = [i for i, hcell in enumerate(header)
             if i not in roles and hcell and not norm(hcell).startswith(tuple(norm(p) for p in _SKIP_PREFIX))]
    if not qcols:
        raise SurveyFileError("لم أجد أعمدة أسئلة في الملف؛ تأكد أن الصف الأول عناوين الأسئلة كما يصدّرها Microsoft Forms")
    id_col = next((i for i, k in roles.items() if k == "id"), None)
    when_col = next((i for i, k in roles.items() if k == "end"), None)
    if when_col is None:
        when_col = next((i for i, k in roles.items() if k == "start"), None)
    responses, seen = [], set()
    for n, r in enumerate(rows[1:], 1):
        r = list(r) + [None] * (len(header) - len(r))
        ext = _cell(r[id_col]) if id_col is not None else ""
        ext = ext or f"row-{n}"
        if ext in seen:
            continue
        seen.add(ext)
        answers = [_cell(r[i])[:4000] for i in qcols]
        if not any(answers):
            continue
        responses.append({"ext_id": ext[:100], "submitted_at": _when(r[when_col]) if when_col is not None else None,
                          "answers": answers})
    if not responses:
        raise SurveyFileError("لا توجد ردود في الملف")
    return [header[i][:500] for i in qcols], responses


def _split_multi(v: str) -> list[str]:
    return [p.strip() for p in v.split(";") if p.strip()]


_TEXT_HINT = re.compile(r"ملاحظ|مقترح|اقتراح|تعليق|اذكر|وضح|comment|suggest|feedback|remark", re.I)


def classify(values: list[str], header: str = "") -> str:
    vals = [v for v in values if v]
    if not vals:
        return "empty"
    mapped = sum(1 for v in vals if norm(v) in SCALE)
    if mapped / len(vals) >= 0.9:
        return "scale"
    if all(re.fullmatch(r"\d{1,2}", v) for v in vals):
        nums = [int(v) for v in vals]
        if min(nums) >= 0 and max(nums) <= 10:
            return "rating"
    if sum(1 for v in vals if v.endswith(";")) / len(vals) >= 0.6:
        return "multi"
    distinct = len(set(vals))
    if _TEXT_HINT.search(norm(header)) or sum(len(v) for v in vals) / len(vals) > 60:
        return "text"
    if distinct <= 15 and (distinct < len(vals) or len(vals) <= 2) and (distinct <= 4 or distinct <= len(vals) * 0.5):
        return "choice"
    return "text"


def _scale_stats(vals: list[str], kind: str) -> dict:
    if kind == "scale":
        scores = [(v, SCALE[norm(v)]) for v in vals if norm(v) in SCALE]
        top = 5
    else:
        scores = [(v, int(v)) for v in vals]
        top = 5 if max(s for _, s in scores) <= 5 else 10
    counts: dict[str, dict] = {}
    for label, s in scores:
        c = counts.setdefault(label, {"label": label, "score": s, "count": 0})
        c["count"] += 1
    n = len(scores)
    mean = sum(s for _, s in scores) / n
    good = sum(1 for _, s in scores if s >= (4 if top == 5 else 8))
    bad = sum(1 for _, s in scores if s <= (2 if top == 5 else 4))
    options = sorted(counts.values(), key=lambda c: (-c["score"], c["label"]))
    for o in options:
        o["pct"] = round(o["count"] * 100 / n, 1)
    return {"n": n, "max": top, "mean": round(mean, 2), "mean5": round(mean * 5 / top, 2),
            "satisfied_pct": round(good * 100 / n, 1), "dissatisfied_pct": round(bad * 100 / n, 1), "options": options}


def _counts(vals: list[str], multi: bool, base: int) -> list[dict]:
    counts: dict[str, int] = {}
    for v in vals:
        for p in (_split_multi(v) if multi else [v]):
            counts[p] = counts.get(p, 0) + 1
    return [{"label": k, "count": c, "pct": round(c * 100 / base, 1) if base else 0}
            for k, c in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]


def level(pct: float | None) -> str | None:
    if pct is None:
        return None
    return "ممتاز" if pct >= 90 else "جيد جداً" if pct >= 80 else "جيد" if pct >= 70 else "مقبول" if pct >= 60 else "يحتاج تحسيناً"


def compute(questions: list[str], responses: list[list[str]], filter_q: int | None = None,
            filter_v: str | None = None) -> dict:
    """الإحصاءات لكل سؤال، مع تصفية اختيارية بقيمة سؤال اختيار (مثل الفئة أو القسم)."""
    all_types = [classify([r[i] if i < len(r) else "" for r in responses], q) for i, q in enumerate(questions)]
    filters = []
    for i, kind in enumerate(all_types):
        if kind in ("choice", "multi"):
            opts = _counts([r[i] for r in responses if i < len(r) and r[i]], kind == "multi", 1)
            filters.append({"index": i, "text": questions[i], "values": [o["label"] for o in opts]})
    if filter_q is not None and 0 <= filter_q < len(questions) and filter_v is not None:
        responses = [r for r in responses if filter_q < len(r) and
                     (filter_v in _split_multi(r[filter_q]) if all_types[filter_q] == "multi" else r[filter_q] == filter_v)]
    total = len(responses)
    out, pooled = [], []
    for i, q in enumerate(questions):
        vals = [r[i] for r in responses if i < len(r) and r[i]]
        kind = all_types[i]
        item: dict = {"index": i, "text": q, "type": kind, "answered": len(vals)}
        if kind in ("scale", "rating") and vals:
            try:
                st = _scale_stats(vals, kind)
            except (ValueError, KeyError):
                st = None
            if st:
                item.update(st)
                item["level"] = level(st["satisfied_pct"])
                pooled.append(st)
        elif kind in ("choice", "multi"):
            item["options"] = _counts(vals, kind == "multi", len(vals))
        elif kind == "text":
            item["samples"] = vals[-TEXT_SAMPLE:][::-1]
        out.append(item)
    n_scale = sum(p["n"] for p in pooled)
    overall = None
    if n_scale:
        sat = sum(p["satisfied_pct"] * p["n"] for p in pooled) / n_scale
        mean5 = sum(p["mean5"] * p["n"] for p in pooled) / n_scale
        overall = {"satisfied_pct": round(sat, 1), "mean5": round(mean5, 2), "level": level(sat),
                   "scale_questions": len(pooled)}
    ranked = sorted((q for q in out if "satisfied_pct" in q), key=lambda q: q["satisfied_pct"])
    return {"responses": total, "overall": overall, "questions": out,
            "filters": filters,
            "weakest": [{"index": q["index"], "text": q["text"], "satisfied_pct": q["satisfied_pct"]} for q in ranked[:3]],
            "strongest": [{"index": q["index"], "text": q["text"], "satisfied_pct": q["satisfied_pct"]}
                          for q in ranked[::-1][:3]]}
