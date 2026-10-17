"""قوالب النماذج الإلكترونية للمعيار الأول (القيادة الإدارية) — مفرّغة من بيانات الأقسام.

كل قالب يصف أقسام النموذج كما في ملف Excel الرسمي: جداول بأعمدة (تخطيط أو متابعة)، وأعمدة محسوبة بنفس صيغ الملف،
وملخصات، وجدول «التوصيات وخطط التحسين» الموحّد الذي يُضاف لكل نموذج تلقائياً.

- phase = "plan": يُعبأ في المسودة ويُقفل بالاعتماد.
- phase = "follow": المتحقق وحالة التنفيذ والمعوقات؛ يبقى مفتوحاً بعد الاعتماد طوال الدورة.
- الصيغ تعبيرات JSON يحسبها app/forms_engine.py وfrontend/js/formcalc.js بالنتيجة نفسها.
"""
from __future__ import annotations

FRAMEWORK = "TVTC-TQ-L2"

STATUS = ["مُنفذ", "مُنفذ جزئي", "لم يُنفذ"]
SEMESTERS = ["الأول", "الثاني"]
WEEKS = ["الأول", "الثاني", "الثالث", "الرابع", "الخامس", "السادس", "السابع", "الثامن", "التاسع", "العاشر",
         "الحادي عشر", "الثاني عشر", "الثالث عشر", "الرابع عشر", "الخامس عشر", "السادس عشر", "السابع عشر",
         "الثامن عشر", "التاسع عشر"]
TRAINER_STATUS = ["غير مفرغ وغير مجاز", "مفرغ", "مفرغ جزئياً", "مجاز", "مكلف خارج المنشأة"]
YES_NO = ["نعم", "لا"]

# مؤشرات الأداء التشغيلية الواردة في خطة المبادرات (مؤشرات المؤسسة، لا تخص قسماً) — اقتراحات قابلة للتعديل
OPERATIONAL_KPIS = [
    "نسبة المدربين المستفيدين من ورش العمل والزيارات التبادلية (%)", "نسبة المدرب للمتدرب",
    "معدل التوظيف خلال 6 شهور من التخرج (%)", "عدد الخريجين (#)", "معدل التسرب للمتدربين (%)", "معدل التعثر",
    "متوسط المعدل التراكمي GPA لمتدربي المنشأة التدريبية (#)",
    "عدد المتدربين المشاركين في الأعمال التطوعية والبرامج والفعاليات", "نسبة التزام المتدرب بالخطة (%)",
    "معدل الرضا الكلي للمتدربين (%)", "عدد المبتكرين والأفكار الإبداعية المطروحة من قبل المنسوبين", "عدد المقبولين",
    "معدل تطبيق معايير الأمن والسلامة بالمنشأة التدريبية (%)", "نسبة إشغال المقاعد التدريبية (#)",
    "نسبة المقبولين للمتقدمين (%)", "معدل إشغال المرافق (%)", "متوسط النصاب التدريبي",
]
OWNERS = ["رئيس القسم", "نائب رئيس القسم", "منسق الجودة", "منسق الجداول", "المرشد التدريبي", "مسجلي القسم",
          "أمين القسم", "مشرف الجداول", "مشرف الأنشطة", "مشرف المعامل", "مدربي المقررات", "الفريق الإعلامي"]


def col(key, label, type_="text", phase="plan", **kw) -> dict:
    return {"key": key, "label": label, "type": type_, "phase": phase, **kw}


def comp(key, label, expr, fmt="pct", **kw) -> dict:
    return {"key": key, "label": label, "type": "computed", "expr": expr, "format": fmt, **kw}


STATUS_COL = col("status", "متابعة التنفيذ", "select", "follow", options=STATUS, group="المتابعة")

# جدول «التوصيات وخطط التحسين» الموحّد (ورقة نموذج خطط التحسين في كل ملف)
IMPROVEMENTS = {
    "key": "improvements", "type": "table", "title": "التوصيات وخطط التحسين", "phase": "follow", "max_rows": 30,
    "help": "لكل توصية تحسين: الإجراء التصحيحي، وتاريخ ومسؤول التنفيذ، وشاهد التحسين، والإنجاز. "
            "نسبة التحسين = (مُنفذ + نصف المُنفذ جزئياً) ÷ عدد التوصيات المدخلة.",
    "columns": [
        col("recommendation", "توصية التحسين", "longtext", "follow", required=True),
        col("action", "الإجراء التصحيحي", "longtext", "follow"),
        col("date", "تاريخ التنفيذ", "text", "follow"),
        col("owner", "مسؤول التنفيذ", "text", "follow", suggest=OWNERS),
        col("evidence", "شاهد التحسين (رابط)", "url", "follow"),
        col("status", "الإنجاز", "select", "follow", options=STATUS),
        col("obstacles", "المعوقات والتحديات", "longtext", "follow"),
        col("solutions", "الحلول المقترحة", "longtext", "follow"),
    ],
    "summary": [{"key": "improvement_pct", "label": "نسبة التحسين", "format": "pct",
                 "expr": {"op": "status_pct", "col": "status", "denominator": "rows"}}],
}


def executive_plan(title: str, target_numeric: bool, target_suggest: list[str] | None = None) -> dict:
    """«نموذج خطة تنفيذية سنوية» المشترك بين 1-3-2 و1-4-1."""
    if target_numeric:
        target = col("target", "المستهدف", "number", required=True, group="التخطيط")
        achieved = col("achieved", "المتحقق", "number", "follow", group="المتابعة")
    else:
        target = col("target", "المستهدف", "text", required=True, suggest=target_suggest or [], group="التخطيط")
        achieved = col("achieved", "المتحقق", "text", "follow", group="المتابعة")
    columns = [
        col("semester", "الفصل", "select", options=SEMESTERS, required=True, group="التخطيط"),
        col("week", "الأسبوع", "select", options=WEEKS, group="التخطيط"),
        col("task", "المهمة", "longtext", required=True, group="التخطيط"),
        target,
        col("mechanism", "آلية التنفيذ", "longtext", group="التخطيط"),
        col("owner", "مسؤول التنفيذ", "text", required=True, suggest=OWNERS, group="التخطيط"),
        col("date", "تاريخ التنفيذ", "text", group="التخطيط"),
        col("status", "حالة التنفيذ", "select", "follow", options=STATUS, group="المتابعة"),
        achieved,
    ]
    summary = [{"key": "execution_pct", "label": "نسبة التنفيذ", "format": "pct",
                "expr": {"op": "status_pct", "col": "status", "denominator": "status"}}]
    if target_numeric:
        columns.append(comp("ratio", "نسبة المتحقق", {"op": "ratio", "a": "achieved", "b": "target"}, group="المتابعة"))
        summary += [{"key": "target_sum", "label": "إجمالي المستهدف", "format": "num", "expr": {"op": "sum", "col": "target"}},
                    {"key": "achieved_sum", "label": "إجمالي المتحقق", "format": "num", "expr": {"op": "sum", "col": "achieved"}},
                    {"key": "achieved_pct", "label": "نسبة المتحقق الإجمالية", "format": "pct",
                     "expr": {"op": "ratio_sums", "num": "achieved", "den": "target"}}]
    columns += [col("obstacles", "المعوقات والتحديات", "longtext", "follow", group="المتابعة"),
                col("improve", "توصيات التحسين", "longtext", "follow", group="المتابعة")]
    return {"sections": [{"key": "tasks", "type": "table", "title": title, "min_rows": 1, "max_rows": 60,
                          "columns": columns, "summary": summary}],
            "progress": {"section": "tasks", "summary": "execution_pct"}}


def two_semester_plan(first_cols: list[dict], title: str) -> dict:
    """نمط «التخطيط ← التنفيذ (مستهدف/متحقق لكل فصل) ← المتابعة» في 1-1-2 و1-2-2."""
    return {
        "key": "rows", "type": "table", "title": title, "min_rows": 1, "max_rows": 110,
        "columns": first_cols + [
            col("t1", "المستهدف (ف1)", "number", required=True, group="التنفيذ — الفصل الأول"),
            col("a1", "المتحقق (ف1)", "number", "follow", group="التنفيذ — الفصل الأول"),
            col("t2", "المستهدف (ف2)", "number", group="التنفيذ — الفصل الثاني"),
            col("a2", "المتحقق (ف2)", "number", "follow", group="التنفيذ — الفصل الثاني"),
            comp("avg", "متوسط نسبة الإنجاز", {"op": "sumratio", "num": ["a1", "a2"], "den": ["t1", "t2"]}, group="المتابعة"),
            col("owner", "مسؤول التنفيذ", "text", required=True, suggest=OWNERS, group="المتابعة"),
            STATUS_COL,
            col("notes", "ملاحظات", "longtext", "follow", group="المتابعة"),
        ],
        "summary": [
            {"key": "execution_pct", "label": "نسبة التنفيذ", "format": "pct",
             "expr": {"op": "status_pct", "col": "status", "denominator": "status"}},
            {"key": "avg_achievement", "label": "متوسط نسبة الإنجاز", "format": "pct", "expr": {"op": "avg", "col": "avg"}},
        ],
    }


def semester_admission(n: int, prev_key: str, prev_label: str) -> list[dict]:
    p = "follow" if n == 2 else "plan"
    g = f"الفصل التدريبي {'الأول' if n == 1 else 'الثاني'}"
    return [
        col(f"cap{n}", f"الطاقة الاستيعابية (ف{n})", "number", p, group=g),
        col(f"app{n}", f"عدد المتقدمين (ف{n})", "number", p, group=g),
        col(f"adm{n}", f"عدد المقبولين (ف{n})", "number", p, group=g),
        comp(f"adm_app{n}", "نسبة المقبولين من المتقدمين", {"op": "ratio", "a": f"adm{n}", "b": f"app{n}"}, group=g),
        comp(f"growth{n}", f"النمو في القبول ({prev_label})", {"op": "sub", "a": f"adm{n}", "b": prev_key}, "num", group=g),
        comp(f"adm_cap{n}", "نسبة المقبولين من الطاقة الاستيعابية", {"op": "ratio", "a": f"adm{n}", "b": f"cap{n}"}, group=g),
    ]


RATIO_BANDS = [[0, 14, "غير متحقق"], [14, 17, "يحتاج تحسين"], [17, 20, "متحقق"], [20, 26, "متميز"], [26, None, "غير متحقق"]]
RATIO_ADVICE = ("1. فتح أو إلغاء شعب لتعديل المسجلين بالشعب حتى لا يزيد أو يقل عن الحد المسموح به. "
                "2. طلب مدربين حسب احتياج القسم عند الوصول للحد الأعلى لأنصبة المدربين.")

TEMPLATES: list[dict] = [
    {
        "requirement_code": "1-1-2", "kind": "plan", "sort_order": 1,
        "title_ar": "خطة المبادرات التنفيذية للقسم والمحققة للأهداف التشغيلية للمنشأة",
        "guidance_ar": "لكل مبادرة: إجراء التنفيذ ومؤشر الأداء والمستهدف لكل فصل. يُحدَّث المتحقق وحالة التنفيذ خلال العام.",
        "schema": {
            "sections": [two_semester_plan([
                col("initiative", "المبادرة التي تحقق الهدف التشغيلي", "longtext", required=True, group="التخطيط"),
                col("action", "إجراء تنفيذ المبادرة", "longtext", group="التخطيط"),
                col("kpi", "مؤشر الأداء", "text", required=True, suggest=OPERATIONAL_KPIS, group="التخطيط"),
            ], "خطة المبادرات التنفيذية للقسم لتحقيق الأهداف التشغيلية للمنشأة")],
            "progress": {"section": "rows", "summary": "execution_pct"},
        },
    },
    {
        "requirement_code": "1-2-2", "kind": "report", "sort_order": 2,
        "title_ar": "تقرير تهيئة ودعم وتوجيه ومتابعة أداء المدربين والتوصيات",
        "guidance_ar": "الجزء الأول أهداف تهيئة المدربين ودعمهم ومؤشراتها، والثاني نتائج تقييم رئيس القسم لأعضاء هيئة التدريب. "
                       "أرفق نموذج تقييم كل مدرب لكل فصل ضمن الشواهد الداعمة.",
        "schema": {
            "sections": [
                two_semester_plan([
                    col("goal", "الهدف", "longtext", required=True, group="التخطيط"),
                    col("activity", "الأنشطة المحققة للهدف", "longtext", group="التخطيط"),
                    col("kpi", "مؤشر الأداء", "text", required=True, group="التخطيط"),
                ], "تقرير تهيئة ودعم وتوجيه ومتابعة أداء المدربين"),
                {"key": "evaluations", "type": "table", "title": "نتائج تقييم رئيس القسم التدريبي لأعضاء هيئة التدريب",
                 "max_rows": 120,
                 "columns": [
                     col("name", "اسم المدرب", "text", required=True, group="بيانات أعضاء هيئة التدريب"),
                     col("emp_no", "رقم الحاسب", "text", group="بيانات أعضاء هيئة التدريب"),
                     col("specialty", "التخصص", "text", group="بيانات أعضاء هيئة التدريب"),
                     col("course1", "المقرر التدريبي (ف1)", "text", "follow", group="الفصل الأول"),
                     col("v11", "الزيارة الإشرافية الأولى (ف1)", "select", "follow", options=YES_NO, group="الفصل الأول"),
                     col("v12", "الزيارة الإشرافية الثانية (ف1)", "select", "follow", options=YES_NO, group="الفصل الأول"),
                     col("score1", "تقييم الأداء من 100 (ف1)", "number", "follow", min=0, max=100, group="الفصل الأول"),
                     col("course2", "المقرر التدريبي (ف2)", "text", "follow", group="الفصل الثاني"),
                     col("v21", "الزيارة الإشرافية الأولى (ف2)", "select", "follow", options=YES_NO, group="الفصل الثاني"),
                     col("v22", "الزيارة الإشرافية الثانية (ف2)", "select", "follow", options=YES_NO, group="الفصل الثاني"),
                     col("score2", "تقييم الأداء من 100 (ف2)", "number", "follow", min=0, max=100, group="الفصل الثاني"),
                     comp("avg_score", "متوسط تقييم الأداء العام", {"op": "avg", "of": ["score1", "score2"]}, "num"),
                 ],
                 "summary": [{"key": "dept_avg_score", "label": "متوسط تقييم أداء المدربين", "format": "num",
                              "expr": {"op": "avg", "col": "avg_score"}},
                             {"key": "visits_done", "label": "نسبة الزيارات الإشرافية المنفذة", "format": "pct",
                              "expr": {"op": "share_eq", "cols": ["v11", "v12", "v21", "v22"], "eq": "نعم", "denominator": "filled"}}]},
            ],
            "progress": {"section": "rows", "summary": "execution_pct"},
        },
    },
    {
        "requirement_code": "1-2-3", "kind": "report", "sort_order": 3,
        "title_ar": "تقرير الاستثمار الأمثل للموارد البشرية في القسم والتوصيات",
        "guidance_ar": "أدخل بيانات المدربين وحالتهم ونصابهم لكل فصل، وعدد المتدربين في كل تخصص؛ "
                       "تُحسب مؤشرات الاستثمار الأمثل لكل تخصص تلقائياً كما في ملف التقرير.",
        "schema": {
            "sections": [
                {"key": "trainers", "type": "table", "title": "بيانات المدربين بالقسم", "min_rows": 1, "max_rows": 150,
                 "columns": [
                     col("name", "اسم المدرب/المدربة", "text", required=True),
                     col("specialty", "التخصص", "text", required=True),
                     col("status1", "حالة المدرب (ف1)", "select", options=TRAINER_STATUS, required=True, group="الفصل الأول"),
                     col("load1", "ساعات النصاب التدريبي (ف1)", "number", group="الفصل الأول"),
                     col("assign1", "التكليف أو اللجان والمهام المسندة (ف1)", "text", group="الفصل الأول"),
                     col("status2", "حالة المدرب (ف2)", "select", "follow", options=TRAINER_STATUS, group="الفصل الثاني"),
                     col("load2", "ساعات النصاب التدريبي (ف2)", "number", "follow", group="الفصل الثاني"),
                     col("assign2", "التكليف أو اللجان والمهام المسندة (ف2)", "text", "follow", group="الفصل الثاني"),
                 ]},
                {"key": "trainees", "type": "table", "title": "إجمالي عدد المتدربين في كل تخصص", "min_rows": 1, "max_rows": 30,
                 "columns": [col("specialty", "التخصص", "text", required=True),
                             col("n1", "عدد المتدربين (ف1)", "number", required=True),
                             col("n2", "عدد المتدربين (ف2)", "number", "follow")]},
                {"key": "summary_by_specialty", "type": "pivot", "title": "تقرير الاستثمار الأمثل للموارد البشرية في القسم",
                 "source": "trainers", "group_by": "specialty",
                 "columns": [
                     {"key": "avg_load1", "requires": "status1", "label": "متوسط النصاب التدريبي (ف1)", "format": "num", "group": "الفصل الأول",
                      "expr": {"op": "avg_where", "col": "load1", "where": "status1", "in": ["غير مفرغ وغير مجاز", "مفرغ جزئياً"]}},
                     {"key": "released1", "requires": "status1", "label": "نسبة المفرغين (ف1)", "format": "pct", "group": "الفصل الأول",
                      "expr": {"op": "share_eq", "cols": ["status1"], "eq": "مفرغ"}},
                     {"key": "partial1", "requires": "status1", "label": "نسبة المفرغين جزئياً (ف1)", "format": "pct", "group": "الفصل الأول",
                      "expr": {"op": "share_eq", "cols": ["status1"], "eq": "مفرغ جزئياً"}},
                     {"key": "outside1", "requires": "status1", "label": "نسبة المكلفين خارج المنشأة (ف1)", "format": "pct", "group": "الفصل الأول",
                      "expr": {"op": "share_eq", "cols": ["status1"], "eq": "مكلف خارج المنشأة"}},
                     {"key": "tasks1", "requires": "status1", "label": "نسبة المكلفين إشرافياً/لجان/مهام مساندة (ف1)", "format": "pct", "group": "الفصل الأول",
                      "expr": {"op": "share_nonempty", "col": "assign1"}},
                     {"key": "ratio1", "label": "عدد المدربين إلى المتدربين (ف1)", "format": "text", "group": "الفصل الأول",
                      "expr": {"op": "per_ratio", "table": "trainees", "key": "specialty", "col": "n1"}},
                     {"key": "avg_load2", "requires": "status2", "label": "متوسط النصاب التدريبي (ف2)", "format": "num", "group": "الفصل الثاني",
                      "expr": {"op": "avg_where", "col": "load2", "where": "status2", "in": ["غير مفرغ وغير مجاز", "مفرغ جزئياً"]}},
                     {"key": "released2", "requires": "status2", "label": "نسبة المفرغين (ف2)", "format": "pct", "group": "الفصل الثاني",
                      "expr": {"op": "share_eq", "cols": ["status2"], "eq": "مفرغ"}},
                     {"key": "partial2", "requires": "status2", "label": "نسبة المفرغين جزئياً (ف2)", "format": "pct", "group": "الفصل الثاني",
                      "expr": {"op": "share_eq", "cols": ["status2"], "eq": "مفرغ جزئياً"}},
                     {"key": "outside2", "requires": "status2", "label": "نسبة المكلفين خارج المنشأة (ف2)", "format": "pct", "group": "الفصل الثاني",
                      "expr": {"op": "share_eq", "cols": ["status2"], "eq": "مكلف خارج المنشأة"}},
                     {"key": "tasks2", "requires": "status2", "label": "نسبة المكلفين إشرافياً/لجان/مهام مساندة (ف2)", "format": "pct", "group": "الفصل الثاني",
                      "expr": {"op": "share_nonempty", "col": "assign2"}},
                     {"key": "ratio2", "label": "عدد المدربين إلى المتدربين (ف2)", "format": "text", "group": "الفصل الثاني",
                      "expr": {"op": "per_ratio", "table": "trainees", "key": "specialty", "col": "n2"}},
                 ]},
                {"key": "recommendations", "type": "text", "title": "التوصيات", "phase": "follow"},
            ],
        },
    },
    {
        "requirement_code": "1-3-2", "kind": "plan", "sort_order": 4,
        "title_ar": "الخطة التنفيذية لتهيئة الشعب وإنشاء الجداول التدريبية في القسم",
        "guidance_ar": "نموذج خطة تنفيذية سنوية: المهام موزعة على الفصول والأسابيع بمستهدف وآلية ومسؤول، "
                       "ثم يُحدَّث المتحقق وحالة التنفيذ. نسبة التنفيذ = (مُنفذ + نصف المُنفذ جزئياً) ÷ المهام المتابَعة.",
        "schema": executive_plan("الخطة التنفيذية لتهيئة الشعب وإنشاء الجداول التدريبية في القسم", target_numeric=True),
    },
    {
        "requirement_code": "1-3-3", "kind": "report", "sort_order": 5,
        "title_ar": "تقرير القبول السنوي للقسم وتحديد الطاقة الاستيعابية",
        "guidance_ar": "لكل تخصص: عدد المقبولين في الفصل الماضي، والطاقة الاستيعابية، والمتقدمين، والمقبولين؛ "
                       "تُحسب نسب القبول والنمو تلقائياً. بيانات الفصل الثاني تُضاف خلال المتابعة.",
        "schema": {
            "sections": [
                {"key": "specialties", "type": "table", "title": "تقرير القبول السنوي للقسم وتحديد الطاقة الاستيعابية",
                 "min_rows": 1, "max_rows": 30,
                 "columns": [col("specialty", "التخصص", "text", required=True),
                             col("prev", "عدد المقبولين الفصل الماضي", "number", group="الفصل التدريبي الأول")]
                            + semester_admission(1, "prev", "عن الفصل الماضي")
                            + semester_admission(2, "adm1", "عن الفصل الأول"),
                 "summary": [
                     {"key": "adm1_total", "label": "إجمالي المقبولين (ف1)", "format": "num", "expr": {"op": "sum", "col": "adm1"}},
                     {"key": "adm_app1", "label": "نسبة المقبولين من المتقدمين (ف1)", "format": "pct",
                      "expr": {"op": "ratio_sums", "num": "adm1", "den": "app1"}},
                     {"key": "adm_cap1", "label": "نسبة المقبولين من الطاقة الاستيعابية (ف1)", "format": "pct",
                      "expr": {"op": "ratio_sums", "num": "adm1", "den": "cap1"}},
                     {"key": "adm2_total", "label": "إجمالي المقبولين (ف2)", "format": "num", "expr": {"op": "sum", "col": "adm2"}},
                     {"key": "adm_cap2", "label": "نسبة المقبولين من الطاقة الاستيعابية (ف2)", "format": "pct",
                      "expr": {"op": "ratio_sums", "num": "adm2", "den": "cap2"}},
                 ]},
                {"key": "recommendations1", "type": "text", "title": "التوصيات — الفصل التدريبي الأول", "phase": "follow"},
                {"key": "recommendations2", "type": "text", "title": "التوصيات — الفصل التدريبي الثاني", "phase": "follow"},
            ],
        },
    },
    {
        "requirement_code": "1-3-4", "kind": "report", "sort_order": 6,
        "title_ar": "تقرير عن أعمال تسجيل الجداول التدريبية والتوصيات",
        "guidance_ar": "قياس مؤشرات عنصر الجداول التدريبية من تقرير SS01 في نظام رايات في الأسبوع الأول من كل فصل. "
                       "أدخل نتيجة كل مؤشر وتقديره، وأرفق ملف التحليل وتقرير SS01 ضمن الشواهد الداعمة.",
        "schema": {
            "sections": [
                {"key": "source", "type": "fields", "title": "مصدر البيانات (نظام رايات — تقرير SS01)",
                 "fields": [col("semester", "الفصل التدريبي", "select", options=SEMESTERS, required=True),
                            col("week", "الأسبوع", "select", options=WEEKS),
                            col("extracted_on", "تاريخ ووقت استخراج التقرير", "text")]},
                {"key": "limits", "type": "table", "title": "الحد الأدنى والأعلى المسموح به لعدد المتدربين في الشعبة",
                 "fixed_rows": [{"id": "tm", "type": "نظري صباحي"}, {"id": "pm", "type": "عملي صباحي"},
                                {"id": "te", "type": "نظري مسائي"}, {"id": "pe", "type": "عملي مسائي"}],
                 "columns": [col("type", "نوع الشعبة", "text", fixed=True),
                             col("min", "الحد الأدنى", "number"), col("max", "الحد الأعلى", "number")]},
                {"key": "indicators", "type": "table", "title": "مؤشرات عنصر الجداول التدريبية",
                 "fixed_rows": [
                     {"id": "i1", "indicator": "مؤشر التأكد من عدد المتدربين في الشعبة التدريبية وفق الحد المسموح به"},
                     {"id": "i2", "indicator": "مؤشر التأكد من التوزيع الأمثل لساعات الاتصال للمقررات التدريبية"},
                     {"id": "i3", "indicator": "مؤشر التأكد من عدد ساعات المدرب وفق الحد المسموح به"},
                     {"id": "i4", "indicator": "مؤشر التأكد من عدم وجود شعب تدريبية لنفس المقرر بأعداد أقل من الحد الأدنى"},
                 ],
                 "columns": [col("indicator", "المؤشر", "text", fixed=True),
                             col("result", "نتيجة القياس", "longtext", "follow"),
                             col("in_range", "نسبة الشعب ضمن الحد المناسب", "number", "follow"),
                             col("rating", "التقدير", "select", "follow", options=["متميز", "متحقق", "يحتاج تحسين", "غير متحقق"]),
                             col("actions", "الإجراءات التصحيحية", "longtext", "follow")]},
                {"key": "ratio", "type": "table",
                 "title": "مؤشر التأكد من نسبة عدد المدربين إلى المتدربين ضمن المستوى المقبول",
                 "fixed_rows": [{"id": "am", "period": "البرنامج الصباحي"}, {"id": "pm", "period": "البرنامج المسائي"}],
                 "columns": [col("period", "الفترة", "text", fixed=True),
                             col("trainers", "عدد المدربين", "number", "follow"),
                             col("avg", "متوسط المتدربين للمدرب", "number", "follow"),
                             comp("rating", "التقييم", {"op": "band", "of": "avg", "trunc": True, "bands": RATIO_BANDS}, "text"),
                             comp("advice", "التوصيات", {"op": "map", "of": "rating",
                                                         "map": {"غير متحقق": RATIO_ADVICE, "يحتاج تحسين": RATIO_ADVICE}}, "text")]},
            ],
        },
    },
    {
        "requirement_code": "1-4-1", "kind": "plan", "sort_order": 7,
        "title_ar": "الخطة التنفيذية للقسم في إدارة التواصل والمشاركة لأصحاب المصلحة (المدربين – المتدربين)",
        "guidance_ar": "نموذج خطة تنفيذية سنوية لوسائل التواصل مع المدربين والمتدربين ومشاركتهم.",
        "schema": executive_plan("الخطة التنفيذية للقسم في إدارة التواصل والمشاركة لأصحاب المصلحة", target_numeric=False,
                                 target_suggest=["المتدربين", "المدربين", "المتدربين والمدربين"]),
    },
    {
        "requirement_code": "1-4-2", "kind": "report", "sort_order": 8, "is_provisional": True,
        "title_ar": "تقرير متابعة شكاوى وتظلمات ومقترحات المتدربين في القسم التدريبي والتوصيات",
        "guidance_ar": "نموذج مبدئي إلى أن يُعتمد النموذج الرسمي: سجل الشكاوى والتظلمات والمقترحات ومعالجتها.",
        "schema": {
            "sections": [
                {"key": "cases", "type": "table", "title": "سجل الشكاوى والتظلمات والمقترحات", "max_rows": 200,
                 "columns": [col("date", "التاريخ", "text", "follow", required=True),
                             col("type", "النوع", "select", "follow", options=["شكوى", "تظلم", "مقترح"], required=True),
                             col("subject", "الموضوع", "longtext", "follow", required=True),
                             col("channel", "قناة الاستلام", "text", "follow", suggest=["مكتب القسم", "البريد الإلكتروني", "المرشد التدريبي", "صندوق المقترحات", "منصة إلكترونية"]),
                             col("action", "الإجراء المتخذ", "longtext", "follow"),
                             col("state", "الحالة", "select", "follow", options=["تمت المعالجة", "قيد المعالجة", "لم تُعالج"]),
                             col("closed_on", "تاريخ الإغلاق", "text", "follow")],
                 "phase": "follow",
                 "summary": [{"key": "n_complaints", "label": "الشكاوى", "format": "num", "expr": {"op": "count_eq", "col": "type", "eq": "شكوى"}},
                             {"key": "n_appeals", "label": "التظلمات", "format": "num", "expr": {"op": "count_eq", "col": "type", "eq": "تظلم"}},
                             {"key": "n_suggestions", "label": "المقترحات", "format": "num", "expr": {"op": "count_eq", "col": "type", "eq": "مقترح"}},
                             {"key": "closed_pct", "label": "نسبة المعالجة", "format": "pct",
                              "expr": {"op": "share_eq", "cols": ["state"], "eq": "تمت المعالجة"}}]},
                {"key": "recommendations", "type": "text", "title": "التوصيات", "phase": "follow"},
            ],
            "progress": {"section": "cases", "summary": "closed_pct"},
        },
    },
]

for _t in TEMPLATES:
    _t["schema"]["sections"].append(IMPROVEMENTS)
