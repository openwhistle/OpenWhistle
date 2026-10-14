// Live preview for /admin/branding. The same WCAG 2.x rule as
// app/services/brand_colour.py; the server's values are the ones saved.
(function () {
  'use strict';
  var LIGHT = '#ffffff', DARK = '#0a0a0b', WHITE = '#ffffff', BLACK = '#000000', MIN = 4.5;

  function channels(c) { return [1, 3, 5].map(function (i) { return parseInt(c.substr(i, 2), 16); }); }
  function lum(c) {
    var v = channels(c).map(function (x) {
      var s = x / 255;
      return s <= 0.04045 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
    });
    return 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2];
  }
  function contrast(a, b) {
    var x = lum(a), y = lum(b);
    return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);
  }
  function mix(c, t, share) {
    var a = channels(c), b = channels(t);
    return '#' + a.map(function (v, i) {
      return ('0' + Math.round(v + (b[i] - v) * share).toString(16)).slice(-2);
    }).join('');
  }
  function readable(c, canvas, toward) {
    for (var step = 0; step <= 50; step++) {
      var candidate = mix(c, toward, step / 50);
      if (contrast(candidate, canvas) >= MIN) { return candidate; }
    }
    return toward;
  }
  function on(fill) { return contrast(fill, WHITE) >= contrast(fill, BLACK) ? WHITE : BLACK; }

  var hex = document.getElementById('bp-colour-hex');
  var picker = document.getElementById('bp-colour-picker');
  var ratios = document.getElementById('bp-contrast');
  var panels = document.querySelectorAll('.bp-panel[data-preview]');

  function apply(colour) {
    if (!/^#[0-9a-fA-F]{6}$/.test(colour)) { return; }
    colour = colour.toLowerCase();
    var light = colour === '#0c7253' ? '#0c7253' : readable(colour, LIGHT, BLACK);
    var dark = colour === '#0c7253' ? '#23c088' : readable(colour, DARK, WHITE);
    panels.forEach(function (panel) {
      var accent = panel.dataset.preview === 'dark' ? dark : light;
      panel.style.setProperty('--bp-accent', accent);
      panel.style.setProperty('--bp-on', colour === '#0c7253' && panel.dataset.preview === 'dark' ? '#06120d' : on(accent));
    });
    if (ratios && ratios.dataset.template) {
      ratios.textContent = ratios.dataset.template
        .replace('{button}', contrast(on(light), light).toFixed(1) + ':1')
        .replace('{light}', contrast(light, LIGHT).toFixed(1) + ':1')
        .replace('{dark}', contrast(dark, DARK).toFixed(1) + ':1');
    }
  }

  if (hex && picker) {
    hex.addEventListener('input', function () {
      if (/^#[0-9a-fA-F]{6}$/.test(hex.value)) { picker.value = hex.value.toLowerCase(); }
      apply(hex.value);
    });
    picker.addEventListener('input', function () { hex.value = picker.value; apply(picker.value); });
  }

  var name = document.getElementById('bp-name');
  if (name) {
    name.addEventListener('input', function () {
      var shown = name.value.trim() || name.getAttribute('placeholder') || '';
      document.querySelectorAll('[data-preview-name]').forEach(function (el) {
        if (shown) { el.textContent = shown; }
      });
    });
  }

  // img-src 'self' data: already allows a data: URL; no CSP change for the preview.
  document.querySelectorAll('[data-preview-logo]').forEach(function (input) {
    input.addEventListener('change', function () {
      var file = input.files && input.files[0];
      if (!file) { return; }
      var reader = new FileReader();
      reader.onload = function () {
        var targets = input.dataset.previewLogo === 'logo_dark' ? ['dark'] : ['light', 'dark'];
        targets.forEach(function (theme) {
          var img = document.querySelector('[data-preview-img="' + theme + '"]');
          if (!img) { return; }
          if (theme === 'dark' && input.dataset.previewLogo === 'logo_light' && img.dataset.ownDark) { return; }
          img.src = reader.result;
          img.hidden = false;
          if (input.dataset.previewLogo === 'logo_dark') { img.dataset.ownDark = '1'; }
        });
      };
      reader.readAsDataURL(file);
    });
  });

  var autosubmit = document.querySelector('select[data-autosubmit]');
  if (autosubmit) { autosubmit.addEventListener('change', function () { autosubmit.form.submit(); }); }
})();
