"""يعبّئ قالب «نموذج العمل الشامل» الرسمي (.xlsb) ببيانات المنصة ويحفظه .xlsx.

يعمل في عملية مستقلة (يستدعيه app.export_official) لأنه يشغّل LibreOffice عبر UNO:
    python -m app.export_filler payload.json template.xlsb out.xlsx

لماذا LibreOffice: صيغة xlsb ثنائية ولا توجد مكتبة Python تكتبها، و LibreOffice يفتح القالب كما هو
(الصيغ، القوائم المنسدلة، التنسيق الشرطي، الرسوم) ويعيد حسابه قبل الحفظ.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import date
from pathlib import Path

SHEET_INST = "بيانات المنشأة التدريبية"
STD_SHEETS = [f"المعيار{i}" for i in range(1, 7)]
IMP_SHEET = "تحسين قسم{}"

# أعمدة صفرية الأساس
STD_FIRST_ROW, STD_LAST_ROW, STD_CODE_COL = 5, 70, 3            # D6 فما بعد
STD_SELF_COL, STD_SLOT_WIDTH = 7, 5                              # H، ثم كل قسم +5
INST_NAME_CELL, INST_REGION_CELL = (16, 7), (16, 3)              # Q8، Q4
INST_DEPT_ROW0, INST_DEPT_COL, INST_TRAINERS_COL, INST_TRAINEES_COL = 20, 4, 16, 23   # E21، Q21، X21
IMP_FIRST_ROW, IMP_LAST_ROW = 11, 58                             # الصفوف 12..59
IMP_REQ_COL, IMP_ACTION_COL, IMP_OWNER_COL, IMP_DATE_COL = 8, 32, 48, 52         # I، AG، AW، BA
IMP_EVID_COL, IMP_ADEQ_COL, IMP_NOTES_COL = 56, 59, 62                           # BE، BH، BK


def _code(text) -> str | None:
    if not isinstance(text, str):
        return None
    head = text.strip().split(" ", 1)[0]
    return head if head.count("-") == 2 and head.replace("-", "").isdigit() else None


def _serial(iso: str) -> float:
    return float((date.fromisoformat(iso) - date(1899, 12, 30)).days)


def improvement_rows(dept: dict, order: list[str], stars: dict[str, int]) -> list[str]:
    """قائمة المتطلبات في ورقة «تحسين قسم» كما تولدها صيغ القالب (الأعمدة R و S و T في ورقة المنهجية):
    لا تظهر إلا إذا اكتمل الذاتي والخارجي لكل متطلبات القسم، وتضم بالترتيب الطبيعي كل متطلب
    ذاتيه «جزئي» أو «غير متحقق»، أو «لا ينطبق» دون شرط نجمة ينطبق على القسم، أو خارجيه «غير منطبق/غير كافٍ»."""
    r = dept["ratings"]
    if not all(r.get(c, {}).get("self") and r.get(c, {}).get("ext") for c in order):
        return []
    general = dept["name"] == "الدراسات العامة"
    out = []
    for c in order:
        x = r[c]
        na_ok = (general and stars.get(c) == 1) or stars.get(c) == 2
        if (x["self"] in ("متحقق جزئي", "غير متحقق") or (x["self"] == "لا ينطبق" and not na_ok)
                or x["ext"] in ("غير منطبق", "غير كافٍ")):
            out.append(c)
    return out


class Office:
    """جلسة LibreOffice معزولة (ملف تعريف مؤقت خاص، قناة اتصال خاصة)."""

    def __init__(self) -> None:
        self.profile = Path(tempfile.mkdtemp(prefix="aqap-lo-"))
        self.pipe = f"aqap{uuid.uuid4().hex[:12]}"
        self.proc = subprocess.Popen(
            [shutil.which("soffice") or "soffice", "--headless", "--invisible", "--nologo", "--norestore",
             "--nodefault", f"-env:UserInstallation=file://{self.profile}",
             f"--accept=pipe,name={self.pipe};urp;StarOffice.ComponentContext"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        import uno

        local = uno.getComponentContext()
        resolver = local.ServiceManager.createInstanceWithContext("com.sun.star.bridge.UnoUrlResolver", local)
        last = None
        for _ in range(120):
            try:
                ctx = resolver.resolve(f"uno:pipe,name={self.pipe};urp;StarOffice.ComponentContext")
                break
            except Exception as exc:  # noqa: BLE001 — المكتب لم يبدأ بعد
                last = exc
                time.sleep(0.5)
        else:
            self.close()
            raise RuntimeError(f"تعذّر تشغيل LibreOffice: {last}")
        self.desktop = ctx.ServiceManager.createInstanceWithContext("com.sun.star.frame.Desktop", ctx)

    def close(self) -> None:
        try:
            self.desktop.terminate()
        except Exception:  # noqa: BLE001
            pass
        try:
            self.proc.wait(timeout=20)
        except Exception:  # noqa: BLE001
            self.proc.kill()
        shutil.rmtree(self.profile, ignore_errors=True)


def _prop(name, value):
    import uno
    from com.sun.star.beans import PropertyValue  # type: ignore

    p = PropertyValue()
    p.Name, p.Value = name, value
    return p


def fill(payload: dict, template: str, out: str, verify: bool = False) -> dict:
    import uno

    report = {"ratings_written": 0, "plans_written": 0, "warnings": []}
    office = Office()
    try:
        doc = office.desktop.loadComponentFromURL(uno.systemPathToFileUrl(str(Path(template).resolve())), "_blank", 0,
                                                  (_prop("Hidden", True),))
        sheets = doc.Sheets
        doc.enableAutomaticCalculation(False)     # آلاف الصيغ على أعمدة كاملة؛ Excel يعيد حسابها عند الفتح

        # 1) بيانات المنشأة والأقسام
        inst = sheets.getByName(SHEET_INST)
        if payload.get("institution_name"):
            inst.getCellByPosition(*INST_NAME_CELL).setString(payload["institution_name"])
        if payload.get("region"):
            inst.getCellByPosition(*INST_REGION_CELL).setString(payload["region"])
        for d in payload["departments"]:
            row = INST_DEPT_ROW0 + 2 * (d["slot"] - 1)
            inst.getCellByPosition(INST_DEPT_COL, row).setString(d["name"])
            for col, key in ((INST_TRAINERS_COL, "trainers"), (INST_TRAINEES_COL, "trainees")):
                if d.get(key) is not None:
                    inst.getCellByPosition(col, row).setValue(d[key])

        # 2) التقديرات في أوراق المعايير الست
        found, order, stars = set(), [], {}
        for name in STD_SHEETS:
            sh = sheets.getByName(name)
            for row in range(STD_FIRST_ROW, STD_LAST_ROW):
                text = sh.getCellByPosition(STD_CODE_COL, row).getString()
                code = _code(text)
                if not code:
                    continue
                found.add(code)
                order.append(code)
                # نفس صيغة العمود A في القالب: ".*" ← 1 (غير مطلوب من الدراسات العامة)، "**" ← 2
                stars[code] = 1 if text.rstrip().endswith(".*") else 2 if text.rstrip().endswith("**") else 0
                for d in payload["departments"]:
                    r = d["ratings"].get(code)
                    if not r:
                        continue
                    base = STD_SELF_COL + STD_SLOT_WIDTH * (d["slot"] - 1)
                    for offset, key in ((0, "self"), (1, "ext"), (2, "recommendation")):
                        if r.get(key):
                            sh.getCellByPosition(base + offset, row).setString(r[key])
                    report["ratings_written"] += 1
        missing = sorted(set(payload["requirement_codes"]) - found)
        if missing:
            report["warnings"].append(f"متطلبات في المنصة غير موجودة في القالب: {', '.join(missing[:10])}")

        # 3) خطط التحسين في صفوف ورقة «تحسين قسم» بالترتيب الذي تولده صيغ القالب
        for d in payload["departments"]:
            rows = improvement_rows(d, order, stars)
            unplanned = [c for c in rows if c not in d["plans"]]
            if unplanned:
                report["warnings"].append(f"{d['name']}: {len(unplanned)} متطلب يحتاج خطة وفق قواعد القالب ولا خطة له في المنصة: "
                                          f"{', '.join(unplanned[:8])}")
            if not d["plans"]:
                continue
            sh = sheets.getByName(IMP_SHEET.format(d["slot"]))
            placed = set()
            for i, code in enumerate(rows):
                plan = d["plans"].get(code)
                if not plan:
                    continue
                row = IMP_FIRST_ROW + i
                placed.add(code)
                for col, key in ((IMP_ACTION_COL, "action"), (IMP_OWNER_COL, "owner"),
                                 (IMP_EVID_COL, "evidence"), (IMP_ADEQ_COL, "adequacy"), (IMP_NOTES_COL, "notes")):
                    if plan.get(key):
                        sh.getCellByPosition(col, row).setString(plan[key])
                if plan.get("due_date"):
                    sh.getCellByPosition(IMP_DATE_COL, row).setValue(_serial(plan["due_date"]))
                report["plans_written"] += 1
            skipped = sorted(set(d["plans"]) - placed)
            if skipped:
                why = ("القالب لا يعرض قائمة التحسين قبل اكتمال التقييم الذاتي والخارجي لكل متطلبات القسم"
                       if not rows else "المتطلب لا يحتاج تحسيناً وفق قواعد القالب")
                report["warnings"].append(f"{d['name']}: {len(skipped)} خطة لم تُكتب ({why}): {', '.join(skipped[:8])}")

        if verify:   # للاختبارات: إعادة حساب القالب ومطابقة قائمته مع ترتيبنا
            doc.calculate()
            for d in payload["departments"]:
                sh = sheets.getByName(IMP_SHEET.format(d["slot"]))
                listed = [c for c in (_code(sh.getCellByPosition(IMP_REQ_COL, r).getString())
                                      for r in range(IMP_FIRST_ROW, IMP_LAST_ROW + 1)) if c]
                report.setdefault("verify", {})[d["name"]] = listed == improvement_rows(d, order, stars)
            # نسب «%المتحقق» كما يحسبها القالب (ورقة القوائم: القسم F، المعيار H، النسبة N) — نمط التقييم الذاتي الافتراضي
            lst = sheets.getByName("م2-قائمة")
            pct = []
            for r in range(2, 160):
                dept_name = lst.getCellByPosition(5, r).getString().strip()
                std = lst.getCellByPosition(7, r).getString().strip()
                if dept_name and dept_name != "0" and std:
                    pct.append([dept_name, std, round(lst.getCellByPosition(13, r).getValue() * 100, 1)])
            report["verify_pct"] = pct
        doc.storeToURL(uno.systemPathToFileUrl(str(Path(out).resolve())),
                       (_prop("FilterName", "Calc Office Open XML"), _prop("Overwrite", True)))
        doc.close(True)
    finally:
        office.close()
    _force_recalc_on_open(out)
    return report


def _force_recalc_on_open(path: str) -> None:
    """يطلب من Excel إعادة حساب كل الصيغ عند الفتح، فلا يعتمد الملف على حساب LibreOffice."""
    import re
    import zipfile

    tmp = path + ".tmp"
    with zipfile.ZipFile(path) as src, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename == "xl/workbook.xml":
                xml = data.decode("utf-8")
                if "<calcPr" in xml:
                    xml = re.sub(r"<calcPr([^>]*?)/>", lambda m: "<calcPr" + re.sub(r'\s*fullCalcOnLoad="[^"]*"', "", m.group(1))
                                 + ' fullCalcOnLoad="1"/>', xml, count=1)
                else:
                    xml = xml.replace("</workbook>", '<calcPr fullCalcOnLoad="1"/></workbook>')
                data = xml.encode("utf-8")
            dst.writestr(item, data)
    os.replace(tmp, path)


if __name__ == "__main__":
    payload_path, template, out = sys.argv[1:4]
    result = fill(json.loads(Path(payload_path).read_text(encoding="utf-8")), template, out,
                  verify="--verify" in sys.argv)
    print(json.dumps(result, ensure_ascii=False))
