// نطاق المتطلبات: ما ينطبق على كل قسم وما هو خارج اختصاصه (بقرار وكالة الجودة)
import { api, ApiError } from './api.js';
import { deptName, go, parseRoute, state, userScope } from './app.js';
import { date, h, mount, num, promptText, toast } from './ui.js';

export async function renderScope() {
  const { params } = parseRoute();
  const sc = userScope();
  const depts = state.departments.map(d => d.id).filter(d => sc.all || sc.depts.includes(d));
  let dept = depts.includes(Number(params.dept)) ? Number(params.dept) : depts[0];
  const root = h('div', { class: 'scope-page' });
  const selected = new Set();

  async function draw() {
    const data = await api(`/departments/${dept}/applicability`);
    const edit = data.can_edit;
    selected.clear();
    const bar = h('div', { class: 'scope-bar' });
    const updateBar = () => mount(bar, edit && selected.size > 0 && [
      h('span', null, `محدد ${num(selected.size)} متطلب`),
      h('button', { class: 'btn primary', onclick: excludeSelected }, 'استبعاد من نطاق القسم'),
      h('button', { class: 'btn', onclick: () => { selected.clear(); draw(); } }, 'إلغاء التحديد')]);

    async function excludeSelected() {
      const ids = [...selected];
      const reqs = data.requirements.filter(r => ids.includes(r.requirement_id));
      const outside = reqs.filter(r => !r.model_allows);
      const reason = await promptText({ title: 'استبعاد متطلبات من نطاق القسم',
        label: `مسوّغ الاستبعاد لـ ${num(ids.length)} متطلب (يظهر للمقيّم الخارجي ويُحفظ في سجل التدقيق)`, confirm: 'استبعاد' });
      if (!reason) return;
      let force = false;
      if (outside.length) {
        const ok = await promptText({ title: 'تنبيه: خارج شرط النجمة في النموذج الرسمي',
          label: `النموذج الرسمي لا يقبل «لا ينطبق» لهذه المتطلبات في هذا القسم: ${outside.map(r => r.requirement_code).join('، ')}. `
            + 'قد يرفض المقيّم الخارجي هذا الاستبعاد. اكتب «أؤكد» للمتابعة.', confirm: 'متابعة' });
        if (ok !== 'أؤكد') { if (ok !== null) toast('لم يُستبعد: عبارة التأكيد غير مطابقة', 'error'); return; }
        force = true;
      }
      try {
        const r = await api(`/departments/${dept}/applicability/exclusions`, { method: 'POST',
          body: { requirement_ids: ids, reason_ar: reason, outside_model_rule: force } });
        toast(`استُبعد ${num(r.excluded)} متطلب من نطاق ${deptName(dept)}`);
        await draw();
      } catch (ex) { if (!(ex instanceof ApiError && ex.status === 401)) toast(ex.message, 'error'); }
    }

    async function restore(r) {
      try {
        await api(`/departments/${dept}/applicability/exclusions/${r.requirement_id}`, { method: 'DELETE' });
        toast(`أُعيد المتطلب ${r.requirement_code} إلى نطاق القسم`);
        await draw();
      } catch (ex) { toast(ex.message, 'error'); }
    }

    // تجميع: معيار ← معيار فرعي ← متطلبات
    const tree = new Map();
    for (const r of data.requirements) {
      if (!tree.has(r.standard_code)) tree.set(r.standard_code, { title: r.standard_title, subs: new Map() });
      const st = tree.get(r.standard_code);
      if (!st.subs.has(r.sub_standard_code)) st.subs.set(r.sub_standard_code, { title: r.sub_standard_title, reqs: [] });
      st.subs.get(r.sub_standard_code).reqs.push(r);
    }

    const reqRow = r => {
      const ex = !!r.exclusion_id;
      const box = edit && !ex && h('input', { type: 'checkbox', 'aria-label': `تحديد ${r.requirement_code}`,
        onchange: e => { e.target.checked ? selected.add(r.requirement_id) : selected.delete(r.requirement_id); updateBar(); } });
      return h('li', { class: `sreq${ex ? ' is-ex' : ''}` },
        box || h('span', { class: 'sreq-dot' }),
        h('div', { class: 'sreq-body' },
          h('div', { class: 'sreq-top' }, h('b', null, r.requirement_code),
            r.model_allows ? h('span', { class: 'chip c-good' }, '★ النموذج يقبل «لا ينطبق»') : null,
            ex && !r.within_model_rule && h('span', { class: 'chip c-bad' }, 'خارج شرط النجمة'),
            ex && h('span', { class: 'chip c-mid' }, 'خارج نطاق القسم')),
          h('p', null, r.text_ar),
          ex && h('p', { class: 'sreq-why' }, `المسوّغ: ${r.reason_ar} — ${r.decided_by_name ?? ''} · ${date(r.decided_at)}`)),
        ex && edit && h('button', { class: 'btn small', onclick: () => restore(r) }, 'إعادة للنطاق'));
    };

    const subBlock = (code, sub) => {
      const exN = sub.reqs.filter(r => r.exclusion_id).length;
      const all = exN === sub.reqs.length;
      const pickAll = edit && !all && h('button', { class: 'btn small', onclick: e => {
        e.preventDefault();
        sub.reqs.filter(r => !r.exclusion_id).forEach(r => selected.add(r.requirement_id));
        details.querySelectorAll('input[type=checkbox]').forEach(c => { c.checked = true; });
        details.open = true; updateBar();
      } }, 'تحديد المعيار الفرعي كاملاً');
      const details = h('details', { class: `ssub${all ? ' all-ex' : ''}`, open: exN > 0 && !all },
        h('summary', null, h('bdi', { class: 'ssub-code' }, code), h('span', { class: 'ssub-title' }, sub.title),
          h('span', { class: 'ssub-count' }, all ? 'خارج نطاق القسم' : exN ? `${num(exN)} من ${num(sub.reqs.length)} مستبعد` : `${num(sub.reqs.length)} متطلب`),
          pickAll),
        h('ul', null, sub.reqs.map(reqRow)));
      return details;
    };

    mount(root,
      h('header', { class: 'scope-hero' },
        h('div', null, h('h1', null, 'نطاق المتطلبات'),
          h('p', null, 'المتطلبات التي ليست من اختصاص القسم تُستبعد من تقديراته ومؤشراته ونماذجه وخطط تحسينه، '
            + 'ويظهر للقسم ما يخصه فقط. القرار من صلاحية وكالة الجودة بمسوّغ موثّق.')),
        h('div', { class: 'scope-pick' },
          h('label', null, 'القسم ', h('select', { onchange: e => go('scope', { dept: e.target.value }) },
            depts.map(d => h('option', { value: String(d), selected: d === dept }, deptName(d))))),
          h('div', { class: 'scope-stats' },
            h('span', null, h('b', null, num(data.requirements.length - data.excluded_count)), ' متطلب ضمن النطاق'),
            h('span', null, h('b', null, num(data.excluded_count)), ' خارج النطاق')))),
      !edit && h('p', { class: 'notice' }, 'للاطلاع فقط: طلب تعديل نطاق القسم يُرفع لوكالة الجودة.'),
      [...tree].map(([code, st]) => h('section', { class: 'card sstd' },
        h('h2', null, h('bdi', { class: 'ssub-code' }, code), ' ', st.title),
        [...st.subs].map(([c, sub]) => subBlock(c, sub)))),
      bar);
    updateBar();
  }

  if (!dept) return h('div', { class: 'empty' }, 'لا توجد أقسام');
  await draw();
  return root;
}
