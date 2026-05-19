/* Jerome Baker Comes to New York — campaign treatment page
   Behaviors: scene-nav active-state tracking, mobile nav drawer,
   image lightbox, scroll progress.
*/

// ─── Mobile nav drawer ─────────────────────────────────────
const navToggle = document.getElementById('navToggle');
const sceneNav = document.getElementById('sceneNav');
navToggle.addEventListener('click', () => {
  sceneNav.classList.toggle('open');
});
// close drawer when a link is clicked (mobile)
sceneNav.querySelectorAll('.scene-link').forEach(a => {
  a.addEventListener('click', () => {
    if (window.innerWidth <= 900) sceneNav.classList.remove('open');
  });
});

// ─── Scene-nav active-state on scroll ──────────────────────
const navLinks = Array.from(document.querySelectorAll('.scene-link'));
const targets = navLinks
  .map(a => document.querySelector(a.getAttribute('href')))
  .filter(Boolean);

const observer = new IntersectionObserver(
  entries => {
    // Find the most-visible section in the viewport
    const visible = entries
      .filter(e => e.isIntersecting)
      .sort((a, b) => b.intersectionRatio - a.intersectionRatio);
    if (!visible.length) return;
    const id = visible[0].target.id;
    navLinks.forEach(a => {
      a.classList.toggle('active', a.getAttribute('href') === '#' + id);
    });
    // Scroll the active link into view inside the sidebar
    const active = navLinks.find(a => a.classList.contains('active'));
    if (active && window.innerWidth > 900) {
      const navRect = sceneNav.getBoundingClientRect();
      const linkRect = active.getBoundingClientRect();
      if (linkRect.top < navRect.top + 60 || linkRect.bottom > navRect.bottom - 60) {
        active.scrollIntoView({ block: 'center', behavior: 'smooth' });
      }
    }
  },
  { rootMargin: '-30% 0px -50% 0px', threshold: [0, 0.25, 0.5, 0.75, 1] }
);
targets.forEach(t => observer.observe(t));

// ─── Lightbox ──────────────────────────────────────────────
const lightbox = document.getElementById('lightbox');
const lightboxImg = document.getElementById('lightboxImg');
const lightboxCaption = document.getElementById('lightboxCaption');

document.querySelectorAll('.img-slot').forEach(slot => {
  slot.addEventListener('click', () => {
    const img = slot.querySelector('img');
    if (!img || img.classList.contains('missing')) return;
    lightboxImg.src = img.src;
    lightboxImg.alt = img.alt;
    lightboxCaption.textContent = slot.dataset.slot || '';
    lightbox.classList.add('show');
    document.body.style.overflow = 'hidden';
  });
});
function closeLightbox(e) {
  if (e && e.target.tagName === 'IMG') return;  // clicks on image bubble — don't close
  lightbox.classList.remove('show');
  document.body.style.overflow = '';
}
document.addEventListener('keydown', e => {
  if (e.key === 'Escape' && lightbox.classList.contains('show')) closeLightbox();
});

// (Hero parallax removed — was pushing Jerome below the cropped edge of
//  .hero-img-wrap on scroll. Static image is correct here.)
