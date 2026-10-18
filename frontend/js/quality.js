// أعمال الجودة: جدول مهام متابعة الجودة الأسبوعي، وتوافقها مع المعايير الفرعية والمتطلبات
// تسليم القسم برابط الشاهد يُربط تلقائياً بتقديرات المتطلبات المرتبطة فلا يتكرر الرفع
import { api } from './api.js';
import { deptName, go, parseRoute, state } from './app.js';
import { date, h, mount, num, toast } from './ui.js';

const ST = { submitted: 'مُسلَّمة', approved: 'معتمدة', returned: 'مُعادة', na: 'لا تنطبق', pending: 'لم تُسلَّم', overdue: 'متأخرة' };
const STC = { submitted: 'st-upcoming', approved: 'st-done', returned: 'st-overdue', na: '', pending: 'st-soon', overdue: 'st-overdue' };
const ORD = ['', 'الأول', 'الثاني', 'الثالث', 'الرابع', 'الخامس', 'السادس', 'السابع', 'الثامن', 'التاسع', 'العاشر', 'الحادي عشر',
  'الثاني عشر', 'الثالث عشر', 'الرابع عشر', 'الخامس عشر', 'السادس عشر', 'السابع عشر', 'الثامن عشر', 'التاسع عشر', 'العشرون'];
const week = n => `الأسبوع ${ORD[n] ?? n}`;

function statusOf(task, deptId, today) {
  const s = task.submissions[String(deptId)];
  if (s) return s.status;
  return task.due_on && String(task.due_on) < String(today) ? 'overdue' : 'pending';
}

function openDialog(title, body, onSubmit, submitLabel = 'حفظ') {
  const dlg = document.getElementById('dialog');
  const err = h('p', { class: 'faint', style: { color: 'var(--not-met)' } });
  const form = h('form', { method: 'dialog', class: 'cal-form qw-form', onsubmit: async e => {
    e.preventDefault();
    try { await onSubmit(); dlg.close(); } catch (ex) { err.textContent = ex.message; }
  } }, h('h2', null, title), body, err,
  h('div', { class: 'row end' }, h('button', { type: 'button', class: 'btn', onclick: () => dlg.close() }, 'إلغاء'),
    onSubmit && h('button', { class: 'btn primary' }, submitLabel)));
  mount(dlg, form);
  dlg.showModal();
}
const field = (label, input) => h('div', { class: 'field' }, h('label', null, label), input);

function seedDialog(cycle, reload) {
  const start = h('input', { class: 'input', type: 'date', required: true, value: String(cycle.starts_on ?? '') });
  openDialog('تحميل جدول أعمال الجودة', [
    h('p', { class: 'muted' }, 'يُحمَّل جدول متابعة أعمال الجودة المعتمد (26 مهمة من الأسبوع 3 إلى 19) بتواريخ محسوبة من بداية الفصل، '
      + 'مع التوافق المقترح لكل مهمة مع المعايير الفرعية. يمكنك تعديل أي مهمة أو موعد بعد التحميل.'),
    field('تاريخ بداية الفصل التدريبي (الأسبوع الأول)', start)],
  async () => {
    const r = await api(`/cycles/${cycle.id}/quality-tasks/seed`, { method: 'POST', body: { semester_start: start.value } });
    toast(`حُمّلت ${num(r.created)} مهمة`); reload();
  }, 'تحميل');
}

function taskDialog(cycle, task, reload) {
  const wk = h('input', { class: 'input', type: 'number', min: 1, max: 30, required: true, value: task?.week_no ?? '' });
  const title = h('textarea', { class: 'input', rows: 2, required: true }, task?.title_ar ?? '');
  const due = h('input', { class: 'input', type: 'date', value: task?.due_on ?? '' });
  const hint = h('input', { class: 'input', value: task?.due_hint_ar ?? '', placeholder: 'مثال: قبل نهاية الأسبوع السادس (يوم الثلاثاء)' });
  const cond = h('input', { class: 'input', value: task?.condition_ar ?? '', placeholder: 'اختياري: في حال تطبيق ...' });
  const notes = h('input', { class: 'input', value: task?.notes_ar ?? '' });
  openDialog(task ? 'تعديل المهمة' : 'إضافة مهمة', [
    h('div', { class: 'row' }, field('الأسبوع', wk), field('موعد التسليم', due)),
    field('المطلوب', title), field('وصف الموعد', hint), field('شرط الانطباق', cond), field('ملاحظات', notes)],
  async () => {
    const body = { week_no: Number(wk.value), title_ar: title.value, due_on: due.value || null, due_hint_ar: hint.value || null,
      condition_ar: cond.value || null, notes_ar: notes.value || null };
    await api(task ? `/quality-tasks/${task.id}` : `/cycles/${cycle.id}/quality-tasks`, { method: task ? 'PATCH' : 'POST', body });
    toast('حُفظت المهمة'); reload();
  });
}

function linksDialog(task, catalog, reload) {
  const subSel = new Set(task.links.filter(l => l.kind === 'sub').map(l => l.code));
  const reqSel = new Set(task.links.filter(l => l.kind === 'req').map(l => l.code));
  const related = new Set(task.links.map(l => l.sub_standard_code));
  let lastStd = null;
  const items = [];
  for (const ss of catalog) {
    if (ss.standard_code !== lastStd) { lastStd = ss.standard_code; items.push(h('h4', { class: 'qw-std' }, ss.standard_title)); }
    items.push(h('details', { class: 'qw-sub', open: related.has(ss.code) },
      h('summary', null,
        h('label', { onclick: e => e.stopPropagation() },
          h('input', { type: 'checkbox', checked: subSel.has(ss.code), onchange: e => e.target.checked ? subSel.add(ss.code) : subSel.delete(ss.code) }),
          ' ', h('bdi', { class: 'ssub-code' }, ss.code), ' ', ss.title)),
      ss.requirements.map(r => h('label', { class: 'qw-req' },
        h('input', { type: 'checkbox', checked: reqSel.has(r.code), onchange: e => e.target.checked ? reqSel.add(r.code) : reqSel.delete(r.code) }),
        h('span', null, h('bdi', { class: 'ssub-code' }, r.code), ' ', r.text)))));
  }
  openDialog('توافق المهمة مع المعايير', [
    h('p', { class: 'muted' }, task.title_ar),
    h('p', { class: 'qw-tip' }, 'المعيار الفرعي = توافق عام يظهر في جدول التوافق. المتطلب = يُربط به شاهد القسم تلقائياً عند التسليم.'),
    h('div', { class: 'qw-tree' }, items)],
  async () => {
    const r = await api(`/quality-tasks/${task.id}/links`, { method: 'PUT',
      body: { sub_standard_codes: [...subSel], requirement_codes: [...reqSel] } });
    toast(`حُفظ التوافق: ${num(r.sub_standards)} معيار فرعي و${num(r.requirements)} متطلب`); reload();
  });
}

function submitDialog(task, deptId, reload) {
  const prev = task.submissions[String(deptId)];
  const url = h('input', { class: 'input', type: 'url', dir: 'ltr', placeholder: 'https://...sharepoint.com/...', value: prev?.url ?? '' });
  const note = h('textarea', { class: 'input', rows: 2 }, prev?.note_ar ?? '');
  const na = h('input', { type: 'checkbox', onchange: () => { url.disabled = na.checked; } });
  if (prev?.status === 'na') { na.checked = true; url.disabled = true; }
  const reqs = task.links.filter(l => l.kind === 'req').length;
  openDialog(`تسليم: ${deptName(deptId)}`, [
    h('p', { class: 'muted' }, task.title_ar),
    prev?.review_note_ar && h('p', { class: 'qw-return' }, `ملاحظة وكالة الجودة: ${prev.review_note_ar}`),
    field('رابط الشاهد (من مجلد الشواهد على OneDrive / SharePoint)', url),
    field('ملاحظات', note),
    h('label', { class: 'qw-na' }, na, ' المهمة لا تنطبق على القسم', task.condition_ar && h('small', null, ` (${task.condition_ar})`)),
    h('p', { class: 'qw-tip' }, reqs ? `سيُربط الشاهد تلقائياً بـ${num(reqs)} متطلب في مساحة القسم، فلا حاجة لرفعه مرة أخرى.`
      : 'لم تُحدد متطلبات لهذه المهمة بعد؛ يُحفظ الشاهد في سجل أعمال الجودة.')],
  async () => {
    const r = await api(`/quality-tasks/${task.id}/submit`, { method: 'POST',
      body: { department_id: deptId, url: na.checked ? null : url.value, note_ar: note.value || null, not_applicable: na.checked } });
    toast(r.status === 'na' ? 'سُجّلت المهمة «لا تنطبق»'
      : `سُلّمت المهمة${r.linked ? ` وربط الشاهد بـ${num(r.linked)} متطلب` : ''}${r.skipped ? ` (تعذر ربط ${num(r.skipped)} متطلب رُفع تقديره)` : ''}`);
    reload();
  }, 'تسليم');
}

function reviewDialog(task, deptId, reload) {
  const s = task.submissions[String(deptId)];
  const note = h('textarea', { class: 'input', rows: 2, placeholder: 'مطلوبة عند الإعادة' });
  const decide = async decision => {
    try {
      await api(`/quality-tasks/${task.id}/review`, { method: 'POST', body: { department_id: deptId, decision, note_ar: note.value || null } });
      document.getElementById('dialog').close(); toast(decision === 'approved' ? 'اعتُمدت' : 'أُعيدت للقسم'); reload();
    } catch (ex) { toast(ex.message, 'error'); }
  };
  openDialog(`${deptName(deptId)} — ${ST[s.status]}`, [
    h('p', { class: 'muted' }, task.title_ar),
    s.url && h('p', null, h('a', { href: s.url, target: '_blank', rel: 'noopener' }, 'فتح الشاهد ↗')),
    s.note_ar && h('p', null, `ملاحظة القسم: ${s.note_ar}`),
    h('p', { class: 'faint' }, `سلّمها ${s.submitted_by_name ?? ''} في ${date(s.submitted_at)}${s.linked_count ? ` · مربوطة بـ${num(s.linked_count)} متطلب` : ''}`),
    field('ملاحظة المراجعة', note),
    h('div', { class: 'row' }, h('button', { type: 'button', class: 'btn primary', onclick: () => decide('approved') }, 'اعتماد'),
      h('button', { type: 'button', class: 'btn', onclick: () => decide('returned') }, 'إعادة للقسم'))], null);
}

export async function renderQuality() {
  const cycle = state.cycle;
  const { params } = parseRoute();
  const [data, catalog] = await Promise.all([api(`/cycles/${cycle.id}/quality-tasks`), api(`/cycles/${cycle.id}/quality-tasks/catalog`)]);
  const { tasks, departments, today, can_edit: canEdit } = data;
  const deptIds = departments.map(d => d.id);
  const dept = deptIds.includes(Number(params.dept)) ? Number(params.dept) : deptIds.length === 1 ? deptIds[0] : null;
  const view = params.view === 'map' ? 'map' : 'weeks';
  const reload = () => go('quality', { dept: dept ?? '', view, t: Date.now() });
  const shown = dept ? [dept] : deptIds;

  const cells = tasks.flatMap(t => shown.map(d => statusOf(t, d, today)));
  const cnt = k => cells.filter(x => k.includes(x)).length;
  const doneP = cells.length ? Math.round((cnt(['submitted', 'approved', 'na']) / cells.length) * 100) : 0;

  const hero = h('header', { class: 'scope-hero qw-hero' },
    h('div', null, h('h1', null, 'أعمال الجودة'),
      h('p', null, 'جدول متابعة أعمال الجودة الأسبوعي: تقارير الاختبارات، ومنصة المهارات العملية، وملف المقرر، والتدقيق الذاتي. '
        + 'كل مهمة مربوطة بالمعايير الفرعية والمتطلبات، فيُرفع الشاهد مرة واحدة وينعكس على تقديرات القسم.'),
      canEdit && h('div', { class: 'row cal-actions' },
        !tasks.length && h('button', { class: 'btn gold', onclick: () => seedDialog(cycle, reload) }, 'تحميل جدول أعمال الجودة'),
        h('button', { class: tasks.length ? 'btn gold' : 'btn ghost', onclick: () => taskDialog(cycle, null, reload) }, '+ إضافة مهمة'))),
    h('div', { class: 'scope-pick' },
      deptIds.length > 1 && h('label', null, 'القسم ', h('select', { onchange: e => go('quality', { dept: e.target.value, view }) },
        h('option', { value: '' }, 'كل الأقسام'), departments.map(d => h('option', { value: String(d.id), selected: d.id === dept }, d.name_ar)))),
      h('div', { class: 'scope-stats' },
        h('span', null, h('b', null, num(tasks.length)), ' مهمة'),
        h('span', { class: 'st-done' }, h('b', null, `${num(doneP)}%`), ' إنجاز'),
        h('span', { class: 'st-soon' }, h('b', null, num(cnt(['submitted']))), ' بانتظار الاعتماد'),
        h('span', { class: 'st-overdue' }, h('b', null, num(cnt(['overdue', 'returned']))), ' متأخرة أو مُعادة'))));

  const tabs = h('div', { class: 'qw-tabs', role: 'tablist' },
    [['weeks', 'الجدول الأسبوعي'], ['map', 'التوافق مع المعايير']].map(([k, t]) =>
      h('button', { role: 'tab', class: view === k ? 'on' : '', 'aria-selected': String(view === k), onclick: () => go('quality', { dept: dept ?? '', view: k }) }, t)));

  if (!tasks.length) {
    return h('div', { class: 'cal-page' }, hero, h('section', { class: 'card empty' }, h('h2', null, 'لم يُحمَّل جدول أعمال الجودة بعد'),
      h('p', null, canEdit ? 'اضغط «تحميل جدول أعمال الجودة» وأدخل تاريخ بداية الفصل، أو أضف المهام واحدة واحدة.'
        : 'يظهر هنا جدول أعمال الجودة بعد أن تحمّله وكالة الجودة.')));
  }

  const subTitle = Object.fromEntries(catalog.map(s => [s.code, s.title]));
  const taskCard = t => {
    const subs = [...new Set(t.links.map(l => l.sub_standard_code))];
    const reqs = t.links.filter(l => l.kind === 'req');
    const single = shown.length === 1 ? shown[0] : null;
    const st = single ? statusOf(t, single, today) : null;
    const sub = single ? t.submissions[String(single)] : null;
    const canSubmit = single && (state.me.grants.some(g => ['dept_coordinator', 'hod', 'faculty'].includes(g.role)
      && (g.department_id == null || g.department_id === single)) || canEdit);
    const left = t.due_on ? Math.round((new Date(`${t.due_on}T00:00:00`) - new Date(`${today}T00:00:00`)) / 864e5) : null;
    return h('article', { class: `qw-task ${st ? `s-${st}` : ''}` },
      h('div', { class: 'qw-due' }, t.due_on ? [h('b', null, num(new Date(`${t.due_on}T00:00:00`).getDate())),
        h('span', null, new Date(`${t.due_on}T00:00:00`).toLocaleDateString('ar-SA-u-ca-gregory', { month: 'short' }))] : h('span', null, '—')),
      h('div', { class: 'qw-body' },
        h('h3', null, t.title_ar),
        h('p', { class: 'muted' }, t.due_hint_ar ?? '', t.due_on && ` · ${date(t.due_on)}`,
          left != null && !(st && ['submitted', 'approved', 'na'].includes(st)) && (left < 0 ? ` · متأخرة ${num(-left)} يوم` : left <= 7 ? ` · باقي ${num(left)} يوم` : '')),
        (t.condition_ar || t.notes_ar) && h('div', { class: 'qw-meta' },
          t.condition_ar && h('span', { class: 'chip c-mid' }, t.condition_ar), t.notes_ar && h('span', { class: 'faint' }, t.notes_ar)),
        h('div', { class: 'qw-links' },
          subs.map(c => h('span', { class: 'qw-sub-chip', title: c }, subTitle[c] ?? c)),
          reqs.length ? h('span', { class: 'chip c-good', title: reqs.map(r => r.title).join('\n') }, `ينعكس على ${num(reqs.length)} متطلب`)
            : canEdit && h('span', { class: 'chip c-mid' }, 'حدّد المتطلبات ليُربط الشاهد تلقائياً')),
        single ? h('div', { class: 'qw-mine' },
          h('span', { class: `chip ${STC[st]}` }, ST[st]),
          sub?.url && h('a', { href: sub.url, target: '_blank', rel: 'noopener' }, 'الشاهد ↗'),
          sub?.review_note_ar && h('span', { class: 'qw-return' }, sub.review_note_ar),
          canSubmit && st !== 'approved' && h('button', { class: 'btn small primary', onclick: () => submitDialog(t, single, reload) },
            sub ? 'تحديث التسليم' : 'تسليم'),
          canEdit && sub && h('button', { class: 'btn small', onclick: () => reviewDialog(t, single, reload) }, 'مراجعة'))
          : h('div', { class: 'qw-depts' }, shown.map(d => {
            const s = statusOf(t, d, today);
            return h('button', { class: `qw-dot ${STC[s]}`, title: `${deptName(d)}: ${ST[s]}`,
              onclick: () => (t.submissions[String(d)] && canEdit ? reviewDialog(t, d, reload) : go('quality', { dept: d, view })) },
            h('span', null, deptName(d)), h('i', null, ST[s]));
          }))),
      canEdit && h('div', { class: 'qw-tools' },
        h('button', { class: 'btn small', onclick: () => linksDialog(t, catalog, reload) }, 'التوافق'),
        h('button', { class: 'btn small', onclick: () => taskDialog(cycle, t, reload) }, 'تعديل'),
        h('button', { class: 'btn small', onclick: async () => {
          if (!confirm('حذف المهمة وتسليماتها؟')) return;
          try { await api(`/quality-tasks/${t.id}`, { method: 'DELETE' }); toast('حُذفت'); reload(); } catch (ex) { toast(ex.message, 'error'); }
        } }, 'حذف')));
  };

  let body;
  if (view === 'weeks') {
    const byWeek = new Map();
    for (const t of tasks) { if (!byWeek.has(t.week_no)) byWeek.set(t.week_no, []); byWeek.get(t.week_no).push(t); }
    body = h('section', { class: 'qw-weeks' }, [...byWeek].map(([w, xs]) =>
      h('div', { class: 'qw-week' }, h('div', { class: 'qw-wk' }, h('b', null, num(w)), h('span', null, week(w))), h('div', { class: 'qw-list' }, xs.map(taskCard)))));
  } else {
    // التوافق: لكل معيار فرعي المهام التي تغذيه والمتطلبات التي ينعكس عليها شاهدها
    let lastStd = null;
    const rows = [];
    let covered = 0, reqCovered = 0;
    for (const ss of catalog) {
      const ts = tasks.filter(t => t.links.some(l => l.sub_standard_code === ss.code));
      const reqCodes = new Set(tasks.flatMap(t => t.links.filter(l => l.kind === 'req' && l.sub_standard_code === ss.code).map(l => l.code)));
      if (ts.length) covered += 1;
      reqCovered += reqCodes.size;
      if (ss.standard_code !== lastStd) { lastStd = ss.standard_code; rows.push(h('tr', { class: 'qw-std-row' }, h('th', { colspan: 3 }, ss.standard_title))); }
      rows.push(h('tr', { class: ts.length ? 'on' : '' },
        h('td', null, h('bdi', { class: 'ssub-code' }, ss.code), ' ', ss.title),
        h('td', null, ts.length ? h('ul', { class: 'qw-tlist' }, ts.map(t => h('li', null, h('span', { class: 'qw-w' }, week(t.week_no)), ' ', t.title_ar)))
          : h('span', { class: 'faint' }, 'لا توجد مهام مرتبطة')),
        h('td', null, ss.requirements.length ? h('ul', { class: 'qw-rlist' }, ss.requirements.map(r =>
          h('li', { class: reqCodes.has(r.code) ? 'hit' : '' }, h('bdi', { class: 'ssub-code' }, r.code), ' ', r.text))) : '—')));
    }
    body = h('section', { class: 'card' },
      h('div', { class: 'qw-map-sum' },
        h('div', null, h('b', null, num(covered)), h('span', null, `من ${num(catalog.length)} معيار فرعي تغذيه أعمال الجودة`)),
        h('div', null, h('b', null, num(reqCovered)), h('span', null, 'متطلب يُربط شاهده تلقائياً من أعمال الجودة')),
        h('div', null, h('b', null, num(tasks.length)), h('span', null, 'مهمة في الجدول'))),
      h('p', { class: 'muted' }, 'المتطلبات المظللة يكفي فيها تسليم مهمة أعمال الجودة؛ يُربط الشاهد بها تلقائياً في مساحة القسم ولا يُرفع مرتين.'
        + (canEdit ? ' لتغيير الربط اضغط «التوافق» على المهمة في الجدول الأسبوعي.' : '')),
      h('div', { class: 'matrix-wrap' }, h('table', { class: 'data qw-map' },
        h('thead', null, h('tr', null, h('th', null, 'المعيار الفرعي'), h('th', null, 'مهام أعمال الجودة المرتبطة'), h('th', null, 'المتطلبات'))),
        h('tbody', null, rows))));
  }
  return h('div', { class: 'cal-page' }, hero, tabs, body);
}
