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
    } catch (ex) { errBox(err, ex.message); }
    finally { btn.disabled = false; }
  } },
    h('input', { type: 'email', autocomplete: 'username', value: state.me.email, hidden: true, readonly: true }),
    h('div', { class: 'field' }, h('label', { for: 'cur' }, 'كلمة المرور الحالية'), cur.wrap),
    h('div', { class: 'field' }, h('label', { for: 'np1' }, 'كلمة المرور الجديدة'), p1.wrap),
    h('div', { class: 'field' }, h('label', { for: 'np2' }, 'تأكيد كلمة المرور الجديدة'), p2.wrap),
    h('p', { class: 'faint' }, '8 خانات على الأقل، تجمع بين الحروف والأرقام. تغييرها ينهي جلساتك على الأجهزة الأخرى.'),
    err, btn);
  return h('section', { class: 'card pw-card' }, h('h2', null, 'تغيير كلمة المرور'), form);
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

function shell(content) {
  const { path } = parseRoute();
  const link = (p, label) => h('a', { href: `#/${p}`, 'aria-current': path === p ? 'page' : null }, label);
  const cycleSelect = h('select', { 'aria-label': 'دورة التقييم', onchange: e => {
    state.cycle = state.cycles.find(c => c.id === Number(e.target.value));
    route();
  } }, state.cycles.map(c => h('option', { value: String(c.id) }, `${c.title_ar} (${CYCLE_STATUS[c.status]})`)));
  if (state.cycle) cycleSelect.value = String(state.cycle.id);

  const roles = [...new Set(state.me.grants.map(g => ROLE[g.role]))].join('، ');
  return [
    h('header', { class: 'topbar' },
      h('a', { class: 'brand', href: 'home.html', title: 'منصة الجودة والاعتماد — الصفحة الرئيسية' },
        h('span', { class: 'org-logo' }, h('img', { src: 'img/tvtc-logo-light.png', alt: 'المؤسسة العامة للتدريب التقني والمهني' })),
        h('span', null, state.me.institution_name ?? 'الكلية التقنية التطبيقية بينبع')),
      h('nav', { 'aria-label': 'الأقسام الرئيسية' },
        // الصف الأول: العمل اليومي للأقسام — الصف الثاني: المتابعة والتقارير والإدارة
        h('div', { class: 'nav-row' },
          link('scope', 'نطاق المتطلبات'), link('workspace', 'التقديرات والشواهد'), link('minutes', 'المحاضر'), link('forms', 'الخطط والتقارير'),
          link('plans', 'خطط التحسين'), link('quality', 'أعمال الجودة'), link('calendar', 'التقويم')),
        h('div', { class: 'nav-row' },
          canDash() && link('dashboard', 'لوحة المؤشرات'), link('training', 'سير العملية التدريبية'), link('report', 'التقرير النهائي'), canDash() && link('college', 'تقارير الكلية'), link('folders', 'مجلدات الشواهد'),
          link('guides', 'الأدلة'), canAdmin() && link('users', 'المستخدمون'))),
      h('div', { class: 'top-side' },
        state.cycles.length > 0 && cycleSelect,
        h('div', { class: 'user' },
          h('span', { title: roles }, state.me.full_name_ar),
          h('a', { href: '#/password', class: 'pw-link', title: 'تغيير كلمة المرور' }, 'كلمة المرور'),
          h('button', { onclick: () => { setToken(null); renderLogin(); } }, 'خروج')))),
    h('main', null, content),
  ];
}

export async function route() {
  let { path } = parseRoute();
  if (!['workspace', 'dashboard', 'plans', 'minutes', 'forms', 'report', 'scope', 'calendar', 'quality', 'college', 'training', 'folders', 'guides', 'users', 'password'].includes(path)) {
    path = 'scope';                     // صفحة الانطلاق: نطاق المتطلبات ومنها إلى مهمة كل متطلب
    history.replaceState(null, '', `#/${path}`);
  }
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
    if (!state.me.grants.length) { renderLogin('حسابك مسجّل لكن لم تُسند إليه أي صلاحية بعد. تواصل مع وكالة الجودة.'); return; }
    await route();
  } catch (ex) {
    if (!(ex instanceof ApiError && ex.status === 401)) renderLogin(ex.message);
  }
}

export const userScope = () => scope(state.me, state.cycle?.id ?? null);
export { toast };
if (setPwToken) { setToken(null); renderSetPassword(setPwToken); } else boot();
