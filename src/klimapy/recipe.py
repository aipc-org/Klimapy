"""Reproducible local JSON recipes. Run with python -m klimapy.recipe CONFIG."""

import argparse
import hashlib
import json
import platform
import uuid
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

import numpy as np

from ._backends.rust import backend_info
from .native import Field, open_collection, read_field
from .native.quality import quality_report
from .statistics import aggregate, evaluate


def _digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _json_write(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def run_recipe(config, *, output_dir=None):
    """Execute sequential load/aggregate/evaluate steps with explicit parents.

    Paths are relative to the config file. Output directory must be new.
    run.json records success/failure, hashes, versions, parameters and parents.
    This runner provides no caching, resumption, arbitrary code or remote jobs.
    """
    if not isinstance(config, (str, Path)):
        raise TypeError("Pass a JSON configuration file path")
    config = Path(config).resolve()
    raw = config.read_bytes()

    def invalid_constant(value):
        raise ValueError("Invalid JSON numeric constant: " + value)

    plan = json.loads(raw, parse_constant=invalid_constant)
    if (
        not isinstance(plan, dict)
        or plan.get("schema_version") != 1
        or not isinstance(plan.get("steps"), list)
        or not plan["steps"]
    ):
        raise ValueError("Recipe requires schema_version=1 and a nonempty steps list")
    if set(plan) - {"schema_version", "steps", "output_dir"}:
        raise ValueError("Unknown recipe fields")
    destination = output_dir if output_dir is not None else plan.get("output_dir")
    if not isinstance(destination, (str, Path)):
        raise TypeError("Specify output_dir")
    destination = Path(destination)
    if not destination.is_absolute():
        destination = config.parent / destination
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=False)
    record = {
        "schema_version": 1,
        "run_id": str(uuid.uuid4()),
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "config_sha256": hashlib.sha256(raw).hexdigest(),
        "configuration": plan,
        "status": "running",
        "versions": {
            "klimapy": version("klimapy"),
            "numpy": np.__version__,
            "python": platform.python_version(),
            **backend_info(),
        },
        "inputs": [],
        "steps": [],
    }
    package = Path(__file__).parent
    code_hash = hashlib.sha256()
    for path in sorted(
        [*package.rglob("*.py"), *package.glob("_backends/_native_core.*")]
    ):
        code_hash.update(str(path.relative_to(package)).encode())
        code_hash.update(bytes.fromhex(_digest(path)))
    record["versions"]["package_code_sha256"] = code_hash.hexdigest()
    record["versions"]["platform"] = platform.platform()
    objects = {}
    fingerprints = {}
    try:
        for step in plan["steps"]:
            entry = {
                "configuration": step,
                "status": "running",
                "parents": [],
                "outputs": [],
            }
            record["steps"].append(entry)
            if not isinstance(step, dict) or set(step) - {
                "id",
                "operation",
                "source",
                "reference",
                "paths",
                "variable",
                "parameters",
                "qc",
                "cell_area",
            }:
                raise ValueError("Invalid step fields")
            identifier = step.get("id")
            if (
                not isinstance(identifier, str)
                or not identifier.isidentifier()
                or identifier in objects
            ):
                raise ValueError("Step id must be a unique identifier")
            parameters = step.get("parameters", {})
            op = step.get("operation")
            allowed = {
                "load": {"id", "operation", "paths", "variable", "parameters", "qc"},
                "aggregate": {"id", "operation", "source", "parameters", "qc"},
                "evaluate": {
                    "id",
                    "operation",
                    "source",
                    "reference",
                    "cell_area",
                    "parameters",
                    "qc",
                },
            }
            if op not in allowed or set(step) - allowed[op]:
                raise ValueError("Unsupported operation or fields for operation")
            if op == "load":
                paths = step.get("paths")
                if (
                    not isinstance(paths, list)
                    or not paths
                    or not all(isinstance(p, str) for p in paths)
                    or not isinstance(step.get("variable"), str)
                    or not isinstance(parameters, dict)
                    or set(parameters) - {"collection"}
                    or not isinstance(parameters.get("collection", True), bool)
                ):
                    raise ValueError(
                        "load requires explicit paths, variable and optional collection flag"
                    )
                resolved = [(config.parent / p).resolve() for p in paths]
                for path in resolved:
                    stat = path.stat()
                    fingerprint = (stat.st_size, stat.st_mtime_ns)
                    if path in fingerprints and fingerprints[path] != fingerprint:
                        raise RuntimeError(
                            "Input changed during recipe execution: " + str(path)
                        )
                    fingerprints[path] = fingerprint
                    record["inputs"].append(
                        {
                            "path": str(path),
                            "sha256": _digest(path),
                            "size_bytes": path.stat().st_size,
                            "step": identifier,
                        }
                    )
                if parameters.get("collection", True):
                    value = open_collection(resolved, step["variable"])
                else:
                    if len(resolved) != 1:
                        raise ValueError("collection=false requires exactly one file")
                    value = read_field(resolved[0], step["variable"])
            elif op in ("aggregate", "evaluate"):
                source = step["source"]
                entry["parents"].append(source)
                value = objects[source]
                if op == "aggregate":
                    value = aggregate(value, **parameters)
                else:
                    reference = step["reference"]
                    entry["parents"].append(reference)
                    ref = objects[reference]
                    if isinstance(value, dict) or isinstance(ref, dict):
                        raise ValueError(
                            "Evaluate requires Fields or loaded collections"
                        )
                    if hasattr(value, "read"):
                        value = value.read()
                    if hasattr(ref, "read"):
                        ref = ref.read()
                    parameters = dict(parameters)
                    if "cell_area" in parameters:
                        raise ValueError(
                            "Use a cell_area step reference, not parameters"
                        )
                    if "cell_area" in step:
                        parent = step["cell_area"]
                        entry["parents"].append(parent)
                        area = objects[parent]
                        parameters["cell_area"] = (
                            area.read() if hasattr(area, "read") else area
                        )
                    value = evaluate(value, ref, **parameters)
            else:
                raise ValueError("Supported operations: load, aggregate, evaluate")
            objects[identifier] = value
            fields = value if isinstance(value, dict) else {"value": value}
            for name, field in fields.items():
                qc = quality_report(field, **step.get("qc", {}))
                qc_path = destination / f"{identifier}-{name}-qc.json"
                _json_write(qc_path, qc)
                entry["outputs"].append(
                    {"kind": "qc", "path": qc_path.name, "sha256": _digest(qc_path)}
                )
                if isinstance(field, Field):
                    target = destination / f"{identifier}-{name}.nc"
                    field.to_netcdf(target)
                    entry["outputs"].append(
                        {
                            "kind": "netcdf",
                            "path": target.name,
                            "sha256": _digest(target),
                        }
                    )
            for path, fingerprint in fingerprints.items():
                stat = path.stat()
                if (stat.st_size, stat.st_mtime_ns) != fingerprint:
                    raise RuntimeError(
                        "Input changed during recipe execution: " + str(path)
                    )
            entry["status"] = "passed"
            _json_write(destination / "run.json", record)
        record["status"] = "passed"
    except Exception as exc:
        record["status"] = "failed"
        record["error"] = {"type": type(exc).__name__, "message": str(exc)}
        if record["steps"]:
            record["steps"][-1]["status"] = "failed"
        raise
    finally:
        record["finished_utc"] = datetime.now(timezone.utc).isoformat()
        _json_write(destination / "run.json", record)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config")
    parser.add_argument("--output-dir")
    args = parser.parse_args()
    run_recipe(args.config, output_dir=args.output_dir)


if __name__ == "__main__":
    main()
