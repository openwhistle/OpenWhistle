# Branding admin page: design

Type: explanation + scope. Approved by the maintainer on 2026-10-14 after a three-track study (FOSS
whistleblowing tools, general self-hosted FOSS, WCAG/OWASP). The study's sources are listed at the end.

## Goal

An operator brands the reporter's pages from the admin area: name, logo (light and dark), brand colour, with a
live preview in both themes. Today the only way is `APP_NAME`, `BRAND_PRIMARY_COLOR` and `BRAND_LOGO_URL`, and
the logo has to be a path on the server's read-only image or a `data:` URI in an environment variable.

## Decisions

| Topic | Decision | Precedent |
|---|---|---|
| Where | `/admin/branding`, one page, a form beside a live preview of both themes | Nextcloud, Discourse, Hush Line |
| Logo formats | PNG, JPEG, WebP, at most 1 MB. **No SVG** | GlobaLeaks, SecureDrop, Hush Line, Mastodon; 1 MB GitLab |
| Logo processing | Decode with Pillow, re-encode as PNG, metadata dropped, scaled to display size | Mattermost, Matomo, Mastodon; OWASP File Upload |
| Dark mode | Optional second logo; without it the light logo is used in both themes | Discourse `logo_dark`, Keycloak, authentik |
| Storage | PostgreSQL (`branding` table, images as `bytea`); the app stays stateless | GlobaLeaks, Zammad (DB store) |
| Colour | Picker plus hex field; the server derives the on-brand text colour and a link/focus colour per theme | Nextcloud `Util.php` |
| Colour output | The existing nonce'd `<style>` in `base.html`, never `style-src 'unsafe-inline'` | Hush Line #821 as the counter-example |
| Preview | Client-side, before saving; logo through `FileReader` → `data:` URL, already allowed by `img-src 'self' data:` | Mattermost |
| Reset | Per field and all at once | Nextcloud, Discourse |
| Organisations | Each organisation may have its own branding; a field it leaves empty falls back to the instance default | GlobaLeaks, Keycloak realms, authentik brands |
| Favicon | Generated from the light logo (32 px and 180 px PNG) | Nextcloud, Mastodon |
| Footer | Not brandable; "Powered by OpenWhistle" stays | Maintainer decision; GlobaLeaks (licence) |
| Custom CSS/JS | Not offered: an XSS surface on the reporter's pages | GlobaLeaks gates it behind re-authentication; we leave it out |
| Logo alt text | `alt=""`: the name is printed beside the logo, so a screen reader read it twice | W3C WAI images tutorial |

## Data model

Migration `018_branding`:

| Column | Type | Note |
|---|---|---|
| `id` | UUID PK | |
| `org_id` | UUID FK `organisations.id`, nullable, unique | `NULL` is the instance default; at most one such row |
| `name` | `String(64)`, nullable | Display name in nav and page titles |
| `primary_color` | `String(7)`, nullable | `#rrggbb`, lower case |
| `logo_light`, `logo_dark` | `LargeBinary`, nullable | Processed PNG |
| `favicon_32`, `favicon_180` | `LargeBinary`, nullable | Generated from `logo_light` |
| `updated_at` | `DateTime(tz)` | |
| `updated_by_id` | UUID FK `admin_users.id`, `ON DELETE SET NULL` | |

A partial unique index enforces one row with `org_id IS NULL`.

## Resolution

For every page, each field resolves in this order: the organisation's row, the instance row, the environment
(`APP_NAME`, `BRAND_PRIMARY_COLOR`, `BRAND_LOGO_URL`), the built-in default. The organisation is the one the
page serves: the wizard's slug, the case on `/status`, the signed-in admin's organisation, else the default
organisation.

The resolved branding is cached in Redis per organisation (key `branding:<org_id|default>`, 1 h) and the cache
is deleted on every save and reset, so a page view costs no database query. Images are served from
`/branding/<sha256>.png`: the hash of the PNG bytes, so the URL names no organisation, changes whenever the
image does, and can be cached `immutable`. Response headers: `Content-Type: image/png`,
`X-Content-Type-Options: nosniff`, `Cache-Control: public, max-age=31536000, immutable`. An unknown hash is
404.

## Logo pipeline

1. Reject when the upload is over 1 MB, before reading it into Pillow.
2. `Image.open` with `Image.MAX_IMAGE_PIXELS` set to 16 megapixels (decompression bomb); accept only the
   formats `PNG`, `JPEG`, `WEBP` as Pillow detects them from the content, never from the name or the declared
   type.
3. `ImageOps.exif_transpose`, convert to `RGBA`, scale to a height of 96 px (nav shows 32 px, 3× for dense
   screens), never upscale.
4. Save as PNG with no `info`, `exif` or `icc_profile`: nothing of the original file survives but pixels.
5. Favicons: the light logo letterboxed onto a transparent square, 32 px and 180 px.

## Colour

Input: `^#[0-9a-fA-F]{6}$`, stored lower case. From it the server computes, with the WCAG 2.x relative
luminance and contrast formula:

| Token | Rule |
|---|---|
| `--brand-on` (text on brand fills, light theme) | White or near-black, whichever contrasts more with the brand colour; this is never below 4.5:1 |
| `--accent` light (links, focus, outlines on `#fff`) | The brand colour, mixed towards black in 2 % steps until it reaches 4.5:1 against the light canvas |
| `--accent` dark (on `#0a0a0b`) | The brand colour, mixed towards white in 2 % steps until 4.5:1 against the dark canvas |
| `--cta-bg` dark | The dark accent; its text colour by the same rule as `--brand-on` |

4.5:1 for links covers the 3:1 that focus rings and component edges need (WCAG 2.2 SC 1.4.3, 1.4.11). The
default colour `#0c7253` keeps the exact values DESIGN.md names (`_DESIGN_ACCENT`). The form shows the
achieved ratios beside the field; it never refuses a colour, because the derived tokens always meet AA.

## Permissions and audit

| Who | May edit |
|---|---|
| Instance admin (`may_run_the_instance`) | The instance default; with multi-tenancy also any organisation, chosen in a selector |
| Organisation admin (multi-tenancy, role `admin`) | Their own organisation's row |
| Case manager | Nothing: the page is 403 and not in the menu |

Every save writes an audit entry `branding.updated` with the changed field names (never the image bytes), every
reset `branding.reset` with the fields reset. Saves go through the existing CSRF check.

## The page

Left: name, light logo, dark logo, colour (native `<input type="color">` and a labelled hex text field kept in
sync), the contrast ratios, Save and Reset. Each image shows its current value with a "Remove" control.
Right: two preview panels, light and dark, each a miniature nav (logo, name), a primary button, a link and a
focused button. The script updates them on every input through the CSSOM (`style.setProperty`, allowed under
the CSP) and computes the same ratios in the browser; the server's values are the ones that are saved.

## Environment variables

`APP_NAME`, `BRAND_PRIMARY_COLOR` and `BRAND_LOGO_URL` stay, as the installation's starting values below the
page's. Documentation says so; nothing else changes for deployments that set them.

## Tests (each must fail without its change)

| Test | Fails when |
|---|---|
| An SVG, an HTML file renamed `.png`, and a 1.1 MB PNG are refused | The type is taken from the name or the size is not checked |
| A JPEG with EXIF GPS comes back as PNG with no metadata and at most 96 px high | The image is stored as uploaded |
| A 20 000 × 20 000 PNG is refused, not decoded | `MAX_IMAGE_PIXELS` is not set |
| Derived tokens meet 4.5:1 for 200 random colours, both themes | A derivation step is missing |
| The default colour yields exactly the DESIGN.md values | The default path changes |
| An organisation's page shows its logo and name; another organisation's shows the default | Resolution ignores the organisation |
| A case manager gets 403; an organisation admin cannot edit another organisation | Permission check missing |
| `/branding/<hash>.png` sends `nosniff` and `image/png`; an unknown hash is 404 | Headers or lookup wrong |
| Saving clears the cache: the next page shows the new name | Cache not invalidated |
| No public page carries `'unsafe-inline'` in its CSP after branding is set | Colour output bypasses the nonce |
| The nav logo has `alt=""` | Alt text reverts to the name |
| E2E: preview updates on colour input before saving; light and dark panels both change | Preview script broken |

The new guards go through `scripts/mutation_audit.py`; the UI through the Chrome check.

## Documentation

- README: feature bullet; the three env vars described as starting values.
- DESIGN.md: how a brand colour derives its tokens; logos in both themes.
- Website (drift rule, linked PR): admin guide section "Branding" with screenshots; configuration reference for
  the three env vars.
- CHANGELOG under Unreleased.

## Sources

- Nextcloud: <https://github.com/nextcloud/server/blob/master/apps/theming/lib/Util.php>
- Hush Line: <https://github.com/scidsg/hushline/blob/4ce8770/hushline/settings/branding.py>,
  <https://github.com/scidsg/hushline/issues/821>
- GlobaLeaks: <https://github.com/globaleaks/globaleaks-whistleblowing-software/blob/41d4ddb/backend/globaleaks/handlers/admin/file.py>
- SecureDrop: <https://github.com/freedomofpress/securedrop/blob/fb5c1f1/securedrop/journalist_app/forms.py#L190>
- Mattermost: <https://github.com/mattermost/mattermost/blob/master/server/channels/app/brand.go>
- Discourse: <https://github.com/discourse/discourse/blob/main/config/site_settings.yml>
- Keycloak: <https://www.keycloak.org/ui-customization/quick-theme>
- GitLab: <https://gitlab.com/gitlab-org/gitlab/-/blob/master/app/models/appearance.rb>
- WCAG 2.2: <https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html>,
  <https://www.w3.org/WAI/WCAG22/Understanding/non-text-contrast.html>
- OWASP: <https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html>
- MDN: <https://developer.mozilla.org/en-US/docs/Web/SVG/Guides/SVG_as_an_image>
- W3C WAI: <https://www.w3.org/WAI/tutorials/images/functional/>
