# Carried forward

Found by a piece of work and deliberately not fixed, with enough context to act
on. **Not** a place for defects a release caused — a release is complete or it
is not finished. Newest first.

## After v1.5.0

Every item from the 2026-09-23 audit was closed in v1.5.0. What remains are
limits of the approach, not open defects:

| Area | Limit | Why it stays |
| --- | --- | --- |
| Office files | Excel writes the comment author's name into the comment *text*; content is not rewritten | changing what a whistleblower wrote would alter evidence; the upload page says metadata, not content, is cleaned |
| S3 | Objects stored before v1.5.0 keep keys that contain the filename | renaming needs bucket access at migration time; new objects use a bare UUID, old ones go with retention |
| Search | Only case numbers are searchable | report content is encrypted per report, by design |
| Whistleblower network | An employer's network can still see that the site was visited | outside the application; the whistleblower page says so |
