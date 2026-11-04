import { api, ApiError, hasToken, setToken } from './api.js';
import { CYCLE_STATUS, ROLE } from './labels.js';
import { h, mount, scope, toast } from './ui.js';
import { renderWorkspace } from './workspace.js';
import { renderDashboard } from './dashboard.js';
import { renderPlans } from './plans.js';
import { renderMinutes } from './minutes.js';
import { renderForms } from './forms.js';
import { renderReport } from './report.js';
import { renderScope } from './scope.js';
import { renderCalendar } from './calendar.js';
import { renderQuality } from './quality.js';
import { renderCollege } from './college.js';
import { renderTraining } from './training.js';
import { renderFolders } from './folders.js';
import { renderGuides } from './guides.js';
import { renderUsers } from './users.js';

const root = document.getElementById('app');
export const state = { me: null, cycles: [], cycle: null, departments: [] };

const DASH_ROLES = ['quality_dean', 'quality_auditor', 'system_admin'];
const canDash = () => state.me.grants.some(g => DASH_ROLES.includes(g.role));
const canAdmin = () => state.me.grants.some(g => ['quality_dean', 'system_admin'].includes(g.role));

// تمرير الرمز من مزوّد الدخول الموحّد عبر #token=...
if (location.hash.startsWith('#token=')) {
  setToken(decodeURIComponent(location.hash.slice(7)));
  history.replaceState(null, '', location.pathname);
}

// رابط تعيين كلمة المرور من البريد: #setpw=...
const setPwToken = location.hash.startsWith('#setpw=') ? decodeURIComponent(location.hash.slice(7)) : null;

window.addEventListener('aqap:logout', () => renderLogin());
window.addEventListener('hashchange', () => {
  if (location.hash.startsWith('#setpw=')) {          // فتح رابط البريد في تبويب المنصة المفتوح
    setToken(null); state.me = null;
    renderSetPassword(decodeURIComponent(location.hash.slice(7)));
  } else if (state.me) route();
});

export function parseRoute() {
  const [path, query = ''] = location.hash.replace(/^#\/?/, '').split('?');
  return { path: path || '', params: Object.fromEntries(new URLSearchParams(query)) };
}

export function go(path, params = {}) {
  const qs = new URLSearchParams(Object.entries(params).filter(([, v]) => v != null && v !== '')).toString();
  location.hash = `#/${path}${qs ? `?${qs}` : ''}`;
}

export function deptName(id) {
  return id == null ? 'متطلبات المنشأة' : (state.departments.find(d => d.id === id)?.name_ar ?? `قسم ${id}`);
}

// ---------------------------------------------------------------- الدخول وكلمة المرور
let authCfg = null;
const authConfig = async () => authCfg ??= await api('/auth/config').catch(() => ({ dev_login: false, mail: false }));

function authCard(...children) {
  document.body.classList.remove('has-sidebar', 'side-open');
  return h('div', { class: 'login' },
    h('div', { class: 'login-brand' }, h('img', { src: 'img/tvtc-logo.png', alt: 'المؤسسة العامة للتدريب التقني والمهني' }),
      h('span', null, 'الكلية التقنية التطبيقية بينبع')),
    h('h1', null, 'منصة الجودة والاعتماد'),
    ...children);
}

const errBox = (el, msg) => mount(el, msg ? h('div', { class: 'error-box', role: 'alert' }, msg) : null);

function pwInput(id, autocomplete) {
  const input = h('input', { type: 'password', id, required: true, autocomplete, dir: 'ltr', minlength: 8 });
  const toggle = h('button', { type: 'button', class: 'pw-toggle', 'aria-label': 'إظهار كلمة المرور', onclick: () => {
    const show = input.type === 'password';
    input.type = show ? 'text' : 'password';
    toggle.textContent = show ? 'إخفاء' : 'إظهار';
    toggle.setAttribute('aria-label', show ? 'إخفاء كلمة المرور' : 'إظهار كلمة المرور');
  } }, 'إظهار');
  return { input, wrap: h('div', { class: 'pw-wrap' }, input, toggle) };
}

async function renderLogin(message) {
  state.me = null;
  const cfg = await authConfig();
  const email = h('input', { type: 'email', id: 'email', required: true, autocomplete: 'username', dir: 'ltr' });
  const pw = pwInput('password', 'current-password');
  const err = h('div');
  errBox(err, message);
  const btn = h('button', { class: 'btn primary' }, 'دخول');
  const form = h('form', { class: 'auth-form', onsubmit: async e => {
    e.preventDefault();
    if (!email.value.trim() || !pw.input.value) { errBox(err, 'أدخل البريد الإلكتروني وكلمة المرور'); return; }
    btn.disabled = true;
    try {
      const r = await api('/auth/login', { method: 'POST', body: { email: email.value.trim(), password: pw.input.value } });
      setToken(r.access_token);
      await boot();
    } catch (ex) { errBox(err, ex.message); pw.input.value = ''; pw.input.focus(); }
    finally { btn.disabled = false; }
  } },
    h('div', { class: 'field' }, h('label', { for: 'email' }, 'البريد الإلكتروني'), email),
    h('div', { class: 'field' }, h('label', { for: 'password' }, 'كلمة المرور'), pw.wrap),
    err, btn,
    h('a', { href: '#', class: 'auth-link', onclick: e => { e.preventDefault(); renderForgot(email.value.trim()); } }, 'نسيت كلمة المرور؟'));
  const dev = cfg.dev_login && h('details', { class: 'dev-login' },
    h('summary', null, 'دخول تجريبي (بيئة التطوير فقط)'),
    h('p', { class: 'faint' }, 'يدخل بالبريد وحده دون كلمة مرور. لا يظهر هذا الخيار في بيئة التشغيل.'),
    h('button', { type: 'button', class: 'btn', onclick: async () => {
      if (!email.value.trim()) { errBox(err, 'أدخل البريد الإلكتروني'); return; }
      try {
        const r = await api('/auth/dev-token', { method: 'POST', body: { email: email.value.trim() } });
        setToken(r.access_token);
        await boot();
      } catch (ex) { errBox(err, ex.message); }
    } }, 'دخول تجريبي بالبريد'));
  mount(root, authCard(
    h('p', { class: 'muted' }, 'سجّل الدخول ببريدك وكلمة المرور للوصول إلى تقديرات قسمك ومؤشرات الجاهزية.'),
    form, dev,
    h('a', { href: 'home.html', class: 'faint', style: { textAlign: 'center' } }, '← العودة للصفحة الرئيسية')));
  email.focus();
}

async function renderForgot(prefill = '') {
  const cfg = await authConfig();
  const email = h('input', { type: 'email', id: 'email', required: true, autocomplete: 'username', dir: 'ltr', value: prefill });
  const out = h('div');
  const btn = h('button', { class: 'btn primary' }, 'أرسل رابط الاستعادة');
  const form = h('form', { class: 'auth-form', onsubmit: async e => {
    e.preventDefault();
    if (!email.value.trim()) { errBox(out, 'أدخل البريد الإلكتروني'); return; }
    btn.disabled = true;
    try {
      const r = await api('/auth/forgot', { method: 'POST', body: { email: email.value.trim() } });
      mount(out, h('div', { class: 'ok-box', role: 'status' }, r.message,
        r.dev_link && h('div', { class: 'faint', style: { marginTop: '.5rem' } }, 'بيئة التطوير: ',
          h('a', { href: r.dev_link, dir: 'ltr' }, 'فتح الرابط'))));
    } catch (ex) { errBox(out, ex.message); }
    finally { btn.disabled = false; }
  } },
    h('div', { class: 'field' }, h('label', { for: 'email' }, 'البريد الإلكتروني المسجّل في المنصة'), email),
    out, btn,
    h('a', { href: '#', class: 'auth-link', onclick: e => { e.preventDefault(); renderLogin(); } }, '← العودة لتسجيل الدخول'));
  mount(root, authCard(
    h('h2', { class: 'auth-title' }, 'نسيت كلمة المرور'),
    h('p', { class: 'muted' }, 'أدخل بريدك وسيصلك رابط لتعيين كلمة مرور جديدة.'),
    !cfg.mail && !cfg.dev_login && h('p', { class: 'notice' }, 'البريد الصادر غير مهيأ بعد. اطلب من مدير المنصة إرسال رابط تعيين كلمة المرور من صفحة المستخدمين.'),
    form));
  email.focus();
}

function renderChangePassword() {
  const cur = pwInput('cur', 'current-password');
  const p1 = pwInput('np1', 'new-password');
  const p2 = pwInput('np2', 'new-password');
  const err = h('div');
  const btn = h('button', { class: 'btn primary' }, 'حفظ');
  const form = h('form', { class: 'auth-form', onsubmit: async e => {
    e.preventDefault();
    if (p1.input.value !== p2.input.value) { errBox(err, 'كلمتا المرور الجديدتان غير متطابقتين'); return; }
    btn.disabled = true;
    try {
      const r = await api('/auth/change-password', { method: 'POST',
        body: { current_password: cur.input.value, new_password: p1.input.value } });
      setToken(r.access_token);
      form.reset();
      errBox(err, null);
      toast('تغيّرت كلمة المرور، وأُنهيت جلساتك على الأجهزة الأخرى');
      if (state.me.must_change) { state.me.must_change = false; go('scope'); }
    } catch (ex) { errBox(err, ex.message); }
    finally { btn.disabled = false; }
  } },
    h('input', { type: 'email', autocomplete: 'username', value: state.me.email, hidden: true, readonly: true }),
    h('div', { class: 'field' }, h('label', { for: 'cur' }, 'كلمة المرور الحالية'), cur.wrap),
    h('div', { class: 'field' }, h('label', { for: 'np1' }, 'كلمة المرور الجديدة'), p1.wrap),
    h('div', { class: 'field' }, h('label', { for: 'np2' }, 'تأكيد كلمة المرور الجديدة'), p2.wrap),
    h('p', { class: 'faint' }, '8 خانات على الأقل، تجمع بين الحروف والأرقام. تغييرها ينهي جلساتك على الأجهزة الأخرى.'),
    err, btn);
  return h('section', { class: 'card pw-card' }, h('h2', null, 'تغيير كلمة المرور'),
    state.me.must_change && h('p', { class: 'notice', role: 'alert' },
      'دخلت بكلمة مرور مؤقتة عيّنها مدير النظام. عيّن كلمة مرورك الخاصة للمتابعة؛ اكتب الكلمة المؤقتة في خانة «كلمة المرور الحالية».'),
    form);
}

async function renderSetPassword(token) {
  history.replaceState(null, '', location.pathname);       // لا يبقى الرمز في شريط العنوان ولا في السجل
  let info;
  try { info = await api(`/auth/link?token=${encodeURIComponent(token)}`); }
  catch (ex) {
    mount(root, authCard(h('div', { class: 'error-box', role: 'alert' }, ex.message),
      h('button', { class: 'btn primary', onclick: () => renderForgot() }, 'طلب رابط جديد'),
      h('a', { href: '#', class: 'auth-link', onclick: e => { e.preventDefault(); renderLogin(); } }, '← العودة لتسجيل الدخول')));
    return;
  }
  const p1 = pwInput('pw1', 'new-password');
  const p2 = pwInput('pw2', 'new-password');
  const err = h('div');
  const btn = h('button', { class: 'btn primary' }, 'حفظ كلمة المرور والدخول');
  const form = h('form', { class: 'auth-form', onsubmit: async e => {
    e.preventDefault();
    if (p1.input.value !== p2.input.value) { errBox(err, 'كلمتا المرور غير متطابقتين'); return; }
    btn.disabled = true;
    try {
      const r = await api('/auth/reset', { method: 'POST', body: { token, password: p1.input.value } });
      setToken(r.access_token);
      toast('حُفظت كلمة المرور');
      await boot();
    } catch (ex) { errBox(err, ex.message); }
    finally { btn.disabled = false; }
  } },
    h('input', { type: 'email', autocomplete: 'username', value: info.email, hidden: true, readonly: true }),
    h('div', { class: 'field' }, h('label', { for: 'pw1' }, 'كلمة المرور الجديدة'), p1.wrap),
    h('div', { class: 'field' }, h('label', { for: 'pw2' }, 'تأكيد كلمة المرور'), p2.wrap),
    h('p', { class: 'faint' }, '8 خانات على الأقل، تجمع بين الحروف والأرقام.'),
    err, btn);
  mount(root, authCard(
    h('h2', { class: 'auth-title' }, info.purpose === 'invite' ? 'تفعيل الحساب' : 'تعيين كلمة مرور جديدة'),
    h('p', { class: 'muted' }, `${info.full_name_ar} — `, h('span', { dir: 'ltr' }, info.email)),
    form));
  p1.input.focus();
}

// ---------------------------------------------------------------- الشريط الجانبي
const ICONS = {
  scope: 'M9 6h11M9 12h11M9 18h11M4.5 6h.01M4.5 12h.01M4.5 18h.01',
  workspace: 'M9 3h6v3H9zM7 4.5H5V21h14V4.5h-2M9 14l2 2 4-4',
  minutes: 'M14 3H6v18h12V7zM14 3v4h4M9 12h6M9 16h6',
  forms: 'M4 4h16v16H4zM8 16v-3M12 16V9M16 16v-5',
  plans: 'M3 17l6-6 4 4 8-8M15 7h6v6',
  quality: 'M12 3l2.6 5.3 5.9.9-4.2 4.1 1 5.8L12 16.4l-5.3 2.7 1-5.8L3.5 9.2l5.9-.9z',
  calendar: 'M4 6h16v15H4zM4 10h16M8 3v4M16 3v4',
  dashboard: 'M4 4h7v7H4zM13 4h7v4h-7zM13 10h7v10h-7zM4 13h7v7H4z',
  training: 'M3 12h4l3-8 4 16 3-8h4',
  report: 'M5 4.5A1.5 1.5 0 016.5 3H19v15H6.5A1.5 1.5 0 005 19.5zM5 19.5A1.5 1.5 0 006.5 21H19',
  college: 'M3 21h18M5 21V9l7-5 7 5v12M9 21v-6h6v6',
  folders: 'M3 6.5a1 1 0 011-1h5l2 2h9a1 1 0 011 1V18a1 1 0 01-1 1H4a1 1 0 01-1-1z',
  guides: 'M2 5h7a3 3 0 013 3v13a2 2 0 00-2-2H2zM22 5h-7a3 3 0 00-3 3v13a2 2 0 012-2h8z',
  users: 'M16 20v-1a4 4 0 00-4-4H6a4 4 0 00-4 4v1M9 11a4 4 0 100-8 4 4 0 000 8zM22 20v-1a4 4 0 00-3-3.9M16 3.1a4 4 0 010 7.8',
  key: 'M5 11h14v10H5zM8 11V7.5a4 4 0 018 0V11M12 15v2',
  logout: 'M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4M16 17l5-5-5-5M21 12H9',
  menu: 'M4 6h16M4 12h16M4 18h16',
  collapse: 'M13 17l5-5-5-5M6 17l5-5-5-5',
};
function icon(name) {
  const NS = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(NS, 'svg');
  svg.setAttribute('viewBox', '0 0 24 24'); svg.setAttribute('aria-hidden', 'true'); svg.setAttribute('class', 'ico');
  const path = document.createElementNS(NS, 'path');
  path.setAttribute('d', ICONS[name]);
  svg.append(path);
  return svg;
}

const NAV = () => [
  ['العمل اليومي', [['scope', 'نطاق المتطلبات'], ['workspace', 'التقديرات والشواهد'], ['minutes', 'المحاضر'], ['forms', 'الخطط والتقارير'],
    ['plans', 'خطط التحسين'], ['quality', 'أعمال الجودة'], ['calendar', 'التقويم']]],
  ['المتابعة والتقارير', [canDash() && ['dashboard', 'لوحة المؤشرات'], ['training', 'سير العملية التدريبية'], ['report', 'التقرير النهائي'],
    canDash() && ['college', 'تقارير الكلية'], ['folders', 'مجلدات الشواهد']]],
  ['المراجع والإدارة', [['guides', 'الأدلة'], canAdmin() && ['users', 'المستخدمون']]],
];
const PAGE_TITLE = { password: 'تغيير كلمة المرور' };

function prefCollapsed(v) {
  try { if (v === undefined) return localStorage.getItem('aqap.side') === 'mini'; localStorage.setItem('aqap.side', v ? 'mini' : 'full'); }
  catch { /* التخزين غير متاح — يبقى الشريط مفتوحاً */ }
  return false;
}

function shell(content) {
  const { path } = parseRoute();
  const groups = NAV().map(([t, items]) => [t, items.filter(Boolean)]);
  const title = PAGE_TITLE[path] ?? groups.flatMap(([, i]) => i).find(([p]) => p === path)?.[1] ?? '';
  const closeDrawer = () => document.body.classList.remove('side-open');

  const cycleSelect = h('select', { class: 'cycle-select', 'aria-label': 'دورة التقييم', onchange: e => {
    state.cycle = state.cycles.find(c => c.id === Number(e.target.value));
    route();
  } }, state.cycles.map(c => h('option', { value: String(c.id) }, `${c.title_ar} (${CYCLE_STATUS[c.status]})`)));
  if (state.cycle) cycleSelect.value = String(state.cycle.id);

  const roles = [...new Set(state.me.grants.map(g => ROLE[g.role]))].join('، ');
  const initial = (state.me.full_name_ar || '؟').trim().replace(/^(د|م|أ)\.\s*/, '')[0];
  const link = (p, label) => h('a', { href: `#/${p}`, class: 'side-link', title: label, 'aria-current': path === p ? 'page' : null,
    onclick: closeDrawer }, icon(p), h('span', { class: 'side-label' }, label));

  const side = h('aside', { class: 'sidebar', id: 'sidebar', 'aria-label': 'القائمة الرئيسية' },
    h('div', { class: 'side-head' },
      h('a', { class: 'side-brand', href: 'home.html', title: 'منصة الجودة والاعتماد — الصفحة الرئيسية' },
        h('img', { src: 'img/tvtc-logo-light.png', alt: 'المؤسسة العامة للتدريب التقني والمهني' }),
        h('span', { class: 'side-label' }, h('b', null, 'منصة الجودة والاعتماد'),
          h('small', null, state.me.institution_name ?? 'الكلية التقنية التطبيقية بينبع')))),
    h('nav', { class: 'side-nav', 'aria-label': 'الأقسام الرئيسية' },
      groups.map(([t, items]) => items.length > 0 && h('div', { class: 'side-group' },
        h('div', { class: 'side-group-title' }, h('span', { class: 'side-label' }, t)),
        items.map(([p, label]) => link(p, label))))),
    h('div', { class: 'side-foot' },
      h('div', { class: 'side-user', title: roles },
        h('span', { class: 'avatar' }, initial),
        h('span', { class: 'side-label' }, h('b', null, state.me.full_name_ar), h('small', null, roles))),
      h('div', { class: 'side-actions' },
        h('a', { href: '#/password', class: 'side-link sm', title: 'تغيير كلمة المرور', 'aria-current': path === 'password' ? 'page' : null,
          onclick: closeDrawer }, icon('key'), h('span', { class: 'side-label' }, 'كلمة المرور')),
        h('button', { type: 'button', class: 'side-link sm', title: 'تسجيل الخروج',
          onclick: () => { closeDrawer(); setToken(null); renderLogin(); } }, icon('logout'), h('span', { class: 'side-label' }, 'خروج'))),
      h('button', { type: 'button', class: 'side-collapse', title: 'طي القائمة / توسيعها', 'aria-label': 'طي القائمة',
        onclick: () => { const mini = !document.body.classList.contains('side-mini'); document.body.classList.toggle('side-mini', mini); prefCollapsed(mini); } },
        icon('collapse'))));

  document.body.classList.add('has-sidebar');
  document.body.classList.toggle('side-mini', prefCollapsed());
  return [
    side,
    h('div', { class: 'side-scrim', onclick: closeDrawer }),
    h('div', { class: 'app-main' },
      h('header', { class: 'appbar' },
        h('button', { type: 'button', class: 'menu-btn', 'aria-label': 'فتح القائمة', 'aria-controls': 'sidebar',
          onclick: () => document.body.classList.add('side-open') }, icon('menu')),
        h('h1', { class: 'appbar-title' }, title),
        state.cycles.length > 0 && h('label', { class: 'appbar-cycle' }, h('span', null, 'دورة التقييم'), cycleSelect)),
      h('main', null, content)),
  ];
}

export async function route() {
  let { path } = parseRoute();
  if (!['workspace', 'dashboard', 'plans', 'minutes', 'forms', 'report', 'scope', 'calendar', 'quality', 'college', 'training', 'folders', 'guides', 'users', 'password'].includes(path)) {
    path = 'scope';                     // صفحة الانطلاق: نطاق المتطلبات ومنها إلى مهمة كل متطلب
    history.replaceState(null, '', `#/${path}`);
  }
  // كلمة مرور مؤقتة من مدير النظام: لا يتجاوز المستخدم صفحة تغييرها
  if (state.me.must_change && path !== 'password') { go('password'); return; }
  if (path === 'dashboard' && !canDash()) { go('workspace'); return; }
  if (path === 'users' && !canAdmin()) { go('workspace'); return; }
  const content = h('div', { class: 'skeleton' }, 'جارٍ التحميل…');
  mount(root, shell(content));
  if (!state.cycle && !['password', 'users'].includes(path)) {   // هاتان الصفحتان لا تحتاجان دورة
    mount(content, h('div', { class: 'empty' }, h('h2', null, 'لا توجد دورة تقييم متاحة'),
      h('p', null, 'تظهر الدورات هنا بعد أن ينشئها وكيل الجودة ويضيف قسمك إليها.')));
    return;
  }
  try {
    const view = path === 'password' ? renderChangePassword() : path === 'dashboard' ? await renderDashboard() : path === 'plans' ? await renderPlans()
      : path === 'minutes' ? await renderMinutes() : path === 'forms' ? await renderForms() : path === 'report' ? await renderReport() : path === 'scope' ? await renderScope() : path === 'calendar' ? await renderCalendar() : path === 'quality' ? await renderQuality() : path === 'college' ? await renderCollege() : path === 'training' ? await renderTraining() : path === 'folders' ? await renderFolders() : path === 'guides' ? await renderGuides() : path === 'users' ? await renderUsers() : await renderWorkspace();
    mount(content, view);
    content.className = '';
  } catch (ex) {
    if (ex instanceof ApiError && ex.status === 401) return;
    mount(content, h('div', { class: 'error-box' }, ex.message));
  }
}

export async function refreshCycles() {
  state.cycles = await api('/cycles');
  state.cycle = state.cycles.find(c => c.id === state.cycle?.id) ?? pickCycle();
}

function pickCycle() {
  const main = state.cycles.filter(c => c.framework_code !== 'TVTC-PATTERNS');   // دورة الأنماط تُفتح عند الحاجة فقط
  return main.find(c => c.status === 'open' || c.status === 'external_review') ?? main[0] ?? state.cycles[0] ?? null;
}

async function boot() {
  if (!hasToken()) { renderLogin(); return; }
  try {
    [state.me, state.cycles, state.departments] = await Promise.all([api('/me'), api('/cycles'), api('/departments')]);
    state.cycle = pickCycle();
    if (!state.me.grants.length && !state.me.must_change) { renderLogin('حسابك مسجّل لكن لم تُسند إليه أي صلاحية بعد. تواصل مع وكالة الجودة.'); return; }
    await route();
  } catch (ex) {
    if (!(ex instanceof ApiError && ex.status === 401)) renderLogin(ex.message);
  }
}

export const userScope = () => scope(state.me, state.cycle?.id ?? null);
export { toast };
if (setPwToken) { setToken(null); renderSetPassword(setPwToken); } else boot();
