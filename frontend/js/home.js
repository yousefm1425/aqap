// الصفحة الرئيسية: ظهور الأقسام عند التمرير، وعدّادات المؤشرات، وشريط علوي يتلوّن عند النزول
(() => {
  const nav = document.getElementById('nav');
  const onScroll = () => nav.classList.toggle('scrolled', window.scrollY > 40);
  onScroll();
  window.addEventListener('scroll', onScroll, { passive: true });

  const fmt = new Intl.NumberFormat('ar-SA-u-nu-latn');
  const count = el => {
    if (el.dataset.done) return;
    el.dataset.done = '1';
    const target = Number(el.dataset.count), pre = el.dataset.prefix || '', suf = el.dataset.suffix || '';
    const t0 = performance.now(), dur = 1800;
    const step = now => {
      const p = Math.min(1, (now - t0) / dur), eased = 1 - Math.pow(1 - p, 3);
      el.textContent = `${pre}${fmt.format(Math.round(target * eased))}${suf}`;
      if (p < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  };

  const io = new IntersectionObserver(entries => {
    for (const e of entries) {
      if (!e.isIntersecting) continue;
      e.target.classList.add('in');
      e.target.querySelectorAll('[data-count]').forEach(count);
      if (e.target.dataset.count) count(e.target);
      io.unobserve(e.target);
    }
  }, { threshold: 0.18 });
  document.querySelectorAll('.reveal').forEach(el => io.observe(el));
})();
