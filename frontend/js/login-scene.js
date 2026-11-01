// خلفية سينمائية لشاشات الدخول: ثلاثة مشاهد من الورش التقنية في حلقة مدتها 20 ثانية
//   ① ورشة اللحام: قوس لحام وشرر يتطاير ودخان
//   ② الكهرباء والإلكترونيات: مسارات دوائر يسري فيها التيار وقوس كهربائي
//   ③ الميكانيكا: تروس متعاشقة تدور فوق مخطط هندسي
// مرسومة بالكود على Canvas (بلا ملفات فيديو)، تتوقف عند إخفاء التبويب، وتصبح صورة ثابتة لمن يفضّل تقليل الحركة.

const LOOP = 20;
const SCENES = [
  { from: 0, to: 7.2, caption: 'ورش اللحام والتصنيع' },
  { from: 6.4, to: 13.8, caption: 'الإلكترونيات والقوى الكهربائية' },
  { from: 13, to: 20.6, caption: 'التقنية الميكانيكية' },
];
const FADE = 0.9;

let active = null;   // { stop }

function rand(seed) {                    // مولّد أرقام ثابت البذرة (الرسم نفسه في كل حلقة)
  let s = seed >>> 0;
  return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 4294967296);
}

function sceneAlpha(t, sc) {
  // يدعم المشهد الأخير الذي يلتف إلى بداية الحلقة
  const tt = t < sc.from - FADE && sc.to > LOOP ? t + LOOP : t;
  if (tt < sc.from || tt > sc.to) return 0;
  return Math.min(1, (tt - sc.from) / FADE, (sc.to - tt) / FADE);
}

// ------------------------------------------------------------------ ① اللحام
function makeWeld(r) {
  return { sparks: [], smoke: Array.from({ length: 14 }, () => ({ x: r(), y: r(), s: 0.08 + r() * 0.12, v: 0.01 + r() * 0.02 })) };
}

function drawWeld(ctx, w, h, t, st, dt, quality) {
  const local = t % LOOP;
  const seamY = h * 0.70;
  // العمل على جانب الشاشة (بطاقة الدخول في الوسط)؛ القوس يتقدم على خط اللحام
  const ax = w * (w < 700 ? 0.18 + 0.5 * Math.min(1, local / 7.2) : 0.16 + 0.13 * Math.min(1, local / 7.2));
  const ay = seamY - h * 0.004;

  // سطح العمل: لوح معدني بمنظور
  const plate = ctx.createLinearGradient(0, seamY - h * 0.08, 0, h);
  plate.addColorStop(0, '#1d2629'); plate.addColorStop(1, '#070a0b');
  ctx.fillStyle = plate;
  ctx.beginPath();
  ctx.moveTo(-w * 0.05, h); ctx.lineTo(w * 0.04, seamY - h * 0.05); ctx.lineTo(w * 0.62, seamY - h * 0.05); ctx.lineTo(w * 0.80, h);
  ctx.fill();

  // خط اللحام الساخن خلف القوس
  const sx0 = w * 0.08;
  const seam = ctx.createLinearGradient(sx0, 0, ax, 0);
  seam.addColorStop(0, 'rgba(120,40,10,0)'); seam.addColorStop(0.7, 'rgba(255,90,20,.55)'); seam.addColorStop(1, 'rgba(255,220,150,.95)');
  ctx.strokeStyle = seam; ctx.lineWidth = Math.max(2, h * 0.006); ctx.lineCap = 'round';
  ctx.beginPath(); ctx.moveTo(sx0, seamY - h * 0.004); ctx.lineTo(ax, ay); ctx.stroke();

  // وهج القوس المتذبذب
  const flick = 0.75 + Math.random() * 0.35;
  ctx.save();
  ctx.globalCompositeOperation = 'lighter';
  const R = Math.min(w, h) * 0.55 * flick;
  const glow = ctx.createRadialGradient(ax, ay, 0, ax, ay, R);
  glow.addColorStop(0, 'rgba(255,255,240,.95)'); glow.addColorStop(0.04, 'rgba(255,215,140,.85)');
  glow.addColorStop(0.12, 'rgba(255,140,40,.55)'); glow.addColorStop(0.4, 'rgba(255,90,20,.16)'); glow.addColorStop(1, 'rgba(0,0,0,0)');
  ctx.fillStyle = glow; ctx.fillRect(ax - R, ay - R, R * 2, R * 2);
  const amb = ctx.createRadialGradient(ax, ay, 0, ax, ay, Math.max(w, h) * 0.9);   // ضوء دافئ يملأ الورشة
  amb.addColorStop(0, `rgba(255,120,40,${0.16 * flick})`); amb.addColorStop(1, 'rgba(0,0,0,0)');
  ctx.fillStyle = amb; ctx.fillRect(0, 0, w, h);
  const core = ctx.createRadialGradient(ax, ay, 0, ax, ay, h * 0.045);
  core.addColorStop(0, 'rgba(220,240,255,1)'); core.addColorStop(1, 'rgba(120,180,255,0)');
  ctx.fillStyle = core; ctx.fillRect(ax - h * 0.045, ay - h * 0.045, h * 0.09, h * 0.09);

  // الشرر
  const emit = Math.round((quality < 1 ? 6 : 12) * flick);
  for (let i = 0; i < emit; i++) {
    const a = -Math.PI / 2 + (Math.random() - 0.5) * Math.PI * 1.1;
    const sp = (0.45 + Math.random() * 1.1) * h;
    st.sparks.push({ x: ax, y: ay, vx: Math.cos(a) * sp * (0.6 + Math.random()), vy: Math.sin(a) * sp, life: 0.5 + Math.random() * 1.1, age: 0 });
  }
  const g = h * 1.6;
  st.sparks = st.sparks.filter(p => (p.age += dt) < p.life);
  if (st.sparks.length > 420 * quality) st.sparks.splice(0, st.sparks.length - 420 * quality);
  for (const p of st.sparks) {
    const px = p.x, py = p.y;
    p.vy += g * dt; p.vx *= 0.995;
    p.x += p.vx * dt; p.y += p.vy * dt;
    if (p.y > seamY + h * 0.02 && p.vy > 0) { p.vy *= -0.32; p.vx *= 0.6; p.y = seamY + h * 0.02; }   // ترتد عن السطح
    const k = 1 - p.age / p.life;
    ctx.strokeStyle = `rgba(255,${120 + 110 * k | 0},${40 * k | 0},${0.95 * k})`;
    ctx.lineWidth = Math.max(1.2, h * 0.003 * k + 0.8);
    ctx.beginPath(); ctx.moveTo(px, py); ctx.lineTo(p.x, p.y); ctx.stroke();
  }
  ctx.restore();

  // دخان خفيف يتصاعد
  for (const s of st.smoke) {
    s.y -= s.v * dt; if (s.y < -0.2) { s.y = 1.0; s.x = Math.random(); }
    const sx = ax + (s.x - 0.5) * w * 0.5, sy = ay - (1 - s.y) * h * 0.7, rr = s.s * h;
    const sm = ctx.createRadialGradient(sx, sy, 0, sx, sy, rr);
    sm.addColorStop(0, 'rgba(160,170,175,.05)'); sm.addColorStop(1, 'rgba(160,170,175,0)');
    ctx.fillStyle = sm; ctx.fillRect(sx - rr, sy - rr, rr * 2, rr * 2);
  }

  // متدرب يلحم: صورة ظلية بخوذة اللحام، مضاءة من الأمام بلون القوس
  const s = h * 0.0013;
  const bx = ax - 60 * s - 4, by = seamY - h * 0.01;     // طرف المشعل عند القوس
  ctx.save();
  ctx.translate(bx, by); ctx.scale(-s, s);              // معكوس ليواجه القوس
  ctx.fillStyle = '#05080a';
  ctx.beginPath();                       // الجذع والكتفان
  ctx.moveTo(20, 0); ctx.bezierCurveTo(10, -60, 20, -120, 55, -150);
  ctx.bezierCurveTo(85, -170, 135, -168, 160, -140); ctx.bezierCurveTo(185, -110, 190, -40, 185, 0); ctx.closePath(); ctx.fill();
  ctx.beginPath();                       // خوذة اللحام
  ctx.moveTo(70, -165); ctx.bezierCurveTo(55, -215, 85, -262, 120, -262);
  ctx.bezierCurveTo(150, -262, 168, -232, 160, -190); ctx.bezierCurveTo(152, -168, 105, -158, 70, -165); ctx.fill();
  ctx.beginPath();                       // الذراع والمشعل باتجاه القوس
  ctx.moveTo(62, -140); ctx.bezierCurveTo(20, -110, -10, -70, -32, -30);
  ctx.lineTo(-20, -18); ctx.bezierCurveTo(5, -55, 40, -95, 78, -118); ctx.closePath(); ctx.fill();
  ctx.lineWidth = 7; ctx.strokeStyle = '#05080a'; ctx.beginPath(); ctx.moveTo(-28, -26); ctx.lineTo(-60, 2); ctx.stroke();
  // إضاءة الحافة من القوس
  ctx.globalCompositeOperation = 'lighter';
  ctx.strokeStyle = `rgba(255,150,60,${0.35 * flick})`; ctx.lineWidth = 3;
  ctx.beginPath(); ctx.moveTo(70, -165); ctx.bezierCurveTo(55, -215, 85, -262, 120, -262); ctx.stroke();
  ctx.beginPath(); ctx.moveTo(20, 0); ctx.bezierCurveTo(10, -60, 20, -120, 55, -150); ctx.stroke();
  ctx.fillStyle = `rgba(60,255,200,${0.18 + 0.12 * flick})`;   // انعكاس زجاج الخوذة
  ctx.beginPath(); ctx.ellipse(92, -212, 9, 18, -0.3, 0, Math.PI * 2); ctx.fill();
  ctx.restore();
}

// ------------------------------------------------------------------ ② الكهرباء
function makeCircuit(r) {
  const paths = [];
  for (let i = 0; i < 26; i++) {
    let x = r(), y = r();
    const pts = [[x, y]];
    let dir = Math.floor(r() * 4);
    for (let k = 0; k < 4 + Math.floor(r() * 5); k++) {
      const L = 0.04 + r() * 0.16;
      const d = [[1, 0], [0, 1], [-1, 0], [0, -1]][dir];
      if (r() < 0.45) { x += d[0] * L * 0.5 + d[1] * L * 0.5; y += d[1] * L * 0.5 + d[0] * L * 0.5; }   // انعطاف 45°
      x += d[0] * L; y += d[1] * L;
      pts.push([x, y]);
      dir = (dir + (r() < 0.5 ? 1 : 3)) % 4;
    }
    paths.push({ pts, speed: 0.12 + r() * 0.25, phase: r(), hue: r() < 0.8 ? 'teal' : 'amber' });
  }
  return { paths, arcSeed: 0 };
}

function polyLen(pts) {
  let L = 0;
  for (let i = 1; i < pts.length; i++) L += Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]);
  return L;
}

function pointAt(pts, f) {
  const L = polyLen(pts) * f;
  let acc = 0;
  for (let i = 1; i < pts.length; i++) {
    const seg = Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]);
    if (acc + seg >= L) {
      const k = (L - acc) / seg;
      return [pts[i - 1][0] + (pts[i][0] - pts[i - 1][0]) * k, pts[i - 1][1] + (pts[i][1] - pts[i - 1][1]) * k];
    }
    acc += seg;
  }
  return pts[pts.length - 1];
}

function drawCircuit(ctx, w, h, t, st) {
  const S = Math.max(w, h);
  const ox = (w - S) / 2 - S * 0.02 * Math.sin(t * 0.15), oy = (h - S) / 2;
  const P = ([x, y]) => [ox + x * S, oy + y * S];
  ctx.lineCap = 'round'; ctx.lineJoin = 'round';
  // المسارات الخافتة والوصلات
  for (const p of st.paths) {
    ctx.strokeStyle = p.hue === 'teal' ? 'rgba(0,170,150,.22)' : 'rgba(230,160,40,.18)';
    ctx.lineWidth = Math.max(1.2, S * 0.0018);
    ctx.beginPath();
    p.pts.forEach((q, i) => { const [x, y] = P(q); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
    ctx.stroke();
    for (const q of [p.pts[0], p.pts[p.pts.length - 1]]) {
      const [x, y] = P(q);
      ctx.fillStyle = 'rgba(0,200,175,.35)'; ctx.beginPath(); ctx.arc(x, y, S * 0.0035, 0, Math.PI * 2); ctx.fill();
    }
  }
  // نبضات التيار
  ctx.save(); ctx.globalCompositeOperation = 'lighter';
  for (const p of st.paths) {
    const f = (p.phase + t * p.speed) % 1;
    for (let k = 0; k < 6; k++) {
      const ff = f - k * 0.012; if (ff < 0) continue;
      const [x, y] = P(pointAt(p.pts, ff));
      const a = (1 - k / 6) * 0.9, rr = S * (0.004 - k * 0.0004);
      ctx.fillStyle = p.hue === 'teal' ? `rgba(90,255,225,${a})` : `rgba(255,200,90,${a})`;
      ctx.beginPath(); ctx.arc(x, y, Math.max(1, rr), 0, Math.PI * 2); ctx.fill();
    }
    const [hx, hy] = P(pointAt(p.pts, f));
    const gl = ctx.createRadialGradient(hx, hy, 0, hx, hy, S * 0.03);
    gl.addColorStop(0, p.hue === 'teal' ? 'rgba(60,240,210,.35)' : 'rgba(255,190,80,.3)'); gl.addColorStop(1, 'rgba(0,0,0,0)');
    ctx.fillStyle = gl; ctx.fillRect(hx - S * 0.03, hy - S * 0.03, S * 0.06, S * 0.06);
  }
  // قوس كهربائي بين طرفين (يومض)
  const ax1 = w * 0.18, ay1 = h * 0.28, ax2 = w * 0.30, ay2 = h * 0.42;
  if (Math.sin(t * 7.3) > -0.2) {
    for (let layer = 0; layer < 2; layer++) {
      ctx.strokeStyle = layer ? 'rgba(220,255,255,.9)' : 'rgba(80,200,255,.45)';
      ctx.lineWidth = layer ? 1.4 : 5;
      ctx.beginPath(); ctx.moveTo(ax1, ay1);
      const n = 12;
      for (let i = 1; i < n; i++) {
        const k = i / n, j = (Math.random() - 0.5) * h * 0.05;
        ctx.lineTo(ax1 + (ax2 - ax1) * k + j, ay1 + (ay2 - ay1) * k - j * 0.6);
      }
      ctx.lineTo(ax2, ay2); ctx.stroke();
    }
    for (const [x, y] of [[ax1, ay1], [ax2, ay2]]) {
      const gl = ctx.createRadialGradient(x, y, 0, x, y, h * 0.09);
      gl.addColorStop(0, 'rgba(170,235,255,.6)'); gl.addColorStop(1, 'rgba(0,0,0,0)');
      ctx.fillStyle = gl; ctx.fillRect(x - h * 0.09, y - h * 0.09, h * 0.18, h * 0.18);
    }
  }
  ctx.restore();
  // طرفا التوصيل
  for (const [x, y] of [[ax1, ay1], [ax2, ay2]]) {
    ctx.fillStyle = '#2b3438'; ctx.beginPath(); ctx.arc(x, y, h * 0.012, 0, Math.PI * 2); ctx.fill();
    ctx.strokeStyle = 'rgba(160,230,255,.6)'; ctx.lineWidth = 1.5; ctx.stroke();
  }
}

// ------------------------------------------------------------------ ③ الميكانيكا
function makeGears() {
  // سلسلة تروس متعاشقة: المسافة بين المركزين = مجموع أنصاف الأقطار، والسرعة تتناسب عكسياً مع عدد الأسنان
  const spec = [[0.13, 24], [0.075, 14], [0.10, 18], [0.06, 11], [0.115, 21], [0.05, 9]];
  const angles = [0.35, -0.6, 0.2, 1.1, -0.2];
  const gears = [];
  let x = 0.70, y = 0.34, prev = null;
  spec.forEach(([r, n], i) => {
    if (prev) {
      const a = angles[i - 1];
      x = prev.x + Math.cos(a) * (prev.r + r) * 0.96; y = prev.y + Math.sin(a) * (prev.r + r) * 0.96;
    }
    const g = { x, y, r, n, dir: i % 2 ? -1 : 1, speed: 0.6 * 12 / n, phase: (i % 2) * Math.PI / n };
    gears.push(g); prev = g;
  });
  return { gears, dust: Array.from({ length: 60 }, () => ({ x: Math.random(), y: Math.random(), v: 0.005 + Math.random() * 0.02 })) };
}

function gearPath(ctx, r, n) {
  const ro = r, ri = r * 0.86, step = Math.PI * 2 / n;
  ctx.beginPath();
  for (let i = 0; i < n; i++) {
    const a = i * step;
    ctx.lineTo(Math.cos(a) * ri, Math.sin(a) * ri);
    ctx.lineTo(Math.cos(a + step * 0.18) * ro, Math.sin(a + step * 0.18) * ro);
    ctx.lineTo(Math.cos(a + step * 0.5) * ro, Math.sin(a + step * 0.5) * ro);
    ctx.lineTo(Math.cos(a + step * 0.68) * ri, Math.sin(a + step * 0.68) * ri);
  }
  ctx.closePath();
}

function drawGears(ctx, w, h, t, st, dt) {
  const S = Math.min(w, h) * 1.25;
  const ox = w * 0.5 - S * 0.5 + Math.sin(t * 0.12) * S * 0.01, oy = h * 0.5 - S * 0.5;
  // مخطط هندسي في الخلفية
  ctx.strokeStyle = 'rgba(80,190,220,.07)'; ctx.lineWidth = 1;
  const gs = Math.max(24, S * 0.04);
  for (let x = (ox % gs); x < w; x += gs) { ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke(); }
  for (let y = (oy % gs); y < h; y += gs) { ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke(); }
  ctx.strokeStyle = 'rgba(120,210,235,.16)'; ctx.setLineDash([6, 6]);
  const g0 = st.gears[0];
  ctx.beginPath(); ctx.arc(ox + g0.x * S, oy + g0.y * S, g0.r * S * 1.35, 0, Math.PI * 2); ctx.stroke();
  ctx.setLineDash([]);

  for (const g of st.gears) {
    const cx = ox + g.x * S, cy = oy + g.y * S, r = g.r * S;
    ctx.save(); ctx.translate(cx, cy); ctx.rotate(g.phase + g.dir * g.speed * t);
    const body = ctx.createLinearGradient(-r, -r, r, r);
    body.addColorStop(0, '#3a474c'); body.addColorStop(0.5, '#1f282c'); body.addColorStop(1, '#0d1214');
    gearPath(ctx, r, g.n); ctx.fillStyle = body; ctx.fill();
    ctx.strokeStyle = 'rgba(0,200,175,.55)'; ctx.lineWidth = Math.max(1, r * 0.02); ctx.stroke();
    // فتحات العجلة والمحور
    ctx.fillStyle = '#0a0e10';
    for (let k = 0; k < 5; k++) {
      const a = k * Math.PI * 2 / 5;
      ctx.beginPath(); ctx.arc(Math.cos(a) * r * 0.5, Math.sin(a) * r * 0.5, r * 0.14, 0, Math.PI * 2); ctx.fill();
    }
    ctx.beginPath(); ctx.arc(0, 0, r * 0.2, 0, Math.PI * 2); ctx.fillStyle = '#2c373b'; ctx.fill();
    ctx.beginPath(); ctx.arc(0, 0, r * 0.08, 0, Math.PI * 2); ctx.fillStyle = '#05080a'; ctx.fill();
    ctx.restore();
    // إضاءة حافة دافئة من جهة واحدة
    ctx.save(); ctx.globalCompositeOperation = 'lighter';
    const rim = ctx.createRadialGradient(cx - r * 0.6, cy - r * 0.7, 0, cx - r * 0.6, cy - r * 0.7, r * 1.4);
    rim.addColorStop(0, 'rgba(255,160,70,.16)'); rim.addColorStop(1, 'rgba(0,0,0,0)');
    ctx.fillStyle = rim; ctx.beginPath(); ctx.arc(cx, cy, r, 0, Math.PI * 2); ctx.fill();
    ctx.restore();
  }
  // غبار معدني في الضوء
  ctx.fillStyle = 'rgba(255,220,170,.35)';
  for (const d of st.dust) {
    d.y -= d.v * dt; d.x += Math.sin(t + d.y * 10) * 0.0004;
    if (d.y < 0) { d.y = 1; d.x = Math.random(); }
    ctx.fillRect(d.x * w, d.y * h, 1.4, 1.4);
  }
}

// ------------------------------------------------------------------ الإطار السينمائي
function grainTile() {
  const c = document.createElement('canvas'); c.width = c.height = 160;
  const g = c.getContext('2d'), img = g.createImageData(160, 160);
  for (let i = 0; i < img.data.length; i += 4) {
    const v = Math.random() * 255;
    img.data[i] = img.data[i + 1] = img.data[i + 2] = v; img.data[i + 3] = 18;
  }
  g.putImageData(img, 0, 0);
  return c;
}

/** يبدأ المشهد خلف شاشة الدخول؛ استدعاؤه مرة ثانية لا يكرر شيئاً */
export function startLoginScene() {
  if (active) return;
  const wrap = document.createElement('div');
  wrap.className = 'auth-scene';
  wrap.setAttribute('aria-hidden', 'true');
  const canvas = document.createElement('canvas');
  const caption = document.createElement('div');
  caption.className = 'auth-scene-caption';
  wrap.append(canvas, caption);
  document.body.prepend(wrap);
  document.body.classList.add('has-auth-scene');

  const ctx = canvas.getContext('2d');
  const r = rand(1447);
  const weld = makeWeld(r), circuit = makeCircuit(r), gears = makeGears();
  const grain = grainTile();
  const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
  let w = 0, h = 0, quality = 1, raf = 0, last = performance.now(), t0 = last, stopped = false, shown = '';

  const resize = () => {
    const dpr = Math.min(window.devicePixelRatio || 1, 1.5);
    w = window.innerWidth; h = window.innerHeight;
    canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
    canvas.style.width = `${w}px`; canvas.style.height = `${h}px`;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    quality = w < 700 ? 0.5 : 1;
  };
  resize();
  window.addEventListener('resize', resize);

  const frame = now => {
    if (stopped) return;
    const dt = Math.min(0.05, (now - last) / 1000); last = now;
    const t = reduce ? 3.2 : ((now - t0) / 1000) % LOOP;

    const bg = ctx.createLinearGradient(0, 0, w, h);
    bg.addColorStop(0, '#0a1416'); bg.addColorStop(0.55, '#0b1a1c'); bg.addColorStop(1, '#050809');
    ctx.globalAlpha = 1; ctx.fillStyle = bg; ctx.fillRect(0, 0, w, h);

    const alphas = SCENES.map(sc => sceneAlpha(t, sc));
    const draws = [
      () => drawWeld(ctx, w, h, t, weld, dt, quality),
      () => drawCircuit(ctx, w, h, t, circuit),
      () => drawGears(ctx, w, h, t, gears, dt),
    ];
    draws.forEach((d, i) => {
      if (alphas[i] <= 0.01) return;
      ctx.save(); ctx.globalAlpha = alphas[i]; d(); ctx.restore();
    });

    // تدرج لوني بهوية المؤسسة + تظليل الحواف + حبيبات الفيلم
    const tint = ctx.createLinearGradient(0, h, w, 0);
    tint.addColorStop(0, 'rgba(0,156,140,.10)'); tint.addColorStop(1, 'rgba(14,90,71,.06)');
    ctx.fillStyle = tint; ctx.fillRect(0, 0, w, h);
    const vig = ctx.createRadialGradient(w / 2, h / 2, Math.min(w, h) * 0.25, w / 2, h / 2, Math.max(w, h) * 0.75);
    vig.addColorStop(0, 'rgba(0,0,0,0)'); vig.addColorStop(1, 'rgba(0,0,0,.72)');
    ctx.fillStyle = vig; ctx.fillRect(0, 0, w, h);
    ctx.globalAlpha = 0.55;
    const gx = Math.random() * 160, gy = Math.random() * 160;
    for (let x = -gx; x < w; x += 160) for (let y = -gy; y < h; y += 160) ctx.drawImage(grain, x, y);
    ctx.globalAlpha = 1;

    // عنوان المشهد
    const i = alphas.indexOf(Math.max(...alphas));
    if (SCENES[i].caption !== shown) { shown = SCENES[i].caption; caption.textContent = shown; }
    caption.style.opacity = String(Math.max(0, Math.min(1, alphas[i] * 1.2 - 0.2)));

    if (!reduce) raf = requestAnimationFrame(frame);
  };
  const onVis = () => {
    if (document.hidden) cancelAnimationFrame(raf);
    else if (!stopped && !reduce) { last = performance.now(); raf = requestAnimationFrame(frame); }
  };
  document.addEventListener('visibilitychange', onVis);
  raf = requestAnimationFrame(frame);

  active = {
    stop() {
      stopped = true; cancelAnimationFrame(raf);
      window.removeEventListener('resize', resize);
      document.removeEventListener('visibilitychange', onVis);
      wrap.remove(); document.body.classList.remove('has-auth-scene');
      active = null;
    },
  };
}

export function stopLoginScene() {
  active?.stop();
}
