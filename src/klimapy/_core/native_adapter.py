"""Bounded native precipitation input. No legacy framework adapters remain."""

import numpy as np

from ..native import Dataset, Field, TimeAxis
from ..native.statistics import affine
from .validation import PRECIP_NAMES, convert_units, normalize_spatial

_ALIASES = {
    "Time": "time",
    "latitude": "lat",
    "Lat": "lat",
    "longitude": "lon",
    "Lon": "lon",
}


class PrecipSource:
    """Own a native file until close; materialize only requested time/space blocks."""

    def __init__(self, source):
        self.handle = None
        try:
            if isinstance(source, Field):
                f = normalize_spatial(source)
                self.field, self.variable = f, None
                self.coords, self.coordinate_attrs = f.coords, f.coordinate_attrs
                self.attrs, self.shape = f.attrs, f.shape
                self.dims = ("time", "lat", "lon")
            else:
                self.handle = Dataset(source)
                names = self.handle.names()
                lookup = {n.lower(): n for n in names}
                name = next((lookup[n] for n in PRECIP_NAMES if n in lookup), None)
                if name is None:
                    raise ValueError("No precipitation variable: " + str(names))
                self.variable = self.handle[name]
                self.field = None
                self.dims = tuple(_ALIASES.get(d, d) for d in self.variable.dims)
                if set(self.dims) != {"time", "lat", "lon"} or len(self.dims) != 3:
                    raise ValueError("Precipitation needs time, lat, lon dimensions")
                self.coords, self.coordinate_attrs = {}, {}
                for d, canonical in zip(self.variable.dims, self.dims):
                    v = self.handle[d]
                    self.coords[canonical], self.coordinate_attrs[canonical] = (
                        v[...],
                        v.attrs,
                    )
                self.attrs = self.variable.attrs
                self.shape = tuple(len(self.coords[d]) for d in ("time", "lat", "lon"))
            self.time = TimeAxis(
                self.coords["time"], self.coordinate_attrs.get("time", {})
            )
            self.time.dates()
            # Unit scaling is metadata policy, evaluated by the Rust affine kernel.
            probe = Field(
                np.array([0.0, 1.0]), ("probe",), {"probe": [0, 1]}, self.attrs
            )
            converted = convert_units(probe, "precip")
            self.scale = float(converted.values[1] - converted.values[0])
            self.converted_attrs = converted.attrs
        except Exception:
            self.close()
            raise

    def read(self, *, time=slice(None), lat=slice(None), lon=slice(None)):
        selectors = {"time": time, "lat": lat, "lon": lon}
        if self.field is not None:
            values = self.field.isel(**selectors).values
        else:
            contiguous, takes = {}, {}
            for dim, selector in selectors.items():
                if isinstance(selector, slice) or np.isscalar(selector):
                    contiguous[dim] = selector
                else:
                    indices = np.asarray(selector)
                    if indices.dtype.kind == "b":
                        indices = np.flatnonzero(indices)
                    if (
                        indices.ndim != 1
                        or indices.dtype.kind not in "iu"
                        or not len(indices)
                    ):
                        raise ValueError(
                            "Time/space index arrays must be nonempty integer vectors"
                        )
                    if np.any(indices < 0) or np.any(indices >= len(self.coords[dim])):
                        raise IndexError("Index outside native variable")
                    lo, hi = int(indices.min()), int(indices.max())
                    contiguous[dim], takes[dim] = slice(lo, hi + 1), indices - lo
            key = tuple(contiguous[d] for d in self.dims)
            values = self.variable[key]
            remaining = [d for d in self.dims if not np.isscalar(contiguous[d])]
            canonical = [d for d in ("time", "lat", "lon") if d in remaining]
            values = values.transpose([remaining.index(d) for d in canonical])
            for d, indices in takes.items():
                values = np.take(values, indices, axis=canonical.index(d))
        return affine(values, self.scale)

    def result(self, values):
        return Field(
            values,
            ("time", "lat", "lon"),
            self.coords,
            self.converted_attrs,
            "pr",
            self.coordinate_attrs,
        )

    def close(self):
        if self.handle is not None:
            self.handle.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def open_precip_dataset(path):
    return PrecipSource(path)
