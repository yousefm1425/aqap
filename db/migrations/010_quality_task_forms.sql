-- ربط مهام أعمال الجودة بنماذج المنصة (تُسلَّم المهمة من النموذج المعتمد دون رفع مكرر). آمن للتكرار.
BEGIN;
SET search_path = aqap, public;

ALTER TABLE quality_task ADD COLUMN IF NOT EXISTS form_code text;   -- رمز قالب النموذج (form_template.requirement_code)

-- المهام المحمّلة سابقاً: ربطها بالنماذج وتصحيح توافق ملف المدرب (المتطلب 4-1-3)
UPDATE quality_task SET form_code = CASE
    WHEN title_ar LIKE 'تقرير جاهزية%' THEN '3-1/جاهزية'
    WHEN title_ar LIKE 'تقرير تنفيذ الاختبار%' THEN '3-1/تنفيذ'
    WHEN title_ar LIKE '%تحليل نتائج المتدربين%' OR title_ar LIKE '%الإجراءات التحسينية لتحليل نتائج%'
      OR title_ar LIKE 'متابعة تنفيذ الخطط التحسينية%' THEN '2-2-2'
    WHEN title_ar LIKE 'متابعة تطبيق ورفع ملف المدرب%' THEN '4-1-3'
    WHEN title_ar LIKE 'تقرير خطط تحسين قياس جودة مخرجات%' THEN '2-2-1'
  END
 WHERE form_code IS NULL;

DELETE FROM quality_task_link l USING quality_task t, sub_standard ss
 WHERE l.task_id = t.id AND t.form_code = '4-1-3' AND ss.id = l.sub_standard_id AND ss.code IN ('3-3', '4-3');

-- النموذج المرتبط بمتطلب محدد: يُضاف المتطلب ومعياره الفرعي لتوافق المهمة
INSERT INTO quality_task_link (task_id, requirement_id)
SELECT t.id, r.id FROM quality_task t JOIN assessment_cycle c ON c.id = t.cycle_id
  JOIN standard s ON s.framework_id = c.framework_id JOIN sub_standard ss ON ss.standard_id = s.id
  JOIN requirement r ON r.sub_standard_id = ss.id AND r.code = t.form_code
 WHERE t.form_code IN ('2-2-2', '4-1-3', '2-2-1')
ON CONFLICT DO NOTHING;
INSERT INTO quality_task_link (task_id, sub_standard_id)
SELECT t.id, ss.id FROM quality_task t JOIN assessment_cycle c ON c.id = t.cycle_id
  JOIN standard s ON s.framework_id = c.framework_id JOIN sub_standard ss ON ss.standard_id = s.id
 WHERE t.form_code = '4-1-3' AND ss.code = '4-1'
ON CONFLICT DO NOTHING;

COMMIT;
