// التقارير الدورية: تقويم أعمال جودة التدريب 1448هـ أسبوعاً بأسبوع. بنود القسم المرتبطة بنموذج تُحسب حالتها من نموذج القسم
// في «الخطط والتقارير» ويجمعها وكيل الجودة من «تقارير الكلية»؛ والبنود الأخرى تُؤشَّر منجزة برابط الشاهد أو «لا ينطبق».
import { api } from './api.js';
import { deptName, go, parseRoute, state } from './app.js';
import { date, h, mount, num, toast } from './ui.js';

const SEM = { 1: 'الفصل التدريبي الأول', 2: 'الفصل التدريبي الثاني' };
const ORD = ['قبل بدء التدريب', 'الأول', 'الثاني', 'الثالث', 'الرابع', 'الخامس', 'السادس', 'السابع', 'الثامن', 'التاسع', 'العاشر',
  'الحادي عشر', 'الثاني عشر', 'الثالث عشر', 'الرابع عشر', 'الخامس عشر', 'السادس عشر', 'السابع عشر', 'الثامن عشر', 'التاسع عشر'];
const weekName = n => (n ? `الأسبوع ${ORD[n] ?? n}` : ORD[0]);
const ST = { done: 'منجز', na: 'لا ينطبق', started: 'بدأ التعبئة', late: 'متأخر', now: 'هذا الأسبوع', upcoming: 'قادم' };
const FILTERS = [['', 'كل البنود'], ['now', 'هذا الأسبوع'], ['late', 'متأخر'], ['dept', 'بنود الأقسام'], ['college', 'بنود وكالة الجودة']];

const field = (label, input) => h('div', { class: 'field' }, h('label', null, label), input);

function openDialog(title, body, onSubmit, submitLabel = 'حفظ') {
  const dlg = document.getElementById('dialog');
  const err = h('p', { class: 'faint', style: { color: 'var(--not-met)' } });
  const form = h('form', { method: 'dialog', class: 'cal-form qw-form', onsubmit: async e => {
    e.preventDefault();
    try { await onSubmit(); dlg.close(); } catch (ex) { err.textContent = ex.message; }
  } }, h('h2', null, title), body, err,
  h('div', { class: 'row end' }, h('button', { type: 'button', class: 'btn', onclick: () => dlg.close() }, 'إغلاق'),
    onSubmit && h('button', { class: 'btn primary' }, submitLabel)));
  mount(dlg, form);
  dlg.showModal();
}

// موقع الفصل المعروض من اليوم: الأسابيع حتى passedUpTo فاتت، وcw هو الأسبوع الجاري
function refWeek(now, sem) {
  if (!now) return { cw: -1, passedUpTo: -1 };
  if (now.semester > sem) return { cw: -1, passedUpTo: 99 };
  if (now.semester < sem) return { cw: -1, passedUpTo: -1 };
  return now.in_break ? { cw: -1, passedUpTo: now.week_no } : { cw: now.week_no, passedUpTo: now.week_no - 1 };
}

// حالة البند لقسم (أو للكلية: deptId = 0)
function itemState(it, deptId, ref) {
  if (it.preset_done) return 'done';
  const m = it.marks[String(deptId)];
  if (m) return m.status;
  const f = it.form?.departments?.[String(deptId)];
  if (f?.state === 'filled') return 'done';
  const timed = it.week_no <= ref.passedUpTo ? 'late' : it.week_no === ref.cw ? 'now' : 'upcoming';
  return f?.state === 'started' && timed !== 'late' ? 'started' : timed;
}

function markDialog(cycle, it, deptId, canMark, reload) {
  const m = it.marks[String(deptId ?? 0)];
  const url = h('input', { class: 'input', type: 'url', dir: 'ltr', placeholder: 'https://...sharepoint.com/...', value: m?.url ?? '' });
  const note = h('textarea', { class: 'input', rows: 2 }, m?.note_ar ?? '');
  const na = h('input', { type: 'checkbox', checked: m?.status === 'na', onchange: () => { url.disabled = na.checked; } });
  url.disabled = na.checked;
  const q = deptId ? `?department_id=${deptId}` : '';
  const undo = async () => {
    try {
      await api(`/cycles/${cycle.id}/periodic/${it.key}/progress${q}`, { method: 'DELETE' });
      document.getElementById('dialog').close(); toast('أُلغي التأشير'); reload();
    } catch (ex) { toast(ex.message, 'error'); }
  };
  openDialog(deptId ? deptName(deptId) : 'وكالة الجودة', [
    h('p', { class: 'muted' }, it.title_ar),
    h('p', null, h('b', null, 'الموعد: '), `${weekName(it.week_no)} من ${SEM[it.semester]}${it.starts_on ? ` (يبدأ ${date(it.starts_on)})` : ''}`),
    m && h('p', { class: 'tl-done-note' }, `${ST[m.status]} — ${m.done_by_name ?? ''} في ${date(m.done_at)}`,
      m.url && [' · ', h('a', { href: m.url, target: '_blank', rel: 'noopener' }, 'فتح الشاهد ↗')], m.note_ar && ` · ${m.note_ar}`),
    canMark && [
      field('رابط الشاهد (اختياري، من مجلد الشواهد على OneDrive / SharePoint)', url),
      field('ملاحظات', note),
      h('label', { class: 'qw-na' }, na, ' لا ينطبق (اذكر السبب في الملاحظات)'),
      m && h('button', { type: 'button', class: 'btn small', onclick: undo }, 'إلغاء التأشير')]],
  canMark ? async () => {
    const r = await api(`/cycles/${cycle.id}/periodic/${it.key}/progress`, { method: 'POST',
      body: { department_id: deptId || null, url: na.checked ? null : url.value, note_ar: note.value || null, not_applicable: na.checked } });
    toast(r.status === 'na' ? 'سُجّل «لا ينطبق»' : 'أُشّر منجزاً');
    reload();
  } : null, 'تأشير منجز');
}

function deptsDialog(it, departments, ref, open) {
  openDialog(`${weekName(it.week_no)} · ${SEM[it.semester]}`, [
    h('p', { class: 'muted' }, it.title_ar),
    h('div', { class: 'qw-depts' }, departments.map(d => {
      const s = itemState(it, d.id, ref);
      const f = it.form?.departments?.[String(d.id)];
      return h('button', { type: 'button', class: `qw-dot tl-${s}`, onclick: () => { document.getElementById('dialog').close(); open(d.id); } },
        h('span', null, d.name_ar), h('i', null, ST[s] + (f?.rows > 1 ? ` (${num(f.rows)})` : '')));
    }))], null);
}

export async function renderPeriodic() {
  const cycle = state.cycle;
  const { params } = parseRoute();
  const data = await api(`/cycles/${cycle.id}/periodic`);
  const { departments, items, weeks, now, can_manage: canManage } = data;
  const deptIds = departments.map(d => d.id);
  const dept = deptIds.includes(Number(params.dept)) ? Number(params.dept) : deptIds.length === 1 && !canManage ? deptIds[0] : null;
  const sem = [1, 2].includes(Number(params.sem)) ? Number(params.sem) : (now?.semester ?? 1);
  const filter = FILTERS.some(([k]) => k === params.f) ? params.f : '';
  const nav = (over = {}) => go('periodic', { dept: dept ?? '', sem, f: filter, ...over });
  const reload = () => nav({ t: Date.now() });
  const ref = refWeek(now, sem);
  const shown = dept ? [dept] : deptIds;
  const canMarkFor = d => canManage || state.me.grants.some(g => ['dept_coordinator', 'hod'].includes(g.role)
    && (g.department_id == null || g.department_id === d));
  const wk = Object.fromEntries(weeks.map(w => [`${w.semester}-${w.week_no}`, w]));

  // حالة البند على الأقسام المعروضة (أو الكلية)
  const summary = it => {
    const sts = it.scope === 'college' ? [itemState(it, 0, ref)] : shown.map(d => itemState(it, d, ref));
    const fin = sts.filter(s => s === 'done' || s === 'na').length;
    const st = fin === sts.length ? 'done' : sts.includes('late') ? 'late' : sts.includes('now') ? 'now'
      : sts.includes('started') ? 'started' : sts[0];
    return { st, fin, n: sts.length };
  };
  const semItems = items.filter(i => i.semester === sem);
  const sums = new Map(semItems.map(i => [i.key, summary(i)]));
  const cnt = k => semItems.filter(i => sums.get(i.key).st === k).length;
  const passed = semItems.filter(i => !i.preset_done && i.week_no <= Math.max(ref.passedUpTo, ref.cw));
  const passedDone = passed.filter(i => ['done', 'na'].includes(sums.get(i.key).st)).length;
  const doneP = passed.length ? Math.round((passedDone / passed.length) * 100) : null;

  const nowText = !now ? '' : now.week_no === 0 ? 'قبل بداية التدريب'
    : now.in_break ? `إجازة — آخر أسبوع مرّ: ${weekName(now.week_no)} من ${SEM[now.semester]}`
      : `نحن في ${weekName(now.week_no)} من ${SEM[now.semester]}`;

  const hero = h('header', { class: 'scope-hero qw-hero' },
    h('div', null, h('h1', null, 'التقارير الدورية'),
      h('p', null, 'المهام الأسبوعية في تقويم أعمال جودة التدريب للعام التدريبي 1448/1449هـ. تقارير الأقسام تُعبّأ من نماذجها في '
        + '«الخطط والتقارير» فتُحسب حالتها تلقائياً ويجمعها وكيل الجودة في تقرير الكلية، وبقية البنود تُؤشَّر منجزة برابط الشاهد.'),
      nowText && h('p', { class: 'tl-now' }, nowText)),
    h('div', { class: 'scope-pick' },
      deptIds.length > 1 && h('label', null, 'القسم ', h('select', { onchange: e => nav({ dept: e.target.value }) },
        h('option', { value: '' }, 'كل الأقسام'), departments.map(d => h('option', { value: String(d.id), selected: d.id === dept }, d.name_ar)))),
      h('div', { class: 'scope-stats' },
        h('span', { class: 'st-upcoming' }, h('b', null, num(cnt('now'))), ' هذا الأسبوع'),
        h('span', { class: 'st-overdue' }, h('b', null, num(cnt('late'))), ' متأخر'),
        h('span', { class: 'st-done' }, h('b', null, doneP == null ? '—' : `${num(doneP)}%`), ' إنجاز حتى الآن'))));

  const tabs = h('div', { class: 'qw-tabs', role: 'tablist' },
    [1, 2].map(s => h('button', { role: 'tab', class: sem === s ? 'on' : '', 'aria-selected': String(sem === s), onclick: () => nav({ sem: s }) }, SEM[s])));
  const tools = h('div', { class: 'tl-tools' },
    h('select', { class: 'input', onchange: e => nav({ f: e.target.value }) },
      FILTERS.map(([k, t]) => h('option', { value: k, selected: k === filter }, t))),
    ref.cw > 0 && h('button', { class: 'btn small', onclick: () => document.getElementById(`pw-${sem}-${ref.cw}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' }) },
      'الأسبوع الحالي ↓'),
    h('span', { class: 'tl-legend' }, ['done', 'now', 'late', 'upcoming'].map(k => h('span', { class: `tl-chip tl-${k}` }, ST[k]))));

  const match = it => {
    const s = sums.get(it.key);
    if (filter === 'now') return s.st === 'now' || it.week_no === ref.cw;
    if (filter === 'late') return s.st === 'late';
    if (filter === 'dept') return it.scope === 'dept';
    if (filter === 'college') return it.scope === 'college';
    return true;
  };

  const openForm = (it, d) => go('forms', { dept: d, t: it.form?.template_id ?? '' });
  const status = it => {
    const s = sums.get(it.key);
    if (it.preset_done) return h('span', { class: 'tl-chip tl-done' }, '✓ مهمة مكتملة');
    if (it.scope === 'college') {
      return h('button', { type: 'button', class: `tl-chip tl-${s.st}`, onclick: () => markDialog(cycle, it, null, canManage, reload) },
        (s.st === 'done' ? '✓ ' : '') + ST[s.st]);
    }
    if (dept) {
      if (it.form && it.college_key) {
        return h('button', { type: 'button', class: `tl-chip tl-${s.st}`, title: 'تُحسب من نموذج القسم', onclick: () => openForm(it, dept) },
          (s.st === 'done' ? '✓ ' : '') + ST[s.st]);
      }
      return h('button', { type: 'button', class: `tl-chip tl-${s.st}`, onclick: () => markDialog(cycle, it, dept, canMarkFor(dept), reload) },
        (s.st === 'done' ? '✓ ' : '') + ST[s.st]);
    }
    const open = d => (it.form && it.college_key ? openForm(it, d) : markDialog(cycle, it, d, canMarkFor(d), reload));
    return h('button', { type: 'button', class: `tl-chip tl-${s.st}`, title: `أنجزته ${s.fin} من ${s.n} أقسام`,
      onclick: () => deptsDialog(it, departments, ref, open) }, ST[s.st], h('small', null, `${num(s.fin)}/${num(s.n)}`));
  };

  const actions = it => [
    it.form && it.form.template_id && (dept || deptIds.length === 1) && h('a', { class: 'btn small', href: `#/forms?dept=${dept ?? deptIds[0]}&t=${it.form.template_id}` },
      'نموذج القسم'),
    canManage && it.college_key && h('a', { class: 'btn small primary', href: `#/college?r=${it.college_key}${it.college_filter ? `&f=${encodeURIComponent(it.college_filter)}` : ''}` },
      'تقرير الكلية المجمّع'),
  ];

  const byWeek = new Map();
  for (const it of semItems.filter(match)) {
    if (!byWeek.has(it.week_no)) byWeek.set(it.week_no, []);
    byWeek.get(it.week_no).push(it);
  }
  const cards = [...byWeek.entries()].sort((a, b) => a[0] - b[0]).map(([n, list]) => {
    const w = wk[`${sem}-${n}`];
    const cls = n === ref.cw ? 'pr-now' : n <= ref.passedUpTo ? 'pr-past' : '';
    return h('section', { class: `card pr-week ${cls}`, id: `pw-${sem}-${n}` },
      h('header', { class: 'pr-week-head' },
        h('h2', null, weekName(n), n === ref.cw && h('span', { class: 'chip c-good' }, 'الأسبوع الحالي')),
        w && h('span', { class: 'faint' }, `${date(w.starts_on)} – ${date(w.ends_on)}${w.days ? ` · ${w.days}` : ''}`)),
      h('ul', { class: 'pr-items' }, list.map(it => h('li', { class: `pr-item s-${sums.get(it.key).st}` },
        h('div', { class: 'pr-main' },
          h('p', { class: 'pr-title' }, it.title_ar),
          h('div', { class: 'pr-meta' },
            h('span', { class: `chip ${it.scope === 'dept' ? 'c-mid' : ''}` }, it.scope === 'dept' ? 'الأقسام' : 'وكالة الجودة'),
            it.form && it.college_key && h('span', { class: 'faint' }, 'تُحسب من نموذج القسم'),
            it.note_ar && h('span', { class: 'faint' }, it.note_ar),
            it.quality_tasks.map(t => h('a', { class: 'chip c-good', href: '#/quality', title: t.title_ar },
              `مرتبط بأعمال الجودة: الأسبوع ${num(t.week_no)}`)))),
        h('div', { class: 'pr-side' }, status(it), actions(it))))));
  });

  const refs = h('details', { class: 'card pr-refs' }, h('summary', null, 'الإجازات وتعليمات التقويم'),
    h('div', { class: 'pr-refs-grid' },
      h('div', null, h('h3', null, 'الإجازات والمناسبات'),
        h('table', { class: 'table' }, h('tbody', null, data.holidays.map(x => h('tr', null, h('td', null, x.title_ar),
          h('td', null, x.hijri), h('td', null, date(x.on))))))),
      h('div', null, h('h3', null, 'تعليمات التقويم'), h('ul', null, data.instructions.map(t => h('li', null, t))))),
    h('p', { class: 'faint' }, data.source));

  return h('div', { class: 'cal-page' }, hero, tabs, tools,
    cards.length ? cards : h('section', { class: 'card empty' }, h('p', null, 'لا توجد بنود تطابق هذه التصفية.')), refs);
}
