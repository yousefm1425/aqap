-- تقويم الإنجاز للمعايير الفرعية والمتطلبات. آمن للتكرار.
BEGIN;
SET search_path = aqap, public;

-- ---------------------------------------------------------------------
-- تقويم الإنجاز: مواعيد يرفعها وكيل الجودة للمعايير الفرعية أو المتطلبات (لكل الأقسام أو لقسم)
-- الموعد الأخص يغلب: المتطلب على المعيار الفرعي، والقسم على «كل الأقسام»
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cycle_deadline (
  id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  cycle_id         bigint NOT NULL REFERENCES assessment_cycle(id) ON DELETE CASCADE,
  sub_standard_id  bigint REFERENCES sub_standard(id),
  requirement_id   bigint REFERENCES requirement(id),
  department_id    bigint REFERENCES department(id),          -- NULL = كل الأقسام
  starts_on        date,
  due_on           date NOT NULL,
  note_ar          text,
  created_by       bigint REFERENCES app_user(id),
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now(),
  CHECK ((sub_standard_id IS NULL) <> (requirement_id IS NULL)),
  CHECK (starts_on IS NULL OR starts_on <= due_on)
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_cycle_deadline ON cycle_deadline
  (cycle_id, COALESCE(sub_standard_id, 0), COALESCE(requirement_id, 0), COALESCE(department_id, 0));

-- الموعد الفعلي لكل تقدير
CREATE OR REPLACE VIEW v_assessment_deadline AS
SELECT a.id AS assessment_id, a.cycle_id, a.department_id, a.requirement_id, a.status, d.id AS deadline_id, d.starts_on, d.due_on
  FROM assessment a
  JOIN requirement r ON r.id = a.requirement_id
  JOIN LATERAL (
    SELECT cd.* FROM cycle_deadline cd
     WHERE cd.cycle_id = a.cycle_id
       AND (cd.requirement_id = a.requirement_id OR cd.sub_standard_id = r.sub_standard_id)
       AND (cd.department_id IS NULL OR cd.department_id IS NOT DISTINCT FROM a.department_id)
     ORDER BY (cd.requirement_id IS NOT NULL) DESC, (cd.department_id IS NOT NULL) DESC
     LIMIT 1) d ON true
 WHERE NOT is_excluded(a.requirement_id, a.department_id, a.cycle_id);

DROP TRIGGER IF EXISTS t_audit_cycle_deadline ON cycle_deadline;
CREATE TRIGGER t_audit_cycle_deadline AFTER INSERT OR UPDATE OR DELETE ON cycle_deadline
  FOR EACH ROW EXECUTE FUNCTION trg_audit();
COMMIT;
