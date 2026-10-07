export const RATING = { met: 'متحقق', partial: 'متحقق جزئي', not_met: 'غير متحقق', na: 'لا ينطبق' };
export const RATING_ORDER = ['met', 'partial', 'not_met', 'na'];
export const RATING_COLOR = { met: 'var(--met)', partial: 'var(--partial)', not_met: 'var(--not-met)', na: 'var(--na)' };
// حكم المقيّم الخارجي على صحة التقييم الذاتي (النموذج الرسمي)
export const VERDICT = { conforms: 'منطبق', not_conforming: 'غير منطبق', insufficient: 'غير كافٍ' };
export const VERDICT_COLOR = { conforms: 'var(--met)', not_conforming: 'var(--not-met)', insufficient: 'var(--partial)' };
export const ADEQUACY = { suitable: 'مناسب', unsuitable: 'غير مناسب', insufficient: 'غير كافٍ' };

export const STATUS = {
  draft: 'مسودة', submitted: 'مرفوع', returned: 'معاد للتعديل', hod_approved: 'معتمد من القسم',
  under_audit: 'قيد التدقيق', audited: 'مُدقَّق', final: 'نهائي',
};
export const CYCLE_STATUS = {
  planning: 'قيد التخطيط', open: 'مفتوحة', external_review: 'مراجعة خارجية', closed: 'مغلقة', archived: 'مؤرشفة',
};
export const ROLE = {
  system_admin: 'مدير النظام', quality_dean: 'وكيل الجودة', quality_auditor: 'مدقق الجودة', hod: 'رئيس القسم',
  dept_coordinator: 'منسق الجودة بالقسم', faculty: 'عضو هيئة التدريب', external_reviewer: 'مقيّم خارجي',
};

// انعكاس لجدول workflow_rule — للعرض فقط؛ قاعدة البيانات هي المرجع النهائي
export const TRANSITIONS = [
  { from: ['draft', 'returned'], to: 'submitted', roles: ['dept_coordinator', 'faculty'], label: 'رفع للاعتماد', primary: true },
  { from: ['submitted'], to: 'hod_approved', roles: ['hod'], label: 'اعتماد', primary: true },
  { from: ['submitted'], to: 'returned', roles: ['hod'], label: 'إعادة للقسم', comment: true },
  { from: ['hod_approved'], to: 'under_audit', roles: ['quality_auditor', 'quality_dean'], label: 'بدء التدقيق', primary: true },
  { from: ['under_audit'], to: 'audited', roles: ['quality_auditor', 'external_reviewer'], label: 'إنهاء التدقيق', primary: true },
  { from: ['under_audit'], to: 'returned', roles: ['quality_auditor'], label: 'إعادة للقسم', comment: true },
  { from: ['audited'], to: 'final', roles: ['quality_dean'], label: 'اعتماد نهائي', primary: true },
  { from: ['audited'], to: 'returned', roles: ['quality_dean'], label: 'إعادة للقسم', comment: true },
  { from: ['final'], to: 'under_audit', roles: ['quality_dean'], label: 'إعادة فتح', comment: true },
];

export const ACTION_STATUS = {
  draft: 'مسودة لدى القسم', submitted: 'بانتظار حكم الملاءمة', revision: 'معادة للقسم', approved: 'قيد التنفيذ',
  completed: 'منجزة بانتظار التحقق', verified: 'مغلقة بعد التحقق', cancelled: 'ملغاة',
};
export const PRIORITY = { 1: 'عالية', 2: 'متوسطة', 3: 'منخفضة' };

// انعكاس لجدول action_workflow_rule ('owner' = المسؤول عن التنفيذ)
export const ACTION_TRANSITIONS = [
  { from: ['draft', 'revision'], to: 'submitted', roles: ['dept_coordinator', 'faculty', 'hod'], label: 'رفع الخطة للمقيّم', primary: true },
  { from: ['submitted'], to: 'approved', roles: ['quality_auditor', 'external_reviewer'], label: 'الخطة مناسبة: اعتماد', primary: true, independent: true },
  { from: ['submitted'], to: 'revision', roles: ['quality_auditor', 'external_reviewer'], label: 'إعادة للقسم', adequacy: true, independent: true },
  { from: ['approved'], to: 'completed', roles: ['owner', 'dept_coordinator', 'hod'], label: 'إعلان الإنجاز', primary: true },
  { from: ['completed'], to: 'verified', roles: ['quality_auditor', 'quality_dean', 'external_reviewer'], label: 'تأكيد الإغلاق', primary: true, independent: true, optionalComment: true },
  { from: ['completed'], to: 'approved', roles: ['quality_auditor', 'quality_dean', 'external_reviewer'], label: 'إعادة للتنفيذ', comment: true, independent: true },
  { from: ['draft', 'submitted', 'revision', 'approved'], to: 'cancelled', roles: ['quality_dean'], label: 'إلغاء الخطة', comment: true, danger: true },
];
