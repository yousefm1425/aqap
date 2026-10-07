import { api, ApiError, hasToken, setToken } from './api.js';
import { CYCLE_STATUS, ROLE } from './labels.js';
import { h, mount, scope, toast } from './ui.js';
import { renderWorkspace } from './workspace.js';
import { renderDashboard } from './dashboard.js';
import { renderPlans } from './plans.js';
import { renderMinutes } from './minutes.js';

const root = document.getElementById('app');
export const state = { me: null, cycles: [], cycle: null, departments: [] };

const DASH_ROLES = ['quality_dean', 'quality_auditor', 'system_admin'];
const canDash = () => state.me.grants.some(g => DASH_ROLES.includes(g.role));

// تمرير الرمز من مزوّد الدخول الموحّد عبر #token=...
if (location.hash.startsWith('#token=')) {
  setToken(decodeURIComponent(location.hash.slice(7)));
  history.replaceState(null, '', location.pathname);
}

window.addEventListener('aqap:logout', () => renderLogin());
window.addEventListener('hashchange', () => state.me && route());

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

function renderLogin(message) {
  state.me = null;
  const email = h('input', { type: 'email', id: 'email', required: true, autocomplete: 'username', dir: 'ltr' });
  const err = h('div');
  if (message) mount(err, h('div', { class: 'error-box' }, message));
  const form = h('form', { class: 'login', onsubmit: async e => {
    e.preventDefault();
    if (!email.value.trim()) { mount(err, h('div', { class: 'error-box' }, 'أدخل البريد الإلكتروني')); return; }
    try {
      const r = await api('/auth/dev-token', { method: 'POST', body: { email: email.value.trim() } });
      setToken(r.access_token);
      await boot();
    } catch (ex) { mount(err, h('div', { class: 'error-box' }, ex.message)); }
  } },
    h('h1', null, 'منصة الجودة والاعتماد'),
    h('p', { class: 'muted' }, 'سجّل الدخول بحسابك في الكلية للوصول إلى تقديرات قسمك ومؤشرات الجاهزية.'),
    h('div', { class: 'field' }, h('label', { for: 'email' }, 'البريد الإلكتروني'), email),
    err,
    h('button', { class: 'btn primary' }, 'دخول'),
    h('p', { class: 'notice' }, 'وضع التطوير: الدخول بالبريد فقط. في بيئة التشغيل يتم الدخول عبر الحساب الموحّد للمؤسسة.'));
  mount(root, form);
  email.focus();
}

function shell(content) {
  const { path } = parseRoute();
  const cycleSelect = h('select', { 'aria-label': 'دورة التقييم', onchange: e => {
    state.cycle = state.cycles.find(c => c.id === Number(e.target.value));
    route();
  } }, state.cycles.map(c => h('option', { value: String(c.id) }, `${c.title_ar} (${CYCLE_STATUS[c.status]})`)));
  if (state.cycle) cycleSelect.value = String(state.cycle.id);

  const roles = [...new Set(state.me.grants.map(g => ROLE[g.role]))].join('، ');
  return [
    h('header', { class: 'topbar' },
      h('div', { class: 'brand' }, h('strong', null, 'منصة الجودة والاعتماد'), h('span', null, state.me.institution_name ?? '')),
      h('nav', { 'aria-label': 'الأقسام الرئيسية' },
        h('a', { href: '#/workspace', 'aria-current': path === 'workspace' ? 'page' : null }, 'التقديرات والشواهد'),
        h('a', { href: '#/minutes', 'aria-current': path === 'minutes' ? 'page' : null }, 'المحاضر'),
        h('a', { href: '#/plans', 'aria-current': path === 'plans' ? 'page' : null }, 'خطط التحسين'),
        canDash() && h('a', { href: '#/dashboard', 'aria-current': path === 'dashboard' ? 'page' : null }, 'لوحة المؤشرات')),
      state.cycles.length > 0 && cycleSelect,
      h('div', { class: 'user' },
        h('span', { title: roles }, state.me.full_name_ar),
        h('button', { onclick: () => { setToken(null); renderLogin(); } }, 'خروج'))),
    h('main', null, content),
  ];
}

export async function route() {
  let { path } = parseRoute();
  if (!['workspace', 'dashboard', 'plans', 'minutes'].includes(path)) {
    path = canDash() ? 'dashboard' : 'workspace';
    history.replaceState(null, '', `#/${path}`);
  }
  if (path === 'dashboard' && !canDash()) { go('workspace'); return; }
  const content = h('div', { class: 'skeleton' }, 'جارٍ التحميل…');
  mount(root, shell(content));
  if (!state.cycle) {
    mount(content, h('div', { class: 'empty' }, h('h2', null, 'لا توجد دورة تقييم متاحة'),
      h('p', null, 'تظهر الدورات هنا بعد أن ينشئها وكيل الجودة ويضيف قسمك إليها.')));
    return;
  }
  try {
    const view = path === 'dashboard' ? await renderDashboard() : path === 'plans' ? await renderPlans()
      : path === 'minutes' ? await renderMinutes() : await renderWorkspace();
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
  return state.cycles.find(c => c.status === 'open' || c.status === 'external_review') ?? state.cycles[0] ?? null;
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
boot();
