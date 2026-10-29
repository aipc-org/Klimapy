"""Portable developer commands; run `python tools/manage.py --help`."""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def run(command, *, installed=False, extra_env=None):
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    if installed:
        paths = env.get("PYTHONPATH", "").split(os.pathsep)
        env["PYTHONPATH"] = os.pathsep.join(
            p for p in paths if p and Path(p).resolve() != ROOT / "src"
        )
    else:
        env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
    if extra_env:
        env.update(extra_env)
    subprocess.run(command, cwd=ROOT, env=env, check=True)


def test_python():
    if (
        Path(sys.prefix).name == "Test"
        and (Path(sys.prefix) / "conda-meta/history").is_file()
    ):
        return sys.executable
    conda = os.environ.get("CONDA_EXE") or shutil.which("conda")
    if not conda and Path("/opt/miniconda3/bin/conda").exists():
        conda = "/opt/miniconda3/bin/conda"
    if conda:
        environments = json.loads(
            subprocess.check_output([conda, "env", "list", "--json"], text=True)
        )["envs"]
        for prefix in environments:
            path = Path(prefix)
            if path.name == "Test":
                executable = path / ("python.exe" if os.name == "nt" else "bin/python")
                if executable.is_file():
                    return str(executable)
    raise RuntimeError(
        "Create the dedicated Test environment first: conda env create -f environment.yml"
    )


def test(*, installed=False, require_rust=False):
    # The native engine is mandatory; retain require_rust as a compatible CLI flag.
    command = [test_python(), str(ROOT / "tools/run_native_tests.py")]
    if installed:
        command.append("--installed")
    run(
        command,
        installed=installed,
        extra_env={
            "PYTHONNOUSERSITE": "1",
            "PYTHONPATH": "" if installed else str(ROOT / "src"),
        },
    )


def compare(*, installed=False):
    command = [test_python(), str(ROOT / "tools/compare_cn05.py")]
    if installed:
        command.append("--installed")
    run(command, installed=installed)


def lint(*, rust=False):
    run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "src/klimapy",
            "tests",
            "benchmarks",
            "tools",
            "setup.py",
            "--select",
            "F821,F822,F823",
        ]
    )
    if rust:
        run(["cargo", "fmt", "--manifest-path", "rust/Cargo.toml", "--check"])
        run(
            [
                "cargo",
                "clippy",
                "--offline",
                "--manifest-path",
                "rust/Cargo.toml",
                "--",
                "-D",
                "warnings",
            ]
        )


def clean(*, apply=False, native=False):
    """Only remove named build/cache outputs; never scientific data directories."""
    candidates = [
        ROOT / name
        for name in (
            "build",
            "dist",
            "wheelhouse",
            "native-dist",
            ".ruff_cache",
            ".pytest_cache",
            ".mypy_cache",
        )
    ]
    candidates.extend((ROOT / "src").glob("*.egg-info"))
    for directory in ("src", "tests", "benchmarks", "tools", "experiments"):
        base = ROOT / directory
        candidates.extend(base.rglob("__pycache__"))
    for directory in ("rust", "experiments"):
        candidates.extend((ROOT / directory).rglob("target"))
    if native:
        base = ROOT / "src/klimapy/_backends"
        candidates.extend(
            base / ("_native_core" + suffix)
            for suffix in (".so", ".pyd", ".dll", ".dylib")
        )
    removed = []
    # Parents before children prevents duplicate traversal after a directory is deleted.
    for path in sorted(set(candidates), key=lambda p: (len(p.parts), str(p))):
        if not path.exists() and not path.is_symlink():
            continue
        print(("remove " if apply else "would remove ") + str(path.relative_to(ROOT)))
        if apply:
            if path.is_symlink() or path.is_file():
                path.unlink()
            else:
                shutil.rmtree(path)
        removed.append(path)
    return removed


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("test", "check"):
        command = sub.add_parser(name)
        command.add_argument(
            "--installed",
            action="store_true",
            help="Test installed wheel instead of injecting src/",
        )
        command.add_argument(
            "--require-rust",
            action="store_true",
            help="Fail if native tests would be skipped",
        )
        if name == "check":
            command.add_argument(
                "--rust", action="store_true", help="Also run cargo fmt/clippy"
            )
    command = sub.add_parser("lint")
    command.add_argument("--rust", action="store_true")
    command = sub.add_parser("build")
    command.add_argument("--rust", choices=("on",), default="on")
    command.add_argument("--outdir", default="dist")
    command.add_argument(
        "--no-isolation",
        action="store_true",
        help="Use an already prepared build environment",
    )
    command = sub.add_parser("clean")
    command.add_argument(
        "--apply",
        action="store_true",
        help="Actually remove listed outputs (default is preview)",
    )
    command.add_argument(
        "--native", action="store_true", help="Also remove the local native library"
    )
    command = sub.add_parser(
        "compare", help="CN05.1 native Test versus independent Test1 references"
    )
    command.add_argument("--installed", action="store_true")
    command = sub.add_parser("benchmark")
    command.add_argument("--repeats", type=int, default=3)
    command.add_argument("--output", default="benchmarks/results/latest.json")
    args = parser.parse_args(argv)
    if args.command in ("lint", "check"):
        lint(rust=args.rust)
    if args.command in ("test", "check"):
        test(installed=args.installed, require_rust=args.require_rust)
        if args.command == "check":
            compare(installed=args.installed)
    elif args.command == "build":
        command = [sys.executable, "-m", "build", "--outdir", args.outdir]
        if args.no_isolation:
            command.append("--no-isolation")
        run(
            command,
            extra_env={"KLIMAPY_BUILD_RUST": "1"},
        )
    elif args.command == "clean":
        clean(apply=args.apply, native=args.native)
    elif args.command == "compare":
        compare(installed=args.installed)
    elif args.command == "benchmark":
        run(
            [
                test_python(),
                "benchmarks/run_rust.py",
                "--repeats",
                str(args.repeats),
                "--output",
                args.output,
            ],
            extra_env={"PYTHONNOUSERSITE": "1", "PYTHONPATH": str(ROOT / "src")},
        )


if __name__ == "__main__":
    try:
        main()
    except (subprocess.CalledProcessError, FileNotFoundError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
