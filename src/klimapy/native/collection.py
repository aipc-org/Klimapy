"""Metadata-indexed NetCDF collections with bounded file reads."""

import os
import tempfile
from pathlib import Path

import numpy as np

from .field import Field, TimeAxis
from .io import Dataset


def _decoded_attrs(attrs):
    return {
        k: v
        for k, v in attrs.items()
        if k
        not in (
            "scale_factor",
            "add_offset",
            "_FillValue",
            "missing_value",
            "valid_min",
            "valid_max",
            "valid_range",
            "actual_range",
        )
    }


def _same_metadata(a, b):
    if set(a) != set(b):
        return False
    for key in a:
        x, y = np.asarray(a[key]), np.asarray(b[key])
        if x.dtype.kind in "fiu" and y.dtype.kind in "fiu":
            if not np.array_equal(x, y, equal_nan=True):
                return False
        elif not np.array_equal(x, y):
            return False
    return True


class FileCollection:
    """Sort files by daily dates; reject overlaps and incompatible grids.

    Opening reads coordinates only. Data are read by iter_blocks() or read().
    Missing dates remain explicit gaps and count against aggregation coverage.
    Files must each contain an ordered, nonempty daily time axis named time.
    """

    def __init__(self, paths, variable):
        if isinstance(paths, (str, Path)):
            raise TypeError("Pass a sequence of file paths, not a string")
        self.variable = variable
        records = []
        for path in paths:
            path = Path(path)
            with Dataset(path) as ds:
                v = ds[variable]
                if "time" not in v.dims:
                    raise ValueError("A time dimension named time is required")
                coords = {d: ds[d][...] for d in v.dims}
                ca = {d: ds[d].attrs for d in v.dims}
                clock = TimeAxis(coords["time"], ca["time"])
                _, days = clock.dates()
                if not len(days):
                    raise ValueError("Empty time axis: " + str(path))
                bounds = None
                if ca["time"].get("bounds"):
                    bv = ds[ca["time"]["bounds"]]
                    if bv.dims[0] != "time" or len(bv.shape) != 2 or bv.shape[1] != 2:
                        raise ValueError("CF time bounds must use (time, two_vertices)")
                    for key in ("units", "calendar"):
                        if key in bv.attrs and bv.attrs[key] != ca["time"].get(
                            key, "standard" if key == "calendar" else None
                        ):
                            raise ValueError("Time bounds metadata must match time")
                    raw = bv[...]
                    Field(
                        np.empty(len(days)),
                        ("time",),
                        {"time": coords["time"]},
                        coordinate_attrs={"time": ca["time"]},
                        time_bounds=raw,
                    )
                    bounds = TimeAxis(raw.ravel(), ca["time"]).serial().reshape(-1, 2)
                if records and (bounds is None) != (records[0][3] is None):
                    raise ValueError(
                        "All collection files must consistently provide time bounds"
                    )
                meta = (v.dims, coords, ca, dict(v.attrs), clock.calendar)
                if not records:
                    (
                        self.dims,
                        self.coords,
                        self.coordinate_attrs,
                        self.attrs,
                        self.calendar,
                    ) = meta
                    self.coords = dict(coords)
                    self.coordinate_attrs = dict(ca)
                    self.attrs = _decoded_attrs(self.attrs)
                else:
                    if meta[0] != self.dims or meta[4] != self.calendar:
                        raise ValueError("Collection dimensions/calendars differ")
                    if meta[3].get("units") != self.attrs.get("units"):
                        raise ValueError("Collection variable units differ")
                    for d in self.dims:
                        if d != "time" and (
                            not np.array_equal(coords[d], self.coords[d])
                            or not _same_metadata(ca[d], self.coordinate_attrs[d])
                        ):
                            raise ValueError(
                                "Collection grid coordinates/metadata differ: " + d
                            )
                records.append((int(days[0]), path, days, bounds, clock.serial()))
        if not records:
            raise ValueError("Collection needs at least one file")
        records.sort(key=lambda r: r[0])
        self._records = records
        self.days = np.concatenate([r[2] for r in records])
        if np.any(np.diff(self.days) <= 0):
            raise ValueError("Overlapping or duplicate collection dates")
        self.coords["time"] = np.concatenate([r[4] for r in records])
        self.coordinate_attrs["time"] = {
            "units": "days since 0001-01-01",
            "calendar": self.calendar,
        }
        # TimeAxis uses zero-based day ordinals.
        self.coords["time"] -= TimeAxis(
            np.array(["0001-01-01"]), {"calendar": self.calendar}
        ).dates()[1][0]
        self.time_bounds = None
        if records[0][3] is not None:
            self.time_bounds = (
                np.concatenate([r[3] for r in records])
                - TimeAxis(
                    np.array(["0001-01-01"]), {"calendar": self.calendar}
                ).serial()[0]
            )
            if np.any(self.time_bounds[1:, 0] < self.time_bounds[:-1, 1]):
                raise ValueError("Collection time bounds overlap")
            self.coordinate_attrs["time"]["bounds"] = "time_bnds"
        TimeAxis(self.coords["time"], self.coordinate_attrs["time"]).dates()
        self.shape = tuple(len(self.coords[d]) for d in self.dims)
        self.name = variable
        self.missing_days = int(
            sum(int(b - a - 1) for a, b in zip(self.days[:-1], self.days[1:]))
        )

    def iter_blocks(self, time_chunk_size=128, *, dtype="float64"):
        """Yield decoded Fields, retaining one file per iterator until exhausted.

        Close the generator when stopping early to release its file immediately.
        Coordinates are reused from the validated collection metadata.
        """
        if (
            isinstance(time_chunk_size, bool)
            or not isinstance(time_chunk_size, (int, np.integer))
            or time_chunk_size < 1
        ):
            raise ValueError("time_chunk_size must be a positive integer")
        offset = 0
        dtype = np.dtype(dtype)
        if dtype not in (np.dtype("float32"), np.dtype("float64")):
            raise ValueError("Read dtype must be native float32 or float64")
        for _, path, days, _, _ in self._records:
            with Dataset(path) as ds:
                variable = ds[self.variable]
                for start in range(0, len(days), time_chunk_size):
                    stop = min(start + time_chunk_size, len(days))
                    key = tuple(
                        slice(start, stop) if d == "time" else slice(None)
                        for d in self.dims
                    )
                    coords = {
                        d: self.coords[d].copy() for d in self.dims if d != "time"
                    }
                    coords["time"] = self.coords["time"][offset + start : offset + stop]
                    bounds = (
                        None
                        if self.time_bounds is None
                        else self.time_bounds[offset + start : offset + stop]
                    )
                    yield Field(
                        variable.read(key, dtype=dtype),
                        self.dims,
                        coords,
                        dict(self.attrs),
                        self.name,
                        {d: dict(a) for d, a in self.coordinate_attrs.items()},
                        bounds,
                    )
            offset += len(days)

    def read(self, *, dtype="float64"):
        """Materialize the complete collection; use iter_blocks for large data."""
        values = np.concatenate(
            [b.values for b in self.iter_blocks(dtype=dtype)],
            axis=self.dims.index("time"),
        )
        return Field(
            values,
            self.dims,
            self.coords,
            self.attrs,
            self.name,
            self.coordinate_attrs,
            self.time_bounds,
        )

    def to_netcdf(self, path, *, time_chunk_size=128):
        """Stream into a new file and atomically publish without overwriting."""
        path = Path(path)
        if path.exists():
            raise FileExistsError(path)
        fd, temporary = tempfile.mkstemp(
            prefix="." + path.name, suffix=".nc", dir=path.parent
        )
        os.close(fd)
        os.unlink(temporary)
        try:
            with Dataset(temporary, "x") as ds:
                for d in self.dims:
                    ds.create_variable(
                        d,
                        (d,),
                        (len(self.coords[d]),),
                        attrs=self.coordinate_attrs.get(d, {}),
                    ).write(self.coords[d])
                if self.time_bounds is not None:
                    if "bnds" in self.dims or self.name == "time_bnds":
                        raise ValueError("Reserved bounds names conflict with field")
                    ds.create_variable(
                        "time_bnds", ("time", "bnds"), self.time_bounds.shape
                    ).write(self.time_bounds)
                output = ds.create_variable(
                    self.name, self.dims, self.shape, attrs=self.attrs
                )
                offset = 0
                for block in self.iter_blocks(time_chunk_size):
                    n = len(block.coords["time"])
                    key = tuple(
                        slice(offset, offset + n) if d == "time" else slice(None)
                        for d in self.dims
                    )
                    output.write(block.values, key)
                    offset += n
            os.link(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


def open_collection(paths, variable):
    """Create a FileCollection without loading variable payloads."""
    return FileCollection(paths, variable)
