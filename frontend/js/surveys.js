// الاستبيانات: استبيان المتدرب، واستبيان المدرب، واستبيان الخدمات للجميع. التعبئة في Microsoft Forms المقيّد بحساب المؤسسة،
// ويرفع وكيل الجودة ملف الردود المصدَّر من Forms فتظهر الإحصاءات هنا (البريد والاسم لا يُحفظان).
import { api } from './api.js';
import { go, parseRoute, state } from './app.js';
import { date, dateTime, h, mount, num, pct, toast } from './ui.js';

const STATE = { open: ['مفتوح للتعبئة', 'c-good'], scheduled: ['لم يبدأ بعد', 'c-mid'], closed: ['مغلق', 'c-bad'], draft: ['لم يُضف الرابط', ''] };
const KIND_ICON = { trainee: '🎓', trainer: '👨‍🏫', services: '🏛️' };
const TYPE = { scale: 'مقياس رضا', rating: 'تقييم رقمي', choice: 'اختيار', multi: 'اختيار متعدد', text: 'إجابة مفتوحة', empty: 'بلا إجابات' };
const levelCls = p => (p == null ? '' : p >= 80 ? 't-good' : p >= 60 ? 't-mid' : 't-bad');
const field = (label, input, hint) => h('div', { class: 'field' }, h('label', null, label), input, hint && h('small', { class: 'faint' }, hint));

function openDialog(title, body, onSubmit, submitLabel = 'حفظ') {
  const dlg = document.getElementById('dialog');
  const err = h('p', { class: 'faint', style: { color: 'var(--not-met)' } });
  const form = h('form', { method: 'dialog', class: 'cal-form qw-form', onsubmit: async e => {
    e.preventDefault();
    try { await onSubmit(); dlg.close(); } catch (ex) { err.textContent = ex.message; }
  } }, h('h2', null, title), body, err,
  h('div', { class: 'row end' }, h('button', { type: 'button', class: 'btn', onclick: () => dlg.close() }, 'إلغاء'),
    h('button', { class: 'btn primary' }, submitLabel)));
  mount(dlg, form);
  dlg.showModal();
}

function settingsDialog(cycle, s, reload) {
  const title = h('input', { class: 'input', value: s.title_ar, required: true, minlength: 3 });
  const url = h('input', { class: 'input', type: 'url', dir: 'ltr', placeholder: 'https://forms.office.com/r/...', value: s.form_url ?? '' });
  const res = h('input', { class: 'input', type: 'url', dir: 'ltr', placeholder: 'https://forms.office.com/... أو رابط ملف الردود على SharePoint', value: s.results_url ?? '' });
  const opens = h('input', { class: 'input', type: 'date', value: s.opens_on ?? '' });
  const closes = h('input', { class: 'input', type: 'date', value: s.closes_on ?? '' });
  openDialog(`إعداد ${s.title_ar}`, [
    h('p', { class: 'muted' }, `الفئة المستهدفة: ${s.audience_ar}`),
    field('عنوان الاستبيان', title),
    field('رابط مشاركة النموذج في Microsoft Forms', url, 'من Forms: «جمع الردود» ← انسخ الرابط. اجعل الإعداد «يمكن فقط للأشخاص في مؤسستي الرد».'),
    field('رابط الردود (اختياري)', res, 'رابط صفحة الردود في Forms أو ملف Excel المرتبط بها، يظهر لوكالة الجودة فقط.'),
    h('div', { class: 'grid2' }, field('يُفتح في', opens), field('يُغلق في', closes)),
  ], async () => {
    await api(`/cycles/${cycle.id}/surveys/${s.kind}`, { method: 'PUT', body: {
      title_ar: title.value.trim(), form_url: url.value.trim() || null, results_url: res.value.trim() || null,
      opens_on: opens.value || null, closes_on: closes.value || null } });
    toast('حُفظ إعداد الاستبيان');
    reload();
  });
}

function uploadResponses(cycle, s, reload) {
  const input = h('input', { type: 'file', accept: '.xlsx,.csv', hidden: true, onchange: async () => {
    const file = input.files[0];
    input.remove();
    if (!file) return;
    const form = new FormData();
    form.append('file', file);
    toast('جارٍ قراءة ملف الردود…');
    try {
      const r = await api(`/cycles/${cycle.id}/surveys/${s.kind}/responses`, { method: 'POST', form });
      toast(`رُفع ${num(r.responses)} رداً على ${num(r.questions)} سؤالاً${r.overall ? ` — نسبة الرضا ${pct(r.overall.satisfied_pct)}` : ''}`);
      go('surveys', { k: s.kind });
      reload();
    } catch (ex) { toast(ex.message, 'error'); }
  } });
  document.body.append(input);
  input.click();
}

async function copyLink(url) {
  try { await navigator.clipboard.writeText(url); toast('نُسخ رابط الاستبيان — أرسله للفئة المستهدفة'); }
  catch { toast(url); }
}

function ring(p) {
  const v = p == null ? 0 : Math.max(0, Math.min(100, p));
  return h('div', { class: `sv-ring ${levelCls(p)}`, style: { '--v': String(v) } },
    h('b', null, p == null ? '—' : pct(p)), h('small', null, 'نسبة الرضا'));
}

function surveyCard(cycle, s, data, selected, reload) {
  const [stLabel, stCls] = STATE[s.state];
  const live = s.form_url && s.state === 'open';
  return h('section', { class: `card sv-card${selected ? ' on' : ''}` },
    h('header', { class: 'sv-card-head' },
      h('span', { class: 'sv-ico', 'aria-hidden': 'true' }, KIND_ICON[s.kind]),
      h('div', null, h('h2', null, s.title_ar), h('p', { class: 'faint' }, s.audience_ar)),
      h('span', { class: `chip ${stCls}` }, stLabel)),
    h('p', { class: 'muted sv-hint' }, s.hint_ar),
    (s.opens_on || s.closes_on) && h('p', { class: 'faint' }, s.opens_on && s.closes_on ? `الفترة: ${date(s.opens_on)} – ${date(s.closes_on)}`
      : s.opens_on ? `يُفتح في ${date(s.opens_on)}` : `يُغلق في ${date(s.closes_on)}`),
    data.can_view_stats && h('div', { class: 'sv-card-stats' }, ring(s.overall?.satisfied_pct ?? null),
      h('div', null, h('b', null, num(s.responses ?? 0)), h('span', null, ' رداً'),
        s.overall && h('div', { class: 'faint' }, `المتوسط ${num(s.overall.mean5)} من 5 · ${s.overall.level}`),
        s.uploaded_at && h('div', { class: 'faint' }, `آخر تحديث ${dateTime(s.uploaded_at)}`))),
    h('div', { class: 'sv-actions' },
      s.form_url
        ? h('a', { class: `btn ${live ? 'primary' : ''}`, href: s.form_url, target: '_blank', rel: 'noopener noreferrer' }, 'تعبئة الاستبيان ↗')
        : h('span', { class: 'faint' }, data.can_manage ? 'أضف رابط النموذج من «الإعداد»' : 'لم يُنشر الاستبيان بعد'),
      s.form_url && h('button', { type: 'button', class: 'btn small', onclick: () => copyLink(s.form_url) }, 'نسخ الرابط'),
      data.can_view_stats && h('button', { type: 'button', class: 'btn small', onclick: () => go('surveys', { k: s.kind }) }, 'الإحصاءات'),
      data.can_manage && h('button', { type: 'button', class: 'btn small', onclick: () => settingsDialog(cycle, s, reload) }, 'الإعداد'),
      data.can_manage && h('button', { type: 'button', class: 'btn small', onclick: () => uploadResponses(cycle, s, reload) }, 'رفع ملف الردود'),
      data.can_manage && s.results_url && h('a', { class: 'btn small', href: s.results_url, target: '_blank', rel: 'noopener noreferrer' }, 'الردود في Forms ↗')));
}

// ---------------------------------------------------------------- الإحصاءات
function bars(options, total, scored) {
  return h('ul', { class: 'sv-bars' }, options.map(o => h('li', null,
    h('span', { class: 'sv-bar-label' }, o.label),
    h('span', { class: 'sv-bar' }, h('i', { class: scored ? `s${o.score}` : '', style: { width: `${o.pct}%` } })),
    h('span', { class: 'sv-bar-val' }, `${num(o.count)} · ${pct(o.pct)}`))));
}

function stacked(q) {
  return h('div', { class: 'sv-stack', role: 'img', 'aria-label': q.options.map(o => `${o.label} ${pct(o.pct)}`).join('، ') },
    q.options.map(o => h('i', { class: `s${q.max === 5 ? o.score : Math.ceil(o.score / 2)}`, style: { width: `${o.pct}%` }, title: `${o.label}: ${num(o.count)} (${pct(o.pct)})` })));
}

function questionCard(q, n) {
  const head = h('header', { class: 'sv-q-head' },
    h('span', { class: 'sv-q-no' }, num(n)),
    h('h3', null, q.text),
    h('span', { class: 'chip' }, TYPE[q.type]));
  if (q.type === 'scale' || q.type === 'rating') {
    return h('article', { class: 'card sv-q' }, head,
      h('div', { class: 'sv-q-kpis' },
        h('span', { class: levelCls(q.satisfied_pct) }, h('b', null, pct(q.satisfied_pct)), ' راضون'),
        h('span', null, h('b', null, `${num(q.mean)} / ${num(q.max)}`), ' المتوسط'),
        h('span', { class: 't-bad' }, h('b', null, pct(q.dissatisfied_pct)), ' غير راضين'),
        h('span', null, h('b', null, num(q.answered)), ' أجابوا'),
        h('span', { class: `chip ${q.satisfied_pct >= 80 ? 'c-good' : q.satisfied_pct >= 60 ? 'c-mid' : 'c-bad'}` }, q.level)),
      stacked(q), bars(q.options, q.answered, true));
  }
  if (q.type === 'choice' || q.type === 'multi') {
    return h('article', { class: 'card sv-q' }, head,
      h('p', { class: 'faint' }, `${num(q.answered)} أجابوا${q.type === 'multi' ? ' · يمكن اختيار أكثر من إجابة' : ''}`),
      bars(q.options, q.answered, false));
  }
  if (q.type === 'text') {
    return h('article', { class: 'card sv-q' }, head,
      h('details', null, h('summary', null, `${num(q.answered)} إجابة مفتوحة — عرض أحدث ${num(q.samples.length)}`),
        h('ul', { class: 'sv-comments' }, q.samples.map(t => h('li', null, t)))));
  }
  return h('article', { class: 'card sv-q' }, head, h('p', { class: 'faint' }, 'لا توجد إجابات'));
}

function statsView(cycle, d, params) {
  if (!d.stats) {
    return h('section', { class: 'card empty' }, h('h2', null, `إحصاءات ${d.title_ar}`),
      h('p', null, 'لم تُرفع ردود بعد. من Microsoft Forms افتح «الردود» ← «فتح في Excel»، ثم ارفع الملف من زر «رفع ملف الردود».'));
  }
  const st = d.stats;
  const fq = params.q != null && params.q !== '' ? Number(params.q) : null;
  const fil = st.filters.find(f => f.index === fq);
  const qSel = h('select', { class: 'input', 'aria-label': 'تصفية حسب سؤال', onchange: e => go('surveys', { k: d.kind, q: e.target.value }) },
    h('option', { value: '' }, 'كل المستجيبين'), st.filters.map(f => h('option', { value: String(f.index), selected: f.index === fq }, f.text)));
  const vSel = fil && h('select', { class: 'input', 'aria-label': 'القيمة', onchange: e => go('surveys', { k: d.kind, q: fq, v: e.target.value }) },
    h('option', { value: '' }, 'اختر القيمة…'), fil.values.map(v => h('option', { value: v, selected: v === params.v }, v)));
  const o = st.overall;
  const list = (title, xs, cls) => xs.length > 0 && h('div', { class: `card sv-rank ${cls}` }, h('h3', null, title),
    h('ol', null, xs.map(x => h('li', null, h('span', null, x.text), h('b', null, pct(x.satisfied_pct))))));
  return h('div', { class: 'sv-stats', id: 'sv-stats' },
    h('header', { class: 'sv-stats-head' },
      h('div', null, h('h2', null, `إحصاءات ${d.title_ar}`),
        h('p', { class: 'faint' }, `${num(d.responses)} رداً${d.first_at ? ` من ${date(d.first_at)} إلى ${date(d.last_at)}` : ''}`
          + `${d.source_name ? ` · الملف: ${d.source_name}` : ''}`)),
      h('div', { class: 'sv-filter' }, qSel, vSel, h('button', { type: 'button', class: 'btn small', onclick: () => window.print() }, 'طباعة'))),
    d.filter && h('p', { class: 'notice' }, `تصفية: ${st.questions[d.filter.q]?.text} = ${d.filter.v} — ${num(st.responses)} رداً`),
    h('div', { class: 'sv-kpis' },
      h('div', { class: `sv-kpi ${levelCls(o?.satisfied_pct)}` }, h('b', null, o ? pct(o.satisfied_pct) : '—'), h('span', null, 'نسبة الرضا العامة')),
      h('div', { class: 'sv-kpi' }, h('b', null, o ? `${num(o.mean5)} / 5` : '—'), h('span', null, 'المتوسط العام')),
      h('div', { class: 'sv-kpi' }, h('b', null, o?.level ?? '—'), h('span', null, 'مستوى الرضا')),
      h('div', { class: 'sv-kpi' }, h('b', null, num(st.responses)), h('span', null, 'عدد الردود')),
      h('div', { class: 'sv-kpi' }, h('b', null, num(st.questions.length)), h('span', null, 'عدد الأسئلة'))),
    (st.strongest.length > 0) && h('div', { class: 'grid2 sv-ranks' },
      list('أعلى البنود رضاً (نقاط القوة)', st.strongest, 'good'), list('أدنى البنود رضاً (فرص التحسين)', st.weakest, 'bad')),
    st.questions.map((q, i) => questionCard(q, i + 1)),
    h('p', { class: 'faint' }, 'نسبة الرضا = نسبة الإجابات في أعلى درجتين من المقياس (موافق بشدة/موافق، ممتاز/جيد جداً، 4–5 من 5). '
      + 'الردود مجهولة الهوية: لا تحفظ المنصة البريد ولا الاسم من ملف Forms.'));
}

export async function renderSurveys() {
  const cycle = state.cycle;
  const params = parseRoute().params;
  const data = await api(`/cycles/${cycle.id}/surveys`);
  const reload = () => import('./app.js').then(m => m.route());
  const kind = data.can_view_stats ? (params.k ?? data.items.find(s => s.responses)?.kind ?? 'trainee') : null;
  let stats = null;
  if (kind) {
    const qs = new URLSearchParams(Object.entries({ q: params.q, v: params.v }).filter(([, v]) => v != null && v !== '')).toString();
    stats = await api(`/cycles/${cycle.id}/surveys/${kind}/stats${qs ? `?${qs}` : ''}`);
  }
  const hero = h('header', { class: 'scope-hero qw-hero' },
    h('div', null, h('h1', null, 'الاستبيانات'),
      h('p', null, 'ثلاثة استبيانات للدورة: المتدرب، والمدرب، والخدمات المقدمة من الكلية للجميع (موظفين ومدربين ومتدربين). '
        + 'التعبئة في Microsoft Forms ولا تفتح إلا بحساب المؤسسة، ثم تظهر الإحصاءات هنا بعد رفع ملف الردود.')));
  const help = data.can_manage && h('details', { class: 'card sv-help' }, h('summary', null, 'طريقة الربط مع Microsoft Forms'),
    h('ol', null,
      h('li', null, 'ادخل forms.office.com بحساب المؤسسة وأنشئ النموذج (أو انسخ نموذجاً جاهزاً). استخدم أسئلة «ليكرت» أو «اختيار» بمقياس موحّد (موافق بشدة… غير موافق بشدة، أو ممتاز… ضعيف) لتُحسب نسب الرضا تلقائياً.'),
      h('li', null, 'أضف سؤال «الفئة» (متدرب / مدرب / موظف) في استبيان الخدمات، وسؤال «القسم» إن أردت التصفية حسب القسم.'),
      h('li', null, 'من «الإعدادات» اختر «يمكن فقط للأشخاص في مؤسستي الرد» — فلا يفتح النموذج إلا ببريد المؤسسة. ويمكن تفعيل «رد واحد لكل شخص».'),
      h('li', null, 'انسخ رابط «جمع الردود» والصقه في «الإعداد» هنا، ثم أرسله للفئة المستهدفة بزر «نسخ الرابط».'),
      h('li', null, 'لتحديث الإحصاءات: في Forms افتح «الردود» ← «فتح في Excel» ونزّل الملف، ثم ارفعه بزر «رفع ملف الردود». كل رفع يستبدل السابق، فارفع دائماً الملف الأحدث.')));
  return h('div', { class: 'cal-page sv-page' }, hero, help,
    h('div', { class: 'sv-grid' }, data.items.map(s => surveyCard(cycle, s, data, s.kind === kind, reload))),
    stats && statsView(cycle, stats, params));
}
