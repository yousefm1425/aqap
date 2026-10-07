"""بيانات عرض تجريبية (ليست نصوص النموذج الرسمي) لتجربة الواجهة أمام رؤساء الأقسام.

الاستخدام:
    python scripts/seed_demo.py postgresql://aqap:aqap@localhost:5432/aqap_demo
القاعدة يجب أن تكون فارغة وقد طُبّق عليها db/schema.sql.
"""
import random
import sys

import psycopg

# بنية النموذج الرسمي (أرقام المعايير والمعايير الفرعية وعدد المتطلبات) بنصوص تجريبية
STANDARDS = [("1", "القيادة الإدارية", [2, 3, 4, 2]), ("2", "نواتج التدريب", [3, 10]),
             ("3", "المناهج وأدوات القياس والتقويم", [2, 5, 2]), ("4", "التدريب والموارد المساندة", [3, 2, 2]),
             ("5", "البيئة التدريبية", [3, 1]), ("6", "الاستدامة", [1, 1, 1, 1])]
DEPTS = [("CS", "تقنية الحاسب"), ("EE", "التقنية الكهربائية"), ("ME", "التقنية الميكانيكية"), ("AD", "التقنية الإدارية")]
STARRED = {"1-3-3": 1, "2-1-1": 1, "2-1-2": 1, "2-1-3": 1, "2-2-4": 1, "2-2-5": 1, "2-2-7": 1,
           "2-2-1": 2, "2-2-6": 2, "2-2-8": 2, "2-2-9": 2, "2-2-10": 2, "3-2-3": 2, "3-2-4": 2, "3-2-5": 2}


def main(dsn: str) -> None:
    rnd = random.Random(1447)
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("SET search_path = aqap")
        rows = []
        order = 0
        for si, (scode, stitle, subs) in enumerate(STANDARDS, 1):
            for j, n in enumerate(subs, 1):
                sub = f"{scode}-{j}"
                for k in range(1, n + 1):
                    order += 1
                    code = f"{sub}-{k}"
                    rows.append((scode, stitle, si, sub, f"معيار فرعي تجريبي {sub}", j, code,
                                 f"نص تجريبي للمتطلب {code} — يُستبدل بنص النموذج الرسمي عند الاستيراد", order,
                                 "department", True, STARRED.get(code, 0)))
        with conn.cursor() as cur:
            cur.executemany("INSERT INTO import_requirement_staging VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", rows)
        conn.execute("SELECT import_framework_from_staging('TVTC-TQ-L2')")

        conn.execute("INSERT INTO institution(code, name_ar) VALUES ('YNB', 'الكلية التقنية التطبيقية بينبع')")
        for code, name in DEPTS:
            conn.execute("INSERT INTO department(institution_id, code, name_ar) VALUES (1, %s, %s)", (code, name))
        conn.execute("INSERT INTO department(institution_id, code, name_ar, is_general_studies) VALUES (1, 'GS', 'الدراسات العامة', true)")
        users = [("dean@ynb", "وكيل الجودة", "quality_dean", None), ("auditor@ynb", "مدقق الجودة", "quality_auditor", None),
                 ("hod.cs@ynb", "رئيس قسم الحاسب", "hod", 1)]
        users += [(f"coord.{c.lower()}@ynb", f"منسق {n}", "dept_coordinator", i) for i, (c, n) in enumerate(DEPTS, 1)]
        users += [(f"trainer{k}.cs@ynb", f"مدرب الحاسب {k}", "faculty", 1) for k in range(1, 4)]
        ids = {}
        for email, name, role, dept in users:
            uid = conn.execute("INSERT INTO app_user(institution_id, email, full_name_ar) VALUES (1,%s,%s) RETURNING id",
                               (email, name)).fetchone()[0]
            conn.execute("INSERT INTO user_role(user_id, role, department_id) VALUES (%s,%s,%s)", (uid, role, dept))
            ids[email] = uid
        conn.execute("""INSERT INTO assessment_cycle(institution_id, framework_id, title_ar, academic_year, starts_on, ends_on, status)
                        VALUES (1, 1, 'التقييم الذاتي 1447هـ', '1447', '2026-09-01', '2027-05-31', 'open')""")
        conn.execute("INSERT INTO cycle_department SELECT 1, id FROM department")
        conn.execute("SELECT generate_cycle_assessments(1)")

        maturity = {1: 0.85, 2: 0.6, 3: 0.35, 4: 0.7}
        for dept_id, (code, _) in enumerate(DEPTS, 1):
            coord = ids[f"coord.{code.lower()}@ynb"]
            ev_ids = []
            for n in range(1, 7):
                ev = conn.execute("""INSERT INTO evidence(institution_id, department_id, title_ar, kind, created_by)
                                     VALUES (1, %s, %s, 'file', %s) RETURNING id""",
                                  (dept_id, f"شاهد تجريبي {n} — {code}", coord)).fetchone()[0]
                conn.execute("INSERT INTO evidence_version(evidence_id, version_no, storage_key, file_name, mime_type, size_bytes) "
                             "VALUES (%s, 0, %s, %s, 'application/pdf', 1024)", (ev, f"demo/{ev}.pdf", f"شاهد-{n}.pdf"))
                ev_ids.append(ev)
            assessments = conn.execute("SELECT id, na_allowed(requirement_id, department_id) FROM assessment "
                                       "WHERE department_id = %s ORDER BY id", (dept_id,)).fetchall()
            for (aid, na_ok) in assessments:
                if rnd.random() > maturity[dept_id] + 0.1:
                    continue
                rating = rnd.choices(["met", "partial", "not_met", "na"], weights=[maturity[dept_id] * 10, 3, 2, 1])[0]
                conn.execute("SELECT set_config('aqap.user_id', %s, false)", (str(coord),))
                if rating == "na" and not na_ok:
                    rating = "not_met"
                conn.execute("UPDATE assessment SET self_rating=%s WHERE id=%s", (rating, aid))
                if rating != "na" and rnd.random() < maturity[dept_id] + 0.1:
                    conn.execute("INSERT INTO assessment_evidence(assessment_id, evidence_id) VALUES (%s,%s)", (aid, rnd.choice(ev_ids)))
                    if rnd.random() < maturity[dept_id]:
                        conn.execute("SELECT transition_assessment(%s,'submitted',%s)", (aid, coord))

        # قسم الحاسب: مسار كامل حتى التدقيق لعدد من المتطلبات
        submitted = conn.execute("SELECT id, self_rating FROM assessment WHERE department_id = 1 AND status = 'submitted' ORDER BY id").fetchall()
        for i, (aid, rating) in enumerate(submitted[:14]):
            conn.execute("SELECT transition_assessment(%s,'hod_approved',%s)", (aid, ids["hod.cs@ynb"]))
            conn.execute("SELECT transition_assessment(%s,'under_audit',%s)", (aid, ids["auditor@ynb"]))
            if i < 10:
                verdict = "conforms" if i % 3 else ("insufficient" if rating == "met" else "not_conforming")
                conn.execute("SELECT set_config('aqap.user_id', %s, false)", (str(ids["auditor@ynb"]),))
                conn.execute("UPDATE assessment SET ext_verdict=%s, ext_recommendation=%s WHERE id=%s",
                             (verdict, "توصية تجريبية من المدقق" if verdict != "conforms" or rating != "met" else None, aid))
                conn.execute("SELECT transition_assessment(%s,'audited',%s)", (aid, ids["auditor@ynb"]))
                if i < 6:
                    conn.execute("SELECT transition_assessment(%s,'final',%s)", (aid, ids["dean@ynb"]))
        one = conn.execute("SELECT id FROM assessment WHERE department_id = 2 AND status = 'submitted' LIMIT 1").fetchone()
        if one:
            conn.execute("INSERT INTO user_role(user_id, role, department_id) VALUES (%s, 'hod', 2)", (ids["dean@ynb"],))
            conn.execute("SELECT transition_assessment(%s,'returned',%s,'الشاهد لا يغطي كل عناصر المتطلب؛ أضف محضر اللجنة')",
                         (one[0], ids["dean@ynb"]))
            conn.execute("DELETE FROM user_role WHERE user_id = %s AND role = 'hod'", (ids["dean@ynb"],))
        # خطط التحسين: تتولد تلقائياً للمتطلبات النهائية «جزئي/غير متحقق»؛ نحركها عبر مراحل مختلفة للعرض
        coord, auditor, dean = ids["coord.cs@ynb"], ids["auditor@ynb"], ids["dean@ynb"]
        plans = conn.execute("SELECT id FROM improvement_action WHERE department_id = 1 ORDER BY id").fetchall()
        cs_ev = conn.execute("SELECT id FROM evidence WHERE department_id = 1 ORDER BY id LIMIT 1").fetchone()[0]
        texts = ["تحديث الهيكل التنظيمي واعتماده من مجلس الكلية وتعميمه", "توثيق محاضر لجنة الجودة شهرياً مع التوصيات",
                 "إعداد تقرير متابعة الخطة التشغيلية فصلياً", "تفعيل استبانة رضا المتدربين وتحليل نتائجها"]
        for k, (pid,) in enumerate(plans):
            conn.execute("SELECT set_config('aqap.user_id', %s, false)", (str(coord),))
            conn.execute("UPDATE improvement_action SET action_ar=%s, owner_id=%s, due_date=%s WHERE id=%s",
                         (texts[k % 4], coord, ["2026-09-20", "2026-12-15", "2027-02-01", "2026-11-30"][k % 4], pid))
            if k % 4 == 0:
                continue
            conn.execute("SELECT transition_action(%s,'submitted',%s)", (pid, coord))
            if k % 4 == 1:
                continue
            conn.execute("SELECT transition_action(%s,'approved',%s)", (pid, auditor))
            if k % 4 == 2:
                conn.execute("SELECT set_config('aqap.user_id', %s, false)", (str(coord),))
                conn.execute("UPDATE improvement_action SET progress_pct = 60 WHERE id = %s", (pid,))
                continue
            conn.execute("SELECT set_config('aqap.user_id', %s, false)", (str(coord),))
            conn.execute("UPDATE improvement_action SET completion_evidence_id = %s WHERE id = %s", (cs_ev, pid))
            conn.execute("SELECT transition_action(%s,'completed',%s)", (pid, coord))
            conn.execute("SELECT transition_action(%s,'verified',%s,'تم التحقق من الشاهد')", (pid, dean))
        print("demo data ready")


if __name__ == "__main__":
    main(sys.argv[1])
