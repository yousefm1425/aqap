// إدارة المستخدمين والصلاحيات (وكيل الجودة ومدير النظام)
import { api } from './api.js';
import { deptName, go, parseRoute, state } from './app.js';
import { ROLE } from './labels.js';
import { h, mount, num, toast } from './ui.js';

const DEPT_ROLES = ['hod', 'dept_coordinator', 'faculty'];

function roleDialog(u, canAdmin, onSaved) {
  const dlg = document.getElementById('dialog');
  const roles = Object.entries(ROLE).filter(([k]) => canAdmin || k !== 'system_admin');
  const role = h('select', { class: 'input' }, roles.map(([k, v]) => h('option', { value: k }, v)));
  const dept = h('select', { class: 'input' }, state.departments.map(d => h('option', { value: String(d.id) }, d.name_ar)));
  const cycle = h('select', { class: 'input' }, state.cycles.map(c => h('option', { value: String(c.id) }, c.title_ar)));
  const until = h('input', { class: 'input', type: 'date' });
  const deptF = h('div', { class: 'field' }, h('label', null, 'القسم'), dept);
  const extF = h('div', { class: 'row' }, h('div', { class: 'field' }, h('label', null, 'الدورة'), cycle),
    h('div', { class: 'field' }, h('label', null, 'تنتهي الصلاحية في'), until));
  const err = h('p', { class: 'faint', style: { color: 'var(--danger-ink)' } });
  const sync = () => { deptF.hidden = !DEPT_ROLES.includes(role.value); extF.hidden = role.value !== 'external_reviewer'; };
  role.addEventListener('change', sync);
  const form = h('form', { method: 'dialog', onsubmit: async e => {
    e.preventDefault();
    const body = { role: role.value };
    if (DEPT_ROLES.includes(role.value)) body.department_id = Number(dept.value);
    if (role.value === 'external_reviewer') { body.cycle_id = Number(cycle.value); body.valid_to = until.value || null; }
    try { await api(`/users/${u.id}/roles`, { method: 'POST', body }); dlg.close(); toast('أُسند الدور'); onSaved(); }
    catch (ex) { err.textContent = ex.message; }
  } },
    h('h2', null, `إسناد دور — ${u.full_name_ar}`),
    h('div', { class: 'field' }, h('label', null, 'الدور'), role), deptF, extF, err,
    h('div', { class: 'row end' }, h('button', { type: 'button', class: 'btn', onclick: () => dlg.close() }, 'إلغاء'),
      h('button', { class: 'btn primary' }, 'إسناد')));
  sync();
  mount(dlg, form);
  dlg.showModal();
}

export async function renderUsers() {
  const { params } = parseRoute();
  const data = await api('/users');
  const reload = () => go('users', { q: params.q ?? '', t: Date.now() });
  const run = async (fn, ok) => { try { await fn(); toast(ok); reload(); } catch (ex) { toast(ex.message, 'error'); } };
  const q = (params.q ?? '').trim();
  const users = data.users.filter(u => !q || `${u.full_name_ar} ${u.email}`.includes(q));
  const active = data.users.filter(u => u.is_active).length;

  const email = h('input', { type: 'email', dir: 'ltr', placeholder: 'البريد الرسمي' });
  const name = h('input', { type: 'text', placeholder: 'الاسم الكامل' });
  const search = h('input', { type: 'text', placeholder: 'بحث بالاسم أو البريد…', value: q,
    onchange: e => go('users', { q: e.target.value }) });

  const roleChip = r => h('span', { class: 'role-chip' },
    `${ROLE[r.role] ?? r.role}${r.department_id ? ` · ${r.department_name ?? deptName(r.department_id)}` : ''}${r.valid_to ? ` · حتى ${r.valid_to}` : ''}`,
    h('button', { 'aria-label': 'سحب الدور', title: 'سحب الدور', onclick: () => run(() => api(`/roles/${r.id}`, { method: 'DELETE' }), 'سُحب الدور') }, '×'));

  const row = u => h('tr', { class: u.is_active ? '' : 'inactive' },
    h('td', null, h('b', null, u.full_name_ar), h('div', { class: 'faint', dir: 'ltr', style: { textAlign: 'end' } }, u.email)),
    h('td', null, h('div', { class: 'chips' }, u.roles.length ? u.roles.map(roleChip) : h('span', { class: 'faint' }, 'بلا صلاحيات'),
      h('button', { class: 'btn small', onclick: () => roleDialog(u, data.can_grant_admin, reload) }, '+ دور'))),
    h('td', null, h('span', { class: `status ${u.is_active ? 's-final' : 'a-revision'}` }, u.is_active ? 'نشط' : 'موقوف')),
    h('td', null, h('button', { class: `btn small${u.is_active ? ' danger' : ''}`, onclick: () => run(
      () => api(`/users/${u.id}`, { method: 'PATCH', body: { is_active: !u.is_active } }), u.is_active ? 'أُوقف الحساب' : 'فُعّل الحساب') },
      u.is_active ? 'إيقاف' : 'تفعيل')));

  return h('div', { class: 'scope-page' },
    h('header', { class: 'scope-hero' },
      h('div', null, h('h1', null, 'إدارة المستخدمين والصلاحيات'),
        h('p', null, 'أضف منسوبي الكلية وأسند لكل منهم دوره: وكيل الجودة، مدقق الجودة، رئيس القسم، منسق الجودة، عضو هيئة التدريب، أو مقيّم خارجي لدورة محددة. كل تغيير يُسجَّل في سجل التدقيق.')),
      h('div', { class: 'scope-stats' }, h('span', null, h('b', null, num(data.users.length)), ' مستخدم'),
        h('span', null, h('b', null, num(active)), ' نشط'))),
    h('section', { class: 'panel' }, h('header', null, h('h2', null, 'إضافة مستخدم')),
      h('div', { class: 'guide-form' }, name, email, h('button', { class: 'btn primary', onclick: () => run(
        () => api('/users', { method: 'POST', body: { email: email.value.trim(), full_name_ar: name.value.trim() } }), 'أُضيف المستخدم — أسند له دوراً') }, 'إضافة')),
      h('p', { class: 'faint' }, 'يدخل المستخدم ببريده الرسمي عبر الدخول الموحّد للمؤسسة، ولا تُحفظ كلمات مرور في المنصة.')),
    h('section', { class: 'panel' },
      h('header', null, h('h2', null, `المستخدمون (${num(users.length)})`), search),
      h('div', { class: 'table-wrap' }, h('table', { class: 'data users-table' },
        h('thead', null, h('tr', null, h('th', null, 'المستخدم'), h('th', null, 'الأدوار والصلاحيات'), h('th', null, 'الحالة'), h('th', null, ''))),
        h('tbody', null, users.map(row))))));
}
