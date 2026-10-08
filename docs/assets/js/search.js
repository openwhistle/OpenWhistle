// Docs search on Pagefind's own pagefind.js, loaded on first use; no third-party UI (spec P3).
// The button stays hidden without JavaScript, so nothing on the page is dead.
// The term rides to a result in the fragment (#highlight=), never in ?highlight=: a fragment
// is not sent with the request, so the term never reaches the server (privacy policy).
(function () {
  var open = document.querySelector('[data-search-open]');
  var dialog = document.getElementById('docs-search');
  if (!open || !dialog) return;
  var input = dialog.querySelector('input');
  var list = dialog.querySelector('ol');
  var status = dialog.querySelector('[role=status]');
  var pagefind = null;
  var seq = 0;

  function show() {
    if (!dialog.open) dialog.showModal();
    input.focus();
  }
  open.hidden = false;
  open.addEventListener('click', show);
  dialog.querySelector('[data-search-close]').addEventListener('click', function () { dialog.close(); });
  // Escape and the close button both end here; opened by `/`, focus would fall to <body>.
  dialog.addEventListener('close', function () { open.focus(); });
  document.addEventListener('keydown', function (e) {
    if (e.key !== '/' || e.ctrlKey || e.metaKey || e.altKey) return;
    var t = e.target;
    if (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName)) return;
    e.preventDefault();
    show();
  });

  input.addEventListener('input', async function () {
    var term = input.value.trim();
    var mine = ++seq;
    if (!term) { list.replaceChildren(); status.textContent = ''; return; }
    if (!pagefind) pagefind = await import('/pagefind/pagefind.js');
    var search = await pagefind.debouncedSearch(term);
    if (search === null || mine !== seq) return;  // a newer keystroke superseded this one
    var found = await Promise.all(search.results.slice(0, 8).map(function (r) { return r.data(); }));
    if (mine !== seq) return;
    list.replaceChildren.apply(list, found.map(function (d) {
      var li = document.createElement('li');
      var a = document.createElement('a');
      var p = document.createElement('p');
      a.href = d.url + '#highlight=' + encodeURIComponent(term);
      a.textContent = d.meta.title;
      p.innerHTML = d.excerpt;  // Pagefind escapes our own page text and adds only <mark>
      li.append(a, p);
      return li;
    }));
    status.textContent = search.results.length
      ? search.results.length + (search.results.length === 1 ? ' result' : ' results')
      : 'Nothing found for “' + term + '”';
  });

  var hash = location.hash.match(/^#highlight=(.+)/);
  if (hash) {
    var terms = decodeURIComponent(hash[1]).split(/\s+/);  // one mark per word, as Pagefind does
    import('/pagefind/pagefind-highlight.js').then(function (m) {
      // Pagefind reads its terms from location.search only; ours come from the fragment.
      // addStyles: false, as its inline <style> breaks the CSP; docs.css colours the marks.
      var FromHash = class extends m.default {
        getHighlightParams() { return terms; }
      };
      new FromHash({ addStyles: false });
      var first = document.querySelector('mark.pagefind-highlight');
      if (first) first.scrollIntoView({ block: 'center' });
    });
  }
})();
