"""Print the Settings field names of an app/config.py read from stdin.

    git show vX.Y.Z:app/config.py | python3 scripts/list_settings.py

Used to refresh tests/data/previous_release_settings.txt (docs-tech/release.md).
"""

import ast
import sys

source = sys.stdin.read()
print("# Settings fields at the previous release; refresh: see docs-tech/release.md.")
for node in ast.walk(ast.parse(source)):
    if isinstance(node, ast.ClassDef) and node.name == "Settings":
        for item in node.body:
            if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                print(item.target.id)
