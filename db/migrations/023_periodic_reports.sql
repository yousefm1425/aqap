-- التقارير الدورية: تأشير إنجاز بنود تقويم أعمال جودة التدريب (البنود نفسها في الكود: app/periodic_catalog.py).
-- بند القسم يُؤشَّر لكل قسم، وبند الكلية بلا قسم (department_id = NULL). البنود المرتبطة بنموذج لا تُخزَّن هنا. آمن للتكرار.
BEGIN;
SET search_path = aqap, public;

CREATE TABLE IF NOT EXISTS periodic_progress (
  id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  cycle_id       bigint NOT NULL REFERENCES assessment_cycle(id) ON DELETE CASCADE,
  item_key       text NOT NULL CHECK (length(item_key) BETWEEN 3 AND 20),
  department_id  bigint REFERENCES department(id),
  status         text NOT NULL CHECK (status IN ('done', 'na')),
  url            text,
  note_ar        text,
  done_by        bigint REFERENCES app_user(id),
  done_at        timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_periodic_progress ON periodic_progress (cycle_id, item_key, (COALESCE(department_id, 0)));
CREATE INDEX IF NOT EXISTS ix_periodic_progress_dept ON periodic_progress (department_id);

DROP TRIGGER IF EXISTS t_audit_periodic_progress ON periodic_progress;
CREATE TRIGGER t_audit_periodic_progress AFTER INSERT OR UPDATE OR DELETE ON periodic_progress FOR EACH ROW EXECUTE FUNCTION trg_audit();
COMMIT;
