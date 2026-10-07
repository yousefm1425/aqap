import { api, apiOpen } from './api.js';
import { deptName, parseRoute, state, userScope } from './app.js';
import { dateTime, h, hasRole, mount, num, pct, promptText, toast } from './ui.js';

const DEPT_ROLES = ['hod', 'dept_coordinator', 'faculty'];
const STATUS = { draft: 'مسودة', submitted: 'بانتظار اعتماد رئيس القسم', returned: 'معاد للتعديل', approved: 'معتمد' };
const STATUS_CLASS = { draft: 's-draft', submitted: 's-submitted', returned: 's-returned', approved: 's-final' };
const FU = { done: 'مُنفذ', partial: 'مُنفذ جزئي', not_done: 'لم يُنفذ' };
const SEMESTERS = ['الأول', 'الثاني', 'الصيفي'];
const ORD = ['الأول', 'الثاني', 'الثالث', 'الرابع', 'الخامس', 'السادس', 'السابع', 'الثامن', 'التاسع', 'العاشر', 'الحادي عشر', 'الثاني عشر'];
const ACTIVE = ['open', 'external_review'];

const hijri = iso => (iso ? new Date(`${iso}T12:00:00`).toLocaleDateString('ar-SA-u-ca-islamic-umalqura-nu-latn',
  { day: 'numeric', month: 'long', year: 'numeric' }) : '');
const weekday = iso => (iso ? new Date(`${iso}T12:00:00`).toLocaleDateString('ar-SA', { weekday: 'long' }) : '');

function setParams(params) {
  const qs = new URLSearchParams(Object.entries(params).filter(([, v]) => v != null && v !== '')).toString();
  history.replaceState(null, '', `#/minutes${qs ? `?${qs}` : ''}`);
}

export async function renderMinutes() {
  const cycle = state.cycle;
  const { params } = parseRoute();
  const sc = userScope();
  const deptOptions = sc.all ? state.departments.map(d => d.id) : sc.depts;
  if (!deptOptions.length) return h('div', { class: 'empty' }, 'لا يوجد قسم مسند إليك في هذه الدورة.');
  let dept = params.dept ? Number(params.dept) : deptOptions[0];
  if (!deptOptions.includes(dept)) dept = deptOptions[0];
  let selected = params.m ? Number(params.m) : null;
  let openTpl = params.tpl ? Number(params.tpl) : null;
  let templates = [];
  let list = [];
  let members = null;

  const head = h('div', { class: 'ws-head' });
  const listEl = h('nav', { class: 'req-list', 'aria-label': 'نماذج المحاضر' });
  const detailEl = h('div', { class: 'detail' });
  const view = h('div', null, head, h('div', { class: 'ws' }, listEl, detailEl));
  const isDept = () => hasRole(state.me, DEPT_ROLES, dept, cycle.id);
  const urlParams = () => ({ dept, tpl: openTpl, m: selected });

  async function load() {
    [templates, list] = await Promise.all([
      api(`/cycles/${cycle.id}/minutes/templates?department_id=${dept}`),
      api(`/cycles/${cycle.id}/minutes?department_id=${dept}`),
    ]);
  }

  function renderHead() {
    const covered = templates.filter(t => t.approved > 0).length;
    const approved = list.filter(m => m.status === 'approved');
    const withFu = approved.filter(m => m.completion_pct != null && Number(m.rec_pending) < Number(m.rec_total));
    const avg = withFu.length ? withFu.reduce((s, m) => s + Number(m.completion_pct), 0) / withFu.length : null;
    const picker = deptOptions.length > 1 && h('select', {
      class: 'input', 'aria-label': 'القسم', style: { width: 'auto' },
      onchange: async e => { dept = Number(e.target.value); selected = null; members = null; setParams(urlParams()); await refresh(); },
    }, deptOptions.map(d => h('option', { value: String(d) }, deptName(d))));
    if (picker) picker.value = String(dept);
    mount(head,
      h('div', { class: 'title' },
        h('h1', null, `المحاضر — ${deptName(dept)}`),
        h('div', { class: 'progress-line' },
          h('span', null, h('b', null, `${num(covered)}/${num(templates.length)}`), ' متطلب له محضر معتمد'),
          h('span', null, h('b', null, num(list.length)), ' محضراً'),
          h('span', null, h('b', null, pct(avg)), ' متوسط تنفيذ التوصيات'))),
      picker);
  }

  function renderList() {
    const top = listEl.scrollTop;
    const canCreate = isDept() && ACTIVE.includes(cycle.status);
    mount(listEl, templates.map(t => {
      const mine = list.filter(m => m.template_id === t.id);
      const expanded = openTpl === t.id || mine.some(m => m.minutes_id === selected);
      return h('div', { class: 'min-group' },
        h('button', { type: 'button', class: 'min-tpl', 'aria-expanded': String(expanded), onclick: () => {
          openTpl = expanded ? null : t.id; setParams(urlParams()); renderList();
        } },
          h('span', { class: `dot ${t.approved ? 'r-met' : mine.length ? 'r-partial' : 'r-none'}`,
                      title: t.approved ? 'له محضر معتمد' : mine.length ? 'محاضر غير معتمدة' : 'لا محاضر' }),
          h('span', { class: 'code' }, t.requirement_code),
          h('span', { class: 'meta faint' }, mine.length ? `${num(t.approved)}/${num(mine.length)} معتمد` : ''),
          h('span', { class: 'text' }, t.title_ar)),
        expanded && h('div', { class: 'min-items' },
          mine.map(m => h('button', { type: 'button', class: 'req-item', 'aria-current': String(m.minutes_id === selected),
                                      onclick: () => select(m.minutes_id) },
            h('span', { class: 'code' }, `رقم ${m.meeting_no}`),
            h('span', { class: 'meta' }, h('span', { class: `status ${STATUS_CLASS[m.status]}` }, STATUS[m.status])),
            h('span', { class: 'text' }, `${m.meeting_date ? hijri(m.meeting_date) : 'بلا تاريخ'} · الفصل ${m.semester}`
              + (m.status === 'approved' && m.rec_total ? ` · التنفيذ ${pct(m.completion_pct)}` : '')))),
          !mine.length && h('p', { class: 'faint', style: { padding: '0 1rem .6rem' } }, 'لا توجد محاضر لهذا المتطلب بعد.'),
          canCreate && h('div', { style: { padding: '0 1rem .8rem' } }, h('button', { class: 'btn small', onclick: () => create(t) },
            '+ محضر جديد'))));
    }));
    listEl.scrollTop = top;
  }

  async function create(t) {
    try {
      const m = await api(`/cycles/${cycle.id}/minutes`, { method: 'POST', body: { template_id: t.id, department_id: dept } });
      toast(`أُنشئ محضر رقم ${m.meeting_no}`);
      openTpl = t.id; selected = m.id; setParams(urlParams());
      await refresh();
    } catch (ex) { toast(ex.message, 'error'); }
  }

  async function select(id) {
    selected = id; setParams(urlParams()); renderList(); await renderDetail();
    if (window.matchMedia('(max-width: 900px)').matches) detailEl.scrollIntoView({ block: 'start' });
  }

  async function refresh() {
    await load();
    if (selected && !list.some(m => m.minutes_id === selected)) selected = null;
    renderHead(); renderList(); await renderDetail();
  }

  async function act(fn, ok) {
    try { const r = await fn(); if (ok) toast(typeof ok === 'function' ? ok(r) : ok); await refresh(); return r; }
    catch (ex) { toast(ex.message, 'error'); return null; }
  }

  async function deptMembers() {
    if (!members) members = await api(`/departments/${dept}/members`).catch(() => []);
    return members;
  }

  async function renderDetail() {
    if (!selected) {
      mount(detailEl, h('div', { class: 'empty' }, h('h2', null, 'اختر متطلباً ثم محضراً'),
        h('p', null, 'لكل متطلب من نوع «محضر» نموذج موحّد: محاور، وتوصيات بمسؤول وفترة تنفيذ، وحضور، واعتماد رئيس القسم. '
          + 'عند الاعتماد يُحفظ المحضر PDF في بنك الشواهد ويُربط بالمتطلب، ثم تُتابع التوصيات حتى تنفيذها.')));
      return;
    }
    mount(detailEl, h('p', { class: 'skeleton', style: { padding: '1.5rem' } }, 'جارٍ تحميل المحضر…'));
    const m = await api(`/minutes/${selected}`);
    const editable = ['draft', 'returned'].includes(m.status) && isDept() && ACTIVE.includes(m.cycle_status);
    const canDecide = m.status === 'submitted' && hasRole(state.me, ['hod', 'quality_dean'], m.department_id, m.cycle_id);
    const canReopen = m.status === 'approved' && hasRole(state.me, ['quality_dean'], m.department_id, m.cycle_id)
      && ACTIVE.includes(m.cycle_status);
    const canFollow = m.status === 'approved' && (isDept() || hasRole(state.me, ['quality_dean', 'quality_auditor'], m.department_id, m.cycle_id));
    const draft = {
      title_ar: m.title_ar, semester: m.semester, meeting_date: m.meeting_date, start_time: m.start_time ?? '',
      location_ar: m.location_ar ?? '', follow_up_owner: m.follow_up_owner ?? '',
      agenda: m.agenda.map(a => ({ title_ar: a.title_ar, recommendations: a.recommendations.map(r => ({
        text_ar: r.text_ar, responsible_ar: r.responsible_ar ?? '', period_ar: r.period_ar ?? '' })) })),
      attendees: m.attendees.map(a => ({ name_ar: a.name_ar, role_ar: a.role_ar ?? '', user_id: a.user_id })),
    };
    let dirty = false;
    const touch = () => { dirty = true; };

    const save = async (quiet = false) => {
      const body = { ...draft, meeting_date: draft.meeting_date || null, start_time: draft.start_time || null,
                     location_ar: draft.location_ar || null, follow_up_owner: draft.follow_up_owner || null };
      await api(`/minutes/${m.id}`, { method: 'PUT', body });
      dirty = false;
      if (!quiet) toast('حُفظ المحضر');
    };

    // ١) الرأس
    const field = (label, input) => h('div', { class: 'field' }, h('label', null, label), input);
    const inp = (key, attrs = {}) => {
      const el = h('input', { type: 'text', disabled: !editable, ...attrs, oninput: e => { draft[key] = e.target.value; touch(); } });
      el.value = draft[key] ?? '';
      return el;
    };
    const dateEl = h('input', { type: 'date', class: 'input', disabled: !editable });
    dateEl.value = draft.meeting_date ?? '';
    const dateHint = h('span', { class: 'faint' }, draft.meeting_date ? `${weekday(draft.meeting_date)} ${hijri(draft.meeting_date)}` : '');
    dateEl.addEventListener('input', e => {
      draft.meeting_date = e.target.value || null; touch();
      dateHint.textContent = draft.meeting_date ? `${weekday(draft.meeting_date)} ${hijri(draft.meeting_date)}` : '';
    });
    const sem = h('select', { class: 'input', disabled: !editable, onchange: e => { draft.semester = e.target.value; touch(); } },
      SEMESTERS.map(s => h('option', { value: s }, `الفصل ${s}`)));
    sem.value = draft.semester;
    const last = [...m.history].reverse().find(x => x.to_status === 'returned');

    const header = h('section', null,
      h('div', { class: 'crumbs' }, `المتطلب ${m.requirement_code}: ${m.requirement_text ?? ''}`),
      h('div', { class: 'row' }, h('strong', null, `محضر رقم ${m.meeting_no}`),
        h('span', { class: `status ${STATUS_CLASS[m.status]}` }, STATUS[m.status]),
        h('span', { class: 'faint' }, `المرجع AQAP-M-${m.id}`)),
      m.status === 'returned' && m.return_reason && h('div', { class: 'notice' },
        h('strong', null, `أعاده ${last?.actor ?? ''}: `), m.return_reason),
      field('اسم الاجتماع', inp('title_ar')),
      h('div', { class: 'grid2' },
        field('تاريخ الاجتماع', h('div', null, dateEl, ' ', dateHint)),
        field('الفصل التدريبي', sem)),
      h('div', { class: 'grid2' },
        field('الوقت', inp('start_time', { placeholder: 'مثال: 10:00 ص' })),
        field('المكان', inp('location_ar', { placeholder: 'مثال: قاعة اجتماعات القسم' }))),
      m.guidance_ar && h('p', { class: 'faint' }, m.guidance_ar));

    // ٢) المحاور والتوصيات
    const agendaWrap = h('div');
    const renderAgenda = () => {
      mount(agendaWrap, draft.agenda.map((a, i) => {
        const title = h('input', { type: 'text', disabled: !editable, 'aria-label': `عنوان المحور ${ORD[i] ?? i + 1}`,
                                  oninput: e => { a.title_ar = e.target.value; touch(); } });
        title.value = a.title_ar;
        const cell = (r, key, ph) => {
          const el = h('textarea', { rows: 2, disabled: !editable, placeholder: ph,
            'aria-label': ph, oninput: e => { r[key] = e.target.value; touch(); } });
          el.value = r[key] ?? '';
          return el;
        };
        return h('div', { class: 'axis' },
          h('div', { class: 'axis-head' }, h('span', { class: 'axis-no' }, `المحور ${ORD[i] ?? i + 1}`), title,
            editable && h('button', { class: 'btn small danger', 'aria-label': 'حذف المحور', onclick: () => {
              draft.agenda.splice(i, 1); touch(); renderAgenda(); } }, 'حذف')),
          h('table', { class: 'data rec-table' },
            h('thead', null, h('tr', null, h('th', { style: { width: '3rem' } }, 'رقم'), h('th', null, 'التوصية'),
              h('th', { style: { width: '22%' } }, 'مسؤول التنفيذ'), h('th', { style: { width: '18%' } }, 'فترة التنفيذ'),
              editable && h('th', { style: { width: '3rem' } }))),
            h('tbody', null, a.recommendations.map((r, j) => h('tr', null,
              h('td', { class: 'faint' }, `${j + 1}.${i + 1}`),
              h('td', null, cell(r, 'text_ar', 'نص التوصية')),
              h('td', null, cell(r, 'responsible_ar', 'مسؤول التنفيذ')),
              h('td', null, cell(r, 'period_ar', 'مثال: الأسبوع الثالث')),
              editable && h('td', null, h('button', { class: 'btn small danger', 'aria-label': 'حذف التوصية', onclick: () => {
                a.recommendations.splice(j, 1); touch(); renderAgenda(); } }, '×')))),
              !a.recommendations.length && h('tr', null, h('td', { colspan: 5, class: 'faint' }, 'لا توجد توصيات لهذا المحور بعد.')))),
          editable && a.recommendations.length < 20 && h('button', { class: 'btn small', onclick: () => {
            a.recommendations.push({ text_ar: '', responsible_ar: '', period_ar: '' }); touch(); renderAgenda();
            agendaWrap.querySelectorAll('.axis')[i]?.querySelectorAll('textarea')[a.recommendations.length - 1]?.focus();
          } }, '+ توصية'));
      }));
      if (editable && draft.agenda.length < 12) agendaWrap.append(h('button', { class: 'btn', onclick: () => {
        draft.agenda.push({ title_ar: '', recommendations: [{ text_ar: '', responsible_ar: '', period_ar: '' }] }); touch(); renderAgenda();
      } }, '+ محور'));
    };
    renderAgenda();
    const agendaSection = h('section', null, h('h2', null, 'محاور الاجتماع والتوصيات'),
      editable && h('p', { class: 'faint' }, 'المحاور المقترحة من النموذج قابلة للتعديل. كل محور يحتاج توصية واحدة على الأقل بمسؤول تنفيذ.'),
      agendaWrap);

    // ٣) الحضور
    const attWrap = h('div');
    const people = editable ? await deptMembers() : [];
    const renderAtt = () => {
      const listed = new Set(draft.attendees.map(a => a.user_id).filter(Boolean));
      const avail = people.filter(p => !listed.has(p.id));
      const pick = editable && avail.length > 0 && h('select', { class: 'input', 'aria-label': 'إضافة من أعضاء القسم', style: { width: 'auto' },
        onchange: e => { const p = avail.find(x => x.id === Number(e.target.value)); if (p) {
          draft.attendees.push({ name_ar: p.full_name_ar, role_ar: 'عضو هيئة تدريب', user_id: p.id }); touch(); renderAtt(); } } },
        h('option', { value: '' }, 'إضافة من أعضاء القسم…'), avail.map(p => h('option', { value: String(p.id) }, p.full_name_ar)));
      mount(attWrap,
        h('table', { class: 'data' },
          h('thead', null, h('tr', null, h('th', { style: { width: '2.5rem' } }, 'م'), h('th', null, 'الاسم'), h('th', null, 'المهمة'),
            h('th', null, 'التأكيد'), editable && h('th', { style: { width: '3rem' } }))),
          h('tbody', null, draft.attendees.map((a, k) => {
            const saved = m.attendees.find(x => x.user_id && x.user_id === a.user_id);
            const nameEl = h('input', { type: 'text', disabled: !editable || Boolean(a.user_id), 'aria-label': 'الاسم',
                                        oninput: e => { a.name_ar = e.target.value; touch(); } });
            nameEl.value = a.name_ar;
            const roleEl = h('input', { type: 'text', disabled: !editable, 'aria-label': 'المهمة',
                                        oninput: e => { a.role_ar = e.target.value; touch(); } });
            roleEl.value = a.role_ar ?? '';
            return h('tr', null, h('td', { class: 'faint' }, k + 1), h('td', null, nameEl), h('td', null, roleEl),
              h('td', { class: 'faint' }, saved?.confirmed_at ? `أكّد ${dateTime(saved.confirmed_at)}`
                : a.user_id ? (m.status === 'draft' || m.status === 'returned' ? 'يؤكد بعد الرفع' : 'لم يؤكد بعد') : 'توقيع يدوي'),
              editable && h('td', null, h('button', { class: 'btn small danger', 'aria-label': 'حذف', onclick: () => {
                draft.attendees.splice(k, 1); touch(); renderAtt(); } }, '×')));
          }))),
        editable && h('div', { class: 'row', style: { marginTop: '.6rem' } }, pick,
          h('button', { class: 'btn small', onclick: () => { draft.attendees.push({ name_ar: '', role_ar: '', user_id: null }); touch(); renderAtt(); } },
            '+ حاضر من خارج المنصة')));
    };
    renderAtt();
    const me = m.attendees.find(a => a.user_id === state.me.id);
    const attSection = h('section', null, h('h2', null, `حضر الاجتماع (${num(draft.attendees.length)})`), attWrap,
      me && !me.confirmed_at && ['submitted', 'approved'].includes(m.status) && h('div', { class: 'notice' },
        'أنت ضمن الحضور. ', h('button', { class: 'btn small primary', onclick: () => act(
          () => api(`/minutes/${m.id}/attendees/confirm`, { method: 'POST' }), 'أُكّد حضورك') }, 'تأكيد حضوري')));

    // ٤) متابعة التوصيات (بعد الاعتماد)
    let fuSection = null;
    if (m.status === 'approved') {
      const s = m.summary;
      const ownerEl = h('span', null, m.follow_up_owner || '—');
      fuSection = h('section', null,
        h('h2', null, 'متابعة تنفيذ التوصيات'),
        h('div', { class: 'progress-line' },
          h('span', null, h('b', null, pct(s.completion_pct)), ' نسبة التنفيذ'),
          h('span', null, h('b', null, num(s.rec_done)), ' مُنفذ'), h('span', null, h('b', null, num(s.rec_partial)), ' جزئي'),
          h('span', null, h('b', null, num(s.rec_not_done)), ' لم يُنفذ'), h('span', null, h('b', null, num(s.rec_pending)), ' لم تُتابع')),
        h('p', { class: 'faint' }, 'مسؤول المتابعة: ', ownerEl, ' — النسبة = (مُنفذ + نصف المُنفذ جزئياً) ÷ إجمالي التوصيات.'),
        m.agenda.map((a, i) => h('div', { class: 'axis' },
          h('div', { class: 'axis-head' }, h('span', { class: 'axis-no' }, `المحور ${ORD[i] ?? i + 1}`), h('strong', null, a.title_ar)),
          a.recommendations.map((r, j) => {
            const st = h('select', { class: 'input', disabled: !canFollow, 'aria-label': 'حالة التنفيذ' },
              h('option', { value: '' }, 'لم تُتابع'), Object.entries(FU).map(([k, l]) => h('option', { value: k }, l)));
            st.value = r.fu_status ?? '';
            const obs = h('textarea', { rows: 2, disabled: !canFollow, placeholder: 'المعوقات والتحديات' }); obs.value = r.fu_obstacles ?? '';
            const sol = h('textarea', { rows: 2, disabled: !canFollow, placeholder: 'الحلول المقترحة' }); sol.value = r.fu_solutions ?? '';
            return h('div', { class: 'fu-row' },
              h('div', null, h('span', { class: 'faint' }, `${j + 1}.${i + 1} `), r.text_ar,
                h('div', { class: 'faint' }, `${r.responsible_ar ?? ''}${r.period_ar ? ` · ${r.period_ar}` : ''}`)),
              h('div', { class: 'fu-fields' }, st, obs, sol,
                canFollow && h('button', { class: 'btn small', onclick: () => act(() => api(`/minutes/recommendations/${r.id}/follow-up`, {
                  method: 'PATCH', body: { fu_status: st.value || null, fu_obstacles: obs.value.trim() || null, fu_solutions: sol.value.trim() || null } }),
                  'حُفظت المتابعة') }, 'حفظ'),
                r.fu_at && h('span', { class: 'faint' }, `${r.fu_by_name ?? ''} · ${dateTime(r.fu_at)}`)));
          }))),
        canFollow && h('div', { class: 'row end' }, h('button', { class: 'btn', onclick: e => {
          e.currentTarget.disabled = true; e.currentTarget.textContent = 'جارٍ الأرشفة…';
          return act(() => api(`/minutes/${m.id}/archive`, { method: 'POST' }), r => `أُرشفت النسخة ${r.version_no} في بنك الشواهد`);
        } }, 'أرشفة نسخة المتابعة')));
    }

    // ٥) الاعتماد والمسار
    const tr = async (to, comment = null) => {
      if (dirty && editable) await save(true);
      return api(`/minutes/${m.id}/transition`, { method: 'POST', body: { to_status: to, comment } });
    };
    const buttons = [];
    if (editable) {
      buttons.push(h('button', { class: 'btn', onclick: () => act(() => save()) }, 'حفظ المحضر'));
      buttons.push(h('button', { class: 'btn primary', onclick: () => act(() => tr('submitted'), 'رُفع المحضر لاعتماد رئيس القسم') },
        'رفع للاعتماد'));
      if (m.status === 'draft') buttons.push(h('button', { class: 'btn danger', onclick: async () => {
        const ok = await promptText({ title: 'حذف المسودة', label: 'اكتب «حذف» للتأكيد', confirm: 'حذف' });
        if (ok !== 'حذف') return;
        selected = null;
        await act(() => api(`/minutes/${m.id}`, { method: 'DELETE' }), 'حُذفت المسودة');
      } }, 'حذف المسودة'));
    }
    if (canDecide) {
      buttons.push(h('button', { class: 'btn primary', onclick: e => {
        const b = e.currentTarget; b.disabled = true; b.textContent = 'جارٍ الاعتماد وتوليد PDF…';
        return act(() => tr('approved'), r => (r.archive?.linked_to_requirement
          ? 'اعتُمد المحضر وأُرشف PDF وربط بالمتطلب شاهداً'
          : 'اعتُمد المحضر وأُرشف PDF في بنك الشواهد (التقدير ليس لدى القسم الآن؛ يُربط عند إعادته)'));
      } }, 'اعتماد المحضر'));
      buttons.push(h('button', { class: 'btn', onclick: async () => {
        const c = await promptText({ title: 'إعادة المحضر', label: 'سبب الإعادة (يظهر للقسم)', confirm: 'إعادة' });
        if (c !== null) await act(() => tr('returned', c), 'أُعيد المحضر للقسم');
      } }, 'إعادة للقسم'));
    }
    if (canReopen) buttons.push(h('button', { class: 'btn', onclick: async () => {
      const c = await promptText({ title: 'إعادة فتح المحضر', label: 'سبب إعادة الفتح (تُمسح المتابعة وتأكيدات الحضور)', confirm: 'إعادة فتح' });
      if (c !== null) await act(() => tr('returned', c), 'أُعيد فتح المحضر');
    } }, 'إعادة فتح'));
    buttons.push(h('button', { class: 'btn', onclick: async () => {
      try { if (dirty && editable) await save(true); await apiOpen(`/minutes/${m.id}/pdf`); } catch (ex) { toast(ex.message, 'error'); }
    } }, m.status === 'approved' ? 'عرض PDF' : 'معاينة PDF'));
    if (m.evidence_id) buttons.push(h('button', { class: 'btn', onclick: async () => {
      try { const r = await api(`/evidence/${m.evidence_id}/download`); window.open(r.url, '_blank', 'noopener'); }
      catch (ex) { toast(ex.message, 'error'); }
    } }, 'النسخة المؤرشفة'));

    const ownerInput = h('input', { type: 'text', disabled: !editable, placeholder: 'مثال: رئيس القسم',
                                    oninput: e => { draft.follow_up_owner = e.target.value; touch(); } });
    ownerInput.value = draft.follow_up_owner;
    const flow = h('section', null, h('h2', null, 'الاعتماد'),
      m.status !== 'approved' && field('مسؤول متابعة تنفيذ التوصيات', ownerInput),
      m.status === 'approved' && h('p', null, `اعتمده ${m.approved_by_name} — ${dateTime(m.approved_at)}`),
      h('div', { class: 'row' }, buttons),
      m.history.length > 0 && h('ol', { class: 'timeline' }, m.history.map(x => h('li', null, h('span', null, dateTime(x.at)),
        h('strong', null, STATUS[x.to_status]), h('span', null, `— ${x.actor}`), x.comment && h('q', null, x.comment)))));

    mount(detailEl, header, agendaSection, attSection, fuSection, flow);
  }

  await load();
  renderHead(); renderList(); await renderDetail();
  return view;
}
