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
