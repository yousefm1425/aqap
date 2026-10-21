-- أقسام الكلية التقنية التطبيقية بينبع الفعلية. آمن للتكرار.
-- 1) حذف قسم «التقنية الإدارية» (من بيانات العرض، غير موجود في الكلية) بكل ما يتبعه.
-- 2) إضافة قسمي «تقنية الاتصالات» و«التقنية الإلكترونية» (أو توحيد اسميهما إن أُضيفا من نافذة الربط)،
--    وإدخالهما في دورات التقييم وتوليد تقديراتهما فيظهران في كل صفحات المنصة.
BEGIN;
SET search_path = aqap, public;

-- حذف صفوف جدول وكل ما يعتمد عليها (تتبّع المفاتيح الأجنبية تلقائياً، الأبناء قبل الآباء)
CREATE OR REPLACE FUNCTION purge_rows(p_table regclass, p_where text, p_depth int DEFAULT 0) RETURNS void
LANGUAGE plpgsql AS $$
DECLARE fk record; v_child_cols text; v_parent_cols text;
BEGIN
  IF p_depth > 10 THEN RETURN; END IF;
  FOR fk IN SELECT c.conrelid::regclass AS child, c.conkey, c.confkey, c.conrelid, c.confrelid
              FROM pg_constraint c WHERE c.contype = 'f' AND c.confrelid = p_table AND c.conrelid <> p_table LOOP
    SELECT string_agg(quote_ident(a.attname), ',' ORDER BY k.i) INTO v_child_cols
      FROM unnest(fk.conkey) WITH ORDINALITY k(n, i) JOIN pg_attribute a ON a.attrelid = fk.conrelid AND a.attnum = k.n;
    SELECT string_agg(quote_ident(a.attname), ',' ORDER BY k.i) INTO v_parent_cols
      FROM unnest(fk.confkey) WITH ORDINALITY k(n, i) JOIN pg_attribute a ON a.attrelid = fk.confrelid AND a.attnum = k.n;
    PERFORM purge_rows(fk.child, format('(%s) IN (SELECT %s FROM %s WHERE %s)', v_child_cols, v_parent_cols, p_table, p_where),
                       p_depth + 1);
  END LOOP;
  EXECUTE format('DELETE FROM %s WHERE %s', p_table, p_where);
END $$;

DO $$
DECLARE d record; v_inst bigint; v_id bigint; v_code text; v_name text; v_like text; v_new bigint[] := '{}'; c record; v_k int;
BEGIN
  -- (1) حذف «التقنية الإدارية» — حراس الحذف (نسخ الشواهد، المحاضر المعتمدة…) معطّلة أثناء هذه العملية فقط
  FOR d IN SELECT id FROM department WHERE name_ar IN ('التقنية الإدارية', 'التقنية الادارية') LOOP
    PERFORM set_config('session_replication_role', 'replica', true);
    UPDATE app_user u SET is_active = false
     WHERE EXISTS (SELECT 1 FROM user_role r WHERE r.user_id = u.id AND r.department_id = d.id)
       AND NOT EXISTS (SELECT 1 FROM user_role r WHERE r.user_id = u.id AND (r.department_id IS DISTINCT FROM d.id));
    PERFORM purge_rows('department'::regclass, format('id = %s', d.id));
    PERFORM set_config('session_replication_role', 'origin', true);
    RAISE NOTICE 'حُذف قسم التقنية الإدارية (%)', d.id;
  END LOOP;

  -- (2) إضافة تقنية الاتصالات والتقنية الإلكترونية لكل منشأة لها أقسام
  FOR v_inst IN SELECT DISTINCT institution_id FROM department LOOP
    FOREACH v_name IN ARRAY ARRAY['تقنية الاتصالات', 'التقنية الإلكترونية'] LOOP
      v_like := CASE WHEN v_name LIKE '%اتصالات%' THEN '%اتصالات%' ELSE '%لكترون%' END;
      SELECT id INTO v_id FROM department WHERE institution_id = v_inst AND (name_ar = v_name OR name_ar LIKE v_like) ORDER BY id LIMIT 1;
      IF v_id IS NULL THEN
        v_code := CASE WHEN v_like = '%اتصالات%' THEN 'TC' ELSE 'EL' END;
        v_k := 1;
        WHILE EXISTS (SELECT 1 FROM department WHERE institution_id = v_inst AND code = v_code) LOOP
          v_code := split_part(v_code, '-', 1) || '-' || v_k; v_k := v_k + 1;
        END LOOP;
        INSERT INTO department (institution_id, code, name_ar) VALUES (v_inst, v_code, v_name) RETURNING id INTO v_id;
      ELSE
        UPDATE department SET name_ar = v_name, is_active = true WHERE id = v_id AND name_ar <> v_name;
      END IF;
      v_new := v_new || v_id;
    END LOOP;
  END LOOP;

  -- إدخال القسمين في دورات التقييم القائمة (التي لها أقسام) وتوليد تقديراتهما
  FOR c IN SELECT DISTINCT cy.id, cy.institution_id FROM assessment_cycle cy JOIN cycle_department cd ON cd.cycle_id = cy.id LOOP
    INSERT INTO cycle_department (cycle_id, department_id)
    SELECT c.id, x FROM unnest(v_new) x JOIN department dp ON dp.id = x AND dp.institution_id = c.institution_id
    ON CONFLICT DO NOTHING;
    PERFORM generate_cycle_assessments(c.id);
  END LOOP;

  -- حسابات منسقين تجريبية للقسمين في بيانات العرض فقط (تُستبدل بالحسابات الفعلية عند الإطلاق)
  IF EXISTS (SELECT 1 FROM app_user WHERE email = 'coord.cs@ynb') THEN
    FOR d IN SELECT dp.id, dp.institution_id, dp.name_ar, CASE WHEN dp.name_ar LIKE '%اتصالات%' THEN 'coord.tc@ynb' ELSE 'coord.el@ynb' END AS email
               FROM department dp WHERE dp.id = ANY(v_new) LOOP
      INSERT INTO app_user (institution_id, email, full_name_ar) VALUES (d.institution_id, d.email, 'منسق ' || d.name_ar)
      ON CONFLICT DO NOTHING;
      INSERT INTO user_role (user_id, role, department_id)
      SELECT u.id, 'dept_coordinator', d.id FROM app_user u WHERE u.email = d.email
         AND NOT EXISTS (SELECT 1 FROM user_role r WHERE r.user_id = u.id AND r.department_id = d.id);
    END LOOP;
  END IF;
END $$;
COMMIT;
