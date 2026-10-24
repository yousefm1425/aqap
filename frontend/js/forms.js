import { api, apiOpen } from './api.js';
import { deptName, parseRoute, state, userScope } from './app.js';
import { compute, fmt, isEmpty, mergedRows, tablePhase } from './formcalc.js';
import { dateTime, h, hasRole, mount, num, pct, promptText, toast } from './ui.js';
// نماذج أعمال الاختبارات ترتبط بمعيار فرعي (الرمز «3-1/...») لا بمتطلب واحد
const reqLabel = x => x.requirement_code.includes('/')
  ? `المعيار الفرعي ${x.requirement_code.split('/')[0]} — يُحدد المتطلب المرتبط من «التوافق» في أعمال الجودة`
  : `المتطلب ${x.requirement_code}: ${x.requirement_text ?? ''}`;

const DEPT_ROLES = ['hod', 'dept_coordinator', 'faculty'];
const STATUS = { draft: 'مسودة', submitted: 'بانتظار اعتماد رئيس القسم', returned: 'معاد للتعديل', approved: 'معتمد' };
const STATUS_CLASS = { draft: 's-draft', submitted: 's-submitted', returned: 's-returned', approved: 's-final' };
const ACTIVE = ['open', 'external_review'];
const KIND = { plan: 'خطة', report: 'تقرير' };
const FU_CLASS = { 'مُنفذ': 'fu-done', 'مُنفذ جزئي': 'fu-partial', 'لم يُنفذ': 'fu-not' };
const newId = () => Math.random().toString(36).slice(2, 12);
// ------------------------------------------------------------------ استيراد صفوف ملصوقة (من Excel أو منصة الإرشاد)
const normLabel = t => String(t ?? '').replace(/[ـً-ْ]/g, '').replace(/[أإآ]/g, 'ا').replace(/ة/g, 'ه')
  .replace(/[٪%]/g, '%').replace(/\s+/g, ' ').trim();
function parseTsv(text) {
  const rows = []; let row = [], cell = '', q = false;
  const t = String(text).replace(/\r\n?/g, '\n');
  for (let i = 0; i < t.length; i++) {
    const c = t[i];
    if (q) { if (c === '"') { if (t[i + 1] === '"') { cell += '"'; i++; } else q = false; } else cell += c; }
    else if (c === '"' && cell === '') q = true;
    else if (c === '\t') { row.push(cell); cell = ''; }
    else if (c === '\n') { row.push(cell); rows.push(row); row = []; cell = ''; }
    else cell += c;
  }
  if (cell || row.length) { row.push(cell); rows.push(row); }
  return rows.filter(r => r.some(x => String(x).trim()));
}
function pastedValue(c, raw) {
  const v = String(raw ?? '').trim();
  if (!v || v === '—') return { v: null };
  if (c.type === 'number') {
    const n = Number(v.replace(/[٠-٩]/g, d => '٠١٢٣٤٥٦٧٨٩'.indexOf(d)).replace(/[٫]/g, '.').replace(/[,،%٪\s]/g, ''));
    return Number.isFinite(n) ? { v: n } : { v: null, bad: true };
  }
  if (c.type === 'select') {
    const hit = c.options.find(o => normLabel(o) === normLabel(v));
    return hit ? { v: hit } : { v: null, bad: true };
  }
  if (c.type === 'url') return /^https?:\/\/\S+$/.test(v) ? { v } : { v: null, bad: true };
  return { v };
}

const clone = o => JSON.parse(JSON.stringify(o ?? {}));

function setParams(params) {
  const qs = new URLSearchParams(Object.entries(params).filter(([, v]) => v != null && v !== '')).toString();
  history.replaceState(null, '', `#/forms${qs ? `?${qs}` : ''}`);
}

export async function renderForms() {
  const cycle = state.cycle;
  const { params } = parseRoute();
  const sc = userScope();
  const deptOptions = sc.all ? state.departments.map(d => d.id) : sc.depts;
  if (!deptOptions.length) return h('div', { class: 'empty' }, 'لا يوجد قسم مسند إليك في هذه الدورة.');
  let dept = params.dept ? Number(params.dept) : deptOptions[0];
  if (!deptOptions.includes(dept)) dept = deptOptions[0];
  let selected = params.t ? Number(params.t) : null;          // قالب
  let templates = [];

  const head = h('div', { class: 'ws-head' });
  const listEl = h('nav', { class: 'req-list', 'aria-label': 'النماذج' });
  const detailEl = h('div', { class: 'detail' });
  const view = h('div', null, head, h('div', { class: 'ws' }, listEl, detailEl));
  const isDept = () => hasRole(state.me, DEPT_ROLES, dept, cycle.id);
  const recordOf = t => t.records.find(r => r.department_id === dept) ?? null;

  async function load() {
    // النماذج المرتبطة بمتطلبات خارج نطاق القسم لا تظهر له
    templates = (await api(`/cycles/${cycle.id}/forms/templates?department_id=${dept}`))
      .filter(t => !(t.excluded_for || []).includes(dept));
  }

  function renderHead() {
    const recs = templates.map(recordOf).filter(Boolean);
    const approved = recs.filter(r => r.status === 'approved').length;
    const prog = recs.map(r => r.summary?.progress).filter(v => v != null);
    const picker = deptOptions.length > 1 && h('select', {
      class: 'input', 'aria-label': 'القسم', style: { width: 'auto' },
      onchange: async e => { dept = Number(e.target.value); setParams({ dept, t: selected }); await refresh(); },
    }, deptOptions.map(d => h('option', { value: String(d) }, deptName(d))));
    if (picker) picker.value = String(dept);
    mount(head,
      h('div', { class: 'title' },
        h('h1', null, `الخطط والتقارير — ${deptName(dept)}`),
        h('div', { class: 'progress-line' },
          h('span', null, h('b', null, `${num(approved)}/${num(templates.length)}`), ' نموذج معتمد'),
          h('span', null, h('b', null, num(recs.length)), ' قيد العمل'),
          h('span', null, h('b', null, pct(prog.length ? (prog.reduce((a, b) => a + b, 0) / prog.length) * 100 : null)), ' متوسط التنفيذ'))),
      picker);
  }

  function renderList() {
    const top = listEl.scrollTop;
    let lastSub = null;
    mount(listEl, templates.map(t => {
      const rec = recordOf(t);
      const sub = t.sub_standard_code ? `${t.sub_standard_code} ${t.sub_standard_title ?? ''}` : 'متطلبات أخرى';
      const header = sub !== lastSub && h('div', { class: 'std-head' }, sub);
      lastSub = sub;
      const p = rec?.summary?.progress;
      return [header, h('button', { type: 'button', class: 'req-item', 'aria-current': String(t.id === selected), onclick: () => select(t.id) },
        h('span', { class: `dot ${rec?.status === 'approved' ? 'r-met' : rec ? 'r-partial' : 'r-none'}` }),
        h('span', { class: 'code' }, `${t.requirement_code.split('/')[0]} · ${KIND[t.kind]}${t.is_provisional ? ' · مبدئي' : ''}`),
        h('span', { class: 'meta' }, rec ? h('span', { class: `status ${STATUS_CLASS[rec.status]}` }, STATUS[rec.status])
          : h('span', { class: 'faint' }, 'لم يُنشأ'), p != null && h('span', { class: 'faint' }, pct(p * 100))),
        h('span', { class: 'text' }, t.title_ar))];
    }));
    listEl.scrollTop = top;
  }

  async function select(id) {
    selected = id; setParams({ dept, t: id }); renderList(); await renderDetail();
    if (window.matchMedia('(max-width: 900px)').matches) detailEl.scrollIntoView({ block: 'start' });
  }

  async function refresh() { await load(); renderHead(); renderList(); await renderDetail(); }

  async function act(fn, ok) {
    try { const r = await fn(); if (ok) toast(typeof ok === 'function' ? ok(r) : ok); await refresh(); return r; }
    catch (ex) { toast(ex.message, 'error'); return null; }
  }

  async function renderDetail() {
    const t = templates.find(x => x.id === selected);
    if (!t) {
      mount(detailEl, h('div', { class: 'empty' }, h('h2', null, 'اختر نموذجاً'),
        h('p', null, 'لكل متطلب من نوع «خطة» أو «تقرير» نموذج إلكتروني بنفس حقول وصيغ ملف Excel الرسمي. '
          + 'تُعبأ بيانات التخطيط ثم تُعتمد، وتُحدَّث المتابعة وخطط التحسين خلال العام، ويُحفظ PDF في بنك الشواهد مربوطاً بالمتطلب.')));
      return;
    }
    const rec = recordOf(t);
    if (!rec) {
      const can = isDept() && ACTIVE.includes(cycle.status);
      mount(detailEl, h('section', null,
        h('div', { class: 'crumbs' }, reqLabel(t)),
        h('h2', null, t.title_ar),
        t.is_provisional && h('div', { class: 'notice' }, 'نموذج مبدئي إلى أن يُعتمد النموذج الرسمي لهذا المتطلب.'),
        t.guidance_ar && h('p', { class: 'muted' }, t.guidance_ar),
        can ? h('div', null, h('button', { class: 'btn primary', onclick: () => act(
          () => api(`/cycles/${cycle.id}/forms`, { method: 'POST', body: { template_id: t.id, department_id: dept } }),
          `أُنشئ نموذج ${t.title_ar}`) }, 'إنشاء النموذج'))
          : h('p', { class: 'faint' }, 'لم ينشئ القسم هذا النموذج بعد.')));
      return;
    }
    mount(detailEl, h('p', { class: 'skeleton', style: { padding: '1.5rem' } }, 'جارٍ تحميل النموذج…'));
    await renderRecord(await api(`/forms/${rec.form_id}`));
  }

  async function renderRecord(f) {
    const schema = f.schema;
    const active = ACTIVE.includes(f.cycle_status);
    const dep = isDept();
    const planEditable = dep && active && ['draft', 'returned'].includes(f.status);
    const followEditable = dep && active && f.status !== 'submitted';
    const canDecide = f.status === 'submitted' && hasRole(state.me, ['hod', 'quality_dean'], f.department_id, f.cycle_id);
    const canReopen = f.status === 'approved' && hasRole(state.me, ['quality_dean'], f.department_id, f.cycle_id) && active;
    const plan = clone(f.plan_data), follow = clone(f.follow_data);
    let dirty = false;
    const live = new Map();             // عناصر القيم المحسوبة لتحديثها دون إعادة بناء الحقول
    const pivotEls = new Map();
    const statusEl = h('span', { class: 'faint' });
    const markDirty = () => { dirty = true; statusEl.textContent = 'تعديلات غير محفوظة'; recalc(); };

    const editableCol = (s, c) => !c.fixed && c.type !== 'computed'
      && (tablePhase(s) === 'follow' || c.phase === 'follow' ? followEditable : planEditable);

    function setCell(s, row, c, value) {
      if (tablePhase(s) === 'follow') { row[c.key] = value; }
      else if (c.phase === 'plan') { plan[s.key].find(r => r.id === row.id)[c.key] = value; }
      else {
        follow[s.key] ??= {};
        follow[s.key][row.id] ??= {};
        follow[s.key][row.id][c.key] = value;
      }
      markDirty();
    }

    function input(c, value, onInput, label) {
      const common = { 'aria-label': label, oninput: e => onInput(e.target.value) };
      let el;
      if (c.type === 'select') {
        el = h('select', { class: `input cell-select ${FU_CLASS[value] ?? ''}`, ...common,
          onchange: e => { e.target.className = `input cell-select ${FU_CLASS[e.target.value] ?? ''}`; } },
        h('option', { value: '' }, '—'), c.options.map(o => h('option', { value: o }, o)));
      } else if (c.type === 'longtext') {
        el = h('textarea', { rows: 2, ...common });
      } else {
        const listId = c.suggest?.length ? `dl-${c.key}` : null;
        el = h('input', { type: 'text', dir: c.type === 'url' ? 'ltr' : null, inputmode: c.type === 'number' ? 'decimal' : null,
          list: listId, ...common });
      }
      el.value = value ?? '';
      return el;
    }

    const datalists = new Map();
    const collectLists = cols => cols.forEach(c => { if (c.suggest?.length && !datalists.has(c.key)) datalists.set(c.key, c.suggest); });

    function groupRow(cols, lead = 1) {
      if (!cols.some(c => c.group)) return null;
      const cells = [h('th', { colspan: lead })];
      let prev, span = 0;
      for (const c of [...cols, { group: Symbol('end') }]) {
        if (span && c.group !== prev) { cells.push(h('th', { class: 'grp', colspan: span }, typeof prev === 'string' ? prev : '')); span = 0; }
        prev = c.group; span += 1;
      }
      return h('tr', null, cells);
    }

    function tableSection(s) {
      collectLists(s.columns);
      const rows = mergedRows(s, plan, follow);
      const fixed = Boolean(s.fixed_rows);
      const rowsEditable = !fixed && (tablePhase(s) === 'follow' ? followEditable : planEditable);
      const tbody = h('tbody');
      const draw = () => {
        const rs = mergedRows(s, plan, follow);
        mount(tbody, rs.map((r, i) => h('tr', null,
          h('td', { class: 'faint num' }, i + 1),
          s.columns.map(c => {
            if (c.type === 'computed') {
              const el = h('td', { class: 'computed num' });
              live.set(`${s.key}:${r.id}:${c.key}`, { el, fmt: c.format });
              return el;
            }
            const v = r[c.key];
            if (!editableCol(s, c)) return h('td', { class: `${c.type === 'number' ? 'num' : ''} ${FU_CLASS[v] ?? ''}` }, fmt(v, c.type === 'number' ? 'num' : null));
            const target = tablePhase(s) === 'follow' ? follow[s.key][i] : r;
            return h('td', { class: `w-${c.type}` }, input(c, v, val => setCell(s, target, c, val), `${c.label} — صف ${i + 1}`));
          }),
          rowsEditable && h('td', null, h('button', { class: 'btn small danger', 'aria-label': `حذف الصف ${i + 1}`, onclick: () => {
            if (tablePhase(s) === 'follow') follow[s.key].splice(i, 1);
            else { plan[s.key] = plan[s.key].filter(x => x.id !== r.id); if (follow[s.key]) delete follow[s.key][r.id]; }
            draw(); markDirty();
          } }, '×')))));
        if (!rs.length) tbody.append(h('tr', null, h('td', { colspan: s.columns.length + 2, class: 'faint' }, 'لا توجد صفوف بعد.')));
        recalc();
      };
      draw();

      // استيراد صفوف ملصوقة: صف العناوين يُطابق بأسماء أعمدة النموذج
      const anyEditable = s.columns.some(c => editableCol(s, c));
      const importPasted = (text, mode) => {
        const grid = parseTsv(text);
        if (grid.length < 2) throw new Error('الصق الجدول مع صف العناوين ثم صف بيانات واحد على الأقل');
        const byLabel = new Map(s.columns.filter(c => c.type !== 'computed').map(c => [normLabel(c.label), c]));
        const map = grid[0].map(hd => byLabel.get(normLabel(hd)) ?? null);
        const unknown = grid[0].filter((hd, i) => !map[i] && String(hd).trim());
        if (!map.some(Boolean)) throw new Error('لم تُطابق أي عنوان عمود في الجدول؛ انسخ صف العناوين كما هو');
        let bad = 0;
        const items = grid.slice(1).map(r => {
          const o = {};
          map.forEach((c, i) => { if (!c) return; const p = pastedValue(c, r[i]); if (p.bad) bad++; o[c.key] = p.v; });
          return o;
        });
        const put = (target, o, phase) => s.columns.forEach(c => {
          if (!(c.key in o) || c.fixed || c.type === 'computed' || !editableCol(s, c)) return;
          if (phase && c.phase !== phase) return;
          target[c.key] = o[c.key];
        });
        let done = 0;
        if (fixed) {                                       // صفوف ثابتة: تُطابق بقيم أعمدتها الثابتة
          const keys = s.columns.filter(c => c.fixed && map.includes(c)).map(c => c.key);
          if (!keys.length) throw new Error('هذا الجدول بصفوف ثابتة: يجب أن يتضمن الملصوق عمود التعريف (مثل «مؤشر القياس»)');
          for (const o of items) {
            const fr = s.fixed_rows.find(f => keys.every(k => normLabel(f[k]) === normLabel(o[k])));
            if (!fr) continue;
            const pr = (plan[s.key] ??= []).find(x => x.id === fr.id) ?? (plan[s.key].push({ id: fr.id }), plan[s.key].at(-1));
            if (planEditable) put(pr, o, 'plan');
            if (followEditable) { follow[s.key] ??= {}; follow[s.key][fr.id] ??= {}; put(follow[s.key][fr.id], o, 'follow'); }
            done++;
          }
        } else if (tablePhase(s) === 'follow') {
          const rows = items.map(o => { const r = { id: newId() }; put(r, o); return r; });
          follow[s.key] = mode === 'replace' ? rows : [...(follow[s.key] ?? []), ...rows];
          follow[s.key] = follow[s.key].slice(0, s.max_rows ?? 100); done = rows.length;
        } else if (planEditable) {
          if (mode === 'replace') { plan[s.key] = []; follow[s.key] = {}; }
          for (const o of items) {
            const r = { id: newId() }; put(r, o, 'plan'); plan[s.key].push(r);
            const f = {}; put(f, o, 'follow'); if (Object.keys(f).length) { follow[s.key] ??= {}; follow[s.key][r.id] = f; }
            done++;
          }
          plan[s.key] = plan[s.key].slice(0, s.max_rows ?? 100);
        } else {                                            // التخطيط معتمد: تُحدَّث المتابعة للصفوف المطابقة
          const keyCol = s.columns.find(c => c.phase === 'plan' && ['longtext', 'text'].includes(c.type) && map.includes(c));
          if (!keyCol) throw new Error(`التخطيط معتمد: أضف عمود «${s.columns.find(c => c.phase === 'plan' && c.type === 'longtext')?.label ?? 'المهمة'}» لمطابقة الصفوف`);
          for (const o of items) {
            const r = (plan[s.key] ?? []).find(x => normLabel(x[keyCol.key]) === normLabel(o[keyCol.key]));
            if (!r) continue;
            follow[s.key] ??= {}; follow[s.key][r.id] ??= {}; put(follow[s.key][r.id], o, 'follow'); done++;
          }
        }
        draw(); markDirty();
        return { done, total: items.length, unknown, bad };
      };
      const importBtn = anyEditable && h('button', { class: 'btn small', onclick: () => {
        const dlg = document.getElementById('dialog');
        const area = h('textarea', { rows: 8, dir: 'auto', placeholder: 'انسخ الجدول من Excel أو من «تقارير منصة الجودة» في منصة الإرشاد مع صف العناوين، ثم الصقه هنا' });
        const mode = h('select', { class: 'input' }, h('option', { value: 'replace' }, 'استبدال الصفوف الحالية'), h('option', { value: 'append' }, 'إضافة إلى الصفوف الحالية'));
        const err = h('p', { class: 'faint', style: { color: 'var(--danger-ink)' } });
        mount(dlg, h('form', { method: 'dialog', onsubmit: e => {
          e.preventDefault();
          try {
            const r = importPasted(area.value, mode.value);
            dlg.close();
            toast(`استُورد ${num(r.done)} من ${num(r.total)} صف${r.unknown.length ? ` · أعمدة لم تُطابق: ${r.unknown.join('، ')}` : ''}${r.bad ? ` · ${num(r.bad)} قيمة غير صالحة تُركت فارغة` : ''} — راجعها ثم احفظ`);
          } catch (ex) { err.textContent = ex.message; }
        } },
          h('h2', null, `استيراد صفوف ملصوقة — ${s.title}`),
          h('p', { class: 'faint' }, 'تُطابق الأعمدة بعناوينها، فلا يلزم ترتيبها. أعمدة الحساب التلقائي تُحسب بعد الاستيراد.'),
          !fixed && (tablePhase(s) === 'follow' || planEditable) && h('div', { class: 'field' }, h('label', null, 'طريقة الاستيراد'), mode),
          h('div', { class: 'field' }, area, err),
          h('div', { class: 'row end' }, h('button', { type: 'button', class: 'btn', onclick: () => dlg.close() }, 'إلغاء'),
            h('button', { class: 'btn primary' }, 'استيراد'))));
        dlg.showModal(); area.focus();
      } }, 'استيراد صفوف ملصوقة');

      const sumEl = s.summary && h('div', { class: 'progress-line form-sum' }, s.summary.map(m => {
        const b = h('b'); live.set(`sum:${s.key}:${m.key}`, { el: b, fmt: m.format });
        return h('span', null, b, ` ${m.label}`);
      }));
      return h('section', null,
        h('h2', null, s.title), s.help && h('p', { class: 'faint' }, s.help),
        h('div', { class: 'table-scroll' }, h('table', { class: 'data form-table' },
          h('thead', null, groupRow(s.columns), h('tr', null, h('th', null, 'م'), s.columns.map(c => h('th', { class: c.type === 'computed' ? 'computed' : null }, c.label)),
            rowsEditable && h('th'))),
          tbody)),
        (rowsEditable || importBtn) && h('div', { class: 'row' }, rowsEditable && (s.max_rows ?? 100) > 0 && h('button', { class: 'btn small', onclick: () => {
          if (tablePhase(s) === 'follow') (follow[s.key] ??= []).push({ id: newId() });
          else plan[s.key].push({ id: newId() });
          draw(); markDirty();
        } }, '+ صف'), importBtn),
        sumEl);
    }

    function pivotSection(s) {
      const wrap = h('div', { class: 'table-scroll' });
      pivotEls.set(s.key, { wrap, s });
      return h('section', null, h('h2', null, s.title), h('p', { class: 'faint' }, 'يُحسب تلقائياً من بيانات الجداول أعلاه.'), wrap);
    }

    function drawPivot(s, groups, wrap) {
      mount(wrap, h('table', { class: 'data form-table' },
        h('thead', null, groupRow(s.columns), h('tr', null, h('th', null, s.group_label || 'التخصص'), s.columns.map(c => h('th', { class: 'computed' }, c.label)))),
        h('tbody', null, groups.length ? groups.map(g => h('tr', null, h('td', null, g.group, h('span', { class: 'faint' }, ` (${g.count})`)),
          s.columns.map(c => h('td', { class: 'computed num' }, fmt(g.values[c.key], c.format)))))
          : h('tr', null, h('td', { colspan: s.columns.length + 1, class: 'faint' }, 'أدخل بيانات الجدول أعلاه لتظهر المؤشرات.')))));
    }

    function fieldsSection(s) {
      collectLists(s.fields);
      return h('section', null, h('h2', null, s.title), h('div', { class: 'grid3' }, s.fields.map(c => {
        const store = c.phase === 'plan' ? (plan[s.key] ??= {}) : (follow[s.key] ??= {});
        const can = c.phase === 'plan' ? planEditable : followEditable;
        return h('div', { class: 'field' }, h('label', null, c.label),
          can ? input(c, store[c.key], v => { store[c.key] = v; markDirty(); }, c.label) : h('div', null, fmt(store[c.key])));
      })));
    }

    function textSection(s) {
      const isFollow = s.phase === 'follow';
      const store = isFollow ? follow : plan;
      const can = isFollow ? followEditable : planEditable;
      const el = h('textarea', { rows: 3, disabled: !can, 'aria-label': s.title, oninput: e => { store[s.key] = e.target.value; markDirty(); } });
      el.value = store[s.key] ?? '';
      return h('section', null, h('h2', null, s.title), el);
    }

    function recalc() {
      const c = compute(schema, plan, follow);
      for (const [key, { el, fmt: f }] of live) {
        if (key.startsWith('sum:')) { const [, sk, mk] = key.split(':'); el.textContent = fmt(c.summaries[sk]?.[mk], f); continue; }
        const [sk, rid, ck] = key.split(':');
        const row = c.tables[sk]?.find(r => r.id === rid);
        if (!row) { live.delete(key); continue; }
        el.textContent = fmt(row[ck], f);
      }
      for (const [k, { wrap, s }] of pivotEls) drawPivot(s, c.pivots[k] ?? [], wrap);
      if (progEl) progEl.textContent = pct(c.progress != null ? c.progress * 100 : null);
      if (impEl) impEl.textContent = pct(c.improvement_pct != null ? c.improvement_pct * 100 : null);
    }

    const save = async (quiet = false) => {
      const body = {};
      if (planEditable) body.plan_data = plan;
      if (followEditable) body.follow_data = follow;
      const r = await api(`/forms/${f.id}`, { method: 'PUT', body });
      dirty = false;
      // المهام «لم يُنفذ / مُنفذ جزئي» تُضاف تلقائياً إلى «التوصيات وخطط التحسين» عند الحفظ
      const auto = rows => (rows ?? []).filter(x => x._src).map(x => `${x._src}|${x.recommendation}`).join(',');
      const before = auto(follow.improvements), after = auto(r.follow_data?.improvements);
      if (before !== after) {
        const added = (r.follow_data.improvements ?? []).filter(x => x._src).length - (follow.improvements ?? []).filter(x => x._src).length;
        toast(added > 0 ? `أُضيفت ${num(added)} خطة تحسين تلقائياً للمهام غير المنفذة أو المنفذة جزئياً` : 'حُدّثت خطط التحسين التلقائية حسب حالة التنفيذ');
        await renderRecord(r);
        return r;
      }
      if (!quiet) toast('حُفظ النموذج');
      return r;
    };
    const tr = async (to, comment = null) => {
      if (dirty && (planEditable || followEditable)) await save(true);
      return api(`/forms/${f.id}/transition`, { method: 'POST', body: { to_status: to, comment } });
    };

    // الرأس
    const last = [...f.history].reverse().find(x => x.to_status === 'returned');
    const progEl = schema.progress ? h('b') : null;
    const impEl = h('b');
    const header = h('section', null,
      h('div', { class: 'crumbs' }, reqLabel(f)),
      h('h2', null, f.title_ar),
      h('div', { class: 'row' }, h('span', { class: `status ${STATUS_CLASS[f.status]}` }, STATUS[f.status]),
        h('span', { class: 'faint' }, `${KIND[f.kind]} · المرجع AQAP-F-${f.id}`), statusEl),
      f.is_provisional && h('div', { class: 'notice' }, 'نموذج مبدئي إلى أن يُعتمد النموذج الرسمي لهذا المتطلب.'),
      f.status === 'returned' && f.return_reason && h('div', { class: 'notice' }, h('strong', null, `أعاده ${last?.actor ?? ''}: `), f.return_reason),
      f.guidance_ar && h('p', { class: 'muted' }, f.guidance_ar),
      f.status === 'approved' && h('p', { class: 'faint' }, 'معتمد: بيانات التخطيط مقفلة، ويستمر تحديث المتابعة وخطط التحسين خلال الدورة.'),
      h('div', { class: 'progress-line' }, progEl && h('span', null, progEl, ' نسبة التنفيذ'), h('span', null, impEl, ' نسبة التحسين')));

    const sections = schema.sections.map(s => (s.type === 'table' ? tableSection(s) : s.type === 'pivot' ? pivotSection(s)
      : s.type === 'fields' ? fieldsSection(s) : textSection(s)));
    const lists = [...datalists].map(([k, opts]) => h('datalist', { id: `dl-${k}` }, opts.map(o => h('option', { value: o }))));

    // الشواهد الداعمة
    const canAttach = dep && active && f.status !== 'submitted';
    const canDetach = canAttach && ['draft', 'returned'].includes(f.status);
    const attachAct = async (fn, ok) => { if (dirty) await save(true); return act(fn, ok); };
    let adder = null;
    if (canAttach) {
      const bank = (await api(`/evidence?department_id=${f.department_id}`).catch(() => []))
        .filter(e => e.confidentiality < 3 && !f.attachments.some(a => a.evidence_id === e.id));
      const pick = h('select', { class: 'input', 'aria-label': 'شاهد من بنك شواهد القسم' },
        h('option', { value: '' }, bank.length ? 'أو اختر شاهداً موجوداً في بنك القسم…' : 'لا توجد شواهد أخرى في بنك القسم'),
        bank.map(e => h('option', { value: String(e.id) }, e.title_ar)));
      const title = h('input', { type: 'text', placeholder: 'بيان الشاهد، مثال: تقرير رايات SS01', 'aria-label': 'بيان الشاهد' });
      const file = h('input', { type: 'file', 'aria-label': 'ملف الشاهد', multiple: true });
      const url = h('input', { type: 'text', dir: 'ltr', placeholder: 'أو رابط https://…', 'aria-label': 'رابط الشاهد' });
      const done = r => (r?.linked_to_requirement ? 'أُرفق الشاهد ورُبط بالمتطلب' : 'أُرفق الشاهد بالنموذج');
      adder = h('div', { class: 'ev-add' },
        h('div', { class: 'field' }, title, h('div', { class: 'row' }, file), url),
        h('button', { class: 'btn primary', style: { alignSelf: 'end' }, onclick: () => attachAct(async () => {
          const files = [...file.files]; const u = url.value.trim(); const tt = title.value.trim();
          if (!files.length && !u) throw new Error('اختر ملفاً أو أدخل رابطاً');
          if (u) {
            if (tt.length < 3) throw new Error('اكتب بيان الشاهد للرابط (3 أحرف على الأقل)');
            return api(`/forms/${f.id}/attachments`, { method: 'POST', body: { title_ar: tt, url: u } });
          }
          let r = null;
          for (const fl of files) {
            const form = new FormData(); form.append('file', fl);
            if (tt && files.length === 1) form.append('title_ar', tt);
            r = await api(`/forms/${f.id}/attachments/upload`, { method: 'POST', form });
          }
          return r;
        }, done) }, 'رفع وإرفاق'),
        pick, h('button', { class: 'btn', disabled: !bank.length, onclick: () => attachAct(async () => {
          if (!pick.value) throw new Error('اختر شاهداً من القائمة أولاً');
          return api(`/forms/${f.id}/attachments`, { method: 'POST', body: { evidence_id: Number(pick.value) } });
        }, done) }, 'إرفاق'));
    }
    const attachSection = h('section', null, h('h2', null, `الشواهد والتقارير الداعمة (${num(f.attachments.length)})`),
      f.attachments.length ? h('ul', { class: 'ev-list' }, f.attachments.map(a => h('li', null,
        h('div', { class: 'grow' },
          h('button', { type: 'button', class: 'linkish', onclick: async () => {
            try { const r = await api(`/evidence/${a.evidence_id}/download`); window.open(r.url, '_blank', 'noopener'); }
            catch (ex) { toast(ex.message, 'error'); } } }, a.title_ar),
          h('div', { class: 'faint' }, `${a.kind === 'link' ? 'رابط' : (a.file_name ?? 'ملف')} · ${a.added_by_name ?? ''} ${dateTime(a.added_at)}`)),
        a.linked ? h('span', { class: 'status s-final' }, 'مربوط بالمتطلب') : h('span', { class: 'status s-draft' }, f.status === 'approved' ? 'غير مربوط' : 'يُربط عند الاعتماد'),
        canDetach && h('button', { class: 'btn small danger', onclick: () => attachAct(
          () => api(`/forms/${f.id}/attachments/${a.evidence_id}`, { method: 'DELETE' }), 'أُزيل الشاهد من النموذج (باقٍ في بنك القسم)') }, 'إزالة'))))
        : h('p', { class: 'muted' }, 'لا توجد شواهد داعمة بعد.'),
      adder);

    // الاعتماد
    const buttons = [];
    if (planEditable || followEditable) buttons.push(h('button', { class: 'btn', onclick: () => act(() => save()) }, 'حفظ'));
    if (planEditable) buttons.push(h('button', { class: 'btn primary', onclick: () => act(() => tr('submitted'), 'رُفع النموذج لاعتماد رئيس القسم') }, 'رفع للاعتماد'));
    if (planEditable && f.status === 'draft') buttons.push(h('button', { class: 'btn danger', onclick: async () => {
      const ok = await promptText({ title: 'حذف المسودة', label: 'اكتب «حذف» للتأكيد', confirm: 'حذف' });
      if (ok === 'حذف') await act(() => api(`/forms/${f.id}`, { method: 'DELETE' }), 'حُذفت المسودة');
    } }, 'حذف المسودة'));
    if (canDecide) {
      buttons.push(h('button', { class: 'btn primary', onclick: e => {
        e.currentTarget.disabled = true; e.currentTarget.textContent = 'جارٍ الاعتماد وتوليد PDF…';
        return act(() => tr('approved'), r => (r.archive?.linked_to_requirement ? 'اعتُمد النموذج وأُرشف PDF وربط بالمتطلب' : 'اعتُمد النموذج وأُرشف PDF في بنك الشواهد'));
      } }, 'اعتماد النموذج'));
      buttons.push(h('button', { class: 'btn', onclick: async () => {
        const c = await promptText({ title: 'إعادة النموذج', label: 'سبب الإعادة (يظهر للقسم)', confirm: 'إعادة' });
        if (c !== null) await act(() => tr('returned', c), 'أُعيد النموذج للقسم');
      } }, 'إعادة للقسم'));
    }
    if (canReopen) buttons.push(h('button', { class: 'btn', onclick: async () => {
      const c = await promptText({ title: 'إعادة فتح النموذج', label: 'سبب إعادة الفتح', confirm: 'إعادة فتح' });
      if (c !== null) await act(() => tr('returned', c), 'أُعيد فتح النموذج');
    } }, 'إعادة فتح'));
    if (f.status === 'approved' && (dep || hasRole(state.me, ['quality_dean', 'quality_auditor'], f.department_id, f.cycle_id))) {
      buttons.push(h('button', { class: 'btn', onclick: () => act(async () => { if (dirty && followEditable) await save(true);
        return api(`/forms/${f.id}/archive`, { method: 'POST' }); }, r => `أُرشفت النسخة ${r.version_no} في بنك الشواهد`) }, 'أرشفة نسخة المتابعة'));
    }
    buttons.push(h('button', { class: 'btn', onclick: async () => {
      try { if (dirty && (planEditable || followEditable)) await save(true); await apiOpen(`/forms/${f.id}/pdf`); } catch (ex) { toast(ex.message, 'error'); }
    } }, f.status === 'approved' ? 'عرض PDF' : 'معاينة PDF'));
    if (f.evidence_id) buttons.push(h('button', { class: 'btn', onclick: async () => {
      try { const r = await api(`/evidence/${f.evidence_id}/download`); window.open(r.url, '_blank', 'noopener'); } catch (ex) { toast(ex.message, 'error'); }
    } }, 'النسخة المؤرشفة'));

    const flow = h('section', null, h('h2', null, 'الاعتماد'),
      planEditable && f.missing.length > 0 && h('div', null, h('p', { class: 'faint' }, 'ما ينقص قبل الرفع (حسب آخر حفظ):'),
        h('ul', { class: 'checks' }, f.missing.map(m => h('li', null, h('span', { 'aria-hidden': 'true' }, '•'), m)))),
      planEditable && !f.missing.length && h('ul', { class: 'checks' }, h('li', { class: 'ok' }, h('span', { 'aria-hidden': 'true' }, '✓'), 'النموذج مكتمل وجاهز للرفع')),
      f.status === 'approved' && h('p', null, `اعتمده ${f.approved_by_name} — ${dateTime(f.approved_at)}`),
      h('div', { class: 'row' }, buttons),
      f.history.length > 0 && h('ol', { class: 'timeline' }, f.history.map(x => h('li', null, h('span', null, dateTime(x.at)),
        h('strong', null, STATUS[x.to_status]), h('span', null, `— ${x.actor}`), x.comment && h('q', null, x.comment)))));

    mount(detailEl, header, sections, attachSection, flow, lists);
    recalc();
  }

  await load();
  renderHead(); renderList(); await renderDetail();
  return view;
}
