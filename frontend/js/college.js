// تقارير الكلية: تُجمع تلقائياً من نماذج الأقسام بأعمدة ملفات الإدارة، ويصدّرها وكيل الجودة Excel
import { api, apiDownload } from './api.js';
import { go, parseRoute, state } from './app.js';
import { h, mount, num, toast } from './ui.js';

const FORM_ST = { draft: 'مسودة', submitted: 'مرفوع', returned: 'مُعاد', approved: 'معتمد' };
const cell = (v, type) => {
  if (v == null || v === '') return '—';
  if (type === 'pct') return `${num(Math.round(Number(v) * 1000) / 10)}%`;
  if (type === 'num') return num(Number(v));
  if (typeof v === 'string' && /^https?:\/\//.test(v)) return h('a', { href: v, target: '_blank', rel: 'noopener' }, 'رابط ↗');
  return String(v);
};

export async function renderCollege() {
  const cycle = state.cycle;
  const { params } = parseRoute();
  const list = await api(`/cycles/${cycle.id}/college-reports`);
  const key = list.some(r => r.key === params.r) ? params.r : list[0].key;
  const q = params.f ? `?f=${encodeURIComponent(params.f)}` : '';
  const data = await api(`/cycles/${cycle.id}/college-reports/${key}${q}`);

  const groups = new Map();
  for (const r of list) { if (!groups.has(r.group)) groups.set(r.group, []); groups.get(r.group).push(r); }
  const side = h('aside', { class: 'card cr-side' }, [...groups].map(([g, xs]) => h('div', null, h('h4', null, g),
    xs.map(r => h('a', { class: r.key === key ? 'on' : '', href: `#/college?r=${r.key}` }, r.title)))));

  const rep = list.find(r => r.key === key);
  const filled = data.departments.filter(d => d.rows).length;
  const head = h('div', { class: 'cr-head' },
    h('div', null, h('h2', null, data.title),
      h('p', { class: 'muted' }, 'يُجمع تلقائياً من نموذج الأقسام: ', h('b', null, data.source_title),
        ` · ${num(filled)} من ${num(data.departments.length)} قسم أدخل بياناته`)),
    h('div', { class: 'row' },
      rep.filter && h('label', null, `${rep.filter.label} `, h('select', { onchange: e => go('college', { r: key, f: e.target.value }) },
        rep.filter.options.map(o => h('option', { value: o, selected: o === data.filter }, o)))),
      h('button', { class: 'btn primary', onclick: () => apiDownload(`/cycles/${cycle.id}/college-reports/${key}/xlsx${data.filter ? `?f=${encodeURIComponent(data.filter)}` : ''}`,
        `${data.title}.xlsx`).catch(ex => toast(ex.message, 'error')) }, 'تصدير Excel')));

  const depts = h('div', { class: 'cr-depts' }, data.departments.map(d => h('span', { class: `cr-dept ${d.rows ? 'ok' : 'no'}` },
    d.name, ' · ', d.rows ? `${num(d.rows)} صف` : d.form_id ? `النموذج ${FORM_ST[d.status] ?? ''} بلا بيانات لهذا الاختيار` : 'لم يُنشئ النموذج')));

  const visitForm = data.editable && (() => {
    const f = { date: h('input', { class: 'input', type: 'date', required: true }),
      program: h('select', { class: 'input' }, ['بكالوريوس', 'دبلوم', 'بكالوريوس ودبلوم'].map(o => h('option', null, o))),
      sname: h('input', { class: 'input', placeholder: 'مشرف الجودة المكلف' }), sphone: h('input', { class: 'input', placeholder: 'جواله', dir: 'ltr' }),
      cname: h('input', { class: 'input', placeholder: 'وكيل الجودة بالكلية' }), cphone: h('input', { class: 'input', placeholder: 'جواله', dir: 'ltr' }),
      done: h('select', { class: 'input' }, h('option', { value: '' }, 'تنفيذ الزيارة'), h('option', { value: 'true' }, 'نعم'), h('option', { value: 'false' }, 'لا')) };
    return h('form', { class: 'cr-visit', onsubmit: async e => {
      e.preventDefault();
      try {
        await api(`/cycles/${cycle.id}/external-visits`, { method: 'POST', body: { visit_date: f.date.value, program: f.program.value,
          supervisor_name: f.sname.value || null, supervisor_phone: f.sphone.value || null, college_name: f.cname.value || null,
          college_phone: f.cphone.value || null, executed: f.done.value === '' ? null : f.done.value === 'true' } });
        toast('أُضيفت الزيارة'); go('college', { r: key, t: Date.now() });
      } catch (ex) { toast(ex.message, 'error'); }
    } }, Object.values(f), h('button', { class: 'btn primary' }, '+ إضافة زيارة'));
  })();
  const patternsOff = rep.needs_patterns && !data.rows.length;
  const table = patternsOff ? h('div', { class: 'empty' }, h('h3', null, 'أنماط التدريب غير مفعّلة'),
      h('p', null, 'يظهر هذا التقرير بعد تسجيل قرار اعتماد نمط التدريب من صفحة «أعمال الجودة»، وتقدير متطلبات دورة منهجية الأنماط.'))
    : data.rows.length ? h('div', { class: 'matrix-wrap' }, h('table', { class: 'data cr-table' },
    h('thead', null, h('tr', null, h('th', null, '#'), data.columns.map(c => h('th', null, c.label)))),
    h('tbody', null, data.rows.map((r, i) => h('tr', null, h('td', null, num(i + 1)), data.columns.map(c => h('td', null, cell(r[c.key], c.type))),
      data.editable && h('td', null, h('button', { class: 'btn small', onclick: async () => {
        try { await api(`/external-visits/${r.id}`, { method: 'DELETE' }); go('college', { r: key, t: Date.now() }); } catch (ex) { toast(ex.message, 'error'); }
      } }, 'حذف')))),
      data.total && h('tr', { class: 'cr-total' }, h('td', null, ''), data.columns.map(c => h('td', null, c.key === 'dept' ? data.total.dept : cell(data.total[c.key], c.type)))))))
    : h('div', { class: 'empty' }, h('h3', null, 'لا توجد بيانات بعد'), h('p', null, 'يظهر التقرير عندما تعبّئ الأقسام النموذج المرتبط به في «الخطط والتقارير».'));

  const root = h('div', { class: 'cal-page' },
    h('header', { class: 'scope-hero' }, h('div', null, h('h1', null, 'تقارير الكلية'),
      h('p', null, 'تقارير الإدارة التي يرفعها وكيل الجودة على مستوى الكلية، تُجمع تلقائياً من نماذج الأقسام دون إعادة إدخال، '
        + 'وتُصدَّر Excel بنفس أعمدة ملفات الإدارة.'))),
    h('div', { class: 'cr-layout' }, side, h('section', { class: 'card' }, head, data.departments.length ? depts : null, visitForm, table)));
  return root;
}
