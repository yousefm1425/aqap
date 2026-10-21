// مجلدات الشواهد: وكيل الجودة يحدد مجلد OneDrive/SharePoint لكل قسم ومعيار، ويضبط سياسة الإرفاق، ويفحص الروابط
import { api } from './api.js';
import { deptName, go, parseRoute, state, userScope } from './app.js';
import { clearEvidenceContext } from './evfolders.js';
import { date, h, mount, num, promptText, toast } from './ui.js';

const MODES = { both: 'الروابط والملفات معاً', links: 'الروابط فقط (OneDrive / SharePoint)', files: 'رفع الملفات فقط' };


// ------------------------------------------------------------------ توليد الروابط من مجلد OneDrive رئيسي
// الهيكل: المجلد الرئيسي ← مجلد لكل معيار ← مجلد لكل معيار فرعي ← مجلد لكل قسم
const STD_DEFAULT = { 1: 'المعيار الاول القيادة الادارية', 2: 'المعيار الثاني نواتج التدريب', 3: 'المعيار الثالث المناهج وأدوات القياس والتقويم',
  4: 'المعيار الرابع التدريب والموارد المساندة', 5: 'المعيار الخامس البيئة التدريبية', 6: 'المعيار السادس الاستدامة' };
const DEPT_DEFAULT = { 'تقنية الحاسب': 'تقنية الحاسب الآلي', 'التقنية الإلكترونية': 'التقنية الالكترونية' };
const KEY = 'aqap.folderGen';
const load = () => { try { return JSON.parse(localStorage.getItem(KEY)) || {}; } catch { return {}; } };
const keep = v => { try { localStorage.setItem(KEY, JSON.stringify(v)); } catch { /* تخزين غير متاح */ } };

/** يحلل رابط المجلد الرئيسي (رابط شريط العنوان في OneDrive) إلى: الخادم، ومسار مكتبة المستندات، ومسار المجلد */
function parseRoot(raw) {
  let u;
  try { u = new URL(raw.trim()); } catch { throw new Error('الرابط غير صالح'); }
  let path = u.searchParams.get('id') || decodeURIComponent(u.pathname);
  path = path.replace(/\/Forms\/[^/]+\.aspx$/i, '').replace(/\/+$/, '');
  const m = /^(\/personal\/[^/]+\/[^/]+|\/sites\/[^/]+\/[^/]+)(\/.*)?$/.exec(path);
  if (!m || !m[2]) throw new Error('انسخ الرابط من شريط العنوان وأنت داخل المجلد الرئيسي في OneDrive');
  return { origin: u.origin, library: m[1], path };
}
const folderUrl = (root, parts) => {
  const full = [root.path, ...parts].join('/');
  return `${root.origin}${encodeURI(root.library)}/Forms/All.aspx?id=${encodeURIComponent(full)}`;
};

function generator(cycle, tree, reload) {
  const saved = load();
  const stdMap = new Map(), subs = [];
  for (const r of tree.requirements) {
    if (!stdMap.has(r.standard_code)) stdMap.set(r.standard_code, r.standard_title);
    if (!subs.some(x => x.code === r.sub_standard_code)) subs.push({ code: r.sub_standard_code, std: r.standard_code, title: r.sub_standard_title });
  }
  const input = (v, wide) => h('input', { class: 'input', value: v, style: wide ? { width: '100%' } : null });
  const rootIn = h('input', { class: 'input', dir: 'ltr', placeholder: 'https://…-my.sharepoint.com/my?id=%2Fpersonal%2F…%2FDocuments%2FQuality%20cat2027',
    value: saved.root ?? '', style: { width: '100%' } });
  const stdIns = new Map([...stdMap].map(([c, t]) => [c, input(saved.std?.[c] ?? STD_DEFAULT[c] ?? `المعيار ${c} ${t}`)]));
  const subIns = new Map(subs.map(x => [x.code, input(saved.sub?.[x.code] ?? `${x.code} ${x.title}`)]));
  const deptIns = new Map(state.departments.map(d => [d.id, input(saved.dept?.[d.id] ?? DEPT_DEFAULT[d.name_ar] ?? d.name_ar)]));
  const out = h('div');
  const names = () => ({ root: rootIn.value.trim(), std: Object.fromEntries([...stdIns].map(([k, i]) => [k, i.value.trim()])),
    sub: Object.fromEntries([...subIns].map(([k, i]) => [k, i.value.trim()])), dept: Object.fromEntries([...deptIns].map(([k, i]) => [k, i.value.trim()])) });
  const build = () => {
    const n = names(); keep(n);
    const root = parseRoot(n.root);
    const items = [];
    for (const d of state.departments) {
      items.push({ department_id: d.id, target_code: null, url: folderUrl(root, []) });
      for (const x of subs) items.push({ department_id: d.id, target_code: x.code, url: folderUrl(root, [n.std[x.std], n.sub[x.code], n.dept[d.id]]) });
    }
    return items;
  };
  const preview = () => {
    try {
      const items = build();
      const sample = items.filter(i => i.target_code).filter((_, k, a) => k === 0 || k === a.length - 1 || k === Math.floor(a.length / 2));
      mount(out, h('div', { class: 'qw-tip' },
        h('p', null, `سيُحفظ ${num(items.length)} رابطاً: المجلد الرئيسي مجلداً عاماً لكل قسم، ومجلد كل قسم داخل كل معيار فرعي (${num(subs.length)} × ${num(state.departments.length)}). `
          + 'افتح الأمثلة للتأكد أن كل رابط يفتح المجلد الصحيح قبل الحفظ:'),
        h('ul', null, sample.map(i => h('li', null, h('a', { href: i.url, target: '_blank', rel: 'noopener' },
          `${deptName(i.department_id)} — المعيار الفرعي ${i.target_code}`)))),
        h('button', { class: 'btn primary', onclick: async () => {
          try { const r = await api(`/cycles/${cycle.id}/folders/bulk`, { method: 'PUT', body: { items } }); toast(`حُفظ ${num(r.saved)} رابط مجلد`); reload(); }
          catch (ex) { toast(ex.message, 'error'); }
        } }, `حفظ ${num(items.length)} رابطاً`)));
    } catch (ex) { mount(out, h('div', { class: 'error-box' }, ex.message)); }
  };
  const grid = (title, ins, label) => h('details', { class: 'fold-names' }, h('summary', null, title),
    h('div', { class: 'fold-grid' }, [...ins].map(([k, i]) => h('label', null, h('span', { class: 'faint' }, label(k)), i))));
  return h('section', { class: 'panel' },
    h('header', null, h('h2', null, 'توليد روابط المجلدات من مجلد OneDrive رئيسي')),
    h('p', { class: 'faint' }, 'إذا أنشأت مجلداً رئيسياً فيه مجلد لكل معيار، وداخله مجلد لكل معيار فرعي، وداخله مجلد لكل قسم: الصق رابط المجلد الرئيسي من شريط العنوان، '
      + 'وتأكد أن أسماء المجلدات أدناه مطابقة حرفياً لأسمائها في OneDrive، ثم «معاينة».'),
    h('div', { class: 'field' }, h('label', null, 'رابط المجلد الرئيسي'), rootIn),
    grid(`أسماء مجلدات المعايير (${num(stdIns.size)})`, stdIns, k => `المعيار ${k}`),
    grid(`أسماء مجلدات المعايير الفرعية (${num(subIns.size)})`, subIns, k => k),
    grid(`أسماء مجلدات الأقسام (${num(deptIns.size)})`, deptIns, k => deptName(Number(k))),
    h('div', { class: 'row end' }, h('button', { class: 'btn', onclick: preview }, 'معاينة')), out);
}

export async function renderFolders() {
  const cycle = state.cycle;
  const { params } = parseRoute();
  const sc = userScope();
  const depts = state.departments.map(d => d.id).filter(d => sc.all || sc.depts.includes(d));
  const dept = depts.includes(Number(params.dept)) ? Number(params.dept) : depts[0];
  if (!dept) return h('div', { class: 'empty' }, 'لا توجد أقسام');
  const [settings, folders, tree, problems] = await Promise.all([
    api('/settings/evidence'), api(`/cycles/${cycle.id}/folders?department_id=${dept}`),
    api(`/departments/${dept}/applicability`), api(`/evidence/links/problems?department_id=${dept}`)]);
  const edit = settings.can_edit;
  const reload = () => { clearEvidenceContext(); go('folders', { dept, t: Date.now() }); };
  const run = async (fn, ok) => { try { await fn(); toast(ok); reload(); } catch (ex) { toast(ex.message, 'error'); } };

  const own = (std, sub) => folders.find(f => (sub ? f.sub_standard_code === sub
    : std ? f.standard_code === std && !f.sub_standard_code : !f.standard_code && !f.sub_standard_code));
  const setFolder = async (code, label) => {
    const url = await promptText({ title: `مجلد شواهد ${label}`,
      label: 'الصق رابط المجلد من OneDrive أو SharePoint (من «مشاركة» ← «نسخ الرابط»، بصلاحية الاطلاع لمنسوبي المؤسسة)',
      confirm: 'حفظ' });
    if (!url) return;
    run(() => api(`/cycles/${cycle.id}/folders`, { method: 'PUT', body: { department_id: dept, target_code: code, url: url.trim() } }), 'حُفظ رابط المجلد');
  };
  const folderCell = (std, sub, label, inherited) => {
    const f = own(std, sub);
    return h('div', { class: 'fold-cell' },
      f ? h('a', { class: 'btn small folder-btn', href: f.url, target: '_blank', rel: 'noopener' }, '📁 فتح')
        : h('span', { class: 'faint' }, inherited ? `يستخدم مجلد ${inherited}` : 'لم يُحدد'),
      edit && h('button', { class: 'btn small', onclick: () => setFolder(sub ?? std, label) }, f ? 'تغيير' : 'تحديد'),
      edit && f && h('button', { class: 'btn small danger', onclick: () => run(() => api(`/folders/${f.id}`, { method: 'DELETE' }), 'حُذف رابط المجلد') }, 'حذف'));
  };

  // شجرة المعايير من نطاق القسم
  const stds = new Map();
  for (const r of tree.requirements) {
    if (!stds.has(r.standard_code)) stds.set(r.standard_code, { title: r.standard_title, subs: new Map() });
    stds.get(r.standard_code).subs.set(r.sub_standard_code, r.sub_standard_title);
  }
  const root = own(null, null);
  const rows = [];
  for (const [sc2, st] of stds) {
    const stdOwn = own(sc2, null);
    rows.push(h('tr', { class: 'fold-std' }, h('th', null, h('bdi', { class: 'ssub-code' }, sc2), ' ', st.title),
      h('td', null, folderCell(sc2, null, `المعيار ${sc2}`, root && 'القسم'))));
    for (const [sub, title] of st.subs) rows.push(h('tr', null, h('td', { class: 'fold-sub' }, h('bdi', { class: 'ssub-code' }, sub), ' ', title),
      h('td', null, folderCell(sc2, sub, `المعيار الفرعي ${sub}`, stdOwn ? `المعيار ${sc2}` : root && 'القسم'))));
  }

  const domains = h('textarea', { rows: 3, dir: 'ltr', placeholder: 'tvtc-my.sharepoint.com\ntvtc.sharepoint.com' });
  domains.value = (settings.allowed_link_domains || []).join('\n');
  const mode = h('select', { class: 'input' }, Object.entries(MODES).map(([k, v]) => h('option', { value: k, selected: k === settings.attachment_mode }, v)));
  const settingsCard = h('section', { class: 'panel' },
    h('header', null, h('h2', null, 'سياسة إرفاق الشواهد في المنشأة')),
    edit ? h('div', { class: 'grid2' },
      h('div', { class: 'field' }, h('label', null, 'طريقة الإرفاق'), mode,
        h('p', { class: 'faint' }, 'المحاضر والنماذج المعتمدة تُؤرشف PDF داخل المنصة دائماً مهما كانت الطريقة.')),
      h('div', { class: 'field' }, h('label', null, 'النطاقات المسموحة للروابط (سطر لكل نطاق؛ فارغ = أي نطاق)'), domains,
        h('p', { class: 'faint' }, 'ضع نطاق SharePoint/OneDrive الخاص بالمؤسسة ليُرفض أي رابط شخصي أو خارجي.')),
      h('div', { class: 'row end', style: { gridColumn: '1 / -1' } }, h('button', { class: 'btn primary', onclick: () => run(
        () => api('/settings/evidence', { method: 'PUT', body: { attachment_mode: mode.value,
          allowed_link_domains: domains.value.split(/[\n,]/).map(s => s.trim()).filter(Boolean) } }), 'حُفظت سياسة الإرفاق') }, 'حفظ')))
      : h('p', null, `طريقة الإرفاق: ${MODES[settings.attachment_mode]}`,
          settings.allowed_link_domains.length ? ` · الروابط المقبولة من: ${settings.allowed_link_domains.join('، ')}` : ''));

  const checkBtn = edit && h('button', { class: 'btn', onclick: async e => {
    e.target.disabled = true; e.target.textContent = 'جارٍ الفحص…';
    try {
      const r = await api(`/evidence/links/check`, { method: 'POST' });
      toast(`فُحص ${num(r.checked)} رابط: ${num(r.ok + r.restricted)} سليم، ${num(r.broken)} معطل، ${num(r.unreachable)} تعذّر الوصول`);
      reload();
    } catch (ex) { toast(ex.message, 'error'); e.target.disabled = false; e.target.textContent = 'فحص الروابط الآن'; }
  } }, 'فحص الروابط الآن');
  const problemsCard = h('section', { class: 'panel' },
    h('header', null, h('h2', null, `روابط تحتاج معالجة (${num(problems.length)})`), checkBtn),
    h('p', { class: 'faint' }, 'الرابط الذي يطلب دخول حساب المؤسسة يُعد سليماً. المعطل: الملف محذوف أو منقول — أعد رفعه وحدّث الرابط.'),
    problems.length ? h('table', { class: 'data' }, h('thead', null, h('tr', null, h('th', null, 'الشاهد'), h('th', null, 'الحالة'), h('th', null, 'آخر فحص'))),
      h('tbody', null, problems.map(p => h('tr', null,
        h('td', null, h('a', { href: p.url, target: '_blank', rel: 'noopener' }, p.title_ar)),
        h('td', null, h('span', { class: 'status a-revision' }, p.link_status === 'broken' ? `معطل${p.link_http ? ` (${p.link_http})` : ''}` : 'تعذّر الوصول')),
        h('td', null, date(p.link_checked_at)))))) : h('p', { class: 'muted' }, 'لا توجد روابط معطلة في آخر فحص.'));

  return h('div', { class: 'scope-page' },
    h('header', { class: 'scope-hero' },
      h('div', null, h('h1', null, 'مجلدات الشواهد'),
        h('p', null, 'تُحفظ الشواهد في مجلدات OneDrive/SharePoint التابعة للمؤسسة، ويرفق القسم رابط الملف في المنصة داعماً للمتطلب أو المحضر أو التقرير أو خطة التحسين. '
          + 'يظهر للقسم زر «فتح مجلد الشواهد» بجانب كل متطلب ويُفتح المجلد الأخص: المعيار الفرعي ثم المعيار ثم مجلد القسم.')),
      h('div', { class: 'scope-pick' },
        depts.length > 1 && h('label', null, 'القسم ', h('select', { onchange: e => go('folders', { dept: e.target.value }) },
          depts.map(d => h('option', { value: String(d), selected: d === dept }, deptName(d))))),
        h('div', { class: 'scope-stats' }, h('span', null, h('b', null, num(folders.length)), ' مجلد محدد'),
          h('span', null, h('b', null, num(problems.length)), ' رابط معطل')))),
    settingsCard,
    edit && generator(cycle, tree, reload),
    h('section', { class: 'panel' },
      h('header', null, h('h2', null, `مجلدات ${deptName(dept)} — ${cycle.title_ar}`)),
      h('table', { class: 'data fold-table' }, h('tbody', null,
        h('tr', { class: 'fold-root' }, h('th', null, 'المجلد العام للقسم'), h('td', null, folderCell(null, null, 'القسم', null))),
        rows))),
    problemsCard);
}
