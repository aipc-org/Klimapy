"""Native BC/SD metadata, cached Rust plans, bounded buffers and atomic output."""

import os
from pathlib import Path
import tempfile

import numpy as np

from .._backends.rust import SpatialPlan
from ..native import Dataset, Field
from .validation import (
    normalize_time,
    normalize_spatial,
    convert_units,
    validate_reference_years,
)


def read_precip(data):
    return convert_units(
        normalize_time(normalize_spatial(data), fill_gaps=False), "precip"
    )


def precip_values(data):
    return np.asarray(data.values, dtype=float)


def calendar_info(time):
    cal = time.calendar
    if cal == "360_day":
        return cal, 360
    if cal in ("noleap", "365_day"):
        return "noleap", 365
    return cal, 366


def date_keys(time):
    return [tuple(d) for d in time.dates()[0].tolist()]


def mapped_days(time, calendar_name):
    dates, _ = time.dates()
    month, day = dates[:, 1], dates[:, 2]
    if calendar_name == "360_day":
        return np.where(day <= 30, (month - 1) * 30 + day, 0).astype(int)
    starts = np.array(
        [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
        if calendar_name in ("noleap", "365_day")
        else [0, 31, 60, 91, 121, 152, 182, 213, 244, 274, 305, 335]
    )
    labels = starts[month - 1] + day
    return (
        np.where((month == 2) & (day == 29), 0, labels).astype(int)
        if calendar_name in ("noleap", "365_day")
        else labels.astype(int)
    )


def check_reference(time, start, end):
    return validate_reference_years(time, start, end)


def align_reference(obs_time, model_time, start, end):
    check_reference(obs_time, start, end)
    check_reference(model_time, start, end)
    lookup = {
        key: i for i, key in enumerate(date_keys(obs_time)) if start <= key[0] <= end
    }
    obs, model = [], []
    for i, key in enumerate(date_keys(model_time)):
        if start <= key[0] <= end and key in lookup:
            obs.append(lookup[key])
            model.append(i)
    if len(obs) < 20:
        raise ValueError("Fewer than 20 matching reference dates")
    return np.asarray(obs), np.asarray(model)


class GridWeights(SpatialPlan):
    """Rust center-selected cosine-weighted coarsening."""


class BilinearWeights(SpatialPlan):
    def __init__(self, source_lat, source_lon, target_lat, target_lon):
        super().__init__(source_lat, source_lon, target_lat, target_lon, bilinear=True)


def allocate(shape, dtype, work_dir=None, prefix="klimapy"):
    if work_dir is None:
        return np.empty(shape, dtype=dtype)
    Path(work_dir).mkdir(parents=True, exist_ok=True)
    fd, path = tempfile.mkstemp(prefix=prefix + "-", suffix=".dat", dir=work_dir)
    os.close(fd)
    return np.memmap(path, mode="w+", dtype=dtype, shape=shape)


class NetCDFWriter:
    def __init__(
        self,
        path,
        time,
        lat,
        lon,
        attrs,
        time_name="time",
        lat_name="lat",
        lon_name="lon",
    ):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(
            prefix=".klimapy-", dir=self.path.parent
        )
        self.staging = Path(self.temporary.name) / "output.nc"
        self.attrs, self.time = attrs, time
        self.written, self.handle = 0, None
        try:
            self.handle = Dataset(self.staging, "x")
            values = np.asarray(time.values)
            time_attrs = dict(time.attrs)
            if values.dtype.kind not in "fiu":
                from ..native.field import _ordinal

                values = time.dates()[1] - _ordinal(1, 1, 1, time.calendar)
                time_attrs = {
                    "units": "days since 0001-01-01",
                    "calendar": time.calendar,
                }
            for name, coord, attr in (
                (time_name, values, time_attrs),
                (lat_name, lat, {"units": "degrees_north"}),
                (lon_name, lon, {"units": "degrees_east"}),
            ):
                v = self.handle.create_variable(
                    name, (name,), (len(coord),), attrs=attr
                )
                v.write(np.asarray(coord))
            self.variable = self.handle.create_variable(
                "pr",
                (time_name, lat_name, lon_name),
                (len(values), len(lat), len(lon)),
                dtype="float32",
                compression=4,
                attrs=attrs,
            )
        except Exception:
            if self.handle is not None:
                self.handle.close()
            self.temporary.cleanup()
            raise

    def __enter__(self):
        return self

    def write(self, start, values):
        if start != self.written or start + len(values) > len(self.time.values):
            raise ValueError("Output chunks must be contiguous and within time bounds")
        self.variable.write(
            values, (slice(start, start + len(values)), slice(None), slice(None))
        )
        self.written += len(values)

    def __exit__(self, typ, exc, tb):
        try:
            if typ is None:
                if self.written != len(self.time.values):
                    raise ValueError("Not all output steps were written")
                for k, v in self.attrs.items():
                    self.variable.set_attr(k, v)
                    self.handle.set_attr(k, v)
            self.handle.close()
            if typ is None:
                os.replace(self.staging, self.path)
        finally:
            self.handle.close()
            self.temporary.cleanup()
