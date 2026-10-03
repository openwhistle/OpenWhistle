// Sidebar active link on scroll
var sections = document.querySelectorAll('.docs-section[id]');
var sidebarLinks = document.querySelectorAll('.sidebar-links a[href^="#"]');

function updateActive() {
  // The section being read is the last one whose top has passed a third of the window:
  // 100 px from the top left 40 px under the 60 px nav, so a heading just below the nav
  // still lit the section before it.
  var line = window.scrollY + window.innerHeight / 3;
  var active = null;
  sections.forEach(function(s) {
    if (s.offsetTop <= line) {
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
