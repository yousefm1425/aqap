"""حماية ملفات Excel/CSV المصدَّرة من «حقن المعادلات» (CSV/Formula Injection).

أي نص يكتبه مستخدم ويبدأ بـ «=» تحوّله openpyxl إلى معادلة تُنفَّذ عند فتح الملف (مثل =HYPERLINK أو أوامر DDE).
- harden(wb): قبل حفظ أي مصنف؛ يُبقي معادلات المنصة نفسها (دوال من قائمة معروفة ومراجع خلايا فقط)،
  ويحوّل أي «معادلة» أخرى إلى نص كما كتبه المستخدم.
- csv_cell(v): لملفات CSV؛ يسبق النص الخطِر بعلامة «'» فيظهر نصاً في Excel.
"""
import re

# الدوال التي تولّدها المنصة في النماذج (forms_xlsx) — أي دالة غيرها في «معادلة» تعني نصاً من مستخدم
ALLOWED_FUNCS = {"IF", "IFERROR", "SUM", "AVERAGE", "PRODUCT", "COUNT", "COUNTA", "COUNTIF", "COUNTIFS", "ROWS",
                 "OR", "AND", "NOT", "ROUND", "MIN", "MAX", "SUMPRODUCT"}
_FUNC = re.compile(r"([A-Za-z_][A-Za-z0-9_.]*)\s*\(")
_DANGER_START = ("=", "+", "-", "@", "\t", "\r")


def trusted_formula(f: str) -> bool:
    body = f[1:] if f.startswith("=") else f
    if any(c in body for c in "|[{") or "://" in body:          # DDE، مراجع ملفات خارجية، روابط
        return False
    stripped = re.sub(r'"[^"]*"', '""', body)                     # النصوص داخل المعادلة لا تُحسب دوالاً
    stripped = re.sub(r"'[^']*'!", "S!", stripped)                # أسماء الأوراق بين علامتي اقتباس
    return all(name.upper() in ALLOWED_FUNCS for name in _FUNC.findall(stripped))


def harden(wb) -> int:
    """يحوّل المعادلات غير الموثوقة في كل أوراق المصنف إلى نص. يعيد عدد الخلايا المعدّلة."""
    fixed = 0
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                if cell.data_type == "f" and isinstance(cell.value, str) and not trusted_formula(cell.value):
                    cell._value, cell.data_type = cell.value, "s"      # يبقى النص كما كتبه، لكن كنص لا معادلة
                    fixed += 1
    return fixed


def csv_cell(v):
    if isinstance(v, str) and v.startswith(_DANGER_START):
        return "'" + v
    return v


def csv_uncell(v: str) -> str:
    """عند استيراد ملف صدّرته المنصة: يزيل علامة الحماية التي أضافها csv_cell."""
    if isinstance(v, str) and len(v) > 1 and v[0] == "'" and v[1:].startswith(_DANGER_START):
        return v[1:]
    return v
