-- منهجية قياس أنماط التدريب: إطار اختياري لا يُفعَّل إلا باعتماد صاحب الصلاحية لنمط التدريب في الكلية.
-- جدول زيارات التقييم الخارجي، وارتباط مهام أعمال الجودة بتفعيل الأنماط. آمن للتكرار.
BEGIN;
SET search_path = aqap, public;

INSERT INTO framework (code, name_ar, issuer, version)
VALUES ('TVTC-PATTERNS', 'منهجية قياس أنماط التدريب', 'المؤسسة العامة للتدريب التقني والمهني', '2024')
ON CONFLICT (code) DO NOTHING;
TRUNCATE import_requirement_staging;
INSERT INTO import_requirement_staging VALUES
('1','التخطيط',1,'1-1','المسؤوليات والمهام',1,'1-1-1','شواهد اعتماد تطبيق أنماط التدريب المختلفة في المنشأة التدريبية',1,'institution',true,0),
('1','التخطيط',1,'1-1','المسؤوليات والمهام',1,'1-1-2','الخطة التنفيذية لتطبيق أنماط التدريب المختلفة',2,'institution',true,0),
('1','التخطيط',1,'1-1','المسؤوليات والمهام',1,'1-1-3','التصميم الموحد لملف المقرر التدريبي',3,'institution',true,0),
('2','التهيئة',2,'2-1','الجاهزية',1,'2-1-1','تقرير جاهزية المنشأة التدريبية لتطبيق أنماط التدريب',1,'institution',true,0),
('2','التهيئة',2,'2-2','التأهيل والمعرفة',2,'2-2-1','تقرير تأهيل وتهيئة المتدربين، والتوصيات وخطط التحسين',1,'institution',true,0),
('2','التهيئة',2,'2-2','التأهيل والمعرفة',2,'2-2-2','تقرير تأهيل وتهيئة المدربين، والتوصيات وخطط التحسين',2,'institution',true,0),
('3','التنفيذ',3,'3-1','المحتوى الإلكتروني',1,'3-1-1','توفر المحتوى الرئيسي للمقرر التدريبي والمصادر الإثرائية الداعمة',1,'institution',true,0),
('3','التنفيذ',3,'3-2','سهولة الوصول',2,'3-2-1','تقرير رضا المتدربين عن سهولة الوصول إلى المنصة الإلكترونية المعتمدة، والتوصيات وخطط التحسين',1,'institution',true,0),
('3','التنفيذ',3,'3-3','إدارة التواصل',3,'3-3-1','تقرير تفعيل وسائل التواصل مع المتدربين للرد على أسئلتهم واستفساراتهم بشكل مستمر باستخدام المنصات الإلكترونية المعتمدة',1,'institution',true,0),
('4','التقويم',4,'4-1','قياس الأثر',1,'4-1-1','تقرير رضا المتدربين عن فاعلية أنماط التدريب المختلفة، والتوصيات وخطط التحسين',1,'institution',true,0),
('4','التقويم',4,'4-1','قياس الأثر',1,'4-1-2','تقرير رضا المدربين عن فاعلية أنماط التدريب المختلفة، والتوصيات وخطط التحسين',2,'institution',true,0),
('4','التقويم',4,'4-1','قياس الأثر',1,'4-1-3','تحليل نتائج المتدربين في المقررات المطبق عليها أنماط التدريب المعتمدة (عن بعد - ذاتي)، والتوصيات وخطط التحسين',3,'institution',true,0);
SELECT import_framework_from_staging('TVTC-PATTERNS');

-- قرار اعتماد نمط التدريب للكلية في الدورة (دون قرار: الأنماط غير مفعّلة ومهامها «لا تنطبق»)
CREATE TABLE IF NOT EXISTS training_pattern_activation (
  id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  cycle_id           bigint NOT NULL REFERENCES assessment_cycle(id) ON DELETE CASCADE,   -- دورة نظام الجودة
  patterns_cycle_id  bigint REFERENCES assessment_cycle(id),                             -- دورة منهجية الأنماط المنشأة
  authority_ar       text NOT NULL,            -- صاحب الصلاحية
  decision_no        text,
  decision_date      date,
  patterns           text[] NOT NULL,          -- ذاتي / مدمج / عن بعد
  specialties        jsonb NOT NULL DEFAULT '[]',   -- التخصص، عدد المقررات، النمط، المستفيدون
  notes_ar           text,
  created_by         bigint REFERENCES app_user(id),
  created_at         timestamptz NOT NULL DEFAULT now(),
  revoked_at         timestamptz,
  revoke_reason_ar   text
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_pattern_active ON training_pattern_activation (cycle_id) WHERE revoked_at IS NULL;

CREATE TABLE IF NOT EXISTS external_visit (
  id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  cycle_id          bigint NOT NULL REFERENCES assessment_cycle(id) ON DELETE CASCADE,
  visit_date        date NOT NULL,
  program           text NOT NULL CHECK (program IN ('بكالوريوس','دبلوم','بكالوريوس ودبلوم')),
  supervisor_name   text,
  supervisor_phone  text,
  college_name      text,
  college_phone     text,
  executed          boolean,
  notes_ar          text,
  created_by        bigint REFERENCES app_user(id),
  created_at        timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE quality_task ADD COLUMN IF NOT EXISTS depends_on text CHECK (depends_on IN ('patterns'));
UPDATE quality_task SET depends_on = 'patterns' WHERE depends_on IS NULL AND condition_ar LIKE '%أنماط التدريب%';

DROP TRIGGER IF EXISTS t_audit_pattern_act ON training_pattern_activation;
CREATE TRIGGER t_audit_pattern_act AFTER INSERT OR UPDATE OR DELETE ON training_pattern_activation FOR EACH ROW EXECUTE FUNCTION trg_audit();
DROP TRIGGER IF EXISTS t_audit_ext_visit ON external_visit;
CREATE TRIGGER t_audit_ext_visit AFTER INSERT OR UPDATE OR DELETE ON external_visit FOR EACH ROW EXECUTE FUNCTION trg_audit();

COMMIT;
