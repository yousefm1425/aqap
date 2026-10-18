// مكتبة الأدلة: الأدلة الرسمية والإجرائية ودليل استخدام المنصة
import { api } from './api.js';
import { go } from './app.js';
import { date, h, num, toast } from './ui.js';

const BUILTIN = [{ id: 'aqap-guide', title_ar: 'دليل استخدام منصة الجودة والاعتماد', category: 'أدلة المنصة',
  description_ar: 'الدليل الشامل لمنسق القسم ورئيس القسم ووكيل الجودة: التقديرات والشواهد، النماذج، أعمال الجودة، خطط التحسين، التقارير والتصدير.',
  url: 'docs/aqap-user-guide.pdf', builtin: true }, { id: 'tvtc-l2', title_ar: 'نظام جودة التدريب في المنشآت التدريبية — المستوى الثاني', category: 'الأدلة الرسمية',
  description_ar: 'الإدارة العامة لجودة التدريب · المؤسسة العامة للتدريب التقني والمهني · سبتمبر 2024',
  url: 'docs/tvtc-training-quality-system-level2-2024.pdf', builtin: true }];
const CATS = ['الأدلة الرسمية', 'دليل إجرائي', 'دليل استخدام المنصة', 'نماذج', 'لوائح وتعليمات'];

export async function renderGuides() {
  const data = await api('/guides');
  const items = [...BUILTIN, ...data.guides];
  const reload = () => go('guides', { t: Date.now() });
  const groups = new Map();
  for (const g of items) { if (!groups.has(g.category)) groups.set(g.category, []); groups.get(g.category).push(g); }
  const isPdf = u => /\.pdf($|\?)/i.test(u);

  const card = g => h('article', { class: 'guide-card' },
    h('span', { class: `guide-ic${isPdf(g.url) ? ' pdf' : ''}` }, isPdf(g.url) ? 'PDF' : '📘'),
    h('div', { class: 'guide-body' }, h('h3', null, g.title_ar), g.description_ar && h('p', { class: 'muted' }, g.description_ar),
      !g.builtin && h('p', { class: 'faint' }, `أضافه ${g.created_by_name ?? ''} · ${date(g.created_at)}`)),
    h('div', { class: 'row' },
      h('a', { class: 'btn small primary', href: g.url, target: '_blank', rel: 'noopener' }, 'فتح'),
      data.can_edit && !g.builtin && h('button', { class: 'btn small danger', onclick: async () => {
        try { await api(`/guides/${g.id}`, { method: 'DELETE' }); toast('حُذف الدليل'); reload(); } catch (ex) { toast(ex.message, 'error'); }
      } }, 'حذف')));

  let form = null;
  if (data.can_edit) {
    const title = h('input', { type: 'text', placeholder: 'عنوان الدليل' });
    const cat = h('input', { type: 'text', list: 'guide-cats', placeholder: 'التصنيف', value: 'دليل إجرائي' });
    const url = h('input', { type: 'text', dir: 'ltr', placeholder: 'https://… (رابط OneDrive/SharePoint أو موقع المؤسسة)' });
    const desc = h('input', { type: 'text', placeholder: 'وصف مختصر (اختياري)' });
    form = h('section', { class: 'panel' }, h('header', null, h('h2', null, 'إضافة دليل')),
      h('datalist', { id: 'guide-cats' }, CATS.map(c => h('option', { value: c }))),
      h('div', { class: 'guide-form' }, title, cat, url, desc,
        h('button', { class: 'btn primary', onclick: async () => {
          try {
            await api('/guides', { method: 'POST', body: { title_ar: title.value.trim(), category: cat.value.trim() || 'دليل إجرائي',
              url: url.value.trim(), description_ar: desc.value.trim() || null } });
            toast('أُضيف الدليل'); reload();
          } catch (ex) { toast(ex.message, 'error'); }
        } }, 'إضافة')));
  }

  return h('div', { class: 'scope-page' },
    h('header', { class: 'scope-hero' },
      h('div', null, h('h1', null, 'مكتبة الأدلة'),
        h('p', null, 'الأدلة الرسمية لنظام جودة التدريب، والأدلة الإجرائية والنماذج، ودليل استخدام المنصة — مرجع واحد لكل منسوبي الأقسام.')),
      h('div', { class: 'scope-stats' }, h('span', null, h('b', null, num(items.length)), ' دليل'),
        h('span', null, h('b', null, num(groups.size)), ' تصنيف'))),
    form,
    [...groups].map(([c, gs]) => h('section', { class: 'panel' }, h('header', null, h('h2', null, c)),
      h('div', { class: 'guide-grid' }, gs.map(card)))));
}
