# openwhistle

Das EU-Whistleblower-Gesetz (Richtlinie (EU) 2019/1937) verpflichtet Unternehmen (ab 50 Mitarbeitern) und Behörden zur Einrichtung sicherer interner Meldekanäle, um Hinweisgeber vor Repressalien zu schützen. In Deutschland wurde dies durch das Hinweisgeberschutzgesetz (HinSchG) umgesetzt, das seit dem 2. Juli 2023 in Kraft ist und Repressalien verbietet.

Referenz zum Hinweisgeberschutzgesetz zum nachlesen: https://www.gesetze-im-internet.de/hinschg/

OpenWhistle ist eine Plattform, wo ein Whistleblower die Möglichkeit hat eine Meldung abzugeben.

Folgende Fakten sind festgelegt:

- Die Serverseite des Programms läuft in einem Docker Container
- Die Serverseite muss immer stateless laufen
- Die Datenhaltung erfolgt in einer PostgreSQL Datenbank.
- Caches oder Sessions oder alles, was die Stateless Applikation stören könnte, soll in Redis festgehalten werden
- Die Sicherheit des Programms ist sehr wichtig, es dürfen keine Daten nach außen gelangen können
- Die Sicherheit des Whistleblowers ist sehr wichtig und seine Identität soll zu 100% geschützt sein
- Der Whistleblower bekommt nach seiner Meldung eine PIN, mit der er sich wieder einloggen kann
- Die PIN muss sicher gestaltet sein. Also z.B. eine GUID oder ähnliches, keine 4-stellige PIN, die man erraten könnte.
- Nach der Installation muss über einen Web-basierten Wizard ein Admin Account angelegt werden
- Multi Faktor Authentifizierung ist verpflichtend für alle Benutzerkonten
- Es soll der Login über Datenbank oder OIDC möglich sein
- Programmiert wird immer auf Englisch. Es gibt keine Deutschen Kommentare oder Deutsche Inhalte.
- Die README und andere Dokumentation ist ebenfalls immer auf Englisch.
- Die Software wird unter der Lizenz "GNU General Public License v3.0" veröffentlicht
- Die Versionierung erfolgt über semantische Versionierung
- Es wird für jede Version ein Changelog in der Datei "CHANGELOG.md" geschrieben
- Es soll eine Live Demo der Software unter der URL "<https://demo.openwhistle.net>" geben.
- Für die Demo sollen die Zugangsdaten Benutzername und Passwort "demo" sein.
- Die Demo wird automatisch jede Stunde geleert und neu gestartet.
- Es gibt eine Website "openwhistle.net", die aktuell auf die GitHub Page weiterleitet. Zukünftig soll dort eine GitHub Page aus dem Repository laufen, wo Informationen über OpenWhistle stehen und auch die Dokumentation gehostet wird.
- Wichtig ist, dass der Whistleblower geschützt wird und sogar keine Logs über seine IP-Adresse vorhanden sind. So kann z.B. ein Mitarbeiter eines Unternehmens geschützt sein, der im Büro eine Nachricht verschickt.
- Das ganze Projekt wird in der Freizeit entwickelt und es kann gespendet werden.
- Es sollen unter GitHub die Sicherheitsfeatures genutzt werden, um den Code zu scannen und Dependencies zu scannen.
- Wenn du eine technische Entscheindung triffst, aktualisiere bitte immer die README.md mit aktuellen Daten
- Der Docker Container soll für jede Version immer auf der GitHub Container Registry, DockerHub und quay.io über einen GitHub Workflow / Action gepushed werden
- Beim erstellen von Commit Messages erwähnst du bitte nicht Claude Code
- Du hast Zugriff auf GitHub über die GitHub CLI
- Markdown Dokumente müssen nach markdownlint Vorgaben erstellt werden
- Documentation in `docs/docs.html`, `README.md`, and `docker-compose.prod.yml` must always be kept in sync. When adding or renaming environment variables, update ALL locations in the same commit.
- The demo at https://demo.openwhistle.net is live and hosted on Hetzner (root01xvp.wdkro.de) via Ansible. It resets hourly.
- All HTML files in `docs/` must use self-hosted fonts from `docs/fonts/` — never Google Fonts CDN or any other external font CDN.

Der Code wird auf GitHub in einem öffentlichen Repository von der Organisation openwhistle gehostet.
Der Code liegt hier: <https://github.com/openwhistle/OpenWhistle>

Für das Design des Frontends beachte bitte folgenden Text:

DISTILLED_AESTHETICS_PROMPT = """
<frontend_aesthetics>
You tend to converge toward generic, "on distribution" outputs. In frontend design, this creates what users call the "AI slop" aesthetic. Avoid this: make creative, distinctive frontends that surprise and delight. Focus on:

Typography: Choose fonts that are beautiful, unique, and interesting. Avoid generic fonts like Arial and Inter; opt instead for distinctive choices that elevate the frontend's aesthetics.

Color & Theme: Commit to a cohesive aesthetic. Use CSS variables for consistency. Dominant colors with sharp accents outperform timid, evenly-distributed palettes. Draw from IDE themes and cultural aesthetics for inspiration.

Motion: Use animations for effects and micro-interactions. Prioritize CSS-only solutions for HTML. Use Motion library for React when available. Focus on high-impact moments: one well-orchestrated page load with staggered reveals (animation-delay) creates more delight than scattered micro-interactions.

Backgrounds: Create atmosphere and depth rather than defaulting to solid colors. Layer CSS gradients, use geometric patterns, or add contextual effects that match the overall aesthetic.

Avoid generic AI-generated aesthetics:

- Overused font families (Inter, Roboto, Arial, system fonts)
- Clichéd color schemes (particularly purple gradients on white backgrounds)
- Predictable layouts and component patterns
- Cookie-cutter design that lacks context-specific character

Interpret creatively and make unexpected choices that feel genuinely designed for the context. Vary between light and dark themes, different fonts, different aesthetics. You still tend to converge on common choices (Space Grotesk, for example) across generations. Avoid this: it is critical that you think outside the box!
</frontend_aesthetics>
"""
