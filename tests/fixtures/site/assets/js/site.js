// Theme toggle — detection already handled by inline head script
var toggle = document.getElementById('theme-toggle');
if (toggle) {
  toggle.addEventListener('click', function() {
    var current = document.documentElement.getAttribute('data-theme');
    var next = current === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    try { localStorage.setItem('ow-theme', next); } catch(e) {}
  });
}

// Follow system preference changes when user hasn't overridden manually
window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', function(e) {
  var stored;
  try { stored = localStorage.getItem('ow-theme'); } catch(e2) {}
  if (!stored) {
    document.documentElement.setAttribute('data-theme', e.matches ? 'dark' : 'light');
  }
});

// Mobile nav toggle
var navToggle = document.querySelector('.nav-toggle');
var navLinks = document.getElementById('nav-links');
if (navToggle && navLinks) {
  navToggle.addEventListener('click', function() {
    var isOpen = navToggle.getAttribute('aria-expanded') === 'true';
    navToggle.setAttribute('aria-expanded', String(!isOpen));
    navLinks.classList.toggle('open', !isOpen);
  });
}
