"""Stage native-only conda-forge runtime libraries into a wheel build directory.

The prefix is a build input, never a Python runtime dependency. Linux requires
patchelf; macOS wheels must subsequently pass delocate-wheel verification.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


def stage_runtime(prefix, destination):
    prefix, destination = Path(prefix).resolve(), Path(destination)
    if destination.exists():
        shutil.rmtree(destination)
    lib_source = prefix / ("Library/bin" if sys.platform == "win32" else "lib")
    share = prefix / ("Library/share" if sys.platform == "win32" else "share")
    if not (prefix / "conda-meta").is_dir():
        raise RuntimeError(
            "Native prefix must be a native-only conda-forge environment"
        )
    records = [
        json.loads(p.read_text())
        for p in sorted((prefix / "conda-meta").glob("*.json"))
    ]
    if any(r["name"] in {"python", "gdal", "numpy", "netcdf4"} for r in records):
        raise RuntimeError("Native runtime prefix must not contain Python packages")
    target = destination / "lib"
    target.mkdir(parents=True)
    candidates = {
        p.name: p
        for p in lib_source.iterdir()
        if p.is_file() and re.search(r"\.so(?:\..*)?$|\.dylib$|\.dll$", p.name, re.I)
    }
    canonical = {name.casefold(): name for name in candidates}
    roots = {}
    for family in ("netcdf", "gdal", "proj"):
        matches = [
            p
            for n, p in candidates.items()
            if n in ("lib" + family + ".so", "lib" + family + ".dylib", family + ".dll")
            or (sys.platform == "win32" and n.startswith(family) and n.endswith(".dll"))
        ]
        if not matches:
            raise RuntimeError("Missing native root library: " + family)
        roots[family] = sorted(matches, key=lambda p: len(p.name))[0]
    selected = {p.name: p for p in roots.values()}
    queue = list(roots.values())
    while queue:
        path = queue.pop()
        if sys.platform.startswith("linux"):
            env = dict(os.environ, LD_LIBRARY_PATH=str(lib_source))
            text = subprocess.check_output(["ldd", str(path)], env=env, text=True)
            if "not found" in text:
                raise RuntimeError("Unresolved native dependency: " + text)
            dependencies = re.findall(r"=> (\S+)", text)
        elif sys.platform == "darwin":
            text = subprocess.check_output(["otool", "-L", str(path)], text=True)
            dependencies = [
                line.strip().split(" (", 1)[0] for line in text.splitlines()[1:]
            ]
        else:
            import pefile

            with pefile.PE(str(path)) as pe:
                dependencies = [
                    d.dll.decode() for d in getattr(pe, "DIRECTORY_ENTRY_IMPORT", [])
                ]
                dependencies += [
                    d.dll.decode()
                    for d in getattr(pe, "DIRECTORY_ENTRY_DELAY_IMPORT", [])
                ]
        for dependency in dependencies:
            name = Path(dependency).name
            if sys.platform == "win32":
                name = canonical.get(name.casefold(), name)
            if name not in candidates:
                continue  # OS libraries remain provided by the platform.
            if name not in selected:
                selected[name] = candidates[name]
                queue.append(candidates[name])
    paths = []
    for name, source in sorted(selected.items()):
        out = target / name
        shutil.copy2(source, out)
        paths.append(out)
    if sys.platform.startswith("linux"):
        for path in paths:
            subprocess.run(
                ["patchelf", "--set-rpath", "$ORIGIN", str(path)], check=True
            )
    elif sys.platform == "darwin":
        names = {p.name for p in paths}
        for path in paths:
            subprocess.run(
                ["install_name_tool", "-id", "@rpath/" + path.name, str(path)],
                check=True,
            )
            deps = subprocess.check_output(["otool", "-L", str(path)], text=True)
            for line in deps.splitlines()[1:]:
                dependency = line.strip().split(" (", 1)[0]
                name = Path(dependency).name
                if name in names:
                    subprocess.run(
                        [
                            "install_name_tool",
                            "-change",
                            dependency,
                            "@loader_path/" + name,
                            str(path),
                        ],
                        check=True,
                    )
        for path in paths:
            subprocess.run(
                ["codesign", "--force", "--sign", "-", str(path)], check=True
            )
    libraries = {family: "lib/" + path.name for family, path in roots.items()}
    for name in ("gdal", "proj"):
        source = share / name
        if not source.is_dir():
            raise RuntimeError("Missing native data directory: " + name)
        shutil.copytree(source, destination / "share" / name)
    if not (destination / "share/proj/proj.db").is_file():
        raise RuntimeError("Missing PROJ coordinate reference database")
    inventory = []
    for record in records:
        name = record["name"]
        license_root = (
            Path(
                record.get("extracted_package_dir")
                or record.get("link", {}).get("source", "")
            )
            / "info/licenses"
        )
        owned = set(record.get("files", []))
        included = {p.relative_to(prefix).as_posix() for p in selected.values()}
        if not owned.intersection(included) and not any(
            f.startswith(
                (
                    "share/gdal/",
                    "share/proj/",
                    "Library/share/gdal/",
                    "Library/share/proj/",
                )
            )
            for f in owned
        ):
            continue
        license_files = [p for p in license_root.rglob("*") if p.is_file()]
        installed_licenses = [
            prefix / f for f in owned if "/licenses/" in f and (prefix / f).is_file()
        ]
        if not license_files and not installed_licenses and name == "libsqlite":
            # SQLite's public-domain dedication is embedded in its API header.
            installed_licenses = [
                prefix / f
                for f in owned
                if f.endswith("/sqlite3.h") and (prefix / f).is_file()
            ]
        if not license_files and not installed_licenses:
            raise RuntimeError("Missing redistribution license files for " + name)
        for source in license_files:
            out = destination / "licenses" / name / source.relative_to(license_root)
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, out)
        for source in installed_licenses:
            out = destination / "licenses" / name / source.relative_to(prefix)
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, out)
        inventory.append(
            {
                k: record[k]
                for k in ("name", "version", "build", "license", "url", "sha256")
                if k in record
            }
        )
    manifest = {
        "format": 1,
        "platform": sys.platform,
        "libraries": libraries,
        "files": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
        "packages": inventory,
        "data": {"gdal": "share/gdal", "proj": "share/proj"},
    }
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prefix", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    result = stage_runtime(args.prefix, args.destination)
    print("Bundled libraries:", result["libraries"])
