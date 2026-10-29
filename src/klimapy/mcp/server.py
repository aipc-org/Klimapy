"""A bounded local MCP stdio server (2025-11-25 protocol family)."""

import argparse
import contextlib
import json
from pathlib import Path
import sys

PROTOCOL = "2025-11-25"
SUPPORTED = (PROTOCOL, "2025-06-18", "2024-11-05")


def _schema(properties, required):
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def tool_definitions():
    path = {
        "type": "string",
        "description": "Path relative to the configured data directory",
    }
    variable = {"type": "string"}
    output = {
        "type": "string",
        "description": "New file relative to the configured output directory",
    }
    region = {
        "type": "array",
        "items": {"type": "integer", "minimum": 0},
        "minItems": 2,
        "maxItems": 2,
    }
    return [
        {
            "name": "inspect_dataset",
            "description": "List NetCDF variables, dimensions, shapes and attributes.",
            "inputSchema": _schema({"path": path}, ["path"]),
            "annotations": {"readOnlyHint": True, "openWorldHint": False},
        },
        {
            "name": "compute_etccdi",
            "description": "Compute selected daily precipitation/temperature indices and save new NetCDF files; default input region is 16x16 and first 366 days.",
            "inputSchema": _schema(
                {
                    "path": path,
                    "variable": variable,
                    "indices": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                        "maxItems": 10,
                    },
                    "output_prefix": output,
                    "lat_slice": region,
                    "lon_slice": region,
                    "time_slice": region,
                    "baseline_years": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "minItems": 2,
                        "maxItems": 2,
                    },
                },
                ["path", "variable", "indices", "output_prefix"],
            ),
            "annotations": {
                "readOnlyHint": False,
                "destructiveHint": False,
                "openWorldHint": False,
            },
        },
        {
            "name": "compute_climatology",
            "description": "Compute monthly, daily or annual climate means with an explicit or standard 30-year baseline, saving a new NetCDF file.",
            "inputSchema": _schema(
                {
                    "path": path,
                    "variable": variable,
                    "output": output,
                    "group": {"type": "string", "enum": ["monthly", "daily", "annual"]},
                    "baseline_years": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "minItems": 2,
                        "maxItems": 2,
                    },
                },
                ["path", "variable", "output"],
            ),
            "annotations": {
                "readOnlyHint": False,
                "destructiveHint": False,
                "openWorldHint": False,
            },
        },
        {
            "name": "export_csv",
            "description": "Export a bounded NetCDF variable region to long-form CSV; default first 366 days and 16x16 spatial region.",
            "inputSchema": _schema(
                {
                    "path": path,
                    "variable": variable,
                    "output": output,
                    "lat_slice": region,
                    "lon_slice": region,
                    "time_slice": region,
                },
                ["path", "variable", "output"],
            ),
            "annotations": {
                "readOnlyHint": False,
                "destructiveHint": False,
                "openWorldHint": False,
            },
        },
    ]


class ClimateServer:
    def __init__(self, data_root, output_root=None):
        self.data_root = Path(data_root).resolve(strict=True)
        if not self.data_root.is_dir():
            raise ValueError("data_root must be a directory")
        self.output_root = (
            None if output_root is None else Path(output_root).resolve(strict=True)
        )
        if self.output_root is not None and not self.output_root.is_dir():
            raise ValueError("output_root must be a directory")
        self.initialized = False

    @staticmethod
    def _contained(root, path):
        if not isinstance(path, str) or not path:
            raise ValueError("A nonempty relative file path is required")
        if Path(path).is_absolute():
            raise ValueError("Use a relative path")
        resolved = (root / path).resolve()
        try:
            resolved.relative_to(root)
        except ValueError:
            raise ValueError("Path lies outside the configured directory") from None
        return resolved

    def _output(self, path):
        if self.output_root is None:
            raise ValueError("Configure --output-root to enable file output")
        result = self._contained(self.output_root, path)
        if result.exists():
            raise FileExistsError(str(result))
        if not result.parent.is_dir():
            raise ValueError("Output parent directory must already exist")
        return result

    def _field(self, arguments):
        from ..native import read_field, Dataset

        source = self._contained(self.data_root, arguments["path"])
        variable = arguments["variable"]
        selectors = {}
        with Dataset(source) as ds:
            v = ds[variable]
            size = 1
            for dim, n in zip(v.dims, v.shape):
                canonical = {"latitude": "lat", "longitude": "lon"}.get(
                    dim.lower(), dim.lower()
                )
                if canonical in ("time", "lat", "lon"):
                    start, stop = arguments.get(
                        canonical + "_slice", [0, 366 if canonical == "time" else 16]
                    )
                    if (
                        any(
                            isinstance(x, bool) or not isinstance(x, int)
                            for x in (start, stop)
                        )
                        or not 0 <= start < stop
                    ):
                        raise ValueError("Slices require nonnegative start < stop")
                    selectors[dim] = slice(start, min(stop, n))
                    n = max(0, min(stop, n) - start)
                size *= n
            if size > 10_000_000:
                raise ValueError(
                    "Requested field exceeds 10 million values; use smaller slices"
                )
        return read_field(source, variable, indexers=selectors)

    def call(self, name, arguments):
        definitions = {d["name"]: d for d in tool_definitions()}
        if name not in definitions:
            raise ValueError("Unknown tool: " + str(name))
        schema = definitions[name]["inputSchema"]
        if (
            not isinstance(arguments, dict)
            or set(arguments) - set(schema["properties"])
            or any(k not in arguments for k in schema["required"])
        ):
            raise ValueError("Missing or unsupported tool arguments")
        if name == "inspect_dataset":
            from ..native import Dataset

            with Dataset(self._contained(self.data_root, arguments["path"])) as ds:
                return {
                    "variables": {
                        n: {
                            "dims": list(v.dims),
                            "shape": list(v.shape),
                            "attrs": _json_safe(v.attrs),
                        }
                        for n, v in ds.variables.items()
                    }
                }
        if name == "compute_climatology":
            from ..statistics.climatology import climatology

            target = self._output(arguments["output"])
            field = climatology(
                self._contained(self.data_root, arguments["path"]),
                variable=arguments["variable"],
                baseline_years=arguments.get("baseline_years"),
                group=arguments.get("group", "monthly"),
            )
            field.to_netcdf(target)
            return {
                "output": str(target),
                "shape": list(field.shape),
                "baseline": field.attrs["baseline_period"],
            }
        if name == "export_csv":
            from ..tools import to_csv

            target = self._output(arguments["output"])
            field = self._field(arguments)
            to_csv(field, target)
            return {"output": str(target), "shape": list(field.shape)}
        from ..etccdi import compute_indices

        indices = arguments["indices"]
        if (
            not isinstance(indices, list)
            or not 1 <= len(indices) <= 10
            or any(
                not isinstance(i, str) or not i.replace("_", "").isalnum()
                for i in indices
            )
        ):
            raise ValueError("Specify 1..10 valid indicator names")
        if len(set(indices)) != len(indices):
            raise ValueError("Duplicate indicator names")
        targets = {
            i: self._output(arguments["output_prefix"] + "_" + i + ".nc")
            for i in indices
        }
        kwargs = {}
        if "baseline_years" in arguments:
            kwargs["baseline_years"] = arguments["baseline_years"]
        result = compute_indices(self._field(arguments), indices, **kwargs)
        for i, field in result.items():
            field.to_netcdf(targets[i])
        return {"outputs": {i: str(p) for i, p in targets.items()}}

    def handle(self, message):
        if (
            not isinstance(message, dict)
            or message.get("jsonrpc") != "2.0"
            or not isinstance(message.get("method"), str)
        ):
            return _error(None, -32600, "Invalid JSON-RPC request")
        method = message["method"]
        identifier = message.get("id")
        if "id" not in message:
            return None
        if (
            identifier is None
            or isinstance(identifier, bool)
            or not isinstance(identifier, (str, int))
        ):
            return _error(None, -32600, "Invalid request ID")
        params = message.get("params", {})
        if not isinstance(params, dict):
            return _error(identifier, -32602, "Expected object params")
        if method == "ping":
            return _result(identifier, {})
        if method == "initialize":
            if self.initialized:
                return _error(identifier, -32600, "Already initialized")
            protocol = params.get("protocolVersion")
            if not isinstance(protocol, str):
                return _error(identifier, -32602, "protocolVersion is required")
            self.initialized = True
            return _result(
                identifier,
                {
                    "protocolVersion": protocol if protocol in SUPPORTED else PROTOCOL,
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "klimapy", "version": "1.2.1"},
                },
            )
        if not self.initialized:
            return _error(identifier, -32002, "Initialize the server first")
        if method == "tools/list":
            return _result(identifier, {"tools": tool_definitions()})
        if method == "tools/call":
            try:
                with contextlib.redirect_stdout(sys.stderr):
                    result = self.call(params.get("name"), params.get("arguments", {}))
                return _result(
                    identifier,
                    {
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(
                                    result, ensure_ascii=False, allow_nan=False
                                ),
                            }
                        ],
                        "structuredContent": result,
                        "isError": False,
                    },
                )
            except (ValueError, TypeError, KeyError, OSError, RuntimeError) as exc:
                return _result(
                    identifier,
                    {"content": [{"type": "text", "text": str(exc)}], "isError": True},
                )
        return _error(identifier, -32601, "Method not found")


def _json_safe(value):
    import numpy as np

    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, np.ndarray)):
        return [_json_safe(v) for v in value]
    if isinstance(value, np.generic):
        return _json_safe(value.item())
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def _result(identifier, value):
    return {"jsonrpc": "2.0", "id": identifier, "result": value}


def _error(identifier, code, message):
    return {
        "jsonrpc": "2.0",
        "id": identifier,
        "error": {"code": code, "message": message},
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--output-root")
    args = parser.parse_args(argv)
    server = ClimateServer(args.data_root, args.output_root)
    for line in sys.stdin:
        try:
            response = server.handle(json.loads(line))
        except (ValueError, TypeError):
            response = _error(None, -32700, "Parse error")
        if response is not None:
            print(json.dumps(response, ensure_ascii=False, allow_nan=False), flush=True)
