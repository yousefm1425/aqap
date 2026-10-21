-- أسماء ثلاثة معايير فرعية حسب النموذج الرسمي (نظام جودة التدريب — المستوى الثاني). آمن للتكرار.
BEGIN;
SET search_path = aqap, public;
UPDATE sub_standard ss SET title_ar = v.new_title
  FROM (VALUES
    ('1-3', 'التشغيل والجداول التدريبية', 'القبول والجداول التدريبية'),
    ('3-1', 'القياس وتقويم المتدربين', 'القياس وتقييم المتدربين'),
    ('3-3', 'إدارة محتوى البرامج التدريبية', 'إدارة محتوى البرنامج التدريبي')
  ) AS v(code, old_title, new_title), standard s, framework f
 WHERE ss.code = v.code AND ss.title_ar = v.old_title AND s.id = ss.standard_id AND f.id = s.framework_id AND f.code = 'TVTC-TQ-L2';
COMMIT;
