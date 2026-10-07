import { api, apiDownload } from './api.js';
import { deptName, go, refreshCycles, route, state } from './app.js';
import { CYCLE_STATUS, RATING, STATUS, VERDICT } from './labels.js';
import { date, h, hasRole, num, pct, promptText, toast } from './ui.js';

const mean = xs => { const v = xs.filter(x => x != null).map(Number); return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null; };
const heatBg = v => v == null ? 'var(--line-2)'
  : `color-mix(in srgb, ${v >= 75 ? 'var(--met)' : v >= 50 ? 'var(--partial)' : 'var(--not-met)'} ${Math.round(25 + v * 0.35)}%, white)`;

function exportButton(cycle) {
  if (!hasRole(state.me, ['quality_dean', 'quality_auditor', 'system_admin'], null, cycle.id)) return null;
  const btn = h('button', { class: 'btn', onclick: async () => {
    btn.disabled = true;
    const label = btn.textContent;
    btn.textContent = 'جارٍ إعداد الملف… (حتى دقيقتين)';
    try {
      const report = await apiDownload(`/cycles/${cycle.id}/export/official`, `نموذج_العمل_الشامل_${cycle.academic_year}.xlsx`);
      toast(`صُدّر الملف: ${num(report?.ratings_written ?? 0)} تقدير و${num(report?.plans_written ?? 0)} خطة تحسين`);
      for (const w of report?.warnings ?? []) toast(w, 'error');
    } catch (ex) { toast(ex.message, 'error'); }
    finally { btn.disabled = false; btn.textContent = label; }
  } }, 'تصدير النموذج الرسمي (Excel)');
  return btn;
}

function cycleControls(cycle, stats) {
  if (!hasRole(state.me, ['quality_dean', 'system_admin'], null, cycle.id)) return exportButton(cycle);
  const run = async (fn, ok) => {
    try { await fn(); toast(ok); await refreshCycles(); await route(); } catch (ex) { toast(ex.message, 'error'); }
  };
  const buttons = [];
  if (cycle.status === 'planning') buttons.push(h('button', { class: 'btn primary', onclick: () => run(
    () => api(`/cycles/${cycle.id}/open`, { method: 'POST' }), 'فُتحت الدورة ووُلّدت التقديرات') }, 'فتح الدورة وتوليد التقديرات'));
  if (cycle.status === 'open') buttons.push(h('button', { class: 'btn', onclick: () => run(
    () => api(`/cycles/${cycle.id}/external-review`, { method: 'POST' }), 'بدأت مرحلة المراجعة الخارجية') }, 'بدء المراجعة الخارجية'));
  if (['open', 'external_review'].includes(cycle.status)) buttons.push(h('button', {
    class: 'btn danger', disabled: stats.final < stats.total,
    title: stats.final < stats.total ? `يلزم اعتماد ${num(stats.total - stats.final)} تقدير نهائياً قبل الإغلاق` : null,
    onclick: async () => {
      const ok = await promptText({ title: 'إغلاق الدورة', label: 'الإغلاق يجمّد كل التقديرات ويثبّت نسخ الشواهد ولا يمكن التراجع عنه. اكتب "إغلاق" للتأكيد', confirm: 'إغلاق الدورة' });
      if (ok !== 'إغلاق') { if (ok !== null) toast('لم يُغلق: كلمة التأكيد غير مطابقة', 'error'); return; }
      await run(() => api(`/cycles/${cycle.id}/close`, { method: 'POST' }), 'أُغلقت الدورة');
    } }, 'إغلاق الدورة'));
  return h('div', { class: 'row' }, exportButton(cycle), buttons);
}

function matrix(assessments, gapIds) {
  const deptRows = assessments.filter(a => a.department_id != null);
  const instRows = assessments.filter(a => a.department_id == null);
  const columns = [];
  const seen = new Set();
  for (const a of deptRows) if (!seen.has(a.requirement_id)) { seen.add(a.requirement_id); columns.push(a); }
  const depts = [...new Set(deptRows.map(a => a.department_id))];
  const byKey = new Map(deptRows.map(a => [`${a.department_id}:${a.requirement_id}`, a]));

  const cell = a => {
    const r = a.eff_rating;
    return h('button', {
      type: 'button', class: `cell r-${r ?? 'none'}${gapIds.has(a.id) ? ' gap-mark' : ''}`,
      title: `${deptName(a.department_id)} · ${a.requirement_code} · ${r ? RATING[r] : 'غير مقدّر'} · ${STATUS[a.status]}`,
      'aria-label': `${deptName(a.department_id)} ${a.requirement_code}: ${r ? RATING[r] : 'غير مقدّر'}`,
      onclick: () => go('workspace', { dept: a.department_id ?? 'inst', a: a.id }),
    });
  };

  const grid = h('div', { class: 'matrix', style: { gridTemplateColumns: `max-content repeat(${columns.length}, minmax(14px, 22px))` } });
  grid.append(h('span'));
  let i = 0;
  while (i < columns.length) {
    const code = columns[i].standard_code;
    let span = 0;
    while (i + span < columns.length && columns[i + span].standard_code === code) span += 1;
    grid.append(h('span', { class: 'stdlabel', style: { gridColumn: `span ${span}` }, title: code }, code));
    i += span;
  }
  for (const d of depts) {
    grid.append(h('span', { class: 'rowlabel' }, deptName(d)));
    for (const c of columns) {
      const a = byKey.get(`${d}:${c.requirement_id}`);
      grid.append(a ? cell(a) : h('span'));
    }
  }
  const inst = instRows.length > 0 && h('div', { class: 'row', style: { marginTop: '.9rem', gap: '.75rem' } },
    h('span', { class: 'rowlabel', style: { fontSize: '.85rem' } }, 'متطلبات المنشأة'),
    h('div', { class: 'matrix', style: { gridTemplateColumns: `repeat(${instRows.length}, 22px)` } }, instRows.map(cell)));

  const legend = h('div', { class: 'legend' },
    ['met', 'partial', 'not_met', 'na'].map(r => h('span', null, h('i', { class: `cell r-${r}` }), RATING[r])),
    h('span', null, h('i', { class: 'cell r-none' }), 'غير مقدّر'),
    h('span', null, h('i', { class: 'cell r-partial gap-mark' }), 'حكم خارجي: غير منطبق أو غير كافٍ'));
  return h('div', null, h('div', { class: 'matrix-wrap' }, grid), inst, legend);
}

export async function renderDashboard() {
  const cycle = state.cycle;
  const base = `/cycles/${cycle.id}`;
  const [deps, stds, rank, gaps, missing, overdue, all, improve, level, badNa] = await Promise.all([
    api(`${base}/reports/departments`), api(`${base}/reports/standards`), api(`${base}/reports/ranking?limit=5`),
    api(`${base}/reports/gaps`), api(`${base}/reports/missing-evidence`), api(`${base}/actions?overdue=true`),
    api(`${base}/assessments`), api(`${base}/reports/improvement`), api(`${base}/reports/pass-level`),
    api(`${base}/reports/invalid-na`),
  ]);

  const stats = {
    total: all.length,
    rated: all.filter(a => a.self_rating).length,
    final: all.filter(a => a.status === 'final').length,
  };
  const deptOnly = deps.filter(d => d.department_id != null);
  const overall = mean(deptOnly.map(d => d.eff_pct));
  const gapIds = new Set(gaps.map(g => g.assessment_id));

  const head = h('div', { class: 'dash-head' },
    h('div', null, h('h1', null, cycle.title_ar),
      h('p', { class: 'muted' }, `${CYCLE_STATUS[cycle.status]} · من ${date(cycle.starts_on)} إلى ${date(cycle.ends_on)}`)),
    cycleControls(cycle, stats));

  if (!all.length) {
    return h('div', null, head, h('div', { class: 'panel empty' },
      h('h2', null, 'لم تُولَّد تقديرات لهذه الدورة بعد'),
      h('p', null, 'افتح الدورة لتوليد سجل تقدير لكل متطلب في كل قسم مشارك.')));
  }

  const figures = h('div', { class: 'figures' },
    h('div', { class: 'figure' }, h('span', { class: 'num' }, pct(overall)), h('span', { class: 'lbl' }, 'متوسط الاستيفاء في الأقسام')),
    h('div', { class: 'figure' }, h('span', { class: 'num' }, num(stats.rated), h('small', null, ` / ${num(stats.total)}`)), h('span', { class: 'lbl' }, 'متطلبات مقدّرة')),
    h('div', { class: 'figure' }, h('span', { class: 'num' }, num(stats.final), h('small', null, ` / ${num(stats.total)}`)), h('span', { class: 'lbl' }, 'معتمدة نهائياً')),
    h('div', { class: `figure${missing.length ? ' alert' : ''}` }, h('span', { class: 'num' }, num(missing.length)), h('span', { class: 'lbl' }, 'متطلبات تنقصها شواهد')),
    h('div', { class: `figure${overdue.length ? ' alert' : ''}` }, h('span', { class: 'num' }, num(overdue.length)), h('span', { class: 'lbl' }, 'إجراءات تحسين متأخرة')),
    badNa.length > 0 && h('div', { class: 'figure alert' }, h('span', { class: 'num' }, num(badNa.length)), h('span', { class: 'lbl' }, '«لا ينطبق» غير مقبول وفق النموذج')),
    h('div', { class: `figure${level.passed === false ? ' alert' : ''}`, title: 'وفق صيغة النموذج: لا يقل أي قسم عن 89.5% في أي معيار رئيسي بعد اكتمال التقييم الخارجي' },
      h('span', { class: 'num' }, level.passed === null ? '—' : level.passed ? 'مجتاز' : 'غير مجتاز'),
      h('span', { class: 'lbl' }, level.passed === null ? 'مستوى الاجتياز (بانتظار اكتمال التقييم الخارجي)' : 'مستوى الاجتياز للمستوى الثالث')));

  const matrixPanel = h('section', { class: 'panel' },
    h('header', null, h('h2', null, 'خريطة الاستيفاء'),
      h('span', { class: 'faint' }, 'كل مربع متطلب؛ اضغطه لفتحه في مساحة القسم')),
    matrix(all, gapIds));

  const deptTable = h('section', { class: 'panel' },
    h('header', null, h('h2', null, 'الأقسام'), h('span', { class: 'faint' }, 'الشريط: الاستيفاء الفعلي، والعلامة: التقييم الذاتي')),
    h('div', { class: 'matrix-wrap' }, h('table', { class: 'data' },
      h('thead', null, h('tr', null, ['القسم', 'الاستيفاء', 'ذاتي', 'خارجي', 'فعلي', 'متحقق', 'يحتاج تحسين', 'لا ينطبق', 'غير مقدّر', 'الإنجاز']
        .map(t => h('th', null, t)))),
      h('tbody', null, deps.map(d => h('tr', null,
        h('td', null, h('a', { href: `#/workspace?dept=${d.department_id ?? 'inst'}` }, d.department_name)),
        h('td', null, h('div', { class: 'bar', role: 'img', 'aria-label': `الاستيفاء ${pct(d.eff_pct)}` },
          h('i', { style: { width: `${d.eff_pct ?? 0}%` } }),
          d.self_pct != null && h('b', { style: { insetInlineStart: `calc(${d.self_pct}% - 1px)` } }))),
        h('td', null, pct(d.self_pct)), h('td', null, pct(d.ext_pct)), h('td', null, h('strong', null, pct(d.eff_pct))),
        h('td', null, num(d.met_count)), h('td', null, num(d.needs_improvement_count)), h('td', null, num(d.na_count)),
        h('td', null, num(d.unrated_count)), h('td', null, pct(d.workflow_completion_pct))))))));

  const stdCodes = [...new Map(stds.map(s => [s.standard_code, s.standard_title])).entries()]
    .sort(([a], [b]) => a.localeCompare(b, 'en', { numeric: true }));
  const stdDepts = [...new Set(stds.map(s => s.department_id))];
  const stdMap = new Map(stds.map(s => [`${s.department_id}:${s.standard_code}`, s]));
  const heatPanel = h('section', { class: 'panel' },
    h('header', null, h('h2', null, 'المعايير الرئيسية في كل قسم')),
    h('div', { class: 'matrix-wrap' }, h('table', { class: 'data' },
      h('thead', null, h('tr', null, h('th', null, 'القسم'), stdCodes.map(([code, title]) => h('th', { title }, `${code} ${title}`)))),
      h('tbody', null, stdDepts.map(dep => h('tr', null, h('td', null, deptName(dep)),
        stdCodes.map(([code]) => {
          const s = stdMap.get(`${dep}:${code}`);
          const v = s?.eff_pct == null ? null : Number(s.eff_pct);
          return h('td', null, s ? h('div', { class: 'heat', style: { background: heatBg(v) } }, pct(v)) : '');
        })))))));

  const rankList = (rows, empty) => rows.length
    ? h('ul', { class: 'rank' }, rows.map(r => h('li', null, h('span', null, `${r.sub_standard_code} ${r.sub_standard_title}`), h('strong', null, pct(r.eff_pct)))))
    : h('p', { class: 'muted' }, empty);
  const ranking = h('div', { class: 'cols2' },
    h('section', { class: 'panel' }, h('header', null, h('h2', null, 'مجال القوة: أفضل خمسة معايير فرعية')), rankList(rank.best, 'لا توجد تقديرات كافية بعد.')),
    h('section', { class: 'panel' }, h('header', null, h('h2', null, 'مجال التحسين: أضعف خمسة معايير فرعية')), rankList(rank.worst, 'لا توجد تقديرات كافية بعد.')));

  const over = gaps;
  const followUp = h('div', { class: 'cols2' },
    h('section', { class: 'panel' },
      h('header', null, h('h2', null, 'أحكام بعدم الانطباق'), h('span', { class: 'faint' }, `${num(over.length)} تقييم ذاتي لم يؤكده المقيّم`)),
      over.length ? h('ul', { class: 'rank' }, over.slice(0, 8).map(g => h('li', null,
        h('a', { href: `#/workspace?dept=${g.department_id ?? 'inst'}&a=${g.assessment_id}` }, `${deptName(g.department_id)} · ${g.requirement_code}`),
        h('span', { class: 'faint' }, `${RATING[g.self_rating]} — ${VERDICT[g.ext_verdict]}`))))
        : h('p', { class: 'muted' }, 'لا توجد فجوات حتى الآن.')),
    h('section', { class: 'panel' },
      h('header', null, h('h2', null, 'إجراءات تحسين متأخرة')),
      overdue.length ? h('ul', { class: 'rank' }, overdue.map(a => h('li', null,
        h('a', { href: `#/plans?dept=${a.department_id ?? 'inst'}&a=${a.id}` }, a.requirement_code ?? a.title_ar,
          h('span', { class: 'faint' }, ` · ${a.owner_name ?? a.owner_label ?? 'بلا مسؤول'} · ${deptName(a.department_id)}`)),
        h('strong', { style: { color: 'var(--not-met)' } }, `${num(a.days_overdue)} يوم`))))
        : h('p', { class: 'muted' }, 'كل الإجراءات ضمن مواعيدها.')));

  const improvePanel = h('section', { class: 'panel' },
    h('header', null, h('h2', null, 'خطط التحسين'),
      h('span', { class: 'faint' }, 'نسبة الإغلاق = المغلقة بعد تحقق مستقل من مجموع الخطط غير الملغاة')),
    improve.length ? h('div', { class: 'matrix-wrap' }, h('table', { class: 'data' },
      h('thead', null, h('tr', null, ['القسم', 'الخطط', 'لدى القسم', 'بانتظار الملاءمة', 'قيد التنفيذ', 'بانتظار التحقق', 'مغلقة', 'متأخرة', 'نسبة الإغلاق']
        .map(t => h('th', null, t)))),
      h('tbody', null, improve.map(r => h('tr', null,
        h('td', null, h('a', { href: `#/plans?dept=${r.department_id ?? 'inst'}&filter=all` }, r.department_name)),
        h('td', null, num(r.total)), h('td', null, num(r.with_department)), h('td', null, num(r.under_review)),
        h('td', null, num(r.in_progress)), h('td', null, num(r.awaiting_verification)), h('td', null, num(r.verified)),
        h('td', { style: r.overdue ? { color: 'var(--not-met)', fontWeight: 600 } : null }, num(r.overdue)),
        h('td', null, h('div', { class: 'bar', role: 'img', 'aria-label': `نسبة الإغلاق ${pct(r.closure_pct)}` },
          h('i', { style: { width: `${r.closure_pct ?? 0}%` } })), h('span', { class: 'faint' }, pct(r.closure_pct))))))))
    : h('p', { class: 'muted' }, 'لا توجد خطط تحسين بعد. تتولد تلقائياً عند الاعتماد النهائي لمتطلب «متحقق جزئي» أو «غير متحقق».'));

  return h('div', null, head, figures, matrixPanel, deptTable, heatPanel, ranking, improvePanel, followUp);
}
