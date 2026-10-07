const BASE = '/api/v1';
const KEY = 'aqap_token';

let token = null;
try { token = sessionStorage.getItem(KEY); } catch { /* التخزين غير متاح */ }

export function setToken(value) {
  token = value;
  try { value ? sessionStorage.setItem(KEY, value) : sessionStorage.removeItem(KEY); } catch { /* تجاهل */ }
}
export const hasToken = () => Boolean(token);

export class ApiError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

export async function api(path, { method = 'GET', body, form } = {}) {
  const headers = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  let payload;
  if (form) payload = form;
  else if (body !== undefined) { headers['Content-Type'] = 'application/json'; payload = JSON.stringify(body); }

  const res = await fetch(BASE + path, { method, headers, body: payload });
  if (res.status === 401) {
    setToken(null);
    window.dispatchEvent(new Event('aqap:logout'));
    throw new ApiError(401, 'انتهت الجلسة، سجّل الدخول مجدداً');
  }
  if (res.status === 204) return null;
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    let msg = data?.detail;
    if (Array.isArray(msg)) msg = msg.map(d => d.msg).join('، ');
    throw new ApiError(res.status, msg || `تعذّر تنفيذ الطلب (${res.status})`);
  }
  return data;
}

/** تنزيل ملف من الواجهة البرمجية مع الرمز، ويعيد ترويسة تقرير التصدير إن وُجدت */
export async function apiDownload(path, fallbackName) {
  const res = await fetch(BASE + path, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  if (res.status === 401) { setToken(null); window.dispatchEvent(new Event('aqap:logout')); throw new ApiError(401, 'انتهت الجلسة'); }
  if (!res.ok) {
    const data = await res.json().catch(() => null);
    throw new ApiError(res.status, data?.detail || `تعذّر التنزيل (${res.status})`);
  }
  const blob = await res.blob();
  const cd = res.headers.get('Content-Disposition') || '';
  const m = cd.match(/filename\*=UTF-8''([^;]+)/);
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = m ? decodeURIComponent(m[1]) : fallbackName;
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 10000);
  const report = res.headers.get('X-AQAP-Export-Report');
  return report ? JSON.parse(decodeURIComponent(report)) : null;
}

/** يفتح ملفاً محمياً (مثل PDF) في تبويب جديد. يُفتح التبويب فوراً لتجنب مانع النوافذ، ثم يُملأ بالملف */
export async function apiOpen(path) {
  const win = window.open('', '_blank');
  const res = await fetch(BASE + path, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  if (!res.ok) {
    if (win) win.close();
    const data = await res.json().catch(() => null);
    throw new ApiError(res.status, data?.detail || `تعذّر فتح الملف (${res.status})`);
  }
  const url = URL.createObjectURL(await res.blob());
  if (win) win.location.href = url; else window.location.href = url;
  setTimeout(() => URL.revokeObjectURL(url), 60000);
}
