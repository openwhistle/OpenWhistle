"""Download axe-core AXE_VERSION from npm into tests/e2e/vendor/ and pin its hash.

    uv run python scripts/vendor_axe.py

Renovate bumps AXE_VERSION in tests/e2e/conftest.py; this writes the file and
the matching AXE_SHA256. Until it runs, tests/test_renovate.py is red.
"""

import hashlib
import io
import re
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFTEST = ROOT / "tests" / "e2e" / "conftest.py"
TARGET = ROOT / "tests" / "e2e" / "vendor" / "axe.min.js"

text = CONFTEST.read_text()
match = re.search(r'^AXE_VERSION = "([\d.]+)"', text, re.M)
assert match, "AXE_VERSION not found in conftest.py"
version = match.group(1)
url = f"https://registry.npmjs.org/axe-core/-/axe-core-{version}.tgz"
with urllib.request.urlopen(url, timeout=30) as resp:  # noqa: S310 - fixed npm registry URL
    tar = tarfile.open(fileobj=io.BytesIO(resp.read()))
member = tar.extractfile("package/axe.min.js")
assert member, "package/axe.min.js missing from the tarball"
data = member.read()
TARGET.parent.mkdir(parents=True, exist_ok=True)
TARGET.write_bytes(data)
digest = hashlib.sha256(data).hexdigest()
CONFTEST.write_text(
    re.sub(r'^AXE_SHA256 = "[0-9a-f]*"', f'AXE_SHA256 = "{digest}"', text, flags=re.M)
)
print(f"axe-core {version}: {digest}")
