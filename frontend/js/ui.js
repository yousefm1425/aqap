// بناء العناصر دون innerHTML لتجنب حقن المحتوى
export function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === 'style' && typeof v === 'object') {
      for (const [prop, val] of Object.entries(v)) {
        if (val == null) continue;
        if (prop.startsWith('--')) el.style.setProperty(prop, val); else el.style[prop] = val;
      }
    }
    else if (k in el && typeof v !== 'string') el[k] = v;
    else el.setAttribute(k, v === true ? '' : v);
  }
  for (const c of children.flat(Infinity)) {
    if (c == null || c === false) continue;
    el.append(c instanceof Node ? c : String(c));
  }
  return el;
}

export function mount(target, ...nodes) {
  target.replaceChildren(...nodes.flat(Infinity).filter(n => n != null && n !== false));
}

export function toast(message, kind = 'info') {
  const el = h('div', { class: `toast ${kind}` }, message);
  document.getElementById('toasts').append(el);
  setTimeout(() => el.remove(), kind === 'error' ? 6000 : 3000);
}

const NUM = new Intl.NumberFormat('ar-SA-u-nu-latn', { maximumFractionDigits: 1 });
export const pct = v => (v == null ? '—' : `${NUM.format(Number(v))}%`);
export const num = v => NUM.format(v ?? 0);
export const date = v => (v ? new Date(v).toLocaleDateString('ar-SA-u-ca-gregory-nu-latn', { day: 'numeric', month: 'short', year: 'numeric' }) : '—');
export const dateTime = v => (v ? new Date(v).toLocaleString('ar-SA-u-ca-gregory-nu-latn', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : '—');

/** حوار نصي يعيد النص أو null عند الإلغاء */
export function promptText({ title, label, confirm = 'تأكيد', required = true, choices = null }) {
  const dlg = document.getElementById('dialog');
  return new Promise(resolve => {
    const area = h('textarea', { id: 'dlg-text' });
    const pick = choices && h('select', { class: 'input', id: 'dlg-choice' },
      Object.entries(choices).map(([v, l]) => h('option', { value: v }, l)));
    const err = h('p', { class: 'faint', style: { color: 'var(--danger-ink)' } });
    const form = h('form', { method: 'dialog' },
      h('h2', null, title),
      pick && h('div', { class: 'field' }, h('label', { for: 'dlg-choice' }, 'الحكم'), pick),
      h('div', { class: 'field' }, h('label', { for: 'dlg-text' }, label), area, err),
      h('div', { class: 'row end' },
        h('button', { type: 'button', class: 'btn', onclick: () => { dlg.close(); resolve(null); } }, 'إلغاء'),
        h('button', { class: 'btn primary', value: 'ok' }, confirm)));
    form.addEventListener('submit', e => {
      if (required && !area.value.trim()) { e.preventDefault(); err.textContent = 'اكتب السبب قبل المتابعة'; return; }
      resolve(pick ? { text: area.value.trim(), choice: pick.value } : area.value.trim());
    });
    area.addEventListener('input', () => { err.textContent = ''; });
    mount(dlg, form);
    dlg.showModal();
    area.focus();
  });
}

export function hasRole(user, roles, departmentId = null, cycleId = null) {
  return user.grants.some(g => roles.includes(g.role)
    && (g.department_id == null || g.department_id === departmentId)
    && (g.cycle_id == null || g.cycle_id === cycleId));
}

export function scope(user, cycleId = null) {
  const active = user.grants.filter(g => g.cycle_id == null || g.cycle_id === cycleId);
  return { all: active.some(g => g.department_id == null),
           depts: [...new Set(active.map(g => g.department_id).filter(d => d != null))] };
}
