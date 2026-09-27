#!/usr/bin/env node
// Renders every diagram in docs/_diagrams/*.mmd to a committed SVG, one per theme,
// via `npx @mermaid-js/mermaid-cli` pinned to an exact version.
//
// Node only runs this rendering step locally; every *check* (staleness, palette,
// no external references, no <script>) is a pytest test in tests/test_diagrams.py
// and needs no node at all — see that file and docs-tech/release.md.
//
//   node scripts/render_diagrams.mjs            render everything
//   node scripts/render_diagrams.mjs --check     fail if a diagram is missing or out of date
//
// Reference: docs/_diagrams/README.md (how to embed a rendered diagram as a
// themed figure).

import { createHash } from 'node:crypto';
import { readFile, writeFile, mkdir, readdir, mkdtemp, rm } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import os from 'node:os';
import path from 'node:path';

const ROOT = path.resolve(import.meta.dirname, '..');
const SRC_DIR = path.join(ROOT, 'docs', '_diagrams');
const OUT_DIR = path.join(ROOT, 'docs', 'img', 'diagrams');
const CHECK = process.argv.includes('--check');

// Not the docs site's own font (Sora, self-hosted from docs/fonts/): mermaid-cli
// only ever appends a `-C cssFile`'s content into the finished SVG's <style>
// *after* `mermaid.render()` has already measured and fixed every node's box
// size (mermaid-cli's src/index.js, renderMermaid — `myCSS` is appended to
// `container.innerHTML` only once `svg` already exists). A `@font-face` supplied
// that way can never be loaded before the layout it would need to affect, so
// "Sora" in a themeVariable resolves to this same fallback stack for the
// measurement pass regardless — and then, if a real Sora font-face were also
// embedded for display, every box would be sized for the fallback while showing
// Sora's (wider) glyphs, clipping text. Verified by rendering a two-node diagram
// both ways: identical geometry with or without an embedded Sora, and visibly
// clipped labels once Sora was actually loaded for display. Generic throughout —
// measured and displayed in the same font — is the one combination mermaid-cli
// can render correctly; ponytail: no custom font, revisit only if mermaid-cli
// adds a pre-render style hook.
const FONT_FAMILY = 'system-ui, sans-serif';

// mermaid-cli is not a project dependency (there is no package.json here — this is
// a Python project); `npx` fetches it into its own cache the first time. Pinned to
// an exact version, not a range, for the same reason easywall pins mermaid itself:
// a renderer upgrade silently moves node geometry, and the digest below folds the
// version in so an upgrade shows up as "needs re-render" instead of a mismatch
// nobody can explain.
const MERMAID_CLI_VERSION = '11.9.0';

// Both themes, because the docs site follows the reader's `data-theme`. Values
// are the CSS custom properties from docs/docs.html — keep them in step with
// that file's `:root` (light) and `[data-theme="dark"]` blocks. Checked against
// docs.html by tests/test_diagrams.py::test_palette_matches_docs_site so a
// stylesheet redesign that forgets this file fails loudly instead of leaving
// four committed pictures in the old colours.
const THEMES = {
  light: {
    background: 'transparent',
    primaryColor: '#efefee', // --bg-raised
    primaryTextColor: '#0a0a0b', // --text-primary
    primaryBorderColor: '#c9c9c6', // --border-strong
    secondaryColor: '#f6f6f5', // --bg-surface
    tertiaryColor: '#ffffff', // --bg-base
    noteBkgColor: '#e9e9e8', // --bg-overlay
    noteTextColor: '#6a6a6e', // --text-muted
    noteBorderColor: '#e6e6e4', // --border-subtle
    lineColor: '#3d3d40', // --text-secondary
    fontFamily: FONT_FAMILY,
    fontSize: '16px',
  },
  dark: {
    background: 'transparent',
    primaryColor: '#1b1b1e', // --bg-raised
    primaryTextColor: '#fafafa', // --text-primary
    primaryBorderColor: '#43434a', // --border-strong
    secondaryColor: '#131315', // --bg-surface
    tertiaryColor: '#08080a', // --bg-base
    noteBkgColor: '#232327', // --bg-overlay
    noteTextColor: '#8e8e93', // --text-muted
    noteBorderColor: '#262629', // --border-subtle
    lineColor: '#bcbcc0', // --text-secondary
    fontFamily: FONT_FAMILY,
    fontSize: '16px',
  },
};

// Emitted regardless of themeVariables, in every mermaid-cli render: a
// `.katex path{fill:#000;stroke:#000}` rule (for a diagram that uses math), an
// `.error-icon`/`.error-text` rule (for a diagram mermaid failed to parse) whose
// colour mermaid derives from the theme's own contrast logic rather than from a
// themeVariable, and a `feDropShadow` node-shadow filter with
// `flood-color="#000000"`. None of our diagrams uses KaTeX, fails to parse, or is
// drawn with a visible drop shadow, so all three are dead CSS that never touches
// a rendered pixel — but the literal bytes are still in the file, and
// tests/test_diagrams.py checks the file's bytes. Documented here rather than
// post-processed away, so a change in this constant is a one-line diff next to
// the reason for it. Kept as a JS array literal (not JSON) so the Python test can
// parse it out of this file with the same regex it uses for the theme objects.
export const HARMLESS_MERMAID_BOILERPLATE_COLORS = ['#000', '#000000', '#f7f7f5'];

const STAMP = 'data-source-digest';

function digest(mermaidCliVersion, source) {
  return createHash('sha256')
    .update(`${mermaidCliVersion}\n${source.trim()}`)
    .digest('hex')
    .slice(0, 16);
}

async function sources() {
  if (!existsSync(SRC_DIR)) return [];
  const names = (await readdir(SRC_DIR)).filter((n) => n.endsWith('.mmd')).sort();
  return Promise.all(
    names.map(async (name) => ({
      name: name.replace(/\.mmd$/, ''),
      source: await readFile(path.join(SRC_DIR, name), 'utf8'),
    })),
  );
}

async function check(diagrams) {
  const problems = [];
  for (const d of diagrams) {
    for (const theme of Object.keys(THEMES)) {
      const file = path.join(OUT_DIR, `${d.name}-${theme}.svg`);
      if (!existsSync(file)) {
        problems.push(`${d.name}-${theme}.svg is missing`);
        continue;
      }
      const svg = await readFile(file, 'utf8');
      const m = svg.match(new RegExp(`${STAMP}="([a-f0-9]+)"`));
      const want = digest(MERMAID_CLI_VERSION, d.source);
      if (!m || m[1] !== want) {
        problems.push(
          `${d.name}-${theme}.svg is stale — ${d.name}.mmd changed, or it ` +
            `was rendered by a mermaid-cli other than ${MERMAID_CLI_VERSION}`,
        );
      }
    }
  }
  if (problems.length) {
    console.error('Diagrams out of date — run: node scripts/render_diagrams.mjs\n');
    for (const p of problems) console.error('  ' + p);
    process.exitCode = 1;
    return;
  }
  console.log(`${diagrams.length} diagram(s), all current`);
}

// Looks for a Chromium the machine already has, newest first, so mermaid-cli's
// puppeteer dependency does not download its own on every contributor's machine.
async function findChromium() {
  if (process.env.PLAYWRIGHT_CHROMIUM) return process.env.PLAYWRIGHT_CHROMIUM;
  const cache = path.join(os.homedir(), '.cache', 'ms-playwright');
  if (existsSync(cache)) {
    const dirs = (await readdir(cache))
      .filter((d) => d.startsWith('chromium-') && !d.includes('headless_shell'))
      .sort()
      .reverse();
    for (const d of dirs) {
      const exe = path.join(cache, d, 'chrome-linux64', 'chrome');
      if (existsSync(exe)) return exe;
    }
  }
  for (const exe of ['/usr/bin/chromium', '/usr/bin/chromium-browser', '/usr/bin/google-chrome']) {
    if (existsSync(exe)) return exe;
  }
  return null; // let puppeteer fetch its own as a last resort
}

async function render(diagrams) {
  await mkdir(OUT_DIR, { recursive: true });
  const tmp = await mkdtemp(path.join(os.tmpdir(), 'ow-diagrams-'));
  const chromium = await findChromium();

  const puppeteerConfig = path.join(tmp, 'puppeteer.json');
  await writeFile(
    puppeteerConfig,
    JSON.stringify({ executablePath: chromium ?? undefined, args: ['--no-sandbox'] }),
  );

  for (const d of diagrams) {
    const mmdFile = path.join(tmp, `${d.name}.mmd`);
    await writeFile(mmdFile, d.source, 'utf8');

    for (const [theme, vars] of Object.entries(THEMES)) {
      const configFile = path.join(tmp, `${d.name}-${theme}.config.json`);
      await writeFile(
        configFile,
        JSON.stringify({
          theme: 'base',
          themeVariables: vars,
          // Concrete pixels, not width:100%: an <img> source needs an intrinsic
          // size to reserve layout before the file arrives.
          flowchart: { htmlLabels: false, curve: 'basis', useMaxWidth: false },
          state: { useMaxWidth: false },
          securityLevel: 'strict',
        }),
      );

      const svgId = `${d.name}-${theme}`;
      const outFile = path.join(tmp, `${svgId}.svg`);
      const args = [
        '--yes',
        `@mermaid-js/mermaid-cli@${MERMAID_CLI_VERSION}`,
        '-i', mmdFile,
        '-o', outFile,
        '-c', configFile,
        '-p', puppeteerConfig,
        '-b', 'transparent',
        '-I', svgId,
        '-q',
      ];
      const run = spawnSync('npx', args, { encoding: 'utf8' });
      if (run.status !== 0) {
        throw new Error(`mermaid-cli failed on ${d.name} (${theme}):\n${run.stderr}`);
      }

      let svg = await readFile(outFile, 'utf8');
      const want = digest(MERMAID_CLI_VERSION, d.source);
      svg = svg.replace('<svg ', `<svg ${STAMP}="${want}" `);
      await writeFile(path.join(OUT_DIR, `${svgId}.svg`), svg, 'utf8');
    }
    console.log(`  ${d.name}`);
  }

  await rm(tmp, { recursive: true, force: true });
}

async function main() {
  const diagrams = await sources();
  if (diagrams.length === 0) {
    console.log(`no .mmd files in ${path.relative(ROOT, SRC_DIR)}`);
    return;
  }
  if (CHECK) return check(diagrams);

  await render(diagrams);
  console.log(`rendered ${diagrams.length} diagram(s) x ${Object.keys(THEMES).length} themes`);
}

main().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
