// مجلدات الشواهد وسياسة الإرفاق (روابط OneDrive/SharePoint أو ملفات) — مشتركة بين الصفحات
import { api } from './api.js';
import { h } from './ui.js';

const cache = new Map();

export async function evidenceContext(cycleId, deptId) {
  const key = `${cycleId}:${deptId}`;
  if (!cache.has(key)) {
    cache.set(key, Promise.all([
      api('/settings/evidence').catch(() => ({ attachment_mode: 'both', allowed_link_domains: [] })),
      deptId == null ? [] : api(`/cycles/${cycleId}/folders?department_id=${deptId}`).catch(() => []),
    ]).then(([settings, folders]) => ({ settings, folders })));
  }
  return cache.get(key);
}
export const clearEvidenceContext = () => cache.clear();

// المجلد الأخص للمتطلب: المعيار الفرعي ← المعيار ← المجلد العام للقسم
export function folderFor(ctx, reqCode) {
  const parts = String(reqCode || '').split('-');
  const sub = parts.slice(0, 2).join('-'), std = parts[0];
  return ctx.folders.find(f => f.sub_standard_code === sub)
    ?? ctx.folders.find(f => f.standard_code === std && !f.sub_standard_code)
    ?? ctx.folders.find(f => !f.standard_code && !f.sub_standard_code) ?? null;
}

export function folderButton(ctx, reqCode) {
  const f = folderFor(ctx, reqCode);
  if (!f) return null;
  const scope = f.sub_standard_code ? `المعيار الفرعي ${f.sub_standard_code}` : f.standard_code ? `المعيار ${f.standard_code}` : 'القسم';
  return h('a', { class: 'btn folder-btn', href: f.url, target: '_blank', rel: 'noopener', title: `مجلد شواهد ${scope}` },
    '📁 فتح مجلد الشواهد');
}

export function modeHint(ctx) {
  const m = ctx.settings.attachment_mode;
  if (m === 'links') return 'ارفع الملف في مجلد الشواهد على OneDrive/SharePoint، ثم انسخ رابطه والصقه هنا.';
  if (m === 'files') return 'إعدادات المنشأة: رفع الملفات فقط.';
  return 'أرفق ملفاً، أو ارفعه في مجلد الشواهد والصق رابطه.';
}

export const LINK_STATUS = {
  ok: ['يفتح', 's-final'], restricted: ['يتطلب دخول المؤسسة', 's-submitted'],
  broken: ['رابط معطل', 'a-revision'], unreachable: ['تعذّر الوصول', 'a-revision'],
};
export function linkBadge(status) {
  if (!status || status === 'ok' || status === 'restricted') return null;
  const [label, cls] = LINK_STATUS[status];
  return h('span', { class: `status ${cls}`, title: 'نتيجة آخر فحص للروابط' }, label);
}
