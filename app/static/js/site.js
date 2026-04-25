/* OpenWhistle — minimal vanilla JS */
'use strict';

// ─── Theme management ──────────────────────────────────────────────────────

(function () {
    const STORAGE_KEY = 'ow-theme';
    const html = document.documentElement;

    function applyTheme(theme) {
        html.setAttribute('data-theme', theme);
        const btn = document.getElementById('theme-toggle');
        if (btn) {
            btn.textContent = theme === 'dark' ? '☀ Light' : '◑ Dark';
            btn.setAttribute('aria-label', `Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`);
        }
    }

    function savedTheme() {
        try { return localStorage.getItem(STORAGE_KEY); } catch { return null; }
    }

    function systemTheme() {
        return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    }

    // Apply on load
    applyTheme(savedTheme() || systemTheme());

    window.toggleTheme = function () {
        const current = html.getAttribute('data-theme') || systemTheme();
        const next = current === 'dark' ? 'light' : 'dark';
        applyTheme(next);
        try { localStorage.setItem(STORAGE_KEY, next); } catch { /* private browsing */ }
    };

    // Listen for system preference changes
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (e) => {
        if (!savedTheme()) applyTheme(e.matches ? 'dark' : 'light');
    });
})();

// ─── Copy to clipboard ────────────────────────────────────────────────────

window.copyToClipboard = async function (text, btn) {
    try {
        await navigator.clipboard.writeText(text);
        const orig = btn.textContent;
        btn.textContent = 'Copied!';
        btn.disabled = true;
        setTimeout(() => { btn.textContent = orig; btn.disabled = false; }, 2000);
    } catch {
        // Fallback for older browsers or non-HTTPS contexts
        const el = document.createElement('textarea');
        el.value = text;
        el.style.position = 'fixed';
        el.style.opacity = '0';
        document.body.appendChild(el);
        el.select();
        document.execCommand('copy');
        document.body.removeChild(el);
    }
};

// ─── IP warning dismiss ────────────────────────────────────────────────────

window.dismissIpWarning = async function (btn) {
    try {
        const res = await fetch('/admin/ip-warning/dismiss', { method: 'POST' });
        if (res.ok) {
            const banner = document.getElementById('ip-warning-banner');
            if (banner) {
                banner.style.transition = 'opacity 0.3s';
                banner.style.opacity = '0';
                setTimeout(() => banner.remove(), 300);
            }
        }
    } catch {
        /* non-critical */
    }
};

// ─── Session expiry warning ────────────────────────────────────────────────

(function () {
    const WARN_BEFORE_MS = 5 * 60 * 1000; // show banner 5 minutes before expiry
    const REDIRECT_DELAY_MS = 5000;        // redirect 5 s after expiry

    const banner = document.getElementById('session-expiry-banner');
    if (!banner) return;

    const expiresAt = parseInt(banner.dataset.expires, 10) * 1000; // to ms
    if (!expiresAt) return;

    const countdown  = document.getElementById('session-expiry-countdown');
    let warnTimer      = null;
    let tickInterval   = null;
    let dismissed      = false;

    function fmt(ms) {
        const total = Math.max(0, Math.floor(ms / 1000));
        const m = Math.floor(total / 60);
        const s = total % 60;
        return `${m}:${s.toString().padStart(2, '0')}`;
    }

    function showBanner() {
        if (dismissed) return;
        banner.style.display = 'flex';
        startTick(expiresAt);
    }

    function startTick(targetMs) {
        if (tickInterval) clearInterval(tickInterval);
        tickInterval = setInterval(() => {
            const remaining = targetMs - Date.now();
            if (countdown) countdown.textContent = fmt(remaining);
            if (remaining <= 0) {
                clearInterval(tickInterval);
                markExpired();
            }
        }, 1000);
        // Tick immediately so countdown is accurate from first render
        if (countdown) countdown.textContent = fmt(targetMs - Date.now());
    }

    function markExpired() {
        banner.classList.add('session-expiry-expired-state');
        banner.style.display = 'flex';

        const bodyEl = banner.querySelector('.session-expiry-body');
        if (bodyEl) {
            const title = banner.dataset.textExpiredTitle || 'Session expired';
            const body  = banner.dataset.textExpiredBody  || 'You will be redirected shortly.';
            bodyEl.innerHTML = `<strong>${title}</strong><p>${body}</p>`;
        }

        const actionsEl = banner.querySelector('.session-expiry-actions');
        if (actionsEl) actionsEl.style.display = 'none';

        setTimeout(() => { window.location.href = '/admin/login'; }, REDIRECT_DELAY_MS);
    }

    // Schedule or show immediately if already inside warning window
    const msUntilWarn = expiresAt - WARN_BEFORE_MS - Date.now();
    if (msUntilWarn <= 0) {
        showBanner();
    } else {
        warnTimer = setTimeout(showBanner, msUntilWarn);
    }

    window.sessionExtend = async function () {
        try {
            const res = await fetch('/admin/session/refresh', { method: 'POST' });
            if (!res.ok) { window.location.href = '/admin/login'; return; }
            const data = await res.json();

            if (tickInterval) clearInterval(tickInterval);
            if (warnTimer)    clearTimeout(warnTimer);
            dismissed = false;

            const newExpiresMs = data.expires_at * 1000;
            banner.dataset.expires = data.expires_at;
            banner.style.display = 'none';
            banner.classList.remove('session-expiry-expired-state');

            const msUntilNextWarn = newExpiresMs - WARN_BEFORE_MS - Date.now();
            if (msUntilNextWarn <= 0) {
                showBanner();
            } else {
                warnTimer = setTimeout(showBanner, msUntilNextWarn);
            }
        } catch {
            window.location.href = '/admin/login';
        }
    };

    window.sessionDismiss = function () {
        dismissed = true;
        banner.style.display = 'none';
    };
})();

// ─── Prevent double-submit ─────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('form').forEach((form) => {
        form.addEventListener('submit', () => {
            const btn = form.querySelector('[type="submit"]');
            if (btn) {
                btn.disabled = true;
                btn.textContent = 'Please wait…';
            }
        });
    });
});
