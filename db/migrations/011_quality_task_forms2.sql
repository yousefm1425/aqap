-- ربط مهام جودة المخرجات ومنصة المهارات بنماذجها. آمن للتكرار.
BEGIN;
SET search_path = aqap, public;
UPDATE quality_task SET form_code = '4-1/المهارات' WHERE form_code IS NULL AND title_ar LIKE '%منصة المهارات العملية%';
UPDATE quality_task SET form_code = '2-2/المخرجات' WHERE form_code IS NULL AND title_ar LIKE 'تقرير متطلبات وتهيئة المتدربين%';
UPDATE quality_task SET form_code = '2-2-1' WHERE form_code IS NULL AND title_ar LIKE 'تقرير تنفيذ قياس جودة مخرجات%';
INSERT INTO quality_task_link (task_id, requirement_id)
SELECT t.id, r.id FROM quality_task t JOIN assessment_cycle c ON c.id = t.cycle_id
  JOIN standard s ON s.framework_id = c.framework_id JOIN sub_standard ss ON ss.standard_id = s.id
  JOIN requirement r ON r.sub_standard_id = ss.id AND r.code = t.form_code
 WHERE t.form_code = '2-2-1'
ON CONFLICT DO NOTHING;
COMMIT;
