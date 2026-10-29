"""Every production module must import with all historical Python libraries blocked."""

import ast
import importlib
from pathlib import Path
import pkgutil
import unittest
import klimapy
from test_environment import FORBIDDEN


class PackageBoundaryTests(unittest.TestCase):
    def test_all_production_modules_import_in_clean_test(self):
        names = [
            m.name
            for m in pkgutil.walk_packages(klimapy.__path__, klimapy.__name__ + ".")
        ]
        self.assertTrue(any(n.endswith("ETCCDI.ETCCDI") for n in names))
        self.assertTrue(any(n.endswith("Supporting_Tools.NCtoTIFF") for n in names))
        for name in names:
            # The C-ABI shared library is loaded by ctypes, not PyInit.
            if name.rsplit(".", 1)[-1] == "_native_core":
                continue
            importlib.import_module(name)

    def test_production_has_no_historical_imports(self):
        forbidden = set(FORBIDDEN)
        bad = []
        for path in Path(klimapy.__file__).parent.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [n.name for n in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0:
                    names = [node.module or ""]
                else:
                    continue
                for name in names:
                    if name.split(".")[0] in forbidden:
                        bad.append(f"{path.name}:{node.lineno}: {name}")
        self.assertEqual(bad, [])
