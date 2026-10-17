// حاسبة صيغ النماذج — نسخة مطابقة لـ app/forms_engine.py (اختبار التطابق في tests/test_forms.py)
const DONE = 'مُنفذ', PARTIAL = 'مُنفذ جزئي', NOT_DONE = 'لم يُنفذ';
const AR_DIGITS = '٠١٢٣٤٥٦٧٨٩';

export function num(v) {
  if (v == null || v === '' || typeof v === 'boolean') return null;
  if (typeof v === 'number') return Number.isFinite(v) ? v : null;
  const s = String(v).trim().replace(/٫/g, '.').replace(/,/g, '').replace(/[٠-٩]/g, d => String(AR_DIGITS.indexOf(d)));
  if (s === '' || !/^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$/.test(s)) return null;
  const f = Number(s);
  return Number.isFinite(f) ? f : null;
}
export const isEmpty = v => v == null || (typeof v === 'string' && !v.trim());
export const tablePhase = s => (s.phase === 'follow' ? 'follow' : 'mixed');

export function mergedRows(section, plan, follow) {
  const k = section.key;
  if (tablePhase(section) === 'follow') return (follow[k] || []).map(r => ({ ...r }));
  const fixed = Object.fromEntries((section.fixed_rows || []).map(fr => [fr.id, fr]));
  const fmap = follow[k] || {};
  return (plan[k] || []).map(r => ({ ...(fixed[r.id] || {}), ...r, ...(fmap[r.id] || {}) }));
}

const roundHalfUp = x => (x >= 0 ? Math.floor(x + 0.5) : -Math.floor(-x + 0.5));
const sum = a => a.reduce((s, x) => s + x, 0);

export function evalRow(e, row) {
  switch (e.op) {
    case 'ratio': { const a = num(row[e.a]), b = num(row[e.b]); return a == null || !b ? null : a / b; }
    case 'sumratio': {
      const nums = e.num.map(x => num(row[x])), dens = e.den.map(x => num(row[x]));
      if (nums.every(n => n == null)) return null;
      const d = sum(dens.filter(x => x != null));
      return !d ? null : sum(nums.filter(x => x != null)) / d;
    }
    case 'mul': { const v = e.of.map(x => num(e.map ? e.map[row[x]] : row[x])); return v.some(x => x == null) ? null : v.reduce((a, b) => a * b, 1); }
    case 'add': { const v = e.of.map(x => num(row[x])).filter(x => x != null); return v.length ? sum(v) : null; }
    case 'sub': { const a = num(row[e.a]), b = num(row[e.b]); return a == null || b == null ? null : a - b; }
    case 'avg': { const v = e.of.map(x => num(row[x])).filter(x => x != null); return v.length ? sum(v) / v.length : null; }
    case 'band': {
      let v = num(row[e.of]);
      if (v == null) return null;
      if (e.trunc) v = Math.trunc(v);
      for (const [lo, hi, label] of e.bands) if (v >= lo && (hi == null || v < hi)) return label;
      return null;
    }
    case 'map': return e.map[row[e.of]] ?? null;
    default: throw new Error(`صيغة غير معروفة: ${e.op}`);
  }
}

const match = (row, cond) => Object.entries(cond).every(([k, v]) => (Array.isArray(v) ? v.includes(row[k]) : row[k] === v));

export function evalSummary(e, rows, tables = {}) {
  switch (e.op) {
    case 'count_filled_any': return rows.filter(r => e.cols.some(c => !isEmpty(r[c]))).length;
    case 'ratio_filled': {
      const den = rows.filter(r => e.den.some(c => !isEmpty(r[c])));
      return !den.length ? null : den.filter(r => !isEmpty(r[e.num])).length / den.length;
    }
    case 'avg_cells': {
      const v = rows.flatMap(r => e.cols.map(c => num(r[c]))).filter(x => x != null);
      return !v.length ? null : (sum(v) / v.length) * (e.scale ?? 1);
    }
    case 'band_of': {
      const v = evalSummary(e.of, rows, tables);
      if (v == null) return null;
      for (const [lo, hi, label] of e.bands) if (v >= lo && (hi == null || v < hi)) return label;
      return null;
    }
    case 'count_match': return rows.filter(r => match(r, e.match)).length;
    case 'ratio_match': {
      const den = rows.filter(r => match(r, e.den)).length;
      return !den ? null : rows.filter(r => match(r, e.num)).length / den;
    }
    case 'per_lookup': case 'per_sum': {
      const n = rows.filter(r => match(r, e.match)).length;
      const other = tables[e.table] || [];
      let d;
      if (e.op === 'per_sum') d = sum(other.map(r => num(r[e.col])).filter(x => x != null));
      else { const hit = other.find(r => trimKey(r[e.key] || '') === e._group); d = hit ? num(hit[e.col]) : null; }
      return !d ? null : n / d;
    }
    case 'status_pct': {
      const c = s => rows.filter(r => r[e.col] === s).length;
      const done = c(DONE), part = c(PARTIAL), nd = c(NOT_DONE);
      const den = e.denominator === 'rows' ? rows.length : done + part + nd;
      return !den ? null : (done + 0.5 * part) / den;
    }
    case 'sum': { const v = rows.map(r => num(r[e.col])).filter(x => x != null); return v.length ? sum(v) : null; }
    case 'ratio_sums': {
      const n = rows.map(r => num(r[e.num])).filter(x => x != null);
      const d = sum(rows.map(r => num(r[e.den])).filter(x => x != null));
      return !n.length || !d ? null : sum(n) / d;
    }
    case 'avg': { const v = rows.map(r => num(r[e.col])).filter(x => x != null); return v.length ? sum(v) / v.length : null; }
    case 'count': return rows.length;
    case 'count_eq': return rows.filter(r => r[e.col] === e.eq).length;
    case 'share_eq': {
      let cells = rows.flatMap(r => e.cols.map(c => r[c]));
      if (e.denominator === 'filled') cells = cells.filter(v => !isEmpty(v));
      return !cells.length ? null : cells.filter(v => v === e.eq).length / cells.length;
    }
    case 'share_nonempty': return !rows.length ? null : rows.filter(r => !isEmpty(r[e.col])).length / rows.length;
    case 'avg_where': {
      const sel = rows.filter(r => e.in.includes(r[e.where]));
      return !sel.length ? null : sum(sel.map(r => num(r[e.col]) ?? 0)) / sel.length;
    }
    default: throw new Error(`صيغة غير معروفة: ${e.op}`);
  }
}

const trimKey = v => (typeof v === 'string' ? v.trim() : v);

function pivot(section, tables) {
  const src = tables[section.source] || [];
  const order = [], groups = new Map();
  for (const r of src) {
    const g = typeof r[section.group_by] === 'string' ? r[section.group_by].trim() : r[section.group_by];
    if (isEmpty(g)) continue;
    if (!groups.has(g)) { order.push(g); groups.set(g, []); }
    groups.get(g).push(r);
  }
  return order.map(g => {
    const rows = groups.get(g);
    const values = {};
    for (const c of section.columns) {
      const e = c.expr;
      if (c.requires && rows.every(r => isEmpty(r[c.requires]))) values[c.key] = null;
      else if (e.op === 'per_ratio') {
        const other = (tables[e.table] || []).find(r => trimKey(r[e.key] || '') === g);
        const n = other ? num(other[e.col]) : null;
        values[c.key] = n == null ? null : `1 : ${roundHalfUp(n / rows.length)}`;
      } else values[c.key] = evalSummary(e.op === 'per_lookup' ? { ...e, _group: g } : e, rows, tables);
    }
    return { group: g, count: rows.length, values };
  });
}

export function compute(schema, plan, follow) {
  const tables = {}, summaries = {};
  for (const s of schema.sections) {
    if (s.type !== 'table') continue;
    const rows = mergedRows(s, plan, follow);
    for (const r of rows) for (const c of s.columns) if (c.type === 'computed') r[c.key] = evalRow(c.expr, r);
    tables[s.key] = rows;
  }
  for (const s of schema.sections) {
    if (s.type === 'table' && s.summary) summaries[s.key] = Object.fromEntries(s.summary.map(m => [m.key, evalSummary(m.expr, tables[s.key], tables)]));
  }
  const pivots = Object.fromEntries(schema.sections.filter(s => s.type === 'pivot').map(s => [s.key, pivot(s, tables)]));
  const prog = schema.progress;
  return {
    tables, summaries, pivots,
    progress: prog ? (summaries[prog.section]?.[prog.summary] ?? null) : null,
    improvement_pct: summaries.improvements?.improvement_pct ?? null,
    rows: Object.entries(tables).filter(([k]) => k !== 'improvements').reduce((s, [, v]) => s + v.length, 0),
    improvements: (tables.improvements || []).length,
  };
}

export function fmt(v, f) {
  if (v == null || v === '') return '—';
  if (f === 'pct' && typeof v === 'number') return `${(v * 100).toFixed(1).replace(/\.0$/, '')}%`;
  if (typeof v === 'number' && !Number.isInteger(v)) return String(Number(v.toFixed(2)));
  return String(v);
}
