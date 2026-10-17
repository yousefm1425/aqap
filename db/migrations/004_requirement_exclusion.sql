-- نطاق انطباق المتطلبات على القسم (استبعاد ما ليس من اختصاصه). آمن للتكرار.
BEGIN;
SET search_path = aqap, public;

CREATE TABLE IF NOT EXISTS requirement_exclusion (
  id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  department_id      bigint NOT NULL REFERENCES department(id),
  requirement_id     bigint NOT NULL REFERENCES requirement(id),
  reason_ar          text NOT NULL CHECK (length(btrim(reason_ar)) >= 5),
  within_model_rule  boolean NOT NULL,           -- يسمح به شرط النجمة في النموذج الرسمي؟
  decided_by         bigint REFERENCES app_user(id),
  decided_at         timestamptz NOT NULL DEFAULT clock_timestamp(),
  revoked_at         timestamptz,
  revoked_by         bigint REFERENCES app_user(id),
  CHECK (revoked_at IS NULL OR revoked_at >= decided_at)
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_requirement_exclusion_active ON requirement_exclusion (department_id, requirement_id) WHERE revoked_at IS NULL;

CREATE OR REPLACE FUNCTION is_excluded(p_requirement bigint, p_department bigint, p_cycle bigint) RETURNS boolean
LANGUAGE sql STABLE AS $$
  SELECT p_department IS NOT NULL AND EXISTS (
    SELECT 1 FROM requirement_exclusion e, assessment_cycle c
     WHERE c.id = p_cycle AND e.department_id = p_department AND e.requirement_id = p_requirement
       AND e.decided_at <= COALESCE(c.closed_at, 'infinity')
       AND (e.revoked_at IS NULL OR e.revoked_at > COALESCE(c.closed_at, 'infinity')))
$$;

CREATE OR REPLACE VIEW v_assessment_scored AS
WITH base AS (
  SELECT a.*, r.code AS requirement_code, r.weight AS requirement_weight, r.evidence_required,
         na_allowed(a.requirement_id, a.department_id) AS na_ok,
         ss.id AS sub_standard_id, ss.code AS sub_standard_code, ss.title_ar AS sub_standard_title,
         s.id AS standard_id, s.code AS standard_code, s.title_ar AS standard_title
    FROM assessment a
    JOIN requirement r   ON r.id  = a.requirement_id
    JOIN sub_standard ss ON ss.id = r.sub_standard_id
    JOIN standard s      ON s.id  = ss.standard_id
   WHERE NOT is_excluded(a.requirement_id, a.department_id, a.cycle_id)
)
SELECT b.id AS assessment_id, b.cycle_id, b.department_id, b.status,
       b.standard_id, b.standard_code, b.standard_title, b.sub_standard_id, b.sub_standard_code, b.sub_standard_title,
       b.requirement_id, b.requirement_code, b.requirement_weight, b.evidence_required, b.na_ok,
       b.self_rating, b.ext_verdict,
       effective_rating(b.self_rating, b.ext_verdict, b.na_ok) AS eff_rating,
       -- NULL = غير مقدّر أو «لا ينطبق» مقبول (يُستبعد من المقام)
       CASE WHEN b.self_rating IS NULL OR (b.self_rating = 'na' AND b.na_ok) THEN NULL
            ELSE COALESCE(rs_self.score, 0) END AS self_score,
       CASE WHEN b.ext_verdict IS NULL OR b.self_rating IS NULL THEN NULL
            WHEN b.ext_verdict = 'conforms' AND b.self_rating = 'na' AND b.na_ok THEN NULL
            WHEN b.ext_verdict = 'conforms' THEN COALESCE(rs_self.score, 0)
            ELSE 0 END AS ext_score,
       CASE WHEN effective_rating(b.self_rating, b.ext_verdict, b.na_ok) IS NULL
              OR effective_rating(b.self_rating, b.ext_verdict, b.na_ok) = 'na' THEN NULL
            ELSE COALESCE(rs_eff.score, 0) END AS eff_score
  FROM base b
  LEFT JOIN rating_score rs_self ON rs_self.rating = b.self_rating
  LEFT JOIN rating_score rs_eff  ON rs_eff.rating  = effective_rating(b.self_rating, b.ext_verdict, b.na_ok);

CREATE OR REPLACE FUNCTION generate_cycle_assessments(p_cycle_id bigint) RETURNS integer
LANGUAGE plpgsql AS $$
DECLARE v_fw bigint; v_n integer;
BEGIN
  SELECT framework_id INTO v_fw FROM assessment_cycle WHERE id = p_cycle_id;
  IF v_fw IS NULL THEN RAISE EXCEPTION 'الدورة % غير موجودة', p_cycle_id; END IF;

  INSERT INTO assessment (cycle_id, department_id, requirement_id)
  SELECT p_cycle_id, cd.department_id, r.id
    FROM cycle_department cd
    CROSS JOIN requirement r
    JOIN sub_standard ss ON ss.id = r.sub_standard_id
    JOIN standard s      ON s.id  = ss.standard_id
   WHERE cd.cycle_id = p_cycle_id AND s.framework_id = v_fw
     AND r.scope = 'department' AND r.is_active
     AND NOT EXISTS (SELECT 1 FROM requirement_exclusion e
                      WHERE e.department_id = cd.department_id AND e.requirement_id = r.id AND e.revoked_at IS NULL)
  UNION ALL
  SELECT p_cycle_id, NULL, r.id
    FROM requirement r
    JOIN sub_standard ss ON ss.id = r.sub_standard_id
    JOIN standard s      ON s.id  = ss.standard_id
   WHERE s.framework_id = v_fw AND r.scope = 'institution' AND r.is_active
  ON CONFLICT DO NOTHING;

  GET DIAGNOSTICS v_n = ROW_COUNT;
  RETURN v_n;
END $$;

CREATE OR REPLACE FUNCTION close_cycle(p_cycle_id bigint, p_actor bigint) RETURNS void
LANGUAGE plpgsql AS $$
DECLARE v_open integer;
BEGIN
  IF NOT (has_role(p_actor, 'quality_dean', NULL, p_cycle_id)
          OR has_role(p_actor, 'system_admin', NULL, p_cycle_id)) THEN
    RAISE EXCEPTION 'إغلاق الدورة من صلاحية وكيل الجودة فقط';
  END IF;

  SELECT count(*) INTO v_open FROM assessment
   WHERE cycle_id = p_cycle_id AND status <> 'final' AND NOT is_excluded(requirement_id, department_id, cycle_id);
  IF v_open > 0 THEN
    RAISE EXCEPTION 'لا يمكن الإغلاق: % تقديرات لم تصل للحالة النهائية', v_open;
  END IF;

  PERFORM set_config('aqap.user_id',   p_actor::text, true);
  PERFORM set_config('aqap.system_op', 'on', true);
  UPDATE assessment_evidence ae
     SET pinned_version_no = e.current_version_no
    FROM evidence e, assessment a
   WHERE ae.evidence_id = e.id AND ae.assessment_id = a.id
     AND a.cycle_id = p_cycle_id AND ae.pinned_version_no IS NULL;
  PERFORM set_config('aqap.system_op', 'off', true);

  UPDATE assessment_cycle
     SET status = 'closed', closed_at = now(), closed_by = p_actor
   WHERE id = p_cycle_id;
END $$;

CREATE OR REPLACE FUNCTION generate_improvement_actions(p_cycle_id bigint) RETURNS integer
LANGUAGE plpgsql AS $$
DECLARE v_n integer;
BEGIN
  INSERT INTO improvement_action (cycle_id, assessment_id, department_id, source, title_ar)
  SELECT a.cycle_id, a.id, a.department_id, 'auto', 'خطة تحسين المتطلب ' || r.code
    FROM assessment a JOIN requirement r ON r.id = a.requirement_id
   WHERE a.cycle_id = p_cycle_id AND a.status = 'final'
     AND NOT is_excluded(a.requirement_id, a.department_id, a.cycle_id)
     AND (effective_rating(a.self_rating, a.ext_verdict, na_allowed(a.requirement_id, a.department_id)) IN ('partial','not_met')
          OR (r.evidence_required
              AND effective_rating(a.self_rating, a.ext_verdict, na_allowed(a.requirement_id, a.department_id)) <> 'na'
              AND NOT EXISTS (SELECT 1 FROM assessment_evidence ae WHERE ae.assessment_id = a.id)))
  ON CONFLICT (assessment_id) WHERE source = 'auto' DO NOTHING;
  GET DIAGNOSTICS v_n = ROW_COUNT;
  RETURN v_n;
END $$;

CREATE OR REPLACE FUNCTION trg_assessment_final_action() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.status = 'final' AND OLD.status IS DISTINCT FROM 'final'
     AND effective_rating(NEW.self_rating, NEW.ext_verdict, na_allowed(NEW.requirement_id, NEW.department_id)) IS DISTINCT FROM 'na' THEN
    -- خطة تحسين: المتطلب غير منفذ/منفذ جزئياً، أو الشاهد المطلوب غير متوفر
    INSERT INTO improvement_action (cycle_id, assessment_id, department_id, source, title_ar)
    SELECT NEW.cycle_id, NEW.id, NEW.department_id, 'auto', 'خطة تحسين المتطلب ' || r.code
      FROM requirement r WHERE r.id = NEW.requirement_id
       AND NOT is_excluded(NEW.requirement_id, NEW.department_id, NEW.cycle_id)
       AND (effective_rating(NEW.self_rating, NEW.ext_verdict, na_allowed(NEW.requirement_id, NEW.department_id)) IN ('partial','not_met')
            OR (r.evidence_required AND NOT EXISTS (SELECT 1 FROM assessment_evidence ae WHERE ae.assessment_id = NEW.id)))
    ON CONFLICT (assessment_id) WHERE source = 'auto' DO NOTHING;
  END IF;
  RETURN NULL;
END $$;

DROP TRIGGER IF EXISTS t_audit_requirement_exclusion ON requirement_exclusion;
CREATE TRIGGER t_audit_requirement_exclusion AFTER INSERT OR UPDATE ON requirement_exclusion
  FOR EACH ROW EXECUTE FUNCTION trg_audit();

COMMIT;
