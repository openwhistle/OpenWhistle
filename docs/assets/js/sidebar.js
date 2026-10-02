// Sidebar active link on scroll
var sections = document.querySelectorAll('.docs-section[id]');
var sidebarLinks = document.querySelectorAll('.sidebar-links a[href^="#"]');

function updateActive() {
  var scrollY = window.scrollY + 100;
  var active = null;
  sections.forEach(function(s) {
    if (s.offsetTop <= scrollY) {
      active = s.getAttribute('id');
    }
  });
  sidebarLinks.forEach(function(a) {
    var href = a.getAttribute('href');
    if (href === '#' + active) {
      a.classList.add('active');
    } else {
      a.classList.remove('active');
    }
  });
}

window.addEventListener('scroll', updateActive, { passive: true });
updateActive();
