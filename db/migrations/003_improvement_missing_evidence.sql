-- خطط التحسين تتولد أيضاً للمتطلبات التي لا يتوفر شاهدها المطلوب (إضافة على «جزئي/غير متحقق»)
SET search_path = aqap, public;

CREATE OR REPLACE FUNCTION generate_improvement_actions(p_cycle_id bigint) RETURNS integer
LANGUAGE plpgsql AS $$
DECLARE v_n integer;
BEGIN
  INSERT INTO improvement_action (cycle_id, assessment_id, department_id, source, title_ar)
  SELECT a.cycle_id, a.id, a.department_id, 'auto', 'خطة تحسين المتطلب ' || r.code
    FROM assessment a JOIN requirement r ON r.id = a.requirement_id
   WHERE a.cycle_id = p_cycle_id AND a.status = 'final'
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
       AND (effective_rating(NEW.self_rating, NEW.ext_verdict, na_allowed(NEW.requirement_id, NEW.department_id)) IN ('partial','not_met')
            OR (r.evidence_required AND NOT EXISTS (SELECT 1 FROM assessment_evidence ae WHERE ae.assessment_id = NEW.id)))
    ON CONFLICT (assessment_id) WHERE source = 'auto' DO NOTHING;
  END IF;
  RETURN NULL;
END $$;
