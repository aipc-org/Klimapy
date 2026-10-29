"""Small explicit NetCDF data model backed by Rust + native libnetcdf.

No xarray/netCDF4-Python import. Coordinates and CF dates stay numeric with their
units/calendar attributes; decoding them into datetime objects is an adapter task.
"""

import ctypes as ct
from ctypes.util import find_library
from functools import lru_cache
import os
from pathlib import Path
import threading
import sys

import numpy as np

from .._backends.rust import _library, _ptr, _SIZE_PTR, _INT_PTR


def _name(value):
    raw = os.fsencode(value)
    if b"\0" in raw:
        raise ValueError("Embedded NUL in file, variable or attribute name")
    return raw


@lru_cache(maxsize=1)
def _io_library():
    lib = _library()
    signatures = {
        "kl_nc_init": [ct.c_char_p],
        "kl_nc_open": [ct.c_char_p, ct.c_int, _INT_PTR],
        "kl_nc_close": [ct.c_int],
        "kl_nc_count": [ct.c_int, ct.c_char_p, _INT_PTR],
        "kl_nc_name": [ct.c_int, ct.c_char_p, ct.c_int, ct.c_char_p],
        "kl_nc_info": [ct.c_int, ct.c_char_p, _INT_PTR, _INT_PTR, _INT_PTR],
        "kl_nc_dimension": [ct.c_int, ct.c_char_p, ct.c_int, ct.c_char_p, _SIZE_PTR],
        "kl_nc_attribute": [
            ct.c_int,
            ct.c_char_p,
            ct.c_int,
            ct.c_char_p,
            _INT_PTR,
            _SIZE_PTR,
        ],
        "kl_nc_string_attribute": [
            ct.c_int,
            ct.c_char_p,
            ct.c_char_p,
            ct.c_size_t,
            ct.c_char_p,
            ct.c_size_t,
            _SIZE_PTR,
        ],
        "kl_nc_get_attribute": [
            ct.c_int,
            ct.c_char_p,
            ct.c_char_p,
            ct.c_void_p,
            ct.c_int,
        ],
        "kl_nc_read": [
            ct.c_int,
            ct.c_char_p,
            _SIZE_PTR,
            _SIZE_PTR,
            ct.POINTER(ct.c_double),
        ],
        "kl_nc_def_dim": [ct.c_int, ct.c_char_p, ct.c_size_t],
        "kl_nc_def_var": [ct.c_int, ct.c_char_p, ct.c_char_p, ct.c_int, ct.c_int],
        "kl_nc_put_attribute": [
            ct.c_int,
            ct.c_char_p,
            ct.c_char_p,
            ct.c_void_p,
            ct.c_size_t,
            ct.c_int,
        ],
        "kl_nc_write": [
            ct.c_int,
            ct.c_char_p,
            _SIZE_PTR,
            _SIZE_PTR,
            ct.POINTER(ct.c_double),
        ],
    }
    for name, args in signatures.items():
        fn = getattr(lib, name)
        fn.argtypes, fn.restype = args, ct.c_int
    lib.kl_nc_error.argtypes, lib.kl_nc_error.restype = [ct.c_int], ct.c_char_p
    library = os.environ.get("KLIMAPY_NETCDF_LIBRARY") or find_library("netcdf")
    if not library and sys.platform == "darwin":
        # ctypes discovery can miss Homebrew outside dyld's search paths.
        for prefix in ("/opt/homebrew", "/usr/local"):
            for relative in ("lib/libnetcdf.dylib", "opt/netcdf/lib/libnetcdf.dylib"):
                candidate = Path(prefix) / relative
                if candidate.is_file():
                    library = str(candidate)
                    break
            if library:
                break
    if not library:
        raise RuntimeError(
            "libnetcdf not found; set KLIMAPY_NETCDF_LIBRARY to its shared-library path"
        )
    _check(lib, lib.kl_nc_init(_name(library)))
    return lib


def _check(lib, code):
    if code:
        message = lib.kl_nc_error(code).decode("utf-8", errors="replace")
        raise OSError(code, message)


class Dataset:
    """Closable native file handle, root variable listing and explicit group paths.

    Read slices have unit stride. Numeric variables are returned as float64;
    Rust masks fill/missing values before applying scale_factor/add_offset.
    Unsupported encodings raise rather than silently falling back.
    """

    def __init__(self, path, mode="r"):
        if mode not in ("r", "x"):
            raise ValueError("mode must be 'r' or 'x' (create without overwriting)")
        self.path, self.mode = Path(path), mode
        self._lib = _io_library()
        self._lock = threading.RLock()
        identifier = ct.c_int()
        _check(
            self._lib,
            self._lib.kl_nc_open(_name(path), int(mode == "x"), ct.byref(identifier)),
        )
        self._id = identifier.value

    def _open(self):
        if self._id is None:
            raise RuntimeError("Dataset is closed")
        return self._id

    def close(self):
        with self._lock:
            if self._id is not None:
                identifier, self._id = self._id, None
                _check(self._lib, self._lib.kl_nc_close(identifier))

    def __enter__(self):
        self._open()
        return self

    def __exit__(self, *exc):
        self.close()

    def __del__(self):
        if getattr(self, "_id", None) is not None:
            try:
                self.close()
            except Exception:
                pass

    def names(self, group=""):
        with self._lock:
            count = ct.c_int()
            _check(
                self._lib,
                self._lib.kl_nc_count(self._open(), _name(group), ct.byref(count)),
            )
            names = []
            for index in range(count.value):
                name = ct.create_string_buffer(257)
                _check(
                    self._lib, self._lib.kl_nc_name(self._id, _name(group), index, name)
                )
                names.append(name.value.decode("utf-8"))
            return names

    @property
    def variables(self):
        return {name: self[name] for name in self.names()}

    def __getitem__(self, name):
        with self._lock:
            return Variable(self, name)

    def set_attr(self, name, value):
        """Set a global file attribute."""
        variable = Variable.__new__(Variable)
        variable._dataset, variable.name, variable.attrs = self, "", {}
        variable.set_attr(name, value)

    def create_variable(
        self, name, dims, shape, *, dtype="float64", compression=0, attrs=None
    ):
        if self.mode != "x":
            raise ValueError("File is read-only")
        if "/" in name or len(dims) != len(shape) or len(dims) > 32:
            raise ValueError(
                "Creation supports root variables with at most 32 named dimensions"
            )
        kinds = {"float32": 5, "float64": 6, "int16": 3}
        if (
            str(np.dtype(dtype)) not in kinds
            or not isinstance(compression, int)
            or not 0 <= compression <= 9
        ):
            raise ValueError(
                "Supported dtypes: float32, float64, int16; compression: 0..9"
            )
        if any(not isinstance(n, (int, np.integer)) or n <= 0 for n in shape):
            raise ValueError("Dimensions must have positive fixed lengths")
        if any(not d or "," in d or "/" in d for d in dims) or len(set(dims)) != len(
            dims
        ):
            raise ValueError(
                "Dimensions must have distinct nonempty names without comma or slash"
            )
        with self._lock:
            for dim, length in zip(dims, shape):
                _check(
                    self._lib,
                    self._lib.kl_nc_def_dim(self._open(), _name(dim), int(length)),
                )
            _check(
                self._lib,
                self._lib.kl_nc_def_var(
                    self._id,
                    _name(name),
                    _name(",".join(dims)),
                    kinds[str(np.dtype(dtype))],
                    compression,
                ),
            )
            variable = self[name]
            for key, value in (attrs or {}).items():
                variable.set_attr(key, value)
            return variable


class Variable:
    def __init__(self, dataset, name):
        if not name:
            raise ValueError("Variable name must be nonempty")
        self._dataset, self.name = dataset, name
        lib, identifier = dataset._lib, dataset._open()
        rank, kind, natts = ct.c_int(), ct.c_int(), ct.c_int()
        _check(
            lib,
            lib.kl_nc_info(
                identifier, _name(name), ct.byref(rank), ct.byref(kind), ct.byref(natts)
            ),
        )
        self.storage_type = kind.value
        dims, shape = [], []
        for axis in range(rank.value):
            dim, length = ct.create_string_buffer(257), ct.c_size_t()
            _check(
                lib,
                lib.kl_nc_dimension(
                    identifier, _name(name), axis, dim, ct.byref(length)
                ),
            )
            dims.append(dim.value.decode("utf-8"))
            shape.append(length.value)
        self.dims, self.shape = tuple(dims), tuple(shape)
        self.attrs = {}
        for index in range(natts.value):
            key, kind, length = ct.create_string_buffer(257), ct.c_int(), ct.c_size_t()
            _check(
                lib,
                lib.kl_nc_attribute(
                    identifier,
                    _name(name),
                    index,
                    key,
                    ct.byref(kind),
                    ct.byref(length),
                ),
            )
            if kind.value == 2:
                buffer = ct.create_string_buffer(length.value + 1)
                _check(
                    lib,
                    lib.kl_nc_get_attribute(identifier, _name(name), key, buffer, 1),
                )
                value = buffer.raw[: length.value].decode("utf-8")
            elif kind.value == 12:
                strings = []
                for index in range(length.value):
                    size = ct.c_size_t()
                    _check(
                        lib,
                        lib.kl_nc_string_attribute(
                            identifier, _name(name), key, index, None, 0, ct.byref(size)
                        ),
                    )
                    buffer = ct.create_string_buffer(size.value + 1)
                    _check(
                        lib,
                        lib.kl_nc_string_attribute(
                            identifier,
                            _name(name),
                            key,
                            index,
                            buffer,
                            size.value,
                            ct.byref(size),
                        ),
                    )
                    strings.append(buffer.raw[: size.value].decode("utf-8"))
                value = strings[0] if len(strings) == 1 else strings
            elif kind.value in (1, 3, 4, 5, 6, 7, 8, 9, 10, 11):
                buffer = np.empty(length.value, dtype=np.float64)
                _check(
                    lib,
                    lib.kl_nc_get_attribute(
                        identifier, _name(name), key, buffer.ctypes.data, 0
                    ),
                )
                value = buffer.item() if buffer.size == 1 else buffer
            else:
                raise NotImplementedError(
                    "Unsupported NetCDF attribute type " + str(kind.value)
                )
            self.attrs[key.value.decode("utf-8")] = value

    def _slice(self, key):
        if key is Ellipsis:
            key = (slice(None),) * len(self.shape)
        elif not isinstance(key, tuple):
            key = (key,)
        if any(k is Ellipsis for k in key):
            if sum(k is Ellipsis for k in key) > 1:
                raise IndexError("Only one ellipsis allowed")
            index = next(i for i, k in enumerate(key) if k is Ellipsis)
            key = (
                key[:index]
                + (slice(None),) * (len(self.shape) - len(key) + 1)
                + key[index + 1 :]
            )
        if len(key) > len(self.shape):
            raise IndexError("Too many indices")
        key += (slice(None),) * (len(self.shape) - len(key))
        starts, counts, squeeze = [], [], []
        for axis, (k, size) in enumerate(zip(key, self.shape)):
            if isinstance(k, (int, np.integer)):
                k = int(k)
                if k < 0:
                    k += size
                if not 0 <= k < size:
                    raise IndexError("Index outside variable")
                start, count = k, 1
                squeeze.append(axis)
            elif isinstance(k, slice):
                start, stop, step = k.indices(size)
                if step != 1:
                    raise ValueError(
                        "Native slices currently require unit positive stride"
                    )
                count = max(0, stop - start)
            else:
                raise TypeError("Only integers, slices and ellipsis are supported")
            starts.append(start)
            counts.append(count)
        return (
            np.asarray(starts, dtype=np.uintp),
            np.asarray(counts, dtype=np.uintp),
            tuple(squeeze),
        )

    def __getitem__(self, key):
        starts, counts, squeeze = self._slice(key)
        out = np.empty(tuple(int(n) for n in counts), dtype=np.float64)
        ds = self._dataset
        with ds._lock:
            identifier = ds._open()
            if out.size:
                _check(
                    ds._lib,
                    ds._lib.kl_nc_read(
                        identifier,
                        _name(self.name),
                        _ptr(starts, _SIZE_PTR),
                        _ptr(counts, _SIZE_PTR),
                        _ptr(out),
                    ),
                )
        return np.squeeze(out, axis=squeeze)

    def write(self, values, key=Ellipsis):
        ds = self._dataset
        if ds.mode != "x":
            raise ValueError("File is read-only")
        if "scale_factor" in self.attrs or "add_offset" in self.attrs:
            raise ValueError(
                "Packed writes require write_raw() with encoded storage values"
            )
        return self.write_raw(values, key)

    def write_raw(self, values, key=Ellipsis):
        """Write storage values; does not apply inverse packing or NaN-to-fill conversion."""
        ds = self._dataset
        if ds.mode != "x":
            raise ValueError("File is read-only")
        starts, counts, squeeze = self._slice(key)
        shape = tuple(int(n) for i, n in enumerate(counts) if i not in squeeze)
        array = np.asarray(values, dtype=np.float64)
        if array.shape != shape:
            raise ValueError("Write shape must exactly match the selected region")
        array = np.ascontiguousarray(array)
        with ds._lock:
            identifier = ds._open()
            if array.size:
                _check(
                    ds._lib,
                    ds._lib.kl_nc_write(
                        identifier,
                        _name(self.name),
                        _ptr(starts, _SIZE_PTR),
                        _ptr(counts, _SIZE_PTR),
                        _ptr(array),
                    ),
                )

    def set_attr(self, name, value):
        ds = self._dataset
        if ds.mode != "x":
            raise ValueError("File is read-only")
        if isinstance(value, str):
            raw = value.encode("utf-8")
            buffer, length, text = ct.create_string_buffer(raw), len(raw), 1
            pointer = ct.cast(buffer, ct.c_void_p)
        else:
            buffer = np.ascontiguousarray(np.atleast_1d(value), dtype=np.float64)
            length, text = buffer.size, 0
            pointer = ct.c_void_p(buffer.ctypes.data)
        with ds._lock:
            _check(
                ds._lib,
                ds._lib.kl_nc_put_attribute(
                    ds._open(), _name(self.name), _name(name), pointer, length, text
                ),
            )
            self.attrs[name] = value


def open_dataset(path):
    return Dataset(path)
