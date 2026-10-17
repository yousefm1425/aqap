// تقويم الإنجاز: مواعيد المعايير الفرعية والمتطلبات ومتابعة إنجاز الأقسام عليها
import { api, apiDownload } from './api.js';
import { deptName, go, parseRoute, state, userScope } from './app.js';
import { date, h, mount, num, toast } from './ui.js';

const ST = { done: 'منجز', overdue: 'متأخر', soon: 'يقترب', upcoming: 'قادم' };
const MONTHS = ['يناير', 'فبراير', 'مارس', 'أبريل', 'مايو', 'يونيو', 'يوليو', 'أغسطس', 'سبتمبر', 'أكتوبر', 'نوفمبر', 'ديسمبر'];
const DAYS = ['الأحد', 'الاثنين', 'الثلاثاء', 'الأربعاء', 'الخميس', 'الجمعة', 'السبت'];
const iso = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;

function deadlineDialog(cycle, targets, depts, onSaved) {
  const dlg = document.getElementById('dialog');
  const list = h('datalist', { id: 'cal-targets' }, targets.map(t => h('option', { value: t.code }, t.label)));
  const code = h('input', { class: 'input', list: 'cal-targets', required: true, placeholder: 'مثال: 2-1 أو 2-1-3', dir: 'ltr' });
  const dept = h('select', { class: 'input' }, h('option', { value: '' }, 'كل الأقسام'),
    depts.map(d => h('option', { value: String(d) }, deptName(d))));
  const start = h('input', { class: 'input', type: 'date' });
  const due = h('input', { class: 'input', type: 'date', required: true });
  const note = h('input', { class: 'input', placeholder: 'اختياري' });
  const err = h('p', { class: 'faint', style: { color: 'var(--not-met)' } });
  const form = h('form', { method: 'dialog', class: 'cal-form', onsubmit: async e => {
    e.preventDefault();
    try {
      await api(`/cycles/${cycle.id}/calendar`, { method: 'POST', body: { target_code: code.value.trim(),
        department_id: dept.value ? Number(dept.value) : null, starts_on: start.value || null, due_on: due.value, note_ar: note.value || null } });
      dlg.close(); toast('حُفظ الموعد'); onSaved();
    } catch (ex) { err.textContent = ex.message; }
  } },
    h('h2', null, 'إضافة موعد إنجاز'),
    h('div', { class: 'field' }, h('label', null, 'المعيار الفرعي أو المتطلب'), code, list),
    h('div', { class: 'field' }, h('label', null, 'القسم'), dept),
    h('div', { class: 'row' }, h('div', { class: 'field' }, h('label', null, 'تاريخ البدء'), start),
      h('div', { class: 'field' }, h('label', null, 'تاريخ الانتهاء'), due)),
    h('div', { class: 'field' }, h('label', null, 'ملاحظات'), note), err,
    h('div', { class: 'row end' }, h('button', { type: 'button', class: 'btn', onclick: () => dlg.close() }, 'إلغاء'),
      h('button', { class: 'btn primary' }, 'حفظ')));
  mount(dlg, form);
  dlg.showModal();
  code.focus();
}

export async function renderCalendar() {
  const cycle = state.cycle;
  const { params } = parseRoute();
  const sc = userScope();
  const depts = state.departments.map(d => d.id).filter(d => sc.all || sc.depts.includes(d));
  const dept = depts.includes(Number(params.dept)) ? Number(params.dept) : null;
  const root = h('div', { class: 'cal-page' });
  let month = params.m ? new Date(`${params.m}-01T00:00:00`) : new Date();
  month = new Date(month.getFullYear(), month.getMonth(), 1);

  const [data, assess] = await Promise.all([
    api(`/cycles/${cycle.id}/calendar${dept ? `?department_id=${dept}` : ''}`),
    api(`/cycles/${cycle.id}/assessments`)]);
  const targets = [];
  const seen = new Set();
  for (const a of assess) {
    if (!seen.has(a.sub_standard_code)) { seen.add(a.sub_standard_code); targets.push({ code: a.sub_standard_code, label: `معيار فرعي: ${a.sub_standard_title}` }); }
    if (!seen.has(a.requirement_code)) { seen.add(a.requirement_code); targets.push({ code: a.requirement_code, label: `متطلب: ${a.requirement_text}` }); }
  }
  const items = data.deadlines;
  const reload = () => go('calendar', { dept: dept ?? '', m: iso(month).slice(0, 7), t: Date.now() });
  const count = s => items.filter(x => x.status === s).length;

  const fileIn = h('input', { type: 'file', accept: '.csv,.xlsx', hidden: true, onchange: async e => {
    const f = e.target.files[0]; if (!f) return;
    const fd = new FormData(); fd.append('file', f);
    try {
      const r = await api(`/cycles/${cycle.id}/calendar/import`, { method: 'POST', form: fd });
      toast(`رُفع التقويم: ${num(r.imported)} موعد${r.errors.length ? ` — ${num(r.errors.length)} صف فيه خطأ` : ''}`);
      for (const x of r.errors.slice(0, 5)) toast(`صف ${x.row} (${x.code}): ${x.error}`, 'error');
      reload();
    } catch (ex) { toast(ex.message, 'error'); }
  } });

  const hero = h('header', { class: 'scope-hero cal-hero' },
    h('div', null, h('h1', null, 'تقويم الإنجاز'),
      h('p', null, 'مواعيد إنجاز المعايير الفرعية والمتطلبات التي يرفعها وكيل الجودة. يُحتسب الإنجاز برفع القسم لتقديراته في الموعد، '
        + 'والموعد الخاص بمتطلب أو بقسم يغلب الموعد العام.'),
      data.can_edit && h('div', { class: 'row cal-actions' },
        h('button', { class: 'btn gold', onclick: () => deadlineDialog(cycle, targets, depts, reload) }, '+ إضافة موعد'),
        h('button', { class: 'btn ghost', onclick: () => fileIn.click() }, 'رفع التقويم (Excel / CSV)'),
        h('button', { class: 'btn ghost', onclick: () => apiDownload(`/cycles/${cycle.id}/calendar/template`, 'قالب_تقويم_الإنجاز.csv')
          .catch(ex => toast(ex.message, 'error')) }, 'تنزيل القالب'), fileIn)),
    h('div', { class: 'scope-pick' },
      depts.length > 1 && h('label', null, 'القسم ', h('select', { onchange: e => go('calendar', { dept: e.target.value, m: iso(month).slice(0, 7) }) },
        h('option', { value: '' }, 'كل الأقسام'), depts.map(d => h('option', { value: String(d), selected: d === dept }, deptName(d))))),
      h('div', { class: 'scope-stats' },
        h('span', null, h('b', null, num(items.length)), ' موعد'),
        h('span', { class: 'st-done' }, h('b', null, num(count('done'))), ' منجز'),
        h('span', { class: 'st-soon' }, h('b', null, num(count('soon'))), ' يقترب'),
        h('span', { class: 'st-overdue' }, h('b', null, num(count('overdue'))), ' متأخر'))));

  // الشبكة الشهرية
  const byDay = new Map();
  for (const x of items) { const k = String(x.due_on); if (!byDay.has(k)) byDay.set(k, []); byDay.get(k).push(x); }
  const first = new Date(month), startPad = first.getDay();
  const daysIn = new Date(month.getFullYear(), month.getMonth() + 1, 0).getDate();
  const todayIso = String(data.today);
  const cells = [];
  for (let i = 0; i < startPad; i++) cells.push(h('div', { class: 'cal-cell empty' }));
  for (let d = 1; d <= daysIn; d++) {
    const k = iso(new Date(month.getFullYear(), month.getMonth(), d));
    const xs = byDay.get(k) || [];
    cells.push(h('div', { class: `cal-cell${k === todayIso ? ' today' : ''}${xs.length ? ' has' : ''}` },
      h('span', { class: 'cal-day' }, num(d)),
      xs.slice(0, 3).map(x => h('a', { class: `cal-chip st-${x.status}`, href: `#dl-${x.id}`, title: x.target_title },
        h('bdi', null, x.target_code))),
      xs.length > 3 && h('span', { class: 'cal-more' }, `+${num(xs.length - 3)}`)));
  }
  const shift = n => go('calendar', { dept: dept ?? '', m: iso(new Date(month.getFullYear(), month.getMonth() + n, 1)).slice(0, 7) });
  const grid = h('section', { class: 'card cal-month' },
    h('div', { class: 'cal-nav' },
      h('button', { class: 'btn small', onclick: () => shift(-1), 'aria-label': 'الشهر السابق' }, '›'),
      h('h2', null, `${MONTHS[month.getMonth()]} ${month.getFullYear()}`),
      h('button', { class: 'btn small', onclick: () => shift(1), 'aria-label': 'الشهر التالي' }, '‹')),
    h('div', { class: 'cal-grid' }, DAYS.map(d => h('div', { class: 'cal-dow' }, d)), cells),
    h('div', { class: 'legend cal-legend' }, Object.entries(ST).map(([k, v]) => h('span', null, h('i', { class: `cal-chip st-${k}` }), v))));

  // القائمة الزمنية
  const groups = new Map();
  for (const x of items) {
    const d = new Date(`${x.due_on}T00:00:00`), key = `${MONTHS[d.getMonth()]} ${d.getFullYear()}`;
    if (!groups.has(key)) groups.set(key, []); groups.get(key).push(x);
  }
  const card = x => {
    const p = x.total ? Math.round((x.done / x.total) * 100) : 0;
    const left = x.status === 'done' ? 'اكتمل' : x.days_left < 0 ? `متأخر ${num(-x.days_left)} يوم` : x.days_left === 0 ? 'ينتهي اليوم' : `باقي ${num(x.days_left)} يوم`;
    return h('article', { class: `dl st-${x.status}`, id: `dl-${x.id}` },
      h('div', { class: 'dl-date' }, h('b', null, num(new Date(`${x.due_on}T00:00:00`).getDate())),
        h('span', null, MONTHS[new Date(`${x.due_on}T00:00:00`).getMonth()])),
      h('div', { class: 'dl-body' },
        h('div', { class: 'dl-top' }, h('bdi', { class: 'ssub-code' }, x.target_code),
          h('span', { class: 'dl-kind' }, x.target_kind === 'sub_standard' ? 'معيار فرعي' : `متطلب في ${x.sub_standard_code}`),
          h('span', { class: `chip st-${x.status}` }, ST[x.status]),
          h('span', { class: 'chip' }, x.department_name ?? 'كل الأقسام')),
        h('h3', null, x.target_title),
        h('p', { class: 'muted' }, `${x.starts_on ? `من ${date(x.starts_on)} ` : ''}إلى ${date(x.due_on)} · ${left}`, x.note_ar && ` · ${x.note_ar}`),
        h('div', { class: 'dl-prog' }, h('div', { class: 'dl-bar' }, h('i', { style: { width: `${p}%` } })),
          h('span', null, x.total ? `${num(x.done)} من ${num(x.total)} تقدير مرفوع (${num(p)}%)` : 'لا توجد تقديرات في النطاق'))),
      data.can_edit && h('button', { class: 'btn small', title: 'حذف الموعد', onclick: async () => {
        try { await api(`/calendar/${x.id}`, { method: 'DELETE' }); toast('حُذف الموعد'); reload(); } catch (ex) { toast(ex.message, 'error'); }
      } }, 'حذف'));
  };
  const listSec = h('section', { class: 'card cal-list' },
    items.length ? [...groups].map(([g, xs]) => h('div', null, h('h3', { class: 'cal-group' }, g), xs.map(card)))
      : h('div', { class: 'empty' }, h('h2', null, 'لم يُرفع تقويم بعد'),
        h('p', null, data.can_edit ? 'نزّل القالب، واكتب تواريخ الانتهاء أمام كل معيار فرعي، ثم ارفعه. أو أضف المواعيد واحداً واحداً.'
          : 'يظهر هنا تقويم الإنجاز بعد أن ترفعه وكالة الجودة.')));

  mount(root, hero, h('div', { class: 'cal-layout' }, grid, listSec));
  return root;
}
