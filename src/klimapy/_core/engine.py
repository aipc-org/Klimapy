"""Shared BC/SD infrastructure: cached grids, calendar alignment and streamed output."""

import logging
import os
from pathlib import Path
import tempfile

import cftime
import numpy as np
from scipy.sparse import csr_matrix
import xarray as xr

from .validation import (
    normalize_spatial,
    normalize_time,
    convert_units,
    season_day,
    validate_reference_years,
)
from .common import calculate_bounds, get_precip_var_name

logger = logging.getLogger("klimapy.processing")


def read_precip(ds):
    """Validate metadata without materializing a file-backed precipitation cube."""
    source = ds if isinstance(ds, xr.DataArray) else ds[get_precip_var_name(ds)]
    data = normalize_time(normalize_spatial(source), fill_gaps=False)
    probe = convert_units(xr.DataArray([1.0], attrs=data.attrs), "precip")
    data = data.copy(deep=False)
    data.attrs = dict(probe.attrs, _klimapy_unit_factor=float(probe.item()))
    return data


def precip_values(data):
    """Load/convert only a caller-selected tile, time block or model row."""
    values = np.array(data.values, dtype=float, copy=True)
    values *= data.attrs.get("_klimapy_unit_factor", 1.0)
    values[~np.isfinite(values)] = np.nan
    return values


def calendar_info(time):
    cal = time.dt.calendar
    if cal == "360_day":
        return cal, 360
    if cal in ("noleap", "365_day"):
        return "noleap", 365
    return cal, 366


def date_keys(time):
    return list(
        zip(
            time.dt.year.values.tolist(),
            time.dt.month.values.tolist(),
            time.dt.day.values.tolist(),
        )
    )


def mapped_days(time, calendar_name):
    month, day = time.dt.month.values, time.dt.day.values
    if calendar_name == "360_day":
        return np.where(day <= 30, (month - 1) * 30 + day, 0).astype(int)
    if calendar_name in ("noleap", "365_day"):
        starts = np.array([0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334])
        return np.where((month == 2) & (day == 29), 0, starts[month - 1] + day).astype(
            int
        )
    return np.asarray(season_day(time), dtype=int)


def check_reference(time, start, end):
    return validate_reference_years(time, start, end)


def align_reference(obs_time, model_time, start, end):
    """Exact year/month/day intersection, with explicit reference-year validation."""
    check_reference(obs_time, start, end)
    check_reference(model_time, start, end)
    lookup = {
        key: i for i, key in enumerate(date_keys(obs_time)) if start <= key[0] <= end
    }
    obs_indices, model_indices = [], []
    for i, key in enumerate(date_keys(model_time)):
        if start <= key[0] <= end and key in lookup:
            obs_indices.append(lookup[key])
            model_indices.append(i)
    if len(obs_indices) < 20:
        raise ValueError(
            "Fewer than 20 matching reference dates; cannot fit bias correction"
        )
    return np.asarray(obs_indices), np.asarray(model_indices)


class GridWeights:
    """Precompute center-selected cosine weights; apply to any batch of fields."""

    def __init__(self, source_lat, source_lon, target_lat, target_lon):
        self.shape = (len(source_lat), len(source_lon))
        self.target_shape = (len(target_lat), len(target_lon))
        latbounds, lonbounds = (
            calculate_bounds(target_lat),
            calculate_bounds(target_lon),
        )
        rows, cols, values = [], [], []
        for i, (lo, hi) in enumerate(latbounds):
            a = np.flatnonzero((source_lat >= lo) & (source_lat <= hi))
            for j, (left, right) in enumerate(lonbounds):
                b = np.flatnonzero((source_lon >= left) & (source_lon <= right))
                for y in a:
                    for x in b:
                        rows.append(i * len(target_lon) + j)
                        cols.append(y * len(source_lon) + x)
                        values.append(np.cos(np.deg2rad(source_lat[y])))
        self.weights = csr_matrix(
            (values, (rows, cols)),
            shape=(np.prod(self.target_shape), np.prod(self.shape)),
        )

    def apply(self, data):
        values = np.asarray(data, dtype=float)
        if values.shape[-2:] != self.shape:
            raise ValueError("Source field does not match cached grid")
        flat = values.reshape((-1, np.prod(self.shape)))
        good = np.isfinite(flat)
        numerator = np.asarray(self.weights @ np.where(good, flat, 0).T).T
        denominator = np.asarray(self.weights @ good.astype(float).T).T
        result = np.divide(
            numerator,
            denominator,
            out=np.full_like(numerator, np.nan),
            where=denominator > 0,
        )
        return result.reshape(values.shape[:-2] + self.target_shape)


def allocate(shape, dtype, work_dir=None, prefix="klimapy"):
    """Use a caller-owned work directory for optional disk-backed large outputs."""
    if work_dir is None:
        return np.empty(shape, dtype=dtype)
    Path(work_dir).mkdir(parents=True, exist_ok=True)
    descriptor, path = tempfile.mkstemp(
        prefix=prefix + "-", suffix=".dat", dir=work_dir
    )
    os.close(descriptor)
    return np.memmap(path, mode="w+", dtype=dtype, shape=shape)


class NetCDFWriter:
    """Chunk writes with netCDF4; disk-backed scipy fallback when it is unavailable."""

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
        self.time, self.lat, self.lon = time, lat, lon
        self.attrs = attrs
        self.names = (time_name, lat_name, lon_name)
        self.temporary = tempfile.TemporaryDirectory(
            prefix=".klimapy-", dir=self.path.parent
        )
        self.staging = Path(self.temporary.name) / "output.nc"
        self.handle = None
        self.buffer = None
        self.written = 0
        try:
            from netCDF4 import Dataset
        except ImportError:
            Dataset = None
        if Dataset is not None:
            self.handle = Dataset(str(self.staging), "w")
            for name, coord in zip(self.names, (time, lat, lon)):
                self.handle.createDimension(name, len(coord))
            cal = time.dt.calendar
            units = time.encoding.get("units", "days since 1970-01-01 00:00:00")
            dates = time.values
            if np.issubdtype(dates.dtype, np.datetime64):
                dates = time.to_index().to_pydatetime()
            tv = self.handle.createVariable(time_name, "f8", (time_name,))
            tv.units = units
            tv.calendar = cal
            tv[:] = cftime.date2num(
                dates.tolist() if hasattr(dates, "tolist") else dates,
                units,
                calendar=cal,
            )
            for name, coord, unit in (
                (lat_name, lat, "degrees_north"),
                (lon_name, lon, "degrees_east"),
            ):
                v = self.handle.createVariable(name, "f8", (name,))
                v[:] = coord
                v.units = unit
            self.variable = self.handle.createVariable(
                "pr", "f4", self.names, zlib=True, complevel=4, fill_value=np.nan
            )
            self.variable.setncatts(attrs)
        else:
            self.buffer = allocate(
                (len(time), len(lat), len(lon)),
                np.float32,
                self.temporary.name,
                "output",
            )

    def __enter__(self):
        return self

    def write(self, start, values):
        if start != self.written:
            raise ValueError("Output chunks must be contiguous and ordered")
        end = start + len(values)
        if self.handle is not None:
            self.variable[start:end] = values
        else:
            self.buffer[start:end] = values
        self.written = end

    def __exit__(self, typ, exc, tb):
        try:
            if typ is None and self.written != len(self.time):
                raise ValueError("Not all output time steps were written")
            if self.handle is not None:
                if typ is None:
                    self.handle.setncatts(self.attrs)
                    self.variable.setncatts(self.attrs)
                self.handle.close()
                self.handle = None
            elif typ is None:
                dims = self.names
                result = xr.Dataset(
                    {"pr": (dims, self.buffer, self.attrs)},
                    coords={
                        dims[0]: self.time.values,
                        dims[1]: self.lat,
                        dims[2]: self.lon,
                    },
                )
                result.to_netcdf(self.staging, engine="scipy")
            if typ is None:
                os.replace(self.staging, self.path)
        finally:
            if self.handle is not None:
                self.handle.close()
                self.handle = None
            if self.buffer is not None:
                self.buffer._mmap.close()
            self.temporary.cleanup()


class BilinearWeights:
    """Cache four source neighbors and interpolation weights for each target point."""

    def __init__(self, source_lat, source_lon, target_lat, target_lon):
        latorder, lonorder = np.argsort(source_lat), np.argsort(source_lon)
        lat, lon = np.asarray(source_lat)[latorder], np.asarray(source_lon)[lonorder]
        if (
            len(lat) < 2
            or len(lon) < 2
            or np.any(np.diff(lat) <= 0)
            or np.any(np.diff(lon) <= 0)
        ):
            raise ValueError(
                "Interpolation needs at least two distinct coordinates per axis"
            )
        y, x = np.meshgrid(target_lat, target_lon, indexing="ij")
        y, x = y.ravel(), x.ravel()
        i = np.clip(np.searchsorted(lat, y) - 1, 0, len(lat) - 2)
        j = np.clip(np.searchsorted(lon, x) - 1, 0, len(lon) - 2)
        fy = (y - lat[i]) / (lat[i + 1] - lat[i])
        fx = (x - lon[j]) / (lon[j + 1] - lon[j])
        self.indices = [
            latorder[i] * len(lon) + lonorder[j],
            latorder[i] * len(lon) + lonorder[j + 1],
            latorder[i + 1] * len(lon) + lonorder[j],
            latorder[i + 1] * len(lon) + lonorder[j + 1],
        ]
        self.weights = [(1 - fy) * (1 - fx), (1 - fy) * fx, fy * (1 - fx), fy * fx]
        self.target_shape = (len(target_lat), len(target_lon))
        self.source_shape = (len(lat), len(lon))

    def apply(self, data):
        values = np.asarray(data, dtype=float)
        if values.shape[-2:] != self.source_shape:
            raise ValueError("Source does not match interpolation grid")
        flat = values.reshape((-1, np.prod(self.source_shape)))
        result = np.zeros((len(flat), np.prod(self.target_shape)))
        for indices, weights in zip(self.indices, self.weights):
            result += flat[:, indices] * weights
        return result.reshape(values.shape[:-2] + self.target_shape)
