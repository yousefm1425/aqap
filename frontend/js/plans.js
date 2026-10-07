import { api } from './api.js';
import { deptName, parseRoute, state, userScope } from './app.js';
import { ACTION_STATUS, ACTION_TRANSITIONS, ADEQUACY, PRIORITY, RATING } from './labels.js';
import { date, dateTime, h, hasRole, mount, num, promptText, toast } from './ui.js';
import { scaleControl } from './workspace.js';

const DEPT_ROLES = ['hod', 'dept_coordinator', 'faculty'];
const MANAGERS = ['quality_dean', 'quality_auditor', 'system_admin'];
const OPEN = ['draft', 'submitted', 'revision', 'approved'];

const isMember = (p) => hasRole(state.me, DEPT_ROLES, p.department_id, p.cycle_id)
  && state.me.grants.some(g => DEPT_ROLES.includes(g.role) && g.department_id === p.department_id);

function myTransitions(p) {
  return ACTION_TRANSITIONS.filter(t => t.from.includes(p.status)
    && t.roles.some(r => (r === 'owner' ? p.owner_id === state.me.id : hasRole(state.me, [r], p.department_id, p.cycle_id)))
    && !(t.independent && isMember(p)));
}

const FILTERS = [
  ['all', 'الكل', () => true],
  ['mine', 'بانتظار إجرائي', p => myTransitions(p).some(t => t.to !== 'cancelled')
    || (['draft', 'revision'].includes(p.status) && isMember(p))],
  ['overdue', 'متأخرة', p => p.is_overdue],
  ['dept', 'لدى القسم', p => ['draft', 'revision'].includes(p.status)],
  ['review', 'بانتظار الملاءمة', p => p.status === 'submitted'],
  ['doing', 'قيد التنفيذ', p => p.status === 'approved'],
  ['verify', 'بانتظار التحقق', p => p.status === 'completed'],
  ['closed', 'مغلقة', p => p.status === 'verified'],
];

function setParams(params) {
  const qs = new URLSearchParams(Object.entries(params).filter(([, v]) => v != null && v !== '')).toString();
  history.replaceState(null, '', `#/plans${qs ? `?${qs}` : ''}`);
}

export async function renderPlans() {
  const cycle = state.cycle;
  const { params } = parseRoute();
  const sc = userScope();
  const deptOptions = sc.all ? ['all', ...state.departments.map(d => d.id), null] : sc.depts;
  let dept = params.dept === 'inst' ? null : params.dept === 'all' ? 'all' : params.dept ? Number(params.dept) : deptOptions[0] ?? 'all';
  if (deptOptions.length && !deptOptions.includes(dept)) dept = deptOptions[0];
  let filter = FILTERS.some(([k]) => k === params.filter) ? params.filter
    : (sc.all ? 'all' : 'mine');
  let selected = params.a ? Number(params.a) : null;
  let plans = [];
  const memberCache = new Map();
  const bankCache = new Map();

  const head = h('div', { class: 'ws-head' });
  const filtersEl = h('div', { class: 'filters', role: 'toolbar', 'aria-label': 'تصفية الخطط' });
  const listEl = h('nav', { class: 'req-list', 'aria-label': 'قائمة خطط التحسين' });
  const detailEl = h('div', { class: 'detail' });
  const view = h('div', null, head, filtersEl, h('div', { class: 'ws' }, listEl, detailEl));
  const urlParams = () => ({ dept: dept === null ? 'inst' : dept, filter, a: selected });
  const match = key => FILTERS.find(([k]) => k === key)[2];

  async function load() {
    const all = await api(`/cycles/${cycle.id}/actions`);
    plans = dept === 'all' ? all : all.filter(p => p.department_id === dept || (!deptOptions.length && p.owner_id === state.me.id));
  }

  function renderHead() {
    const open = plans.filter(p => OPEN.includes(p.status)).length;
    const closed = plans.filter(p => p.status === 'verified').length;
    const active = plans.filter(p => p.status !== 'cancelled').length;
    const late = plans.filter(p => p.is_overdue).length;
    const picker = deptOptions.length > 1 && h('select', {
      class: 'input', 'aria-label': 'القسم', style: { width: 'auto' },
      onchange: async e => {
        const v = e.target.value;
        dept = v === 'all' ? 'all' : v === 'inst' ? null : Number(v);
        selected = null; setParams(urlParams()); await refresh();
      },
    }, deptOptions.map(d => h('option', { value: d === null ? 'inst' : String(d) }, d === 'all' ? 'كل الأقسام' : deptName(d))));
    if (picker) picker.value = dept === null ? 'inst' : String(dept);
    mount(head,
      h('div', { class: 'title' },
        h('h1', null, `خطط التحسين — ${dept === 'all' ? 'كل الأقسام' : deptName(dept)}`),
        h('div', { class: 'progress-line' },
          h('span', null, h('b', null, num(open)), ' مفتوحة'),
          h('span', null, h('b', null, `${num(closed)}/${num(active)}`), ' مغلقة بعد التحقق'),
          h('span', { style: late ? { color: 'var(--not-met)' } : null }, h('b', null, num(late)), ' متأخرة'))),
      picker);
    mount(filtersEl, FILTERS.map(([key, label, fn]) => h('button', {
      type: 'button', 'aria-pressed': String(filter === key),
      onclick: () => { filter = key; setParams(urlParams()); renderHead(); renderList(); },
    }, `${label} (${num(plans.filter(fn).length)})`)));
  }

  function renderList() {
    const top = listEl.scrollTop;
    const items = plans.filter(match(filter));
    if (!items.length) {
      mount(listEl, h('p', { class: 'empty' }, plans.length
        ? 'لا توجد خطط في هذا التصنيف.'
        : 'لا توجد خطط تحسين بعد. تتولد الخطة تلقائياً عند الاعتماد النهائي لأي متطلب بتقدير «متحقق جزئي» أو «غير متحقق».'));
      return;
    }
    const nodes = [];
    let group;
    for (const p of items) {
      const g = dept === 'all' ? deptName(p.department_id) : null;
      if (g && g !== group) { group = g; nodes.push(h('div', { class: 'req-group' }, g)); }
      nodes.push(h('button', {
        type: 'button', class: 'req-item', 'aria-current': String(p.id === selected), onclick: () => select(p.id),
      },
        h('span', { class: `dot r-${p.eff_rating ?? 'none'}`, title: p.eff_rating ? RATING[p.eff_rating] : '' }),
        h('span', { class: 'code' }, p.requirement_code ?? 'خطة يدوية'),
        h('span', { class: 'meta' },
          p.due_date && h('span', { class: 'faint', style: p.is_overdue ? { color: 'var(--not-met)' } : null },
            p.is_overdue ? `متأخرة ${num(p.days_overdue)} يوم` : date(p.due_date)),
          h('span', { class: `status a-${p.status}` }, ACTION_STATUS[p.status])),
        h('span', { class: 'text' }, p.action_ar || p.requirement_text || p.title_ar)));
    }
    mount(listEl, nodes);
    listEl.scrollTop = top;
  }

  async function select(id) {
    selected = id; setParams(urlParams()); renderList(); await renderDetail();
    if (window.matchMedia('(max-width: 900px)').matches) detailEl.scrollIntoView({ block: 'start' });
  }

  async function refresh() {
    await load();
    if (selected && !plans.some(p => p.id === selected)) selected = null;
    renderHead(); renderList(); await renderDetail();
  }

  async function act(fn, ok) {
    try { await fn(); if (ok) toast(ok); await refresh(); } catch (ex) { toast(ex.message, 'error'); }
  }

  async function members(deptId) {
    if (deptId == null) return [];
    if (!memberCache.has(deptId)) memberCache.set(deptId, await api(`/departments/${deptId}/members`).catch(() => []));
    return memberCache.get(deptId);
  }

  async function bank(deptId) {
    const key = deptId ?? 'inst';
    if (!bankCache.has(key)) bankCache.set(key, await api(`/evidence${deptId == null ? '' : `?department_id=${deptId}`}`));
    return bankCache.get(key);
  }

  async function runTransition(p, t) {
    let comment = null, adequacy = null;
    if (t.adequacy) {
      const r = await promptText({ title: t.label, label: 'ملاحظات للقسم: ما الذي يجعل الخطة مناسبة', confirm: t.label,
                                   choices: { insufficient: ADEQUACY.insufficient, unsuitable: ADEQUACY.unsuitable } });
      if (r === null) return;
      comment = r.text; adequacy = r.choice;
    } else if (t.comment || t.optionalComment) {
      comment = await promptText({ title: t.label, label: t.comment ? 'السبب (يظهر للقسم)' : 'ملاحظة التحقق (اختيارية)',
                                   confirm: t.label, required: Boolean(t.comment) });
      if (comment === null) return;
    }
    await act(() => api(`/actions/${p.id}/transition`, { method: 'POST', body: { to_status: t.to, comment, adequacy } }),
              `تم: ${t.label}`);
  }

  async function renderDetail() {
    if (!selected) {
      mount(detailEl, h('div', { class: 'empty' }, h('h2', null, 'اختر خطة من القائمة'),
        h('p', null, 'لكل متطلب يحتاج تحسيناً خطة: يكتبها القسم، ويحكم المقيّم على ملاءمتها، ثم تُنفَّذ، ولا تُغلق إلا بتحقق طرف مستقل.')));
      return;
    }
    mount(detailEl, h('p', { class: 'skeleton', style: { padding: '1.5rem' } }, 'جارٍ تحميل الخطة…'));
    const p = await api(`/actions/${selected}`);
    const member = isMember(p);
    const canPlan = ['draft', 'revision'].includes(p.status)
      && (member || hasRole(state.me, MANAGERS, p.department_id, p.cycle_id));
    const canExtend = p.status === 'approved'
      && hasRole(state.me, ['hod', 'quality_dean', 'quality_auditor'], p.department_id, p.cycle_id);
    const canDo = p.status === 'approved' && (member || p.owner_id === state.me.id);
    const lastBack = [...p.history].reverse().find(x => ['revision', 'approved'].includes(x.to_status) && x.comment);

    // 1) المتطلب والتوصية
    const header = h('section', null,
      h('div', { class: 'crumbs' }, `${deptName(p.department_id)} ‹ ${p.title_ar}`),
      h('div', { class: 'row' }, h('strong', null, p.requirement_code ?? 'خطة يدوية'),
        h('span', { class: `status a-${p.status}` }, ACTION_STATUS[p.status]),
        p.eff_rating && h('span', { class: 'readonly-val' }, h('span', { class: `dot r-${p.eff_rating}` }), RATING[p.eff_rating])),
      p.requirement_text && h('p', { class: 'req-text' }, p.requirement_text),
      h('div', { class: 'field' }, h('label', null, 'توصيات المقيّم الخارجي'),
        h('p', { class: p.ext_recommendation ? '' : 'muted' }, p.ext_recommendation || 'لا توجد توصية مسجلة.')),
      ['revision', 'approved'].includes(p.status) && lastBack && lastBack.to_status === p.status && h('div', { class: 'notice' },
        h('strong', null, `${p.status === 'revision' ? 'أعادها' : 'أعادها للتنفيذ'} ${lastBack.actor}: `), lastBack.comment));

    // 2) الخطة
    const draft = { action_ar: p.action_ar ?? '', owner_id: p.owner_id, owner_label: p.owner_label ?? '', due_date: p.due_date,
                    priority: p.priority };
    const actionTa = h('textarea', { id: 'plan-action', disabled: !canPlan, oninput: e => { draft.action_ar = e.target.value; } });
    actionTa.value = draft.action_ar;
    const people = await members(p.department_id);
    const owner = h('select', { class: 'input', id: 'plan-owner', disabled: !canPlan,
                               onchange: e => { draft.owner_id = e.target.value ? Number(e.target.value) : null; } },
      h('option', { value: '' }, 'اختر من أعضاء القسم…'),
      people.map(u => h('option', { value: String(u.id) }, u.full_name_ar)));
    owner.value = draft.owner_id ? String(draft.owner_id) : '';
    if (draft.owner_id && !people.some(u => u.id === draft.owner_id)) {
      owner.append(h('option', { value: String(draft.owner_id) }, p.owner_name)); owner.value = String(draft.owner_id);
    }
    const ownerLabel = h('input', { type: 'text', id: 'plan-owner-label', disabled: !canPlan, placeholder: 'أو جهة: لجنة الجداول، وحدة التدريب…',
                                    oninput: e => { draft.owner_label = e.target.value; } });
    ownerLabel.value = draft.owner_label;
    const due = h('input', { type: 'date', class: 'input', id: 'plan-due', disabled: !(canPlan || canExtend),
                             oninput: e => { draft.due_date = e.target.value || null; } });
    due.value = draft.due_date ?? '';
    const planSection = h('section', null,
      h('h2', null, 'الخطة'),
      h('div', { class: 'field' }, h('label', { for: 'plan-action' }, 'الإجراءات التحسينية'), actionTa),
      h('div', { class: 'grid2' },
        h('div', { class: 'field' }, h('label', { for: 'plan-owner' }, 'المسؤول عن التنفيذ'), owner, ownerLabel),
        h('div', { class: 'field' }, h('label', { for: 'plan-due' }, 'تاريخ اكتمال التنفيذ'), due,
          h('label', null, 'الأولوية'),
          scaleControl({ options: ['1', '2', '3'], labels: PRIORITY, value: String(draft.priority), disabled: !canPlan,
                         onChange: v => { draft.priority = Number(v); } }))),
      canPlan && h('div', { class: 'row end' }, h('button', { class: 'btn', onclick: () => act(() => api(`/actions/${p.id}`, {
        method: 'PATCH', body: { ...draft, owner_label: draft.owner_label || null } }), 'حُفظت الخطة') }, 'حفظ الخطة')),
      canExtend && h('div', { class: 'row end' }, h('button', { class: 'btn', onclick: () => act(() => api(`/actions/${p.id}`, {
        method: 'PATCH', body: { due_date: draft.due_date } }), 'عُدّل موعد التنفيذ') }, 'تعديل الموعد')));

    // 3) حكم الملاءمة
    const reviewSection = (p.adequacy || p.status === 'submitted') && h('section', null,
      h('h2', null, 'ملاءمة الإجراءات'),
      p.adequacy
        ? h('div', { class: 'readonly-val' }, h('strong', null, ADEQUACY[p.adequacy]),
            h('span', { class: 'faint' }, `— ${p.adequacy_by_name ?? ''}، ${dateTime(p.adequacy_at)}`))
        : h('p', { class: 'muted' }, 'بانتظار حكم المقيّم على ملاءمة الإجراءات.'),
      p.reviewer_notes && h('p', null, p.reviewer_notes),
      p.status === 'submitted' && isMember(p) && hasRole(state.me, ['quality_auditor', 'external_reviewer'], p.department_id, p.cycle_id)
        && h('p', { class: 'notice' }, 'لا يمكنك الحكم على خطة قسم تنتمي إليه؛ يحكم عليها مقيّم من خارج القسم.'));

    // 4) التنفيذ
    let doSection = null;
    if (['approved', 'completed', 'verified'].includes(p.status)) {
      const progress = h('input', { type: 'range', min: '0', max: '100', step: '10', value: String(p.progress_pct), disabled: !canDo,
                                   id: 'plan-progress', 'aria-label': 'نسبة الإنجاز' });
      const progressVal = h('b', null, `${p.progress_pct}%`);
      progress.addEventListener('input', () => { progressVal.textContent = `${progress.value}%`; });
      const evRow = h('div', { class: 'field' });
      if (canDo) {
        const evs = await bank(p.department_id);
        const pick = h('select', { class: 'input', 'aria-label': 'شاهد التحسين' },
          h('option', { value: '' }, 'اختر شاهد التحسين من بنك القسم…'),
          evs.map(e => h('option', { value: String(e.id) }, e.title_ar)));
        pick.value = p.completion_evidence_id ? String(p.completion_evidence_id) : '';
        const title = h('input', { type: 'text', placeholder: 'أو عنوان شاهد جديد', 'aria-label': 'عنوان شاهد جديد' });
        const file = h('input', { type: 'file', 'aria-label': 'ملف الشاهد' });
        mount(evRow, h('label', null, 'شواهد التحسين'), pick, h('div', { class: 'ev-add' },
          h('div', { class: 'field' }, title, file),
          h('button', { class: 'btn', style: { alignSelf: 'end' }, onclick: () => act(async () => {
            if (title.value.trim().length < 3 || !file.files[0]) throw new Error('اكتب عنوان الشاهد وأرفق ملفه');
            const ev = await api('/evidence', { method: 'POST', body: { title_ar: title.value.trim(), kind: 'file', department_id: p.department_id } });
            const form = new FormData(); form.append('file', file.files[0]);
            await api(`/evidence/${ev.id}/versions`, { method: 'POST', form });
            await api(`/actions/${p.id}`, { method: 'PATCH', body: { completion_evidence_id: ev.id } });
            bankCache.delete(p.department_id ?? 'inst');
          }, 'رُفع شاهد التحسين') }, 'رفع')));
        evRow.append(h('div', { class: 'row end' }, h('button', { class: 'btn', onclick: () => act(() => api(`/actions/${p.id}`, {
          method: 'PATCH', body: { progress_pct: Number(progress.value), completion_evidence_id: pick.value ? Number(pick.value) : null } }),
          'حُفظ التقدم') }, 'حفظ التقدم')));
      } else {
        mount(evRow, h('label', null, 'شواهد التحسين'), p.completion_evidence_id
          ? h('div', { class: 'row' }, h('span', null, p.completion_evidence_title),
              h('button', { class: 'btn small', onclick: async () => {
                try { const r = await api(`/evidence/${p.completion_evidence_id}/download`); window.open(r.url, '_blank', 'noopener'); }
                catch (ex) { toast(ex.message, 'error'); }
              } }, 'فتح'))
          : h('p', { class: 'muted' }, 'لم يُربط شاهد تحسين بعد.'));
      }
      doSection = h('section', null, h('h2', null, 'التنفيذ'),
        h('div', { class: 'field' }, h('label', { for: 'plan-progress' }, 'نسبة الإنجاز'), h('div', { class: 'row' }, progress, progressVal)),
        evRow,
        p.completed_on && h('p', { class: 'faint' }, `أُعلن الإنجاز ${date(p.completed_on)} — ${p.completed_by_name ?? ''}`),
        p.status === 'verified' && h('div', { class: 'readonly-val' }, h('strong', null, 'تحقق مستقل:'),
          h('span', null, `${p.verified_by_name}، ${dateTime(p.verified_at)}`)),
        p.verification_note && h('p', null, p.verification_note));
    }

    // 5) المسار
    const transitions = myTransitions(p);
    const flow = h('section', null, h('h2', null, 'مسار الخطة'),
      transitions.length > 0 && h('div', { class: 'row' }, transitions.map(t => h('button', {
        class: `btn${t.primary ? ' primary' : ''}${t.danger ? ' danger' : ''}`, onclick: () => runTransition(p, t) }, t.label))),
      p.history.length
        ? h('ol', { class: 'timeline' }, p.history.map(x => h('li', null, h('span', null, dateTime(x.at)),
            h('strong', null, ACTION_STATUS[x.to_status]), h('span', null, `— ${x.actor}`), x.comment && h('q', null, x.comment))))
        : h('p', { class: 'faint' }, 'لم تُرفع الخطة بعد.'));

    mount(detailEl, header, planSection, reviewSection, doSection, flow);
  }

  await load();
  renderHead(); renderList(); await renderDetail();
  return view;
}
