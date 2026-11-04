// الخط الزمني لتنفيذ متطلبات نظام الجودة (المستوى الثاني): مواعيد كل متطلب حسب أسابيع التقويم التدريبي،
// والمسؤول عنه في القسم، وتأشير الإنجاز برابط الشاهد الذي يُربط تلقائياً بتقدير القسم للمتطلب
import { api } from './api.js';
import { deptName, go, parseRoute, state } from './app.js';
import { date, h, mount, num, toast } from './ui.js';

const SEM = { 1: 'الفصل التدريبي الأول', 2: 'الفصل التدريبي الثاني' };
const ST = { done: 'منجز', na: 'لا ينطبق', late: 'متأخر', now: 'هذا الأسبوع', upcoming: 'قادم', open: 'مستمر' };
const FILTERS = [['', 'كل المتطلبات'], ['due', 'مستحق هذا الأسبوع'], ['late', 'متأخر'], ['noowner', 'بلا مسؤول'], ['active', 'له مواعيد في الفصل']];

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

// الأسبوع المرجعي للفصل المعروض: ما قبله فات، وهو الحالي (إلا في الإجازة فيُعد قد مرّ)
function refWeek(now, sem) {
  if (!now) return { cw: 0, passedUpTo: 0 };
  if (now.semester > sem) return { cw: 0, passedUpTo: 99 };
  if (now.semester < sem) return { cw: 0, passedUpTo: 0 };
  return now.in_break ? { cw: 0, passedUpTo: now.week_no } : { cw: now.week_no, passedUpTo: now.week_no - 1 };
}

function occStatus(o, deptId, ref) {
  const p = o.progress[String(deptId)];
  if (p) return p.status;
  if (o.week_no == null) return 'open';
  if (o.week_no <= ref.passedUpTo) return 'late';
  if (o.week_no === ref.cw) return 'now';
  return 'upcoming';
}

function seedDialog(cycle, loaded, reload) {
  const s1 = h('input', { class: 'input', type: 'date' });
  const s2 = h('input', { class: 'input', type: 'date' });
  openDialog(loaded ? 'إعادة تحميل الخط الزمني' : 'تحميل الخط الزمني للمستوى الثاني', [
    h('p', { class: 'muted' }, 'تُحمَّل الخطة المعتمدة 1447هـ (48 متطلباً بأسابيع تنفيذها في الفصلين) مع أسابيع التقويم التدريبي 1448هـ '
      + 'الصادر من المؤسسة: بداية الفصل الأول 23 أغسطس 2026 والثاني 17 يناير 2027، ولا تُحسب أسابيع إجازة الخريف وعيدي الفطر والأضحى.'),
    loaded && h('p', { class: 'qw-return' }, 'إعادة التحميل تحذف المواعيد الحالية وما أشّرته الأقسام عليها. الشواهد تبقى مربوطة بتقديرات المتطلبات.'),
    h('details', null, h('summary', null, 'تاريخ بداية مختلف (اختياري)'),
      h('p', { class: 'faint' }, 'عند إدخال تاريخ تُحسب الأسابيع متتالية من أحد ذلك الأسبوع دون استثناء الإجازات.'),
      h('div', { class: 'row' }, field('بداية الفصل الأول', s1), field('بداية الفصل الثاني', s2)))],
  async () => {
    const r = await api(`/cycles/${cycle.id}/l2-timeline/seed`, { method: 'POST',
      body: { semester1_start: s1.value || null, semester2_start: s2.value || null, replace: !!loaded } });
    toast(`حُمّل ${num(r.requirements)} متطلباً و${num(r.occurrences)} موعداً${r.missing.length ? ` (لم يُعثر على ${num(r.missing.length)} رمز في إطار الدورة)` : ''}`);
    reload();
  }, loaded ? 'إعادة التحميل' : 'تحميل');
}

function occDialog(req, o, deptId, weekStart, canMark, reload) {
  const p = o.progress[String(deptId)];
  const when = o.week_no ? `الأسبوع ${num(o.week_no)} من ${SEM[o.semester]}${weekStart ? ` (يبدأ ${date(weekStart)})` : ''}` : o.label_ar;
  const url = h('input', { class: 'input', type: 'url', dir: 'ltr', placeholder: 'https://...sharepoint.com/...', value: p?.url ?? '' });
  const note = h('textarea', { class: 'input', rows: 2 }, p?.note_ar ?? '');
  const na = h('input', { type: 'checkbox', checked: p?.status === 'na', onchange: () => { url.disabled = na.checked; } });
  url.disabled = na.checked;
  const undo = async () => {
    try {
      await api(`/l2-timeline/${o.id}/progress?department_id=${deptId}`, { method: 'DELETE' });
      document.getElementById('dialog').close(); toast('أُلغي التأشير'); reload();
    } catch (ex) { toast(ex.message, 'error'); }
  };
  openDialog(`${req.code} · ${deptName(deptId)}`, [
    h('p', { class: 'muted' }, req.text_ar),
    h('p', null, h('b', null, 'الموعد: '), when),
    p && h('p', { class: 'tl-done-note' }, `${ST[p.status]} — ${p.done_by_name ?? ''} في ${date(p.done_at)}`,
      p.url && [' · ', h('a', { href: p.url, target: '_blank', rel: 'noopener' }, 'فتح الشاهد ↗')],
      p.linked && h('span', { class: 'chip c-good' }, 'مربوط بتقدير المتطلب')),
    canMark && [
      field('رابط الشاهد (من مجلد الشواهد على OneDrive / SharePoint)', url),
      field('ملاحظات', note),
      h('label', { class: 'qw-na' }, na, ' هذا الموعد لا ينطبق على القسم (اذكر السبب في الملاحظات)'),
      h('p', { class: 'qw-tip' }, 'يُربط الشاهد تلقائياً بتقدير القسم لهذا المتطلب في «التقديرات والشواهد»، فلا يُرفع مرة أخرى.'),
      p && h('button', { type: 'button', class: 'btn small', onclick: undo }, 'إلغاء التأشير')]],
  canMark ? async () => {
    const r = await api(`/l2-timeline/${o.id}/progress`, { method: 'POST',
      body: { department_id: deptId, url: na.checked ? null : url.value, note_ar: note.value || null, not_applicable: na.checked } });
    toast(r.status === 'na' ? 'سُجّل «لا ينطبق»' : r.linked ? 'أُشّر منجزاً ورُبط الشاهد بتقدير المتطلب'
      : 'أُشّر منجزاً (التقدير مرفوع، فحُفظ الشاهد في السجل دون ربط)');
    reload();
  } : null, 'تأشير منجز');
}

function deptsDialog(req, o, departments, ref, weekStart) {
  const when = o.week_no ? `الأسبوع ${num(o.week_no)} من ${SEM[o.semester]}${weekStart ? ` (يبدأ ${date(weekStart)})` : ''}` : o.label_ar;
  openDialog(`${req.code} · ${when}`, [
    h('p', { class: 'muted' }, req.text_ar),
    h('div', { class: 'qw-depts' }, departments.map(d => {
      const s = occStatus(o, d.id, ref);
      const p = o.progress[String(d.id)];
      return h('button', { type: 'button', class: `qw-dot tl-${s}`, title: p?.note_ar ?? '',
        onclick: () => { document.getElementById('dialog').close(); go('timeline', { dept: d.id, sem: o.semester }); } },
      h('span', null, d.name_ar), h('i', null, ST[s]));
    }))], null);
}

export async function renderTimeline() {
  const cycle = state.cycle;
  const { params } = parseRoute();
  const data = await api(`/cycles/${cycle.id}/l2-timeline`);
  const { departments, requirements, weeks, now, can_edit: canEdit } = data;
  const deptIds = departments.map(d => d.id);
  const dept = deptIds.includes(Number(params.dept)) ? Number(params.dept) : deptIds.length === 1 ? deptIds[0] : null;
  const sem = [1, 2].includes(Number(params.sem)) ? Number(params.sem) : (now?.semester ?? 1);
  const filter = FILTERS.some(([k]) => k === params.f) ? params.f : '';
  const q = (params.q ?? '').trim();
  const nav = (over = {}) => go('timeline', { dept: dept ?? '', sem, f: filter, q, ...over });
  const reload = () => nav({ t: Date.now() });
  const ref = refWeek(now, sem);
  const shown = dept ? [dept] : deptIds;
  const wkStart = Object.fromEntries(weeks.map(w => [`${w.semester}-${w.week_no}`, w.starts_on]));
  const canMarkFor = d => canEdit || state.me.grants.some(g => ['dept_coordinator', 'hod', 'faculty'].includes(g.role)
    && (g.department_id == null || g.department_id === d));
  const canPlanFor = d => canEdit || state.me.grants.some(g => ['dept_coordinator', 'hod'].includes(g.role)
    && (g.department_id == null || g.department_id === d));

  // الإحصاءات على الفصل المعروض والأقسام المعروضة
  let due = 0, late = 0, passed = 0, passedDone = 0, noOwner = 0;
  const stat = new Map();
  for (const r of requirements) {
    const occ = r.occurrences.filter(o => o.semester === sem);
    const s = { due: false, late: 0, active: occ.length > 0, noowner: shown.some(d => !r.planners[String(d)]) };
    for (const o of occ) for (const d of shown) {
      const st = occStatus(o, d, ref);
      if (st === 'now') s.due = true;
      if (st === 'late') s.late += 1;
      if (o.week_no != null && (o.week_no <= ref.passedUpTo || o.week_no === ref.cw)) {
        passed += 1; if (['done', 'na'].includes(st)) passedDone += 1;
      }
    }
    if (s.due) due += 1;
    if (s.late) late += 1;
    if (s.noowner) noOwner += 1;
    stat.set(r.code, s);
  }
  const doneP = passed ? Math.round((passedDone / passed) * 100) : null;

  const nowText = !now ? 'لم يُحمَّل التقويم التدريبي بعد'
    : now.week_no === 0 ? 'قبل بداية التدريب'
      : now.in_break ? `إجازة — آخر أسبوع مرّ: الأسبوع ${num(now.week_no)} من ${SEM[now.semester]}`
        : `الأسبوع ${num(now.week_no)} من ${SEM[now.semester]}${now.week_no >= 18 ? ' (الاختبارات النهائية)' : ''}`;

  const hero = h('header', { class: 'scope-hero qw-hero' },
    h('div', null, h('h1', null, 'الخط الزمني للمستوى الثاني'),
      h('p', null, 'مواعيد تنفيذ متطلبات نظام جودة التدريب (المستوى الثاني) حسب أسابيع التقويم التدريبي. يحدد القسم المسؤول عن كل متطلب، '
        + 'ويؤشّر كل موعد منجزاً برابط الشاهد فينعكس على تقدير المتطلب.'),
      h('p', { class: 'tl-now' }, nowText),
      canEdit && h('div', { class: 'row cal-actions' },
        h('button', { class: requirements.length ? 'btn ghost' : 'btn gold', onclick: () => seedDialog(cycle, requirements.length > 0, reload) },
          requirements.length ? 'إعادة تحميل الخطة' : 'تحميل الخط الزمني'))),
    h('div', { class: 'scope-pick' },
      deptIds.length > 1 && h('label', null, 'القسم ', h('select', { onchange: e => nav({ dept: e.target.value }) },
        h('option', { value: '' }, 'كل الأقسام'), departments.map(d => h('option', { value: String(d.id), selected: d.id === dept }, d.name_ar)))),
      requirements.length > 0 && h('div', { class: 'scope-stats' },
        h('span', { class: 'st-upcoming' }, h('b', null, num(due)), ' مستحق هذا الأسبوع'),
        h('span', { class: 'st-overdue' }, h('b', null, num(late)), ' متأخر'),
        h('span', { class: 'st-done' }, h('b', null, doneP == null ? '—' : `${num(doneP)}%`), ' إنجاز حتى الآن'),
        h('span', { class: 'st-soon' }, h('b', null, num(noOwner)), ' بلا مسؤول'))));

  if (!requirements.length) {
    return h('div', { class: 'cal-page' }, hero, h('section', { class: 'card empty' }, h('h2', null, 'لم يُحمَّل الخط الزمني بعد'),
      h('p', null, canEdit ? 'اضغط «تحميل الخط الزمني» لتحميل الخطة المعتمدة وأسابيع التقويم التدريبي.'
        : 'يظهر هنا الخط الزمني بعد أن تحمّله وكالة الجودة.')));
  }

  const tabs = h('div', { class: 'qw-tabs', role: 'tablist' },
    [1, 2].map(s => h('button', { role: 'tab', class: sem === s ? 'on' : '', 'aria-selected': String(sem === s), onclick: () => nav({ sem: s }) }, SEM[s])));
  const search = h('input', { class: 'input', type: 'search', placeholder: 'ابحث برقم المتطلب أو نصه أو المسؤول', value: q,
    onchange: e => nav({ q: e.target.value }) });
  const tools = h('div', { class: 'tl-tools' }, search,
    h('select', { class: 'input', onchange: e => nav({ f: e.target.value }) },
      FILTERS.map(([k, t]) => h('option', { value: k, selected: k === filter }, t))),
    h('span', { class: 'tl-legend' }, ['done', 'now', 'late', 'upcoming'].map(k => h('span', { class: `tl-chip tl-${k}` }, ST[k]))));

  const match = r => {
    const s = stat.get(r.code);
    if (q && !(r.code.includes(q) || r.text_ar.includes(q) || Object.values(r.planners).some(n => n.includes(q)))) return false;
    if (filter === 'due') return s.due;
    if (filter === 'late') return s.late > 0;
    if (filter === 'noowner') return s.noowner;
    if (filter === 'active') return s.active;
    return true;
  };

  const chip = (r, o) => {
    const ws = o.week_no ? wkStart[`${o.semester}-${o.week_no}`] : null;
    const label = o.week_no ?? o.label_ar;
    if (dept) {
      const st = occStatus(o, dept, ref);
      return h('button', { type: 'button', class: `tl-chip tl-${st}`, title: `${o.week_no ? `الأسبوع ${o.week_no}${ws ? ` · ${date(ws)}` : ''}` : o.label_ar} — ${ST[st]}`,
        onclick: () => occDialog(r, o, dept, ws, canMarkFor(dept), reload) }, (st === 'done' ? '✓ ' : '') + label);
    }
    const sts = shown.map(d => occStatus(o, d, ref));
    const fin = sts.filter(x => x === 'done' || x === 'na').length;
    const st = fin === sts.length ? 'done' : sts.includes('late') ? 'late' : sts.includes('now') ? 'now' : sts[0];
    return h('button', { type: 'button', class: `tl-chip tl-${st}`, title: `${o.week_no ? `الأسبوع ${o.week_no}` : o.label_ar}: أنجزته ${fin} من ${sts.length} أقسام`,
      onclick: () => deptsDialog(r, o, departments.filter(d => shown.includes(d.id)), ref, ws) },
    label, h('small', null, `${num(fin)}/${num(sts.length)}`));
  };

  const planner = r => {
    if (!dept) {
      const n = shown.filter(d => r.planners[String(d)]).length;
      return h('span', { class: `chip ${n === shown.length ? 'c-good' : 'c-mid'}` }, `المسؤول محدد في ${num(n)} من ${num(shown.length)}`);
    }
    const cur = r.planners[String(dept)] ?? '';
    if (!canPlanFor(dept)) return h('span', { class: 'tl-owner' }, cur || 'لم يُحدد المسؤول');
    return h('label', { class: 'tl-owner' }, h('span', null, 'المسؤول'),
      h('input', { class: 'input', type: 'text', value: cur, placeholder: 'اسم المسؤول', onchange: async e => {
        try {
          await api(`/cycles/${cycle.id}/l2-timeline/planner`, { method: 'PUT',
            body: { requirement_code: r.code, department_id: dept, owner_name_ar: e.target.value } });
          r.planners[String(dept)] = e.target.value.trim();
          toast(e.target.value.trim() ? 'حُفظ المسؤول' : 'أُزيل المسؤول');
        } catch (ex) { toast(ex.message, 'error'); e.target.value = cur; }
      } }));
  };

  const sections = [];
  let std = null, sub = null, box = null;
  for (const r of requirements.filter(match)) {
    if (r.standard_code !== std) {
      std = r.standard_code; sub = null;
      box = h('section', { class: 'card tl-std' }, h('h2', null, h('bdi', { class: 'ssub-code' }, r.standard_code), ' ', r.standard_title));
      sections.push(box);
    }
    if (r.sub_standard_code !== sub) {
      sub = r.sub_standard_code;
      box.append(h('h3', { class: 'tl-sub' }, h('bdi', { class: 'ssub-code' }, sub), ' ', r.sub_standard_title));
    }
    const occ = r.occurrences.filter(o => o.semester === sem || (o.week_no == null && sem === 1));
    const s = stat.get(r.code);
    box.append(h('article', { class: `tl-req ${s.late ? 's-late' : s.due ? 's-now' : ''}` },
      h('div', { class: 'tl-main' },
        h('p', { class: 'tl-title' }, h('bdi', { class: 'ssub-code' }, r.code), ' ', r.text_ar),
        h('div', { class: 'tl-chips' }, occ.length ? [h('span', { class: 'faint' }, 'أسابيع التنفيذ:'), occ.map(o => chip(r, o))]
          : h('span', { class: 'faint' }, `لا مواعيد له في ${SEM[sem]}`))),
      h('div', { class: 'tl-side' }, planner(r))));
  }

  return h('div', { class: 'cal-page' }, hero, tabs, tools,
    sections.length ? sections : h('section', { class: 'card empty' }, h('p', null, 'لا توجد متطلبات تطابق هذا البحث أو التصفية.')));
}
