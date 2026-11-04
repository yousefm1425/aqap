// استقبال نتائج «منصة الإرشاد الأكاديمي» في نماذج الخطط والتقارير (مثل تقرير الجداول 1-3-4).
// المنصتان مستقلتان: النتائج تنتقل عبر متصفح المستخدم نفسه (رابط أو نص منسوخ)، ولا تُحفظ إلا بعد مراجعته والضغط على «حفظ».

const isBlank = v => v == null || String(v).trim() === '';
const norm = s => String(s ?? '').normalize('NFKC').replace(/[ً-ْـ]/g, '')
  .replace(/[أإآ]/g, 'ا').replace(/ة/g, 'ه').replace(/ى/g, 'ي').replace(/^ال|\sال/g, ' ').replace(/\s+/g, ' ').trim();

/** يفك حزمة منصة الإرشاد من معامل الرابط (base64url) أو من نص JSON ملصوق. يعيد null إن لم تكن حزمة منها. */
export function decodeIrshad(raw) {
  let text = String(raw ?? '').trim();
  if (!text) return null;
  if (!text.startsWith('{')) {
    const b64 = text.replace(/-/g, '+').replace(/_/g, '/');
    const bin = atob(b64 + '='.repeat((4 - (b64.length % 4)) % 4));
    text = new TextDecoder().decode(Uint8Array.from(bin, c => c.charCodeAt(0)));
  }
  const pkg = JSON.parse(text);
  if (!pkg || pkg.app !== 'irshad' || !pkg.req || typeof pkg.sections !== 'object') return null;
  return pkg;
}

/** يطابق اسم القسم في منصة الإرشاد مع أقسام منصة الجودة (بتجاهل «ال» والهمزات والتشكيل). */
export function matchDept(name, departments) {
  const n = norm(name);
  if (!n) return null;
  return departments.find(d => norm(d.name_ar) === n)
    ?? departments.find(d => norm(d.name_ar).includes(n) || n.includes(norm(d.name_ar))) ?? null;
}

/**
 * يعبّئ بيانات النموذج من الحزمة في الحقول القابلة للتعديل فقط، ويعيد عدد القيم التي عُبّئت.
 * الجداول ذات الصفوف الثابتة تُطابق بمعرّف الصف أو بقيمة عمودها الثابت (مثل «نوع الشعبة»).
 */
export function applyIrshad(schema, plan, follow, pkg, can) {
  let n = 0;
  const allowed = c => !c.fixed && c.type !== 'computed' && (c.phase === 'follow' ? can.follow : can.plan);
  const put = (store, c, v) => { if (v === undefined || v === null || v === '' || !allowed(c)) return; store[c.key] = typeof v === 'number' ? String(v) : v; n++; };
  for (const s of schema.sections) {
    const data = pkg.sections[s.key];
    if (data == null) continue;
    if (s.type === 'fields') {
      for (const c of s.fields) {
        let v = data[c.key];
        if (c.type === 'select' && v != null && !c.options.includes(v)) v = c.options.find(o => norm(o) === norm(v));
        put(c.phase === 'follow' ? (follow[s.key] ??= {}) : (plan[s.key] ??= {}), c, v);
      }
    } else if (s.type === 'table' && s.phase === 'follow' && Array.isArray(data) && can.follow) {
      // جداول حرة (مثل التوصيات وخطط التحسين): تُضاف الصفوف الجديدة فقط، ولا يُمس ما أدخله القسم
      const keyCol = s.columns.find(c => c.required) ?? s.columns[0];
      const rows = (follow[s.key] ??= []);
      for (const o of data) {
        if (isBlank(o[keyCol.key]) || rows.some(r => norm(r[keyCol.key]) === norm(o[keyCol.key]))) continue;
        if (rows.length >= (s.max_rows ?? 100)) break;
        const r = { id: Math.random().toString(36).slice(2, 10) };
        for (const c of s.columns) {
          let v = o[c.key];
          if (c.type === 'select' && v != null && !c.options.includes(v)) v = c.options.find(x => norm(x) === norm(v));
          put(r, c, v);
        }
        rows.push(r);
      }
    } else if (s.type === 'table' && s.fixed_rows && Array.isArray(data)) {
      const fixedCols = s.columns.filter(c => c.fixed);
      for (const o of data) {
        const fr = s.fixed_rows.find(f => f.id === o.id)
          ?? s.fixed_rows.find(f => fixedCols.length && fixedCols.every(c => norm(f[c.key]) === norm(o[c.key])));
        if (!fr) continue;
        const pr = (plan[s.key] ??= []).find(x => x.id === fr.id) ?? (plan[s.key].push({ id: fr.id }), plan[s.key].at(-1));
        for (const c of s.columns) {
          let v = o[c.key];
          if (c.type === 'select' && v != null && !c.options.includes(v)) v = c.options.find(x => norm(x) === norm(v));
          if (c.phase === 'follow') { follow[s.key] ??= {}; follow[s.key][fr.id] ??= {}; put(follow[s.key][fr.id], c, v); }
          else put(pr, c, v);
        }
      }
    }
  }
  return n;
}
