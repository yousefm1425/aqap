// سير العملية التدريبية: قراءة تقرير التحضير الأسبوعي SO09 (رايات) داخل المتصفح وتحويله إلى مؤشرات ورسوم وتقرير تنفيذي
import { api } from './api.js';
import { go, parseRoute, state } from './app.js';
import { date, h, mount, num, toast } from './ui.js';

const ATT = '#009C8C';      // الحضور (فيروزي المؤسسة) — مُتحقق من التمييز لعمى الألوان والتباين
const REC = '#B7791F';      // رصد التحضير
const BAD = '#C2463D';
const COLS = { 'رقم الحاسب': 'trainer_no', 'اسم المدرب': 'trainer_name', 'رمز المقرر': 'section_ref', 'اسم المقرر': 'course_name',
  'نوع الجدولة': 'schedule_type', 'إجمالي المتدربين': 'total', 'عدد المسجلين': 'registered', 'عدد المحرومين': 'deprived',
  'عدد المنسحبين': 'withdrawn', 'إجمالي التحضير': 'slots', 'تحضير مسجل': 'present', 'غياب مسجل': 'absent',
  'غير مدرج فعال': 'unlisted_active', 'غير مدرج غير فعال': 'unlisted_inactive', 'نسبة التحضير': 'recording_pct' };
const NUMERIC = ['total', 'registered', 'deprived', 'withdrawn', 'slots', 'present', 'absent', 'unlisted_active', 'unlisted_inactive'];
const P = v => (v == null ? '—' : `${(Math.round(v * 1000) / 10).toLocaleString('ar-SA-u-nu-latn')}%`);
const getT = (k, d) => { try { return Number(localStorage.getItem(`aqap.att.${k}`)) || d; } catch { return d; } };
const setT = (k, v) => { try { localStorage.setItem(`aqap.att.${k}`, String(v)); } catch { /* تخزين غير متاح */ } };
const SVG = 'http://www.w3.org/2000/svg';
const s = (tag, attrs = {}, ...kids) => {
  const el = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs || {})) if (v != null) el.setAttribute(k, v);
  for (const c of kids.flat()) if (c != null) el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  return el;
};

// ------------------------------------------------------------------ قراءة CSV داخل المتصفح
function parseCSV(text) {
  const out = []; let row = [], cell = '', q = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (q) { if (c === '"') { if (text[i + 1] === '"') { cell += '"'; i++; } else q = false; } else cell += c; }
    else if (c === '"') q = true;
    else if (c === ',') { row.push(cell); cell = ''; }
    else if (c === '\n' || c === '\r') { if (c === '\r' && text[i + 1] === '\n') i++; row.push(cell); out.push(row); row = []; cell = ''; }
    else cell += c;
  }
  if (cell || row.length) { row.push(cell); out.push(row); }
  return out.filter(r => r.some(x => x.trim()));
}

function readSO09(text) {
  const rows = parseCSV(text.replace(/^﻿/, ''));
  const head = rows[0].map(x => x.trim());
  const missing = Object.keys(COLS).filter(k => !head.includes(k));
  if (missing.length) throw new Error(`الملف ليس تقرير التحضير SO09؛ أعمدة ناقصة: ${missing.join('، ')}`);
  return rows.slice(1).map(r => {
    const o = {};
    head.forEach((k, i) => { if (COLS[k]) o[COLS[k]] = (r[i] ?? '').trim(); });
    for (const k of NUMERIC) o[k] = Number(o[k]) || 0;
    o.recording_pct = o.recording_pct === '' ? null : Number(o.recording_pct);
    return o;
  }).filter(o => o.trainer_no);
}

function guessPeriod(fileName, cycle) {
  const m = /(20\d{2})(\d{2})(\d{2})/.exec(fileName || '');
  const exp = m ? new Date(`${m[1]}-${m[2]}-${m[3]}T00:00:00`) : new Date();
  const sun = new Date(exp); sun.setDate(exp.getDate() - ((exp.getDay() + 7) % 7) - 7);   // أحد الأسبوع السابق للتصدير
  const thu = new Date(sun); thu.setDate(sun.getDate() + 4);
  const start = new Date(`${cycle.starts_on}T00:00:00`); start.setDate(start.getDate() - start.getDay());
  const week = Math.max(1, Math.floor((sun - start) / 6048e5) + 1);
  const iso = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  return { from: iso(sun), to: iso(thu), week };
}

// ------------------------------------------------------------------ الرسوم (SVG)
function groupedBars(items, target) {           // صف لكل قسم: شريط الحضور وشريط رصد التحضير (من اليمين لليسار)
  const W = 640, L = 165, bh = 14, gap = 22, H = items.length * (bh * 2 + gap) + 30;
  const x0 = W - L, span = x0 - 60;
  const x = v => x0 - span * Math.max(0, Math.min(1, v ?? 0));
  const g = s('svg', { viewBox: `0 0 ${W} ${H}`, class: 'tr-chart', direction: 'rtl', role: 'img', 'aria-label': 'الحضور ورصد التحضير لكل قسم' });
  [0, .25, .5, .75, 1].forEach(t => g.append(s('line', { x1: x(t), x2: x(t), y1: 0, y2: H - 22, class: 'grid' }),
    s('text', { x: x(t), y: H - 6, class: 'tick', 'text-anchor': 'middle' }, `${t * 100}%`)));
  if (target) g.append(s('line', { x1: x(target), x2: x(target), y1: 0, y2: H - 22, class: 'target' }));
  items.forEach((it, i) => {
    const y = i * (bh * 2 + gap) + 6;
    g.append(s('text', { x: W - 4, y: y + bh + 4, class: 'lbl', 'text-anchor': 'start' }, it.name));
    [[it.attendance, ATT, 'الحضور'], [it.recording, REC, 'رصد التحضير']].forEach(([v, c, t], k) => {
      const yy = y + k * (bh + 2), len = Math.max(2, x0 - x(v));
      g.append(s('rect', { x: x0 - len, y: yy, width: len, height: bh, rx: 4, fill: c },
        s('title', null, `${it.name} — ${t}: ${P(v)}`)),
      s('text', { x: x0 - len - 6, y: yy + bh - 3, class: 'val', 'text-anchor': 'start' }, P(v)));
    });
  });
  return g;
}

function trendLine(points, deps) {
  const W = 640, H = 230, L = 46, R = 20, T = 14, B = 34;
  const xs = points.map(p => p.week_no);
  const x = w => (points.length < 2 ? (L + W - R) / 2 : L + (W - L - R) * ((w - xs[0]) / (xs[xs.length - 1] - xs[0] || 1)));
  const lo = Math.min(.5, ...points.flatMap(p => [p.attendance ?? 1, p.recording ?? 1])) - .05;
  const y = v => T + (H - T - B) * (1 - (v - lo) / (1 - lo));
  const g = s('svg', { viewBox: `0 0 ${W} ${H}`, class: 'tr-chart', direction: 'ltr', role: 'img', 'aria-label': 'اتجاه الحضور ورصد التحضير أسبوعياً' });
  for (let t = Math.ceil(lo * 10) / 10; t <= 1.0001; t += .1) {
    g.append(s('line', { x1: L, x2: W - R, y1: y(t), y2: y(t), class: 'grid' }), s('text', { x: L - 8, y: y(t) + 4, class: 'tick', 'text-anchor': 'end' }, `${Math.round(t * 100)}%`));
  }
  points.forEach(p => g.append(s('text', { x: x(p.week_no), y: H - 12, class: 'tick', 'text-anchor': 'middle' }, `أ${p.week_no}`)));
  [['attendance', ATT, 'الحضور'], ['recording', REC, 'رصد التحضير']].forEach(([k, c, t]) => {
    const pts = points.filter(p => p[k] != null);
    if (pts.length > 1) g.append(s('polyline', { points: pts.map(p => `${x(p.week_no)},${y(p[k])}`).join(' '), fill: 'none', stroke: c, 'stroke-width': 2.5 }));
    pts.forEach(p => g.append(s('circle', { cx: x(p.week_no), cy: y(p[k]), r: 5, fill: c, stroke: '#fff', 'stroke-width': 2 },
      s('title', null, `الأسبوع ${p.week_no} — ${t}: ${P(p[k])}`))));
  });
  return g;
}

function columns(entries) {                      // توزيع الشعب حسب نسبة الرصد
  const W = 640, H = 200, B = 30, T = 18, max = Math.max(1, ...entries.map(e => e[1]));
  const bw = (W - 40) / entries.length - 18;
  const g = s('svg', { viewBox: `0 0 ${W} ${H}`, class: 'tr-chart', role: 'img', 'aria-label': 'توزيع الشعب حسب نسبة رصد التحضير' });
  entries.forEach(([label, v], i) => {
    const hgt = (H - B - T) * (v / max), xx = 20 + i * (bw + 18);
    const c = i === 0 ? ATT : i === entries.length - 1 || i === entries.length - 2 ? BAD : REC;
    g.append(s('rect', { x: xx, y: H - B - hgt, width: bw, height: Math.max(2, hgt), rx: 4, fill: c }, s('title', null, `${label}: ${v} شعبة`)),
      s('text', { x: xx + bw / 2, y: H - B - hgt - 6, class: 'val', 'text-anchor': 'middle' }, num(v)),
      s('text', { x: xx + bw / 2, y: H - 10, class: 'tick', 'text-anchor': 'middle' }, label));
  });
  return g;
}

// ------------------------------------------------------------------ النوافذ
function dialog(title, body, onOk, okLabel = 'حفظ', wide = false) {
  const dlg = document.getElementById('dialog');
  const err = h('p', { class: 'faint', style: { color: 'var(--not-met)' } });
  mount(dlg, h('form', { method: 'dialog', class: `cal-form qw-form${wide ? ' tr-wide' : ''}`, onsubmit: async e => {
    e.preventDefault(); try { await onOk(); dlg.close(); } catch (ex) { err.textContent = ex.message; }
  } }, h('h2', null, title), body, err, h('div', { class: 'row end' },
    h('button', { type: 'button', class: 'btn', onclick: () => dlg.close() }, 'إلغاء'), h('button', { class: 'btn primary' }, okLabel))));
  dlg.showModal();
}

function uploadFlow(cycle, reload) {
  const inp = h('input', { type: 'file', accept: '.csv', hidden: true, onchange: async e => {
    const f = e.target.files[0]; if (!f) return;
    let rows;
    try { rows = readSO09(await f.text()); } catch (ex) { toast(ex.message, 'error'); return; }
    const g = guessPeriod(f.name, cycle);
    const wk = h('input', { class: 'input', type: 'number', min: 1, max: 30, value: g.week, required: true });
    const from = h('input', { class: 'input', type: 'date', value: g.from }), to = h('input', { class: 'input', type: 'date', value: g.to });
    const P2 = rows.reduce((a, r) => a + r.present, 0), A2 = rows.reduce((a, r) => a + r.absent, 0);
    dialog('رفع تقرير التحضير الأسبوعي (SO09)', [
      h('div', { class: 'tr-mini' },
        h('span', null, h('b', null, num(rows.length)), ' شعبة'),
        h('span', null, h('b', null, num(new Set(rows.map(r => r.trainer_no)).size)), ' مدرب'),
        h('span', null, h('b', null, P(P2 / (P2 + A2 || 1))), ' حضور'),
        h('span', null, h('b', null, num(rows.filter(r => (r.recording_pct ?? 0) < 100).length)), ' شعبة رصدها ناقص')),
      h('p', { class: 'qw-tip' }, 'قُرئ الملف على جهازك. تُحفظ الإحصاءات على مستوى الشعبة فقط، ولا يحتوي الملف بيانات شخصية للمتدربين.'),
      h('div', { class: 'row' }, h('div', { class: 'field' }, h('label', null, 'الأسبوع التدريبي'), wk),
        h('div', { class: 'field' }, h('label', null, 'من'), from), h('div', { class: 'field' }, h('label', null, 'إلى'), to))],
    async () => {
      const r = await api(`/cycles/${cycle.id}/attendance`, { method: 'POST', body: { week_no: Number(wk.value), period_from: from.value || null,
        period_to: to.value || null, file_name: f.name, rows } });
      toast(`رُفع تقرير الأسبوع ${wk.value}: ${num(r.rows)} شعبة${r.new_trainers ? ` و${num(r.new_trainers)} مدرب جديد` : ''}`);
      go('training', { w: wk.value, t: Date.now() });
      if (r.unconfirmed) setTimeout(() => mapDialog(reload), 400);
    }, 'رفع');
    inp.value = '';
  } });
  document.body.append(inp);
  inp.click();
}

async function mapDialog(reload) {
  const list = await api('/attendance/trainers');
  const touched = new Set();
  const opt = d => h('option', { value: String(d.id) }, d.name_ar);
  const sels = list.map((t, i) => {
    const sel = h('select', { class: 'input', onchange: () => touched.add(i) }, h('option', { value: '' }, '— اختر القسم —'),
      state.departments.map(opt));
    sel.value = t.department_id ? String(t.department_id) : '';
    return sel;
  });
  const checks = list.map(() => h('input', { type: 'checkbox' }));
  const rows = list.map((t, i) => h('tr', { class: t.confirmed ? '' : 'pending' },
    h('td', null, checks[i]),
    h('td', null, t.trainer_name ?? t.trainer_no, !t.confirmed && h('small', { class: 'chip c-mid' }, 'مقترح')),
    h('td', { class: 'faint' }, (t.courses ?? []).filter(Boolean).slice(0, 4).join('، ')),
    h('td', null, sels[i])));
  // تصفية: بحث بالاسم/المقرر + القسم الحالي
  const q = h('input', { class: 'input', type: 'search', placeholder: 'ابحث باسم المدرب أو المقرر…', oninput: filter });
  const fDept = h('select', { class: 'input', onchange: filter }, h('option', { value: '*' }, 'كل الأقسام'),
    h('option', { value: '' }, 'غير مربوط'), state.departments.map(opt));
  function filter() {
    const t = q.value.trim();
    list.forEach((x, i) => {
      const text = `${x.trainer_name ?? ''} ${(x.courses ?? []).join(' ')}`;
      const okText = !t || text.includes(t);
      const okDept = fDept.value === '*' || sels[i].value === fDept.value;
      rows[i].hidden = !(okText && okDept);
    });
  }
  // نقل جماعي للمحدد
  const bulk = h('select', { class: 'input' }, h('option', { value: '' }, 'نقل المحدَّد إلى…'), state.departments.map(opt));
  bulk.onchange = () => {
    if (!bulk.value) return;
    let n = 0;
    checks.forEach((c, i) => { if (c.checked && !rows[i].hidden) { sels[i].value = bulk.value; touched.add(i); c.checked = false; n++; } });
    toast(n ? `نُقل ${num(n)} مدرب — اضغط «تأكيد وحفظ الربط» للحفظ` : 'حدّد مدربين أولاً');
    bulk.value = ''; filter();
  };
  const all = h('input', { type: 'checkbox', title: 'تحديد الظاهر', onchange: e => checks.forEach((c, i) => { if (!rows[i].hidden) c.checked = e.target.checked; }) });
  // إضافة قسم غير موجود (مثل الاتصالات أو التقنية الإلكترونية)
  const newName = h('input', { class: 'input', placeholder: 'اسم قسم جديد، مثل: التقنية الإلكترونية',
    onkeydown: e => { if (e.key === 'Enter') { e.preventDefault(); addBtn.click(); } } });
  const addBtn = h('button', { type: 'button', class: 'btn', onclick: async () => {
    const name = newName.value.trim(); if (name.length < 2) { newName.focus(); return; }
    try {
      const r = await api('/attendance/departments', { method: 'POST', body: { name_ar: name } });
      if (!r.existing) {
        const d = { id: r.id, name_ar: r.name_ar };
        state.departments.push(d);
        [...sels, fDept, bulk].forEach(s => s.append(opt(d)));
        // تحديث الاقتراحات لغير المؤكَّدين ما لم يعدّلها المستخدم يدوياً
        const fresh = await api('/attendance/trainers');
        const byNo = new Map(fresh.map(x => [x.trainer_no, x]));
        let moved = 0;
        list.forEach((t, i) => {
          const f = byNo.get(t.trainer_no);
          if (!t.confirmed && !touched.has(i) && f && f.department_id === r.id) { sels[i].value = String(r.id); moved++; }
        });
        toast(`أُضيف قسم «${r.name_ar}»${moved ? ` واقتُرح له ${num(moved)} مدرب` : ''} — اختره للمدربين ثم احفظ`);
      } else toast(`القسم «${r.name_ar}» موجود مسبقاً`);
      newName.value = ''; filter();
    } catch (ex) { toast(ex.message, 'error'); }
  } }, '+ إضافة القسم');
  dialog('ربط المدربين بالأقسام', [
    h('p', { class: 'qw-tip' }, 'تقرير SO09 لا يحتوي عمود القسم؛ اقترحت المنصة قسم كل مدرب من مقرراته. عدّل من القائمة أو حدّد عدة مدربين وانقلهم دفعة واحدة، ثم احفظ — يُحفظ الربط لكل الأسابيع القادمة. القسم غير الموجود أضِفه من الأسفل.'),
    h('div', { class: 'tr-maptools' }, q, fDept, bulk),
    h('div', { class: 'tr-map' }, h('table', { class: 'data' },
      h('thead', null, h('tr', null, h('th', null, all), h('th', null, 'المدرب'), h('th', null, 'مقرراته'), h('th', null, 'القسم'))),
      h('tbody', null, rows))),
    h('div', { class: 'tr-maptools' }, newName, addBtn)],
  async () => {
    const items = list.map((t, i) => ({ trainer_no: t.trainer_no, department_id: sels[i].value ? Number(sels[i].value) : null }))
      .filter(x => x.department_id);
    const r = await api('/attendance/trainers', { method: 'PUT', body: { items } });
    toast(`حُفظ ربط ${num(r.updated)} مدرب`); reload();
  }, 'تأكيد وحفظ الربط', true);
}

// ------------------------------------------------------------------ التقرير التنفيذي (طباعة)
function insights(d, tAtt, tRec) {
  const c = d.college, out = [];
  out.push(`بلغت نسبة الحضور الفعلية ${P(c.attendance)} ${c.attendance >= tAtt ? 'وهي ضمن' : 'وهي دون'} المستهدف (${P(tAtt)}).`);
  out.push(`نسبة رصد التحضير ${P(c.recording)}؛ ${num(c.incomplete)} شعبة من ${num(c.sections)} لم يكتمل رصدها${c.not_recorded ? `، منها ${num(c.not_recorded)} لم يُرصد لها أي تحضير` : ''}.`);
  const deps = d.by_department.filter(x => x.department_id && x.attendance != null).sort((a, b) => a.attendance - b.attendance);
  if (deps.length) out.push(`أدنى الأقسام حضوراً: ${deps[0].name} (${P(deps[0].attendance)})، وأعلاها: ${deps[deps.length - 1].name} (${P(deps[deps.length - 1].attendance)}).`);
  if (d.low_courses.length) out.push(`أدنى المقررات حضوراً: ${d.low_courses.slice(0, 3).map(x => `${x.course.trim()} (${P(x.attendance)})`).join('، ')}.`);
  out.push(`المحرومون ${num(c.deprived)} والمنسحبون ${num(c.withdrawn)} من إجمالي ${num(c.total)} متدرب في الشعب.`);
  return out;
}

function printReport(d, tAtt, tRec, e) {
  const c = d.college, wk = d.week;
  const recs = [];
  if (c.incomplete) recs.push('متابعة المدربين الذين لم يكتمل رصد التحضير في شعبهم وإكماله قبل نهاية الأسبوع التالي.');
  if (c.attendance < tAtt) recs.push('تفعيل دور المرشد التدريبي مع المتدربين المتكرر غيابهم والتواصل مع أولياء الأمور.');
  if (d.low_courses.length) recs.push(`دراسة أسباب انخفاض الحضور في: ${d.low_courses.slice(0, 3).map(x => x.course.trim()).join('، ')}.`);
  recs.push('إدراج نتائج هذا التقرير في تقرير قياس سير العملية التدريبية (4-3-1) لكل قسم.');
  const kpi = (l, v, cls = '') => `<div class="k ${cls}"><small>${l}</small><b>${v}</b></div>`;
  const deptRows = d.by_department.map(x => `<tr><td>${x.name}</td><td>${num(x.sections)}</td><td>${num(x.trainers)}</td><td>${num(x.registered)}</td>
    <td class="${x.attendance < tAtt ? 'bad' : ''}">${P(x.attendance)}</td><td class="${x.recording < tRec ? 'bad' : ''}">${P(x.recording)}</td>
    <td>${num(x.incomplete)}</td><td>${num(x.deprived)}</td><td>${num(x.withdrawn)}</td></tr>`).join('');
  const fu = d.follow_up.slice(0, 30).map((x, i) => `<tr><td>${i + 1}</td><td>${x.department}</td><td>${x.trainer ?? ''}</td><td>${(x.course ?? '').trim()}</td>
    <td>${x.section ?? ''}</td><td class="bad">${P(x.recording / 100)}</td></tr>`).join('');
  const enr = e?.latest && e.by_department?.length ? `<div style="break-inside:avoid"><h2>المتدربون المستمرون والبرامج (ST06${e.latest.term_label ? ` — ${e.latest.term_label}` : ''})</h2>
    <p class="sub" style="margin:0 0 4px">إجمالي المتدربين المستمرين ${num(e.total)} في ${num(e.programs)} برنامج${e.same_snapshot ? '' : ` · بداية الفصل ${num(e.baseline_total)} (الاستمرار ${P(e.baseline_total ? e.total / e.baseline_total : null)})`}</p>
    <table><tr><th>القسم</th><th>البرامج</th><th>المتدربون</th>${e.same_snapshot ? '' : '<th>بداية الفصل</th>'}<th>المدربون</th><th>متدرب لكل مدرب</th></tr>
    ${e.by_department.map(x => `<tr><td>${x.name}</td><td>${x.programs.map(p => p.program.replace(/\s*-\s*تطبيقي$/, '').replace(/-تطبيقي$/, '') + (p.shift && p.shift !== 'صباحي' ? ` (${p.shift})` : '')).join('، ')}</td>
      <td>${num(x.trainees)}</td>${e.same_snapshot ? '' : `<td>${num(x.baseline)}</td>`}<td>${x.trainers ? num(x.trainers) : '—'}</td><td>${x.per_trainer ?? '—'}</td></tr>`).join('')}</table></div>` : '';
  const chart1 = groupedBars(d.by_department, tAtt).outerHTML, chart2 = d.trend.length > 1 ? trendLine(d.trend).outerHTML : '';
  const html = `<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><title>التقرير التنفيذي — سير العملية التدريبية</title>
  <style>
    @page { size: A4; margin: 14mm 12mm; }
    body { font-family: "IBM Plex Sans Arabic", "Segoe UI", Tahoma, sans-serif; color: #1f2d2c; margin: 0; font-size: 11pt; }
    .hd { display: flex; justify-content: space-between; align-items: center; border-bottom: 3px solid #009C8C; padding-bottom: 8px; }
    .hd img { height: 52px; } .hd .t { text-align: left; color: #126C66; font-weight: 700; }
    .college { color: #126C66; font-weight: 700; margin-top: 4px; font-size: 10.5pt; }
    h1 { font-size: 18pt; color: #126C66; margin: 14px 0 2px; } .sub { color: #66706f; margin: 0 0 12px; }
    .kpis { display: grid; grid-template-columns: repeat(5, 1fr); gap: 8px; margin: 10px 0 14px; }
    .k { border: 1px solid #d6e6e3; border-top: 4px solid #009C8C; border-radius: 8px; padding: 8px; }
    .k.r { border-top-color: #B7791F; } .k.b { border-top-color: #C2463D; }
    .k small { display: block; color: #66706f; font-size: 8.5pt; } .k b { font-size: 16pt; }
    h2 { font-size: 12.5pt; color: #126C66; border-right: 5px solid #009C8C; padding-right: 8px; margin: 16px 0 8px; break-after: avoid; }
    ul { margin: 0; padding-right: 18px; } li { margin: 3px 0; line-height: 1.7; }
    table { width: 100%; border-collapse: collapse; font-size: 9pt; margin-top: 4px; }
    th { background: #126C66; color: #fff; padding: 5px; } td { border-bottom: 1px solid #e3ecea; padding: 4px 5px; text-align: center; }
    td:first-child, td:nth-child(2) { text-align: right; } .bad { color: #C2463D; font-weight: 700; }
    .legend { font-size: 9pt; color: #555; } .legend i { display: inline-block; width: 10px; height: 10px; border-radius: 3px; margin: 0 4px 0 10px; }
    svg { width: 100%; height: auto; } svg .grid { stroke: #e6eeed; } svg .target { stroke: #C2463D; stroke-dasharray: 4 3; }
    svg .tick { font-size: 10px; fill: #78807f; } svg .lbl { font-size: 11px; fill: #1f2d2c; } svg .val { font-size: 10px; fill: #3b4544; }
    .two { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; } .sign { display: grid; grid-template-columns: 1fr 1fr; gap: 30px; margin-top: 26px; }
    .sign div { border-top: 1px solid #999; padding-top: 6px; text-align: center; color: #555; }
    .ft { margin-top: 18px; font-size: 8.5pt; color: #8a9291; border-top: 1px solid #e3ecea; padding-top: 6px; display: flex; justify-content: space-between; }
  </style></head><body>
  <div class="hd"><div><img src="${location.origin}/app/img/tvtc-logo.png" alt=""><div class="college">الكلية التقنية التطبيقية بينبع</div></div>
    <div class="t">وكالة الجودة<br><span style="font-weight:400;color:#66706f;font-size:9pt">تقريرا SO09 و ST06 — رايات</span></div></div>
  <h1>التقرير التنفيذي لسير العملية التدريبية</h1>
  <p class="sub">الأسبوع التدريبي ${wk.week_no}${wk.period_from ? ` · من ${date(wk.period_from)} إلى ${date(wk.period_to)}` : ''}</p>
  <div class="kpis">${kpi('نسبة الحضور الفعلية', P(c.attendance))}${kpi('نسبة رصد التحضير', P(c.recording), 'r')}${kpi('الشعب', num(c.sections))}
    ${kpi('المتدربون المسجلون', num(c.registered))}${kpi('شعب رصدها ناقص', num(c.incomplete), 'b')}</div>
  <h2>أبرز النتائج</h2><ul>${insights(d, tAtt, tRec).map(x => `<li>${x}</li>`).join('')}</ul>
  <h2>الحضور ورصد التحضير حسب القسم</h2>
  <div class="legend"><i style="background:${ATT}"></i>الحضور<i style="background:${REC}"></i>رصد التحضير<i style="background:#C2463D;height:2px"></i>المستهدف ${P(tAtt)}</div>${chart1}
  ${chart2 ? `<h2>اتجاه الأسابيع</h2>${chart2}` : ''}
  <h2>ملخص الأقسام</h2><table><tr><th>القسم</th><th>الشعب</th><th>المدربون</th><th>المسجلون</th><th>الحضور</th><th>رصد التحضير</th><th>رصد ناقص</th><th>المحرومون</th><th>المنسحبون</th></tr>${deptRows}</table>
  ${enr}
  <h2>التوصيات</h2><ul>${recs.map(x => `<li>${x}</li>`).join('')}</ul>
  ${fu ? `<h2>شعب تحتاج متابعة رصد التحضير (أدنى 30)</h2><table><tr><th>#</th><th>القسم</th><th>المدرب</th><th>المقرر</th><th>الشعبة</th><th>الرصد</th></tr>${fu}</table>` : ''}
  <div class="sign"><div>رئيس القسم</div><div>وكيل الجودة</div></div>
  <div class="ft"><span>المؤسسة العامة للتدريب التقني والمهني · الكلية التقنية التطبيقية بينبع</span><span>منصة الجودة والاعتماد</span></div>
  <script>setTimeout(() => print(), 600)<\/script></body></html>`;
  const w = window.open('', '_blank');
  if (!w) { toast('اسمح بالنوافذ المنبثقة لعرض التقرير', 'error'); return; }
  w.document.write(html); w.document.close();
}

// ------------------------------------------------------------------ ST06: المتدربون المستمرون والبرامج
const COLS06 = { 'الفصل التدريبي': 'term', 'القسم': 'dept_name', 'البرنامج': 'program', 'المرحلة': 'stage', 'نوع التدريب': 'shift', 'عدد المتدربين': 'trainees' };

function readST06(text) {
  const rows = parseCSV(text.replace(/^﻿/, ''));
  const head = rows[0].map(x => x.trim());
  const need = ['القسم', 'البرنامج', 'عدد المتدربين'];
  const missing = need.filter(k => !head.includes(k));
  if (missing.length) throw new Error(`الملف ليس تقرير ST06؛ أعمدة ناقصة: ${missing.join('، ')}`);
  return rows.slice(1).map(r => {
    const o = {};
    head.forEach((k, i) => { if (COLS06[k]) o[COLS06[k]] = (r[i] ?? '').trim(); });
    o.trainees = Number(o.trainees) || 0;
    return o;
  }).filter(o => o.dept_name && o.program);
}

function programBars(depts) {                   // شريط لكل برنامج، مجمّعة حسب القسم (سلسلة واحدة)
  const items = depts.flatMap(d => d.programs.map(p => ({ dept: d.name, label: `${p.program.replace(/\s*-\s*تطبيقي$/, '').replace(/-تطبيقي$/, '')}${p.shift && p.shift !== 'صباحي' ? ` (${p.shift})` : ''}`, v: p.trainees })));
  const L = 250, R = 60, row = 26, gap = 14, W = 760;
  const H = items.length * row + (depts.length - 1) * gap + 10, max = Math.max(1, ...items.map(i => i.v));
  const g = s('svg', { viewBox: `0 0 ${W} ${H}`, class: 'tr-chart', direction: 'rtl', role: 'img', 'aria-label': 'المتدربون المستمرون حسب البرنامج' });
  let y = 4, prev = null;
  items.forEach(it => {
    if (prev !== null && it.dept !== prev) y += gap;
    if (it.dept !== prev) g.append(s('line', { x1: R, x2: W - 4, y1: y - gap / 2, y2: y - gap / 2, class: 'grid' }));
    prev = it.dept;
    const w = (W - L - R) * (it.v / max);
    g.append(s('text', { x: W - 4, y: y + row / 2 + 4, class: 'lbl', 'text-anchor': 'start' }, it.label),
      s('rect', { x: W - L - w, y: y + 4, width: Math.max(2, w), height: row - 9, rx: 4, fill: ATT }, s('title', null, `${it.dept} — ${it.label}: ${num(it.v)} متدرب`)),
      s('text', { x: W - L - w - 6, y: y + row / 2 + 4, class: 'val', 'text-anchor': 'start' }, num(it.v)));
    y += row;
  });
  return g;
}

function uploadST06(cycle, e, reload) {
  const inp = h('input', { type: 'file', accept: '.csv', hidden: true, onchange: async ev => {
    const f = ev.target.files[0]; if (!f) return;
    let rows;
    try { rows = readST06(await f.text()); } catch (ex) { toast(ex.message, 'error'); return; }
    const term = rows.find(r => r.term)?.term ?? '';
    const total = rows.reduce((a, r) => a + r.trainees, 0);
    const asBase = h('input', { type: 'checkbox' });
    dialog('رفع تقرير ST06 — المتدربون المستمرون', [
      h('p', null, `${f.name}: ${num(rows.length)} برنامج/فترة، ${num(total)} متدرب${term ? ` — ${term}` : ''}.`),
      h('p', { class: 'qw-tip' }, e.baseline
        ? 'سيحل هذا الملف محل «الأحدث» ويُقارَن بنسخة بداية الفصل المحفوظة. لا تُحفظ أي بيانات شخصية.'
        : 'هذا أول رفع في الفصل؛ سيُحفظ «بداية الفصل» للمقارنة لاحقاً، وكل رفع بعده يحدّث «الأحدث» فقط.'),
      e.baseline && h('label', { class: 'row' }, asBase, ' اعتبره أيضاً «بداية الفصل» (يستبدل نسخة المقارنة)')],
    async () => {
      const r = await api(`/cycles/${cycle.id}/enrollment`, { method: 'POST', body: { term_label: term || null, file_name: f.name,
        as_baseline: asBase.checked, rows: rows.map(({ term: _t, ...x }) => x) } });
      toast(`رُفع ST06: ${num(r.trainees)} متدرب${r.baseline ? ' (حُفظ كبداية الفصل)' : ''}`);
      if (r.unmatched.length) setTimeout(() => addDeptsDialog(r.unmatched, reload), 300); else reload();
    }, 'رفع');
    inp.value = '';
  } });
  document.body.append(inp);
  inp.click();
}

function addDeptsDialog(names, reload) {
  const checks = names.map(() => h('input', { type: 'checkbox', checked: true }));
  dialog('أقسام في ST06 غير موجودة في المنصة', [
    h('p', { class: 'qw-tip' }, 'هذه الأقسام وردت في تقرير رايات ولا يقابلها قسم في المنصة. أضِفها لتظهر أعدادها وتُربط بمدربيها.'),
    h('ul', { class: 'rank' }, names.map((n, i) => h('li', null, h('label', { class: 'row' }, checks[i], ` ${n}`))))],
  async () => {
    for (const [i, n] of names.entries()) {
      if (!checks[i].checked) continue;
      const r = await api('/attendance/departments', { method: 'POST', body: { name_ar: n } });
      if (!r.existing) state.departments.push({ id: r.id, name_ar: r.name_ar });
    }
    toast('أُضيفت الأقسام؛ اربط مدربيها من «ربط المدربين بالأقسام»');
  }, 'إضافة المحدد');
  document.getElementById('dialog').addEventListener('close', reload, { once: true });
}

function enrollmentSection(e, d, cycle, reload) {
  const head = h('header', null, h('h2', null, 'المتدربون المستمرون والبرامج (ST06)'),
    e.latest && h('span', { class: 'faint' }, `${e.latest.term_label ?? ''} · آخر رفع ${date(e.latest.uploaded_at)}`));
  if (!e.latest) {
    return h('section', { class: 'panel' }, head, h('p', { class: 'muted' }, e.can_edit
      ? 'ارفع تقرير ST06 من رايات (CSV) مرة في بداية الفصل، ثم كلما تحدّث. يُستخدم مصدراً لعدد متدربي كل قسم ولنسبة المتدربين لكل مدرب والاستمرار خلال الفصل.'
      : 'تظهر هنا أعداد المتدربين المستمرين لكل برنامج بعد أن ترفع وكالة الجودة تقرير ST06.'));
  }
  if (!e.by_department?.length) {
    return h('section', { class: 'panel' }, head, h('p', { class: 'muted' }, 'لا توجد برامج لهذا القسم في تقرير ST06 (مثل قسم الدراسات العامة).'));
  }
  const kpi = (label, value, cls, sub) => h('div', { class: `tr-kpi ${cls ?? ''}` }, h('small', null, label), h('b', null, value), sub && h('span', null, sub));
  const change = e.total - e.baseline_total;
  const coursesPer = d?.college && e.total ? d.college.registered / e.total : null;
  const shifts = Object.entries(e.by_shift).map(([k, v]) => `${k} ${num(v)}`).join(' · ');
  const kpis = h('section', { class: 'tr-kpis' },
    kpi('المتدربون المستمرون', num(e.total), 'att', shifts),
    kpi('البرامج', num(e.programs), '', `في ${num(e.departments)} أقسام`),
    !e.same_snapshot && kpi('التغير منذ بداية الفصل', `${change > 0 ? '+' : ''}${num(change)}`, change < 0 ? 'bad' : '',
      `الاستمرار ${P(e.baseline_total ? e.total / e.baseline_total : null)}`),
    coursesPer && kpi('متوسط المقررات لكل متدرب', coursesPer.toFixed(1), '', 'تسجيلات SO09 ÷ متدربو ST06'));
  const diff = e.by_department.filter(x => x.department_id && x.platform_count !== x.trainees);
  const tools = e.can_edit && h('div', { class: 'tr-thr' },
    h('button', { class: 'btn small', onclick: () => uploadST06(cycle, e, reload) }, 'تحديث ST06'),
    diff.length > 0 && h('button', { class: 'btn primary small', onclick: async () => {
      const r = await api(`/cycles/${cycle.id}/enrollment/apply-counts`, { method: 'POST' });
      toast(`اعتُمد عدد المتدربين من ST06 لـ: ${r.updated.join('، ')}`); reload();
    } }, `اعتماد أعداد المتدربين في المنصة (${num(diff.length)} قسم مختلف)`),
    e.unmatched.length > 0 && h('button', { class: 'btn small', onclick: () => addDeptsDialog(e.unmatched, reload) },
      `${num(e.unmatched.length)} قسم غير موجود في المنصة`));
  const table = h('div', { class: 'matrix-wrap' }, h('table', { class: 'data' },
    h('thead', null, h('tr', null, ['القسم', 'البرامج', 'المتدربون', !e.same_snapshot && 'بداية الفصل', !e.same_snapshot && 'التغير', 'المدربون (SO09)', 'متدرب لكل مدرب', 'المسجل في المنصة']
      .filter(Boolean).map(t => h('th', null, t)))),
    h('tbody', null, e.by_department.map(x => h('tr', null,
      h('td', null, x.name, !x.department_id && h('small', { class: 'chip c-mid' }, 'غير موجود')),
      h('td', null, x.programs.map(p => p.program.replace(/\s*-\s*تطبيقي$/, '').replace(/-تطبيقي$/, '') + (p.shift && p.shift !== 'صباحي' ? ` (${p.shift})` : '')).join('، ')),
      h('td', null, h('b', null, num(x.trainees))),
      !e.same_snapshot && h('td', null, num(x.baseline)),
      !e.same_snapshot && h('td', { class: x.trainees < x.baseline ? 'tr-bad' : '' }, `${x.trainees - x.baseline > 0 ? '+' : ''}${num(x.trainees - x.baseline)}`),
      h('td', null, x.trainers ? num(x.trainers) : '—'), h('td', null, x.per_trainer ?? '—'),
      h('td', { class: x.department_id && x.platform_count != null && x.platform_count !== x.trainees ? 'tr-bad' : 'faint' }, x.platform_count == null ? '—' : num(x.platform_count)))))));
  return h('section', { class: 'panel tr-enr' }, head, kpis, tools,
    table, h('h3', null, 'المتدربون حسب البرنامج'), h('div', { class: 'tr-prog' }, programBars(e.by_department)),
    h('p', { class: 'qw-tip' }, '«المسجلون» في SO09 عدد تسجيلات المقررات (المتدرب يُحسب في كل مقرر)، أما ST06 فعدد المتدربين الفعلي — لذلك هو مصدر عدد المتدربين في المنصة. '
      + 'قسم الدراسات العامة لا برامج له فلا يظهر هنا.'));
}

// ------------------------------------------------------------------ الصفحة
export async function renderTraining() {
  const cycle = state.cycle;
  const { params } = parseRoute();
  const [d, e] = await Promise.all([api(`/cycles/${cycle.id}/attendance${params.w ? `?week=${params.w}` : ''}`), api(`/cycles/${cycle.id}/enrollment`)]);
  const reload = () => go('training', { w: d.week?.week_no ?? '', t: Date.now() });
  let tAtt = getT('att', 0.9), tRec = getT('rec', 1);

  const hero = h('header', { class: 'scope-hero' },
    h('div', null, h('h1', null, 'سير العملية التدريبية'),
      h('p', null, 'تقرير التحضير الأسبوعي SO09 وتقرير المتدربين المستمرين ST06 من رايات يُقرآن داخل المتصفح ويتحولان إلى مؤشرات حضور ورصد تحضير '
        + 'وأعداد متدربين لكل قسم وبرنامج، ورسوم تفاعلية، وتقرير تنفيذي جاهز للطباعة، ويُعبّأ منهما تقرير 4-3-1 للأقسام.'),
      d.can_edit && h('div', { class: 'row cal-actions' },
        h('button', { class: 'btn gold', onclick: () => uploadFlow(cycle, reload) }, 'رفع تقرير SO09 (CSV)'),
        h('button', { class: 'btn ghost', onclick: () => uploadST06(cycle, e, reload) }, e.latest ? 'تحديث ST06' : 'رفع تقرير ST06 (CSV)'),
        d.trainers_total > 0 && h('button', { class: 'btn ghost', onclick: () => mapDialog(reload) },
          `ربط المدربين بالأقسام${d.trainers_unconfirmed ? ` (${num(d.trainers_unconfirmed)} بحاجة لتأكيد)` : ''}`))),
    d.uploads.length > 0 && h('div', { class: 'scope-pick' },
      h('label', null, 'الأسبوع ', h('select', { onchange: e => go('training', { w: e.target.value }) },
        d.uploads.map(u => h('option', { value: u.week_no, selected: u.week_no === d.week?.week_no }, `الأسبوع ${u.week_no}${u.period_from ? ` (${date(u.period_from)})` : ''}`))))));

  if (!d.week) {
    return h('div', { class: 'cal-page' }, hero, h('section', { class: 'card empty' }, h('h2', null, 'لم يُرفع تقرير تحضير بعد'),
      h('p', null, d.can_edit ? 'صدّر تقرير SO09 من رايات بصيغة CSV ثم اضغط «رفع تقرير SO09». يُقرأ الملف على جهازك ولا يُحفظ منه إلا الإحصاءات.'
        : 'تظهر هنا مؤشرات سير العملية التدريبية بعد أن ترفع وكالة الجودة تقرير التحضير الأسبوعي.')),
      enrollmentSection(e, null, cycle, reload));
  }
  const c = d.college;
  const banner = d.trainers_unconfirmed > 0 && d.can_edit && h('div', { class: 'qw-patt off' },
    h('div', null, h('b', null, `${num(d.trainers_unconfirmed)} مدرب بربط قسم مقترح غير مؤكد`),
      h('span', null, ' — مؤشرات الأقسام تعتمد على هذا الربط؛ أكّده مرة واحدة ويُحفظ للأسابيع القادمة.')),
    h('button', { class: 'btn small', onclick: () => mapDialog(reload) }, 'مراجعة الربط'));
  const kpi = (label, value, cls, sub) => h('div', { class: `tr-kpi ${cls ?? ''}` }, h('small', null, label), h('b', null, value), sub && h('span', null, sub));
  const kpis = h('section', { class: 'tr-kpis' },
    kpi('نسبة الحضور الفعلية', P(c.attendance), c.attendance < tAtt ? 'bad' : 'att', `المستهدف ${P(tAtt)}`),
    kpi('نسبة رصد التحضير', P(c.recording), c.recording < tRec ? 'warn' : 'rec', `${num(c.incomplete)} شعبة رصدها ناقص`),
    kpi('الشعب', num(c.sections), '', `${num(c.trainers)} مدرب`),
    kpi('المتدربون المسجلون', num(c.registered), '', `من ${num(c.total)} في الشعب`),
    kpi('المحرومون', num(c.deprived), c.deprived ? 'bad' : ''),
    kpi('المنسحبون', num(c.withdrawn)),
    kpi('لم يُرصد إطلاقاً', num(c.not_recorded), c.not_recorded ? 'bad' : '', 'شعبة'));

  const thr = h('div', { class: 'tr-thr' }, 'المستهدف: الحضور ',
    h('input', { type: 'number', min: 50, max: 100, value: Math.round(tAtt * 100), onchange: e => { setT('att', e.target.value / 100); reload(); } }), '٪ · رصد التحضير ',
    h('input', { type: 'number', min: 50, max: 100, value: Math.round(tRec * 100), onchange: e => { setT('rec', e.target.value / 100); reload(); } }), '٪',
    h('button', { class: 'btn primary small', onclick: () => printReport(d, tAtt, tRec, e) }, 'التقرير التنفيذي (طباعة / PDF)'),
    d.can_edit && h('button', { class: 'btn small', onclick: async () => {
      try {
        const r = await api(`/cycles/${cycle.id}/attendance/${d.week.week_no}/fill-431`, { method: 'POST' });
        toast(`عُبّئ صف الأسبوع في نموذج 4-3-1 لـ: ${r.filled.join('، ') || '—'}${r.skipped.length ? ` (تُخطّي المرفوع: ${r.skipped.join('، ')})` : ''}`);
      } catch (ex) { toast(ex.message, 'error'); }
    } }, 'تعبئة 4-3-1 للأقسام'));

  const legend = h('div', { class: 'legend tr-legend' }, h('span', null, h('i', { class: 'cell', style: { background: ATT } }), 'الحضور'),
    h('span', null, h('i', { class: 'cell', style: { background: REC } }), 'رصد التحضير'),
    h('span', null, h('i', { class: 'cell', style: { background: BAD, height: '3px' } }), `المستهدف ${P(tAtt)}`));
  const charts = h('div', { class: 'cols2 tr-charts' },
    h('section', { class: 'panel' }, h('header', null, h('h2', null, 'الحضور ورصد التحضير حسب القسم')), legend,
      groupedBars(d.by_department, tAtt)),
    h('section', { class: 'panel' }, h('header', null, h('h2', null, d.trend.length > 1 ? 'اتجاه الأسابيع' : 'توزيع الشعب حسب نسبة الرصد')),
      d.trend.length > 1 ? [legend.cloneNode(true), trendLine(d.trend)] : columns(Object.entries(d.recording_buckets))));

  const deptTable = h('section', { class: 'panel' }, h('header', null, h('h2', null, 'الأقسام')),
    h('div', { class: 'matrix-wrap' }, h('table', { class: 'data' },
      h('thead', null, h('tr', null, ['القسم', 'الشعب', 'المدربون', 'المسجلون', 'الحضور', 'رصد التحضير', 'رصد ناقص', 'المحرومون', 'المنسحبون'].map(t => h('th', null, t)))),
      h('tbody', null, d.by_department.map(x => h('tr', null, h('td', null, x.name), h('td', null, num(x.sections)), h('td', null, num(x.trainers)),
        h('td', null, num(x.registered)), h('td', { class: x.attendance < tAtt ? 'tr-bad' : '' }, P(x.attendance)),
        h('td', { class: x.recording < tRec ? 'tr-bad' : '' }, P(x.recording)), h('td', null, num(x.incomplete)),
        h('td', null, num(x.deprived)), h('td', null, num(x.withdrawn))))))));

  const types = h('section', { class: 'panel' }, h('header', null, h('h2', null, 'حسب نوع الجدولة')),
    h('ul', { class: 'rank' }, d.by_type.map(t => h('li', null, h('span', null, t.type, h('small', { class: 'faint' }, ` · ${num(t.sections)} شعبة`)),
      h('strong', null, P(t.attendance))))));
  const low = h('section', { class: 'panel' }, h('header', null, h('h2', null, 'أدنى المقررات حضوراً')),
    d.low_courses.length ? h('ul', { class: 'rank' }, d.low_courses.slice(0, 8).map(x => h('li', null,
      h('span', null, x.course.trim(), h('small', { class: 'faint' }, ` · ${num(x.sections)} شعبة`)), h('strong', { style: { color: x.attendance < tAtt ? BAD : '' } }, P(x.attendance)))))
      : h('p', { class: 'muted' }, 'لا توجد بيانات كافية.'));

  const fuRows = d.follow_up;
  const follow = h('section', { class: 'panel' },
    h('header', null, h('h2', null, `شعب تحتاج متابعة رصد التحضير (${num(d.follow_up_total)})`), h('span', { class: 'faint' }, 'مرتبة من الأقل رصداً')),
    fuRows.length ? h('div', { class: 'matrix-wrap tr-follow' }, h('table', { class: 'data' },
      h('thead', null, h('tr', null, ['القسم', 'المدرب', 'المقرر', 'الشعبة', 'النوع', 'المسجلون', 'الرصد', 'الحضور'].map(t => h('th', null, t)))),
      h('tbody', null, fuRows.map(x => h('tr', null, h('td', null, x.department), h('td', null, x.trainer), h('td', null, (x.course ?? '').trim()),
        h('td', null, x.section), h('td', null, x.type), h('td', null, num(x.registered)),
        h('td', { class: 'tr-bad' }, P(x.recording / 100)), h('td', null, P(x.attendance)))))))
      : h('p', { class: 'muted' }, 'اكتمل رصد التحضير في جميع الشعب.'));

  return h('div', { class: 'cal-page' }, hero, banner, kpis, thr, charts, deptTable, enrollmentSection(e, d, cycle, reload),
    h('div', { class: 'cols2' }, types, low), follow);
}
