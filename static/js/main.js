/* ═══════════════════════════════════════
   MIND DRIJI Admin — main.js
═══════════════════════════════════════ */

document.addEventListener('DOMContentLoaded', () => {

  /* ── Sidebar Toggle ── */
  const toggle    = document.getElementById('sidebarToggle');
  const sidebar   = document.getElementById('sidebar');
  const isMobile  = () => window.innerWidth <= 768;

  toggle?.addEventListener('click', () => {
    if (isMobile()) {
      sidebar.classList.toggle('show');
    } else {
      document.body.classList.toggle('sidebar-collapsed');
    }
  });

  /* ── Close sidebar on outside click (mobile) ── */
  document.addEventListener('click', (e) => {
    if (isMobile() && sidebar.classList.contains('show')) {
      if (!sidebar.contains(e.target) && !toggle.contains(e.target)) {
        sidebar.classList.remove('show');
      }
    }
  });

  /* ── Current Date ── */
  const dateEl = document.getElementById('currentDate');
  if (dateEl) {
    const now = new Date();
    dateEl.textContent = now.toLocaleDateString('id-ID', {
      weekday: 'long', year: 'numeric', month: 'long', day: 'numeric'
    });
  }

  /* ── Animated Counter ── */
  function animateCounter(el, target, duration = 1400) {
    const startTime = performance.now();
    const update = (currentTime) => {
      const elapsed = currentTime - startTime;
      const progress = Math.min(elapsed / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3); // ease-out cubic
      const value = Math.round(eased * target);
      el.textContent = value.toLocaleString('id-ID');
      if (progress < 1) requestAnimationFrame(update);
    };
    requestAnimationFrame(update);
  }

  /* ── Intersection Observer for counters ── */
  const counterEls = document.querySelectorAll('.stat-card__value[data-target]');
  if ('IntersectionObserver' in window && counterEls.length) {
    const observer = new IntersectionObserver((entries) => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          const el = entry.target;
          const target = parseInt(el.dataset.target, 10);
          animateCounter(el, target);
          observer.unobserve(el);
        }
      });
    }, { threshold: 0.4 });

    counterEls.forEach(el => observer.observe(el));
  } else {
    // Fallback: set values immediately
    counterEls.forEach(el => {
      el.textContent = parseInt(el.dataset.target, 10).toLocaleString('id-ID');
    });
  }

  /* ── Chip button toggle ── */
  document.querySelectorAll('.chip-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const group = btn.closest('.d-flex');
      group?.querySelectorAll('.chip-btn').forEach(b => b.classList.remove('chip-btn--active'));
      btn.classList.add('chip-btn--active');
    });
  });

  /* ── Refresh activity button ── */
  document.querySelector('.icon-btn')?.addEventListener('click', function () {
    this.style.transform = 'rotate(360deg)';
    this.style.transition = 'transform .5s ease';
    setTimeout(() => {
      this.style.transform = '';
      this.style.transition = '';
    }, 500);
  });

});