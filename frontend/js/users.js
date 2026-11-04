// إدارة المستخدمين والصلاحيات (وكيل الجودة ومدير النظام)
import { api, setToken } from './api.js';
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
  const inactive = data.users.filter(u => !u.is_active && u.id !== state.me.id);

  const email = h('input', { type: 'email', dir: 'ltr', placeholder: 'البريد الرسمي' });
  const name = h('input', { type: 'text', placeholder: 'الاسم الكامل' });
  const search = h('input', { type: 'text', placeholder: 'بحث بالاسم أو البريد…', value: q,
    onchange: e => go('users', { q: e.target.value }) });

  const roleChip = r => h('span', { class: 'role-chip' },
    `${ROLE[r.role] ?? r.role}${r.department_id ? ` · ${r.department_name ?? deptName(r.department_id)}` : ''}${r.valid_to ? ` · حتى ${r.valid_to}` : ''}`,
    h('button', { 'aria-label': 'سحب الدور', title: 'سحب الدور', onclick: () => run(() => api(`/roles/${r.id}`, { method: 'DELETE' }), 'سُحب الدور') }, '×'));

  // رابط تعيين كلمة المرور: يُرسل بالبريد، أو يُعرض لنسخه ومشاركته إن لم يكن البريد مهيأً
  const invite = async (u, created = false) => {
    try {
      const r = await api(`/users/${u.id}/invite`, { method: 'POST' });
      if (r.sent) { toast(`${created ? 'أُضيف المستخدم و' : ''}أُرسل رابط تعيين كلمة المرور إلى ${u.email}`); reload(); return; }
      showLink(u, r);
    } catch (ex) { toast(ex.message, 'error'); }
  };
  const showLink = (u, r) => {
    const dlg = document.getElementById('dialog');
    const field = h('input', { type: 'text', dir: 'ltr', readonly: true, value: r.link, style: { width: '100%' } });
    mount(dlg, h('form', { method: 'dialog' },
      h('h2', null, 'رابط تعيين كلمة المرور'),
      h('p', null, `البريد الصادر غير مهيأ بعد، فلم يُرسل الرابط تلقائياً. انسخه وأرسله إلى ${u.full_name_ar} بنفسك (رسالة خاصة، لا في مجموعة).`),
      field,
      h('p', { class: 'faint' }, `صالح ${r.expires_hours} ساعة ولمرة واحدة.`),
      h('div', { class: 'row end' },
        h('button', { type: 'button', class: 'btn', onclick: async () => {
          try { await navigator.clipboard.writeText(r.link); toast('نُسخ الرابط'); } catch { field.select(); }
        } }, 'نسخ'),
        h('button', { class: 'btn primary', onclick: () => reload() }, 'تم'))));
    dlg.showModal();
    field.select();
  };

  // تعديل الاسم والبريد
  const editUser = u => {
    const dlg = document.getElementById('dialog');
    const n = h('input', { type: 'text', id: 'eu-name', value: u.full_name_ar });
    const e = h('input', { type: 'email', id: 'eu-email', dir: 'ltr', value: u.email });
    const err = h('div');
    const form = h('form', { method: 'dialog', onsubmit: async ev => {
      ev.preventDefault();
      const body = {};
      if (n.value.trim() !== u.full_name_ar) body.full_name_ar = n.value.trim();
      if (e.value.trim().toLowerCase() !== u.email) body.email = e.value.trim();
      if (!Object.keys(body).length) { dlg.close(); return; }
      try {
        await api(`/users/${u.id}`, { method: 'PATCH', body });
        dlg.close();
        if (u.id === state.me.id && body.email) { toast('تغيّر بريدك — سجّل الدخول بالبريد الجديد وكلمة المرور نفسها'); setToken(null); window.dispatchEvent(new Event('aqap:logout')); return; }
        toast('حُفظت بيانات المستخدم'); reload();
      } catch (ex) { mount(err, h('div', { class: 'error-box' }, ex.message)); }
    } },
      h('h2', null, 'تعديل بيانات المستخدم'),
      h('div', { class: 'field' }, h('label', { for: 'eu-name' }, 'الاسم الكامل'), n),
      h('div', { class: 'field' }, h('label', { for: 'eu-email' }, 'البريد الإلكتروني'), e),
      h('p', { class: 'faint' }, 'تغيير البريد ينهي جلسات المستخدم الحالية؛ يدخل بعدها بالبريد الجديد وكلمة المرور نفسها.'),
      err,
      h('div', { class: 'row end' },
        h('button', { type: 'button', class: 'btn', onclick: () => dlg.close() }, 'إلغاء'),
        h('button', { class: 'btn primary' }, 'حفظ')));
    mount(dlg, form);
    dlg.showModal();
    n.focus();
  };

  // ---------------- لوحة تحكم مدير النظام: كلمة مرور مؤقتة، فك القفل، إنهاء الجلسات
  const sys = data.is_sysadmin;
  const fmtLogin = t => t ? new Date(t).toLocaleString('ar-SA-u-ca-gregory-nu-latn', { dateStyle: 'medium', timeStyle: 'short' }) : 'لم يدخل بعد';
  const passwordDialog = u => {
    const dlg = document.getElementById('dialog');
    const auto = h('input', { type: 'radio', name: 'pwmode', id: 'pw-auto', checked: true });
    const manual = h('input', { type: 'radio', name: 'pwmode', id: 'pw-manual' });
    const pw = h('input', { type: 'text', dir: 'ltr', id: 'pw-val', autocomplete: 'off', placeholder: '8 خانات على الأقل، حروف وأرقام', disabled: true });
    const sync = () => { pw.disabled = !manual.checked; if (manual.checked) pw.focus(); };
    auto.addEventListener('change', sync); manual.addEventListener('change', sync);
    const err = h('div');
    const btn = h('button', { class: 'btn primary' }, 'تعيين كلمة المرور');
    const form = h('form', { method: 'dialog', onsubmit: async ev => {
      ev.preventDefault();
      btn.disabled = true;
      try {
        const r = await api(`/users/${u.id}/password`, { method: 'POST', body: { password: manual.checked ? pw.value : null } });
        showTemp(u, r.password ?? pw.value);
      } catch (ex) { mount(err, h('div', { class: 'error-box' }, ex.message)); btn.disabled = false; }
    } },
      h('h2', null, `كلمة مرور مؤقتة — ${u.full_name_ar}`),
      h('p', null, 'تُعيَّن الكلمة فوراً، وتنتهي جلسات المستخدم على كل أجهزته، ويُفك قفل حسابه إن كان مقفلاً. عند أول دخول تطلب منه المنصة تعيين كلمة مروره الخاصة.'),
      h('div', { class: 'field' }, h('label', { class: 'check' }, auto, ' تولّدها المنصة (أقوى — يُنصح بها)')),
      h('div', { class: 'field' }, h('label', { class: 'check' }, manual, ' أكتبها بنفسي'), pw),
      h('p', { class: 'faint' }, 'لا تُرسل كلمة المرور في مجموعة أو قناة عامة؛ سلّمها للمستخدم نفسه. يُسجَّل الإجراء في سجل التدقيق دون الكلمة.'),
      err,
      h('div', { class: 'row end' }, h('button', { type: 'button', class: 'btn', onclick: () => dlg.close() }, 'إلغاء'), btn));
    mount(dlg, form);
    dlg.showModal();
  };
  const showTemp = (u, pw) => {
    const dlg = document.getElementById('dialog');
    const field = h('input', { type: 'text', dir: 'ltr', readonly: true, value: pw, class: 'temp-pw' });
    mount(dlg, h('form', { method: 'dialog' },
      h('h2', null, 'عُيّنت كلمة المرور المؤقتة'),
      h('p', null, `سلّمها إلى ${u.full_name_ar} (${u.email}). تظهر هنا مرة واحدة فقط ولا تُحفظ في المنصة بنص مقروء.`),
      field,
      h('p', { class: 'faint' }, 'يدخل بها مرة واحدة، ثم تطلب منه المنصة تعيين كلمة مرور جديدة.'),
      h('div', { class: 'row end' },
        h('button', { type: 'button', class: 'btn', onclick: async () => {
          try { await navigator.clipboard.writeText(pw); toast('نُسخت كلمة المرور'); } catch { field.select(); }
        } }, 'نسخ'),
        h('button', { class: 'btn primary', onclick: () => reload() }, 'تم'))));
    dlg.showModal();
    field.select();
  };
  const sysInfo = u => sys && u.has_password && h('div', { class: 'faint', style: { fontSize: '.8rem', marginTop: '.2rem' } },
    `آخر دخول: ${fmtLogin(u.last_login_at)}`,
    u.is_locked && h('span', { class: 'status a-revision', style: { marginInlineStart: '.4rem' } }, 'مقفل مؤقتاً'),
    u.must_change && h('span', { class: 'status s-draft', style: { marginInlineStart: '.4rem' } }, 'كلمة مؤقتة'));
  const sysActions = u => sys && u.id !== state.me.id && u.is_active && [
    h('button', { class: 'btn small', title: 'تعيين كلمة مرور مؤقتة يغيّرها المستخدم عند أول دخول', onclick: () => passwordDialog(u) }, 'كلمة المرور'),
    u.is_locked && h('button', { class: 'btn small', onclick: () => run(() => api(`/users/${u.id}/unlock`, { method: 'POST' }), 'فُك قفل الحساب') }, 'فك القفل'),
    u.has_password && h('button', { class: 'btn small', title: 'يُخرج المستخدم من كل أجهزته دون تغيير كلمة المرور',
      onclick: () => confirm(`إخراج ${u.full_name_ar} من كل أجهزته؟`) && run(() => api(`/users/${u.id}/end-sessions`, { method: 'POST' }), 'أُنهيت جلسات المستخدم') }, 'إنهاء الجلسات'),
  ];

  const row = u => h('tr', { class: u.is_active ? '' : 'inactive' },
    h('td', null, h('b', null, u.full_name_ar), h('div', { class: 'faint', dir: 'ltr', style: { textAlign: 'end' } }, u.email)),
    h('td', null, h('div', { class: 'chips' }, u.roles.length ? u.roles.map(roleChip) : h('span', { class: 'faint' }, 'بلا صلاحيات'),
      h('button', { class: 'btn small', onclick: () => roleDialog(u, data.can_grant_admin, reload) }, '+ دور'))),
    h('td', null, h('span', { class: `status ${u.is_active ? 's-final' : 'a-revision'}` }, u.is_active ? 'نشط' : 'موقوف'),
      h('div', { class: 'faint', style: { fontSize: '.8rem', marginTop: '.25rem' } }, u.has_password ? 'كلمة المرور معيّنة' : 'لم يعيّن كلمة المرور بعد'),
      sysInfo(u)),
    h('td', null, h('div', { class: 'row-actions' },
      sys && h('button', { class: 'btn small', onclick: () => editUser(u) }, 'تعديل'),
      sysActions(u),
      u.is_active && h('button', { class: 'btn small', title: 'يرسل للمستخدم رابطاً لتعيين كلمة المرور (للحساب الجديد أو لمن نسيها)',
        onclick: () => invite(u) }, u.has_password ? 'رابط إعادة التعيين' : 'إرسال رابط التفعيل'),
      h('button', { class: `btn small${u.is_active ? ' danger' : ''}`, onclick: () => run(
      () => api(`/users/${u.id}`, { method: 'PATCH', body: { is_active: !u.is_active } }), u.is_active ? 'أُوقف الحساب' : 'فُعّل الحساب') },
      u.is_active ? 'إيقاف' : 'تفعيل'))));

  return h('div', { class: 'scope-page' },
    h('header', { class: 'scope-hero' },
      h('div', null, h('h1', null, 'إدارة المستخدمين والصلاحيات'),
        h('p', null, 'أضف منسوبي الكلية وأسند لكل منهم دوره: وكيل الجودة، مدقق الجودة، رئيس القسم، منسق الجودة، عضو هيئة التدريب، أو مقيّم خارجي لدورة محددة. كل تغيير يُسجَّل في سجل التدقيق.')),
      h('div', { class: 'scope-stats' }, h('span', null, h('b', null, num(data.users.length)), ' مستخدم'),
        h('span', null, h('b', null, num(active)), ' نشط'))),
    sys && inactive.length > 0 && h('section', { class: 'panel' },
      h('p', { class: 'notice' }, `يوجد ${num(inactive.length)} حساب موقوف لا يستطيع أصحابها الدخول ولا استلام روابط التفعيل.`,
        ' ', h('button', { class: 'btn small primary', onclick: () => confirm(`إعادة تفعيل ${inactive.length} حساب موقوف؟`) && run(async () => {
          for (const u of inactive) await api(`/users/${u.id}`, { method: 'PATCH', body: { is_active: true } });
        }, 'أُعيد تفعيل الحسابات') }, 'إعادة تفعيل الكل'))),
    h('section', { class: 'panel' }, h('header', null, h('h2', null, 'إضافة مستخدم')),
      h('div', { class: 'guide-form' }, name, email, h('button', { class: 'btn primary', onclick: async () => {
        try {
          const r = await api('/users', { method: 'POST', body: { email: email.value.trim(), full_name_ar: name.value.trim() } });
          await invite({ id: r.id, email: email.value.trim(), full_name_ar: name.value.trim() }, true);
        } catch (ex) { toast(ex.message, 'error'); }
      } }, 'إضافة')),
      h('p', { class: 'faint' }, 'يصل المستخدم الجديد بريد فيه رابط لتعيين كلمة المرور، ثم يدخل ببريده وكلمة مروره. أسند له دوره حتى يرى صفحات قسمه.')),
    h('section', { class: 'panel' },
      h('header', null, h('h2', null, `المستخدمون (${num(users.length)})`), search),
      h('div', { class: 'table-wrap' }, h('table', { class: 'data users-table' },
        h('thead', null, h('tr', null, h('th', null, 'المستخدم'), h('th', null, 'الأدوار والصلاحيات'), h('th', null, 'الحالة'), h('th', null, ''))),
        h('tbody', null, users.map(row))))));
}
