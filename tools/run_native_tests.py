"""Guard first, then discover only the dependency-free native acceptance suite."""

import argparse
from pathlib import Path
import sys
import unittest

from test_environment import verify


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installed", action="store_true")
    args = parser.parse_args()
    verify(installed=args.installed)
    print(
        "Acceptance scope: tests/native; legacy compatibility tests are not executed",
        flush=True,
    )
    root = Path(__file__).resolve().parents[1]
    suite = unittest.defaultTestLoader.discover(str(root / "tests" / "native"))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.skipped or result.testsRun == 0:
        print(
            "Native acceptance requires executed tests with no skips", file=sys.stderr
        )
        return 1
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
