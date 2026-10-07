import { api } from './api.js';
import { deptName, parseRoute, state, userScope } from './app.js';
import { RATING, RATING_COLOR, RATING_ORDER, STATUS, TRANSITIONS, VERDICT, VERDICT_COLOR } from './labels.js';
import { date, dateTime, h, hasRole, mount, num, promptText, toast } from './ui.js';

const EDITORS = ['dept_coordinator', 'faculty'];
const REVIEWERS = ['quality_auditor', 'external_reviewer'];
const ACTIVE_CYCLE = ['open', 'external_review'];

const FILTERS = [
  ['all', 'الكل'],
  ['mine', 'بانتظار إجرائي'],
  ['unrated', 'غير مقدّر'],
  ['noev', 'بلا شاهد'],
  ['returned', 'معاد للتعديل'],
];

const effRating = a => a.eff_rating;
const myTransitions = a => TRANSITIONS.filter(t => t.from.includes(a.status)
  && hasRole(state.me, t.roles, a.department_id, a.cycle_id));
const missingEvidence = a => a.evidence_required && a.evidence_count === 0 && a.self_rating !== 'na';

const MATCH = {
  all: () => true,
  mine: a => myTransitions(a).some(t => t.label !== 'إعادة فتح')
    || (['draft', 'returned'].includes(a.status) && hasRole(state.me, EDITORS, a.department_id, a.cycle_id)),
  unrated: a => !a.self_rating,
  noev: missingEvidence,
  returned: a => a.status === 'returned',
};

function setParams(params) {
  const qs = new URLSearchParams(Object.entries(params).filter(([, v]) => v != null && v !== '')).toString();
  history.replaceState(null, '', `#/workspace${qs ? `?${qs}` : ''}`);
}

export function scaleControl({ options, labels, value, disabled, onChange, colors }) {
  const wrap = h('div', { class: `scale${options.length === 3 ? ' three' : ''}`, role: 'group' });
  const buttons = options.map(opt => h('button', {
    type: 'button', disabled, 'aria-pressed': String(value === opt),
    style: colors ? { '--sel': colors[opt] } : null,
    onclick: () => {
      value = opt;
      buttons.forEach((b, i) => b.setAttribute('aria-pressed', String(options[i] === opt)));
      onChange(opt);
    },
  }, colors && h('span', { class: 'dot', style: { '--c': colors[opt] }, 'aria-hidden': 'true' }), labels[opt]));
  wrap.append(...buttons);
  return wrap;
}

export async function renderWorkspace() {
  const cycle = state.cycle;
  const { params } = parseRoute();
  const sc = userScope();
  const deptOptions = sc.all ? [...state.departments.map(d => d.id), null] : sc.depts;
  if (!deptOptions.length) return h('div', { class: 'empty' }, 'لا يوجد قسم مسند إليك في هذه الدورة.');

  let dept = params.dept === 'inst' ? null : params.dept ? Number(params.dept) : deptOptions[0];
  if (!deptOptions.includes(dept)) dept = deptOptions[0];
  let filter = FILTERS.some(([k]) => k === params.filter) ? params.filter : 'all';
  let selected = params.a ? Number(params.a) : null;
  let assessments = [];
  const bankCache = new Map();
  let minutesTpl = null;

  const cycleActive = ACTIVE_CYCLE.includes(cycle.status);
  const head = h('div', { class: 'ws-head' });
  const filtersEl = h('div', { class: 'filters', role: 'toolbar', 'aria-label': 'تصفية المتطلبات' });
  const listEl = h('nav', { class: 'req-list', 'aria-label': 'قائمة المتطلبات' });
  const detailEl = h('div', { class: 'detail' });
  const view = h('div', null, head, filtersEl, h('div', { class: 'ws' }, listEl, detailEl));

  const urlParams = () => ({ dept: dept === null ? 'inst' : dept, filter: filter === 'all' ? null : filter, a: selected });

  async function load() {
    const all = await api(`/cycles/${cycle.id}/assessments`);
    assessments = all.filter(a => a.department_id === dept);
  }

  function renderHead() {
    const total = assessments.length;
    const rated = assessments.filter(a => a.self_rating).length;
    const withEv = assessments.filter(a => a.evidence_count > 0).length;
    const moved = assessments.filter(a => !['draft', 'returned'].includes(a.status)).length;
    const deptPicker = deptOptions.length > 1 && h('select', {
      class: 'input', 'aria-label': 'القسم', style: { width: 'auto' },
      onchange: async e => {
        dept = e.target.value === 'inst' ? null : Number(e.target.value);
        selected = null;
        setParams(urlParams());
        await refresh();
      },
    }, deptOptions.map(d => h('option', { value: d === null ? 'inst' : String(d) }, deptName(d))));
    if (deptPicker) deptPicker.value = dept === null ? 'inst' : String(dept);

    mount(head,
      h('div', { class: 'title' },
        h('h1', null, deptName(dept)),
        h('div', { class: 'progress-line' },
          h('span', null, h('b', null, `${num(rated)}/${num(total)}`), ' مقدّر ذاتياً'),
          h('span', null, h('b', null, num(withEv)), ' بشواهد'),
          h('span', null, h('b', null, num(moved)), ' تجاوز مرحلة القسم'))),
      deptPicker,
      !cycleActive && h('p', { class: 'notice' }, `الدورة ${cycle.status === 'planning' ? 'لم تُفتح بعد' : 'مغلقة'}؛ العرض للاطلاع فقط.`));

    mount(filtersEl, FILTERS.map(([key, label]) => {
      const count = assessments.filter(MATCH[key]).length;
      return h('button', { type: 'button', 'aria-pressed': String(filter === key), onclick: () => {
        filter = key; setParams(urlParams()); renderHead(); renderList();
      } }, `${label} (${num(count)})`);
    }));
  }

  function renderList() {
    const top = listEl.scrollTop;
    const items = assessments.filter(MATCH[filter]);
    if (!items.length) {
      mount(listEl, h('p', { class: 'empty' }, filter === 'all' ? 'لا توجد متطلبات لهذا القسم في الدورة.' : 'لا توجد متطلبات تطابق هذا التصنيف.'));
      return;
    }
    const nodes = [];
    let group = null;
    for (const a of items) {
      const g = `${a.sub_standard_code} ${a.sub_standard_title ?? ''}`.trim();
      if (g !== group) { group = g; nodes.push(h('div', { class: 'req-group' }, g)); }
      const r = effRating(a);
      nodes.push(h('button', {
        type: 'button', class: 'req-item', 'aria-current': String(a.id === selected),
        onclick: () => select(a.id),
      },
        h('span', { class: `dot r-${r ?? 'none'}`, title: r ? RATING[r] : 'غير مقدّر' }),
        h('span', { class: 'code' }, a.requirement_code),
        h('span', { class: 'meta' },
          missingEvidence(a) && h('span', { class: 'faint', title: 'يستلزم شاهداً' }, 'بلا شاهد'),
          h('span', { class: `status s-${a.status}` }, STATUS[a.status])),
        h('span', { class: 'text' }, a.requirement_text)));
    }
    mount(listEl, nodes);
    listEl.scrollTop = top;
  }

  async function select(id) {
    selected = id;
    setParams(urlParams());
    renderList();
    await renderDetail();
    if (window.matchMedia('(max-width: 900px)').matches) detailEl.scrollIntoView({ block: 'start' });
  }

  async function refresh() {
    await load();
    if (selected && !assessments.some(a => a.id === selected)) selected = null;
    renderHead();
    renderList();
    await renderDetail();
  }

  async function act(fn, okMessage) {
    try {
      await fn();
      if (okMessage) toast(okMessage);
      await refresh();
    } catch (ex) {
      toast(ex.message, 'error');
    }
  }

  async function renderDetail() {
    if (!selected) {
      mount(detailEl, h('div', { class: 'empty' }, h('h2', null, 'اختر متطلباً من القائمة'),
        h('p', null, 'ستظهر هنا تفاصيله، والتقييم الذاتي، والشواهد المرتبطة به، ومسار اعتماده.')));
      return;
    }
    mount(detailEl, h('p', { class: 'skeleton', style: { padding: '1.5rem' } }, 'جارٍ تحميل المتطلب…'));
    const d = await api(`/assessments/${selected}`);
    const req = d.requirement;
    const canSelf = cycleActive && ['draft', 'returned'].includes(d.status) && hasRole(state.me, EDITORS, d.department_id, d.cycle_id);
    const canExt = cycleActive && d.status === 'under_audit' && hasRole(state.me, REVIEWERS, d.department_id, d.cycle_id);
    const lastReturn = [...d.history].reverse().find(t => t.to_status === 'returned');

    // 1) رأس المتطلب
    const header = h('section', null,
      h('div', { class: 'crumbs' }, `${req.standard_code} ${req.standard_title} ‹ ${req.sub_standard_code} ${req.sub_standard_title}`),
      h('div', { class: 'row' }, h('strong', null, req.code), h('span', { class: `status s-${d.status}` }, STATUS[d.status]),
        d.due_date && h('span', { class: 'faint' }, `الموعد: ${date(d.due_date)}`)),
      h('p', { class: 'req-text' }, req.text_ar),
      req.guidance_ar && h('p', { class: 'muted' }, req.guidance_ar),
      req.expected_evidence_ar && h('p', { class: 'faint' }, `الشواهد المتوقعة: ${req.expected_evidence_ar}`),
      d.status === 'returned' && lastReturn && h('div', { class: 'notice' },
        h('strong', null, `أعاده ${lastReturn.actor}: `), lastReturn.comment));

    // 2) التقييم الذاتي
    const draft = { self_rating: d.self_rating, self_notes: d.self_notes ?? '' };
    const notes = h('textarea', { id: 'self-notes', disabled: !canSelf, oninput: e => { draft.self_notes = e.target.value; } });
    notes.value = draft.self_notes;
    const selfSection = h('section', null,
      h('h2', null, 'التقييم الذاتي'),
      h('div', { class: 'field' }, h('label', null, 'مستوى التحقق'),
        scaleControl({ options: req.na_ok || draft.self_rating === 'na' ? RATING_ORDER : RATING_ORDER.filter(r => r !== 'na'),
                       labels: RATING, colors: RATING_COLOR, value: draft.self_rating,
                       disabled: !canSelf, onChange: v => { draft.self_rating = v; } }),
        !req.na_ok && h('p', { class: 'faint' }, '«لا ينطبق» غير متاح لهذا المتطلب في هذا القسم وفق شرط النجمة في النموذج.'),
        req.na_ok === false && draft.self_rating === 'na' && h('p', { class: 'notice' },
          'تقدير «لا ينطبق» هنا غير مقبول وفق النموذج ويُحسب «غير متحقق»؛ اختر مستوى التحقق الفعلي.')),
      h('div', { class: 'field' }, h('label', { for: 'self-notes' }, 'ملاحظات القسم'), notes),
      canSelf && h('div', { class: 'row end' }, h('button', { class: 'btn', onclick: () => act(
        () => api(`/assessments/${d.id}/self`, { method: 'PATCH', body: draft }), 'حُفظ التقييم الذاتي') }, 'حفظ التقييم')),
      d.self_at && h('p', { class: 'faint' }, `آخر تحديث ${dateTime(d.self_at)}`));

    // محاضر هذا المتطلب (إن كان من نوع «محضر»)
    if (minutesTpl === null) minutesTpl = await api(`/cycles/${cycle.id}/minutes/templates`).catch(() => []);
    const tpl = minutesTpl.find(t => t.requirement_code === req.code);
    let minutesSection = null;
    if (tpl && d.department_id != null) {
      const mins = await api(`/cycles/${cycle.id}/minutes?department_id=${d.department_id}&template_id=${tpl.id}`).catch(() => []);
      const ok = mins.filter(x => x.status === 'approved').length;
      minutesSection = h('section', null, h('h2', null, 'محاضر هذا المتطلب'),
        h('p', { class: 'muted' }, mins.length
          ? `${num(mins.length)} محضر، منها ${num(ok)} معتمد. المحضر المعتمد يُؤرشف PDF ويُربط هنا شاهداً تلقائياً.`
          : 'هذا المتطلب محضر اجتماع. أنشئه من النموذج الموحّد ليُؤرشف ويُربط هنا شاهداً عند اعتماده.'),
        h('div', { class: 'row' }, h('a', { class: 'btn', href: `#/minutes?dept=${d.department_id}&tpl=${tpl.id}` },
          mins.length ? 'فتح المحاضر' : 'إنشاء محضر من النموذج')));
    }

    // 3) الشواهد
    const evSection = h('section', null, h('h2', null, 'الشواهد'));
    evSection.append(d.evidence.length
      ? h('ul', { class: 'ev-list' }, d.evidence.map(e => h('li', null,
          h('div', { class: 'grow' }, h('div', null, e.title_ar),
            h('div', { class: 'faint' }, e.kind === 'link' ? 'رابط' : `النسخة ${e.pinned_version_no ?? e.current_version_no ?? '—'}`)),
          h('button', { class: 'btn small', onclick: async () => {
            try { const r = await api(`/evidence/${e.id}/download`); window.open(r.url, '_blank', 'noopener'); }
            catch (ex) { toast(ex.message, 'error'); }
          } }, 'فتح'),
          canSelf && h('button', { class: 'btn small danger', onclick: () => act(
            () => api(`/assessments/${d.id}/evidence/${e.id}`, { method: 'DELETE' }), 'أُزيل الشاهد من المتطلب') }, 'إزالة'))))
      : h('p', { class: 'muted' }, req.evidence_required ? 'لم يُربط أي شاهد بعد. هذا المتطلب يستلزم شاهداً واحداً على الأقل قبل الرفع.' : 'لا توجد شواهد مرتبطة.'));
    if (canSelf) evSection.append(await evidenceAdder(d));

    // 4) التقييم الخارجي
    const extSection = (d.ext_verdict || canExt || d.ext_recommendation) ? (() => {
      const ext = { ext_verdict: d.ext_verdict, ext_recommendation: d.ext_recommendation ?? '' };
      const rec = h('textarea', { id: 'ext-rec', disabled: !canExt, oninput: e => { ext.ext_recommendation = e.target.value; } });
      rec.value = ext.ext_recommendation;
      return h('section', null,
        h('h2', null, 'التقييم الخارجي'),
        h('div', { class: 'field' }, h('label', null, 'حكم المقيّم على التقييم الذاتي'),
          scaleControl({ options: Object.keys(VERDICT), labels: VERDICT, colors: VERDICT_COLOR, value: ext.ext_verdict,
                         disabled: !canExt, onChange: v => { ext.ext_verdict = v; } })),
        h('div', { class: 'field' }, h('label', { for: 'ext-rec' }, 'توصيات المقيّم الخارجي'), rec),
        d.eff_rating && h('p', { class: 'readonly-val' }, h('span', { class: `dot r-${d.eff_rating}` }),
          `التقدير المعتمد في الحساب: ${RATING[d.eff_rating]}`),
        canExt && h('div', { class: 'row end' }, h('button', { class: 'btn', onclick: () => act(
          () => api(`/assessments/${d.id}/external`, { method: 'PATCH', body: ext }), 'حُفظ التقييم الخارجي') }, 'حفظ التقييم الخارجي')));
    })() : null;

    // 5) مسار الاعتماد
    const transitions = cycleActive ? myTransitions(d) : [];
    const flowSection = h('section', null,
      h('h2', null, 'مسار الاعتماد'),
      transitions.length > 0 && h('div', { class: 'row' }, transitions.map(t => h('button', {
        class: `btn${t.primary ? ' primary' : ''}`,
        onclick: async () => {
          let comment = null;
          if (t.comment) {
            comment = await promptText({ title: t.label, label: 'سبب الإجراء (يظهر للقسم)', confirm: t.label });
            if (comment === null) return;
          }
          await act(() => api(`/assessments/${d.id}/transition`, { method: 'POST', body: { to_status: t.to, comment } }),
                    `تم: ${t.label}`);
        },
      }, t.label))),
      d.history.length
        ? h('ol', { class: 'timeline' }, d.history.map(t => h('li', null,
            h('span', null, dateTime(t.at)), h('strong', null, STATUS[t.to_status]), h('span', null, `— ${t.actor}`),
            t.comment && h('q', null, t.comment))))
        : h('p', { class: 'faint' }, 'لم يُرفع المتطلب بعد.'));

    mount(detailEl, header, selfSection, minutesSection, evSection, extSection, flowSection);
  }

  async function evidenceAdder(d) {
    const key = d.department_id ?? 'inst';
    if (!bankCache.has(key)) {
      const q = d.department_id == null ? '' : `?department_id=${d.department_id}`;
      bankCache.set(key, await api(`/evidence${q}`));
    }
    const linked = new Set(d.evidence.map(e => e.id));
    const bank = bankCache.get(key).filter(e => !linked.has(e.id));

    const pick = h('select', { class: 'input', 'aria-label': 'شاهد من بنك الشواهد' },
      h('option', { value: '' }, bank.length ? 'اختر شاهداً موجوداً…' : 'لا توجد شواهد أخرى في بنك القسم'),
      bank.map(e => h('option', { value: String(e.id) }, `${e.title_ar}${e.usage_count ? ` (مستخدم في ${e.usage_count})` : ''}`)));
    const title = h('input', { type: 'text', placeholder: 'عنوان الشاهد الجديد', 'aria-label': 'عنوان الشاهد الجديد' });
    const file = h('input', { type: 'file', 'aria-label': 'ملف الشاهد' });
    const url = h('input', { type: 'text', dir: 'ltr', placeholder: 'أو رابط https://…', 'aria-label': 'رابط الشاهد' });

    const linkExisting = () => act(async () => {
      if (!pick.value) throw new Error('اختر شاهداً من القائمة أولاً');
      await api(`/assessments/${d.id}/evidence`, { method: 'POST', body: { evidence_id: Number(pick.value) } });
    }, 'رُبط الشاهد بالمتطلب');

    const createNew = () => act(async () => {
      const t = title.value.trim();
      const f = file.files[0];
      const u = url.value.trim();
      if (t.length < 3) throw new Error('اكتب عنواناً واضحاً للشاهد (3 أحرف على الأقل)');
      if (!f && !u) throw new Error('أرفق ملفاً أو أدخل رابطاً');
      const ev = await api('/evidence', { method: 'POST', body: {
        title_ar: t, kind: f ? (f.type.startsWith('image/') ? 'image' : 'file') : 'link',
        url: f ? null : u, department_id: d.department_id } });
      if (f) {
        const form = new FormData();
        form.append('file', f);
        await api(`/evidence/${ev.id}/versions`, { method: 'POST', form });
      }
      await api(`/assessments/${d.id}/evidence`, { method: 'POST', body: { evidence_id: ev.id } });
      bankCache.delete(key);
    }, 'رُفع الشاهد ورُبط بالمتطلب');

    return h('div', { class: 'ev-add' },
      pick, h('button', { class: 'btn', onclick: linkExisting, disabled: !bank.length }, 'ربط'),
      h('div', { class: 'field' }, title, h('div', { class: 'row' }, file), url),
      h('button', { class: 'btn primary', style: { alignSelf: 'end' }, onclick: createNew }, 'رفع وربط'));
  }

  await load();
  renderHead();
  renderList();
  await renderDetail();
  return view;
}
