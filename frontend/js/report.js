// التقرير النهائي: لوحة نتائج المعايير الرئيسية والفرعية للقسم أو للكلية، وخطط التحسين المطلوبة
import { api } from './api.js';
import { deptName, go, parseRoute, state } from './app.js';
import { ACTION_STATUS, ADEQUACY } from './labels.js';
import { date, h, num, pct } from './ui.js';

const PASS = 89.5;                       // حد الاجتياز في النموذج الرسمي
const ORDINAL = ['الأول', 'الثاني', 'الثالث', 'الرابع', 'الخامس', 'السادس', 'السابع', 'الثامن'];
const BASIS = { eff: 'النتيجة النهائية', self: 'التقييم الذاتي', ext: 'التقييم الخارجي' };
const NS = 'http://www.w3.org/2000/svg';

function s(tag, attrs = {}, ...kids) {
  const el = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) if (v != null) el.setAttribute(k, v);
  el.append(...kids.filter(k => k != null));
  return el;
}
const mean = xs => { const v = xs.filter(x => x != null).map(Number); return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null; };
const tone = v => v == null ? 'none' : v >= PASS ? 'good' : v >= 50 ? 'mid' : 'bad';

// عدّاد نصف دائري بثلاث مناطق (ضعيف < 50 ≤ يحتاج تحسين < 89.5 ≤ متحقق) ومؤشر عند القيمة
function gauge(value) {
  const cx = 100, cy = 100, r = 80, w = 26;
  const pt = (p, rad = r) => { const a = Math.PI * (1 - p / 100); return [cx + rad * Math.cos(a), cy - rad * Math.sin(a)]; };
  const arc = (a, b) => { const [x1, y1] = pt(a), [x2, y2] = pt(b); return `M${x1} ${y1} A${r} ${r} 0 0 1 ${x2} ${y2}`; };
  const v = value == null ? 0 : Math.max(0, Math.min(100, Number(value)));
  return s('svg', { viewBox: '0 0 200 115', class: 'gauge', role: 'img', 'aria-label': `النسبة ${pct(value)}` },
    s('path', { d: arc(0, 50), class: 'z-bad', 'stroke-width': w, fill: 'none' }),
    s('path', { d: arc(50, PASS), class: 'z-mid', 'stroke-width': w, fill: 'none' }),
    s('path', { d: arc(PASS, 100), class: 'z-good', 'stroke-width': w, fill: 'none' }),
    v > 0.5 && s('path', { d: arc(0, v), class: `z-val t-${tone(value)}`, 'stroke-width': w - 12, fill: 'none', 'stroke-linecap': 'round', pathLength: 100 }),
    s('text', { x: 18, y: 113, class: 'gl' }, '0'), s('text', { x: 182, y: 113, class: 'gl' }, '100'),
    value != null && s('line', { x1: cx, y1: cy, x2: cx - (r - 22), y2: cy, class: 'needle', style: `--a:${v * 1.8}deg` }),
    s('circle', { cx, cy, r: 6, class: 'hub' }));
}

function ring(value, size = 92) {
  const r = 40, c = 2 * Math.PI * r, v = value == null ? 0 : Math.max(0, Math.min(100, Number(value)));
  return h('div', { class: `ring t-${tone(value)}`, style: { width: `${size}px`, height: `${size}px` } },
    s('svg', { viewBox: '0 0 100 100', 'aria-hidden': 'true' },
      s('circle', { cx: 50, cy: 50, r, class: 'track' }),
      s('circle', { cx: 50, cy: 50, r, class: 'val', 'stroke-dasharray': `${(c * v) / 100} ${c}`, transform: 'rotate(-90 50 50)' })),
    h('b', { 'data-v': value == null ? '' : Math.round(Number(value)) }, pct(value == null ? null : Math.round(Number(value)))));
}

// حركة المؤشرات: تمتلئ العدادات والحلقات من الصفر وتعدّ الأرقام، وتتكرر كل 5 ثوانٍ
const PERIOD = 5000;
// عند الطباعة تُفتح مجموعات الخطط المطوية حتى تظهر كاملة في PDF
window.addEventListener('beforeprint', () => document.querySelectorAll('.final-report details:not([open])').forEach(d => {
  d.open = true; d.dataset.printOpened = '1'; }));
window.addEventListener('afterprint', () => document.querySelectorAll('.final-report details[data-print-opened]').forEach(d => {
  d.open = false; delete d.dataset.printOpened; }));
function countUp(el, to, ms = 1200) {
  const t0 = performance.now();
  const step = t => { const k = Math.min(1, (t - t0) / ms), e = 1 - (1 - k) ** 3;
    el.textContent = pct(Math.round(to * e)); if (k < 1) requestAnimationFrame(step); };
  requestAnimationFrame(step);
}
function replay(section, stagger) {
  const items = [...section.querySelectorAll('.anim-item')];
  items.forEach(x => x.classList.remove('play'));
  void section.offsetWidth;                       // إعادة تشغيل حركة CSS
  items.forEach((x, i) => setTimeout(() => {
    x.classList.add('play');
    const n = x.querySelector('[data-v]');
    if (n && n.dataset.v !== '') countUp(n, Number(n.dataset.v));
  }, i * stagger));
}
function animateEvery(root, sections) {
  const run = () => sections.forEach(([sec, stagger]) => replay(sec, stagger));
  requestAnimationFrame(run);
  const id = setInterval(() => {
    if (!root.isConnected) { clearInterval(id); return; }   // غادر المستخدم الصفحة
    if (!document.hidden) run();
  }, PERIOD);
}

// جدول الأعداد بعرض ثابت يدخل صفحة A4: صف لكل معيار بارتفاع موحّد، وعمود لكل قسم.
// قسم واحد: أعمدة متحقق/غير متحقق/يحتاج تحسين/المجموع/النسبة. عدة أقسام: خلية مدمجة بثلاثة أرقام ملوّنة لكل قسم.
function countsTable(title, rows, keyOf, labelOf, depts, subs) {
  const cell = (d, k) => {
    const xs = subs.filter(x => x.department_id === d && keyOf(x) === k);
    const sum = f => xs.reduce((a, x) => a + Number(x[f] ?? 0), 0);
    return { met: sum('met_count'), not: sum('not_met_count'), mid: sum('partial_count') };
  };
  const label = k => h('th', { scope: 'row' }, h('div', { class: 'rowlabel' }, labelOf(k)));
  if (depts.length === 1) {
    const d = depts[0];
    const body = rows.map(k => {
      const c = cell(d, k), all = c.met + c.not + c.mid;
      return h('tr', null, label(k), h('td', { class: 'n-good' }, num(c.met)), h('td', { class: 'n-bad' }, num(c.not)),
        h('td', { class: 'n-mid' }, num(c.mid)), h('td', { class: 'n-tot' }, num(all)),
        h('td', null, all ? h('span', { class: 'pctbar' }, h('i', { style: { width: `${Math.round(c.met / all * 100)}%` } }),
          h('b', null, pct(Math.round(c.met / all * 100)))) : '—'));
    });
    return h('div', { class: 'table-wrap' }, h('table', { class: 'data counts one' },
      h('colgroup', null, h('col', { class: 'c-label' }), [1, 2, 3, 4].map(() => h('col', { class: 'c-num' })), h('col', { class: 'c-pct' })),
      h('thead', null, h('tr', null, h('th', null, title), h('th', { class: 'c-good' }, 'متحقق'), h('th', { class: 'c-bad' }, 'غير متحقق'),
        h('th', { class: 'c-mid' }, 'يحتاج تحسين'), h('th', null, 'المجموع'), h('th', null, 'نسبة التحقق'))),
      h('tbody', null, body)));
  }
  const body = rows.map(k => h('tr', null, label(k), depts.map(d => {
    const c = cell(d, k);
    return h('td', null, h('span', { class: 'trio' }, h('b', { class: 'n-good', title: 'متحقق' }, num(c.met)),
      h('b', { class: 'n-bad', title: 'غير متحقق' }, num(c.not)), h('b', { class: 'n-mid', title: 'يحتاج تحسين' }, num(c.mid))));
  })));
  return h('div', { class: 'table-wrap' },
    h('p', { class: 'trio-legend' }, 'في كل خلية: ', h('b', { class: 'n-good' }, 'متحقق'), ' · ', h('b', { class: 'n-bad' }, 'غير متحقق'),
      ' · ', h('b', { class: 'n-mid' }, 'يحتاج تحسين')),
    h('table', { class: 'data counts multi', style: { '--cols': depts.length } },
      h('colgroup', null, h('col', { class: 'c-label' }), depts.map(() => h('col', { class: 'c-dept' }))),
      h('thead', null, h('tr', null, h('th', null, title), depts.map(d => h('th', { class: 'grp' }, deptName(d))))),
      h('tbody', null, body)));
}

function reasons(p) {
  return h('div', { class: 'chips' },
    p.not_implemented && h('span', { class: 'chip c-bad' }, 'غير منفذ'),
    p.partially_implemented && h('span', { class: 'chip c-mid' }, 'منفذ جزئياً'),
    p.evidence_issue && h('span', { class: 'chip c-mid' }, p.ext_verdict === 'insufficient' ? 'الشاهد غير كافٍ' : 'الشاهد غير متوفر'),
    p.plan_not_supporting && h('span', { class: 'chip c-bad' }, `خطة التحسين غير داعمة (${ADEQUACY[p.adequacy]})`));
}

function planTable(list) {
  return h('div', { class: 'table-wrap' }, h('table', { class: 'data plan-table' },
      h('thead', null, h('tr', null, h('th', null, 'المتطلب'), h('th', null, 'الملاحظة'),
        h('th', null, 'توصيات المقيّم الخارجي'), h('th', null, 'الإجراءات التحسينية'), h('th', null, 'المسؤول'),
        h('th', null, 'تاريخ الاكتمال'), h('th', null, 'شاهد التحسين'), h('th', null, 'الحالة'))),
      h('tbody', null, list.map(p => h('tr', null,
        h('td', { title: p.requirement_text }, h('b', null, p.requirement_code), h('div', { class: 'muted clamp' }, p.requirement_text)),
        h('td', null, reasons(p)),
        h('td', null, p.ext_recommendation || '—'),
        h('td', null, p.action_ar || h('span', { class: 'muted' }, 'لم تُعبّأ')),
        h('td', null, p.owner_name || p.owner_label || '—'),
        h('td', null, date(p.due_date)),
        h('td', null, p.completion_evidence_id ? 'مرفق' : '—'),
        h('td', null, p.action_id
          ? h('button', { class: 'btn small', onclick: () => go('plans', { dept: p.department_id ?? 'inst', a: p.action_id }) },
              `${ACTION_STATUS[p.action_status] ?? p.action_status} · فتح`)
          : h('span', { class: 'muted' }, 'تُنشأ عند الاعتماد النهائي')))))));
}

// في نطاق الكلية: مجموعة قابلة للطي لكل قسم
function planGroups(list, scopeKey) {
  if (scopeKey !== 'all') return planTable(list);
  const groups = new Map();
  for (const p of list) { if (!groups.has(p.department_id)) groups.set(p.department_id, []); groups.get(p.department_id).push(p); }
  return h('div', { class: 'plan-groups' }, [...groups].map(([d, xs]) => h('details', null,
    h('summary', null, h('b', null, deptName(d)), ` — ${num(xs.length)} متطلب`,
      xs.some(p => !p.action_id) && h('span', { class: 'chip c-bad' }, `${num(xs.filter(p => !p.action_id).length)} دون خطة`)),
    planTable(xs))));
}

export async function renderReport() {
  const cycle = state.cycle, base = `/cycles/${cycle.id}`;
  const { params } = parseRoute();
  const [stds, subs, plans] = await Promise.all([
    api(`${base}/reports/standards`), api(`${base}/reports/sub-standards`), api(`${base}/reports/final-plans`)]);

  const depts = [...new Set(subs.map(x => x.department_id).filter(d => d != null))];
  const canCollege = depts.length > 1;
  const scopeKey = params.dept && depts.includes(Number(params.dept)) ? Number(params.dept) : canCollege ? 'all' : depts[0];
  const basis = BASIS[params.basis] ? params.basis : 'eff';
  const field = `${basis}_pct`;
  const inScope = x => (scopeKey === 'all' ? x.department_id != null : x.department_id === scopeKey);

  // نسبة الكلية = متوسط نسب الأقسام (كما في لوحة المؤشرات)
  const stdCodes = [...new Map(stds.map(x => [x.standard_code, x.standard_title])).entries()];
  const stdVal = code => mean(stds.filter(x => x.standard_code === code && inScope(x)).map(x => x[field]));
  const subList = [...new Map(subs.map(x => [x.sub_standard_code, x])).values()]
    .sort((a, b) => a.sub_standard_code.localeCompare(b.sub_standard_code, 'en', { numeric: true }));
  const subVal = code => mean(subs.filter(x => x.sub_standard_code === code && inScope(x)).map(x => x[field]));
  const overall = mean(stdCodes.map(([c]) => stdVal(c)));
  const ranked = subList.map(x => ({ ...x, v: subVal(x.sub_standard_code) })).filter(x => x.v != null);
  const best = [...ranked].sort((a, b) => b.v - a.v).slice(0, 5);
  const worst = [...ranked].sort((a, b) => a.v - b.v).slice(0, 5);
  const scopeName = scopeKey === 'all' ? 'الكلية (جميع الأقسام)' : deptName(scopeKey);

  const controls = h('div', { class: 'row report-controls' },
    h('label', null, 'النطاق ', h('select', { onchange: e => go('report', { dept: e.target.value, basis }) },
      canCollege && h('option', { value: 'all', selected: scopeKey === 'all' }, 'الكلية (جميع الأقسام)'),
      depts.map(d => h('option', { value: String(d), selected: scopeKey === d }, deptName(d))))),
    h('label', null, 'أساس الاحتساب ', h('select', { onchange: e => go('report', { dept: scopeKey, basis: e.target.value }) },
      Object.entries(BASIS).map(([k, v]) => h('option', { value: k, selected: k === basis }, v)))),
    h('button', { class: 'btn', onclick: () => window.print() }, 'طباعة / PDF'));

  const inSubs = subs.filter(inScope);
  const tot = f => inSubs.reduce((a, x) => a + Number(x[f] ?? 0), 0);
  const myPlansCount = plans.filter(p => (scopeKey === 'all' ? p.department_id != null : p.department_id === scopeKey)).length;
  const kpi = (label, value, cls) => h('div', { class: `kpi ${cls}` }, h('b', null, value), h('span', null, label));
  const head = h('header', { class: 'hero' },
    h('div', { class: 'hero-top' },
      h('div', null, h('span', { class: 'eyebrow' }, 'نظام جودة التدريب · المستوى الثاني'),
        h('h1', null, 'التقرير النهائي'),
        h('p', null, `${cycle.title_ar} · ${scopeName} · ${BASIS[basis]}`)), controls),
    h('div', { class: 'kpis' },
      kpi('النسبة العامة', pct(overall == null ? null : Math.round(overall)), `t-${tone(overall)}`),
      kpi('متطلبات متحققة', num(tot('met_count')), 'k-good'),
      kpi('تحتاج تحسين', num(tot('partial_count')), 'k-mid'),
      kpi('غير متحققة', num(tot('not_met_count')), 'k-bad'),
      kpi('خطط تحسين مطلوبة', num(myPlansCount), 'k-plan')));
  const block = (...kids) => h('div', { class: 'rep-block' }, ...kids);
  const title = (n, t, sub) => h('div', { class: 'sec-title' }, h('i', null, n), h('div', null, h('h2', null, t), sub && h('p', null, sub)));

  const gauges = h('section', { class: 'gauges' }, stdCodes.map(([code, title], i) => {
    const v = stdVal(code);
    return h('article', { class: `gcard anim-item t-${tone(v)}` }, h('h3', null, title), gauge(v),
      h('strong', { 'data-v': v == null ? '' : Math.round(v) }, pct(v == null ? null : Math.round(v))), h('span', { class: 'tag' }, `المعيار ${ORDINAL[i] ?? code}`));
  }));

  const rings = h('section', { class: 'card rings' }, subList.map(x =>
    h('div', { class: 'ringcell anim-item', title: x.sub_standard_title },
      h('bdi', { class: 'ssub-code' }, x.sub_standard_code), h('small', null, x.sub_standard_title), ring(subVal(x.sub_standard_code)))));

  const rankList = (items, cls, label) => h('div', { class: `rankbox ${cls}` }, h('h3', null, label),
    items.length ? h('ol', null, items.map(x => h('li', null, h('span', null, h('bdi', { class: 'ssub-code' }, x.sub_standard_code), ' ', x.sub_standard_title), h('b', null, pct(Math.round(x.v))))))
      : h('p', { class: 'muted' }, 'لا توجد تقديرات بعد'));
  const summary = h('section', { class: 'summary3' },
    rankList(best, 'good', 'مجال القوة (أفضل خمسة معايير فرعية)'),
    h('div', { class: 'overall anim-item' }, ring(overall, 180), h('span', null, `العام التدريبي ${cycle.academic_year}`),
      h('span', { class: 'muted' }, overall == null ? '' : overall >= PASS ? 'مجتاز' : 'دون حد الاجتياز (89.5%)')),
    rankList(worst, 'bad', 'مجال التحسين (أضعف خمسة معايير فرعية)'));

  const tDepts = scopeKey === 'all' ? depts : [scopeKey];
  const tables = h('section', { class: 'card' },
    countsTable('المعيار الرئيسي', stdCodes.map(([c]) => c), x => x.standard_code,
      c => stdCodes.find(([k]) => k === c)?.[1] ?? c, tDepts, subs),
    countsTable('المعيار الفرعي', subList.map(x => x.sub_standard_code), x => x.sub_standard_code,
      c => { const x = subList.find(y => y.sub_standard_code === c); return h('span', null, h('bdi', { class: 'ssub-code' }, c), ' ', x?.sub_standard_title ?? ''); }, tDepts, subs));

  const myPlans = plans.filter(p => (scopeKey === 'all' ? p.department_id != null : p.department_id === scopeKey));
  const noPlan = myPlans.filter(p => !p.action_id).length;
  const plansSec = h('section', { class: 'card' },
    h('div', { class: 'row', style: { justifyContent: 'space-between' } },
      h('h3', { class: 'card-h' }, `المتطلبات التي عليها ملاحظات (${num(myPlans.length)})`),
      noPlan > 0 && h('span', { class: 'chip c-bad' }, `${num(noPlan)} متطلب دون خطة بعد`)),
    h('p', { class: 'muted' }, 'تُعد خطة التحسين لكل متطلب عليه ملاحظة: غير منفذ، أو الشاهد غير متوفر أو غير كافٍ، أو خطة التحسين غير داعمة. '
      + 'الخطة تتولد تلقائياً عند الاعتماد النهائي للتقدير، ويعبّئها القسم من صفحة «خطط التحسين».'),
    myPlans.length ? planGroups(myPlans, scopeKey)
      : h('p', { class: 'empty' }, 'لا توجد متطلبات عليها ملاحظات في هذا النطاق.'));

  // للطباعة فقط: ترويسة رسمية في أول التقرير، وخانات الاعتماد في آخره
  const today = new Date();
  const issued = [today.toLocaleDateString('ar-SA-u-ca-islamic-umalqura-nu-latn', { day: 'numeric', month: 'long', year: 'numeric' }), h('br'),
    today.toLocaleDateString('ar-SA-u-ca-gregory-nu-latn', { day: 'numeric', month: 'long', year: 'numeric' })];
  const letter = h('header', { class: 'print-letter' },
    h('div', { class: 'pl-org' }, h('img', { src: 'img/tvtc-logo.png', alt: 'المؤسسة العامة للتدريب التقني والمهني' }),
      h('div', null, h('b', null, 'المؤسسة العامة للتدريب التقني والمهني'), h('span', null, state.me.institution_name ?? 'الكلية التقنية التطبيقية بينبع'),
        h('span', null, 'وكالة الجودة'))),
    h('div', { class: 'pl-title' }, h('h1', null, 'التقرير النهائي للتقييم'), h('p', null, `${cycle.title_ar} · ${scopeName}`),
      h('p', null, `أساس الاحتساب: ${BASIS[basis]}`)),
    h('dl', { class: 'pl-meta' }, h('dt', null, 'تاريخ الإصدار'), h('dd', null, issued),
      h('dt', null, 'العام التدريبي'), h('dd', null, cycle.academic_year ?? '—'),
      h('dt', null, 'حد الاجتياز'), h('dd', null, '89.5%')));
  const sign = (role) => h('div', { class: 'sig' }, h('b', null, role), h('span', null, 'الاسم: '), h('span', null, 'التوقيع: '), h('span', null, 'التاريخ: '));
  const signatures = h('section', { class: 'print-sign' }, h('h3', null, 'الاعتماد'),
    h('div', { class: 'sig-row' }, scopeKey === 'all'
      ? [sign('إعداد: مدقق الجودة'), sign('مراجعة: وكيل الجودة'), sign('اعتماد: عميد الكلية')]
      : [sign('إعداد: منسق الجودة بالقسم'), sign('مراجعة: رئيس القسم'), sign('اعتماد: وكيل الجودة')]));

  const page = h('div', { class: 'final-report' }, letter, head,
    block(title('١', 'المعايير الرئيسية', 'حد الاجتياز 89.5% — الأخضر مجتاز، والبرتقالي يحتاج تحسيناً، والأحمر أقل من 50%'), gauges),
    block(title('٢', 'المعايير الفرعية'), rings),
    block(title('٣', 'مجالات القوة والتحسين'), summary),
    h('div', { class: 'rep-block flow' }, title('٤', 'أعداد المتطلبات حسب نتيجة التقييم'), tables),
    h('div', { class: 'rep-block flow' }, title('٥', 'المتطلبات التي تتطلب خطة تحسينية'), plansSec), signatures);
  animateEvery(page, [[gauges, 120], [rings, 45], [summary, 0]]);
  return page;
}
