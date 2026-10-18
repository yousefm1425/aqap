-- منطقة المنشأة (تُكتب في ترويسة ملفات الإدارة). آمن للتكرار.
BEGIN;
SET search_path = aqap, public;
ALTER TABLE institution ADD COLUMN IF NOT EXISTS region_ar text;
UPDATE institution SET region_ar = 'المدينة المنورة' WHERE region_ar IS NULL AND name_ar LIKE '%ينبع%';
COMMIT;
