"""Native ETCCDI interfaces. Rust owns reductions, quantiles and event counting.

Inputs and outputs are klimapy.native.Field, or mappings of those fields for
compute_indices. No dataframe framework is imported by the production package.
"""

from functools import wraps
import inspect

import numpy as np

from ..native.field import Field, month_lengths
from ..native.statistics import index as _index, threshold as _threshold
from .._core.validation import (
    convert_units,
    normalize_time,
    year_length,
    validate_reference_years,
    PRECIP_NAMES,
    TEMP_NAMES,
)


def check_data(pr, valid_var_names=None):
    return normalize_time(convert_units(pr, "precip"))


def check_temperature_data(temp, valid_var_names=None):
    return normalize_time(convert_units(temp, "temperature"))


def _periods(data, freq):
    dates, _ = data.time.dates()
    if freq == "YS":
        labels, groups = np.unique(dates[:, 0], return_inverse=True)
        expected = [year_length(y, data.time.calendar) for y in labels]
        dim, coords = "year", labels
    elif freq == "MS":
        labels, groups = np.unique(dates[:, 0] * 100 + dates[:, 1], return_inverse=True)
        expected = [
            month_lengths(int(n // 100), data.time.calendar)[int(n % 100) - 1]
            for n in labels
        ]
        dim, coords = "time", labels * 100 + 1
    else:
        raise ValueError("freq must be 'YS' or 'MS'")
    return dim, coords, groups, expected


def _run(
    data,
    op,
    *,
    name,
    limit=0.0,
    window=1,
    aux=None,
    freq="YS",
    min_valid_fraction=0.9,
    late=None,
    units="days/year",
    quality=None,
):
    dim, coords, groups, expected = _periods(data, freq)
    values = _index(
        data.values,
        groups,
        expected,
        op=op,
        aux=aux,
        late=late,
        limit=limit,
        window=window,
        fraction=min_valid_fraction if quality is None else 0.0,
    )
    if quality is not None:
        _, qcoords, qgroups, qexpected = _periods(quality, freq)
        if not np.array_equal(coords, qcoords):
            raise ValueError("Quality periods differ from calculation periods")
        qmask = _index(
            quality.values, qgroups, qexpected, op=7, fraction=min_valid_fraction
        )
        values[~np.isfinite(qmask)] = np.nan
    output_coords = {k: v for k, v in data.coords.items() if k != "time"}
    output_coords[dim] = coords
    attrs = {
        "units": units,
        "min_valid_fraction": min_valid_fraction,
        "reporting_frequency": freq,
        "engine": "rust",
    }
    attrs["input_units"] = data.attrs.get("units", "")
    if "units_assumed" in data.attrs:
        attrs["units_assumed"] = data.attrs["units_assumed"]
    if freq == "MS":
        attrs["time_encoding"] = "YYYYMMDD integer at month start"
    return Field(values, (dim, *data.dims[1:]), output_coords, attrs, name)


def select_baseline_period(data, start_year, end_year):
    validate_reference_years(data.time, start_year, end_year)
    years = data.time.labels()[0]
    return data.isel(time=(years >= start_year) & (years <= end_year))


def _aligned(*fields):
    a = fields[0]
    for b in fields[1:]:
        if a.dims != b.dims or a.shape != b.shape:
            raise ValueError("Input dimensions must match exactly")
        for d in a.dims:
            if d == "time":
                if a.time.calendar != b.time.calendar or not np.array_equal(
                    a.time.dates()[1], b.time.dates()[1]
                ):
                    raise ValueError("Input time coordinates must match exactly")
            elif not np.array_equal(a.coords[d], b.coords[d]):
                raise ValueError("Input coordinates must match exactly: " + d)


def _baseline(data, baseline_years):
    if baseline_years is None or len(baseline_years) != 2:
        raise ValueError("baseline_years must explicitly contain start and end years")
    return select_baseline_period(data, *map(int, baseline_years))


def PRCPTOT(pr, *, min_valid_fraction=0.9):
    return _run(
        check_data(pr),
        0,
        name="PRCPTOT",
        limit=1.0,
        units="mm",
        min_valid_fraction=min_valid_fraction,
    )


def R1mm_days(pr, *, min_valid_fraction=0.9):
    return _run(
        check_data(pr),
        1,
        name="R1mm_days",
        limit=1.0,
        min_valid_fraction=min_valid_fraction,
    )


def SDII(pr, *, min_valid_fraction=0.9):
    return _run(
        check_data(pr),
        2,
        name="SDII",
        limit=1.0,
        units="mm/day",
        min_valid_fraction=min_valid_fraction,
    )


def RXnday(pr, window=5, *, freq="YS", min_valid_fraction=0.9):
    result = _run(
        check_data(pr),
        4,
        name="RXnday",
        window=window,
        freq=freq,
        units="mm",
        min_valid_fraction=min_valid_fraction,
    )
    result.attrs.update(
        window_days=window,
        window_assignment="ending date; windows may cross reporting periods",
    )
    return result


def RX1DAY(pr, *, freq="YS", min_valid_fraction=0.9):
    value = RXnday(pr, 1, freq=freq, min_valid_fraction=min_valid_fraction)
    value.name = "RX1DAY"
    return value


def RX5DAY(pr, *, freq="YS", min_valid_fraction=0.9):
    value = RXnday(pr, 5, freq=freq, min_valid_fraction=min_valid_fraction)
    value.name = "RX5DAY"
    return value


def CDD(pr, *, min_valid_fraction=0.9):
    return _run(
        check_data(pr), 5, name="CDD", limit=1.0, min_valid_fraction=min_valid_fraction
    )


def CWD(pr, *, min_valid_fraction=0.9):
    return _run(
        check_data(pr), 6, name="CWD", limit=1.0, min_valid_fraction=min_valid_fraction
    )


def Rnnmm(pr, threshold=10.0, *, min_valid_fraction=0.9):
    if not np.isfinite(threshold) or threshold < 0:
        raise ValueError("threshold must be finite and nonnegative")
    return _run(
        check_data(pr),
        1,
        name="Rnnmm",
        limit=threshold,
        min_valid_fraction=min_valid_fraction,
    )


def _fixed_factory(n, mode):
    op, units = {
        "precipitation": (0, "mm"),
        "days": (1, "days/year"),
        "intensity": (2, "mm/day"),
        "ratio": (3, "1"),
    }[mode]

    def metric(pr, *, min_valid_fraction=0.9):
        return _run(
            check_data(pr),
            op,
            name=f"R{n}mm_{mode}",
            limit=float(n),
            units=units,
            min_valid_fraction=min_valid_fraction,
        )

    metric.__name__ = f"R{n}mm_{mode}"
    return metric


for _n in (10, 20, 25, 50):
    for _mode in ("precipitation", "days", "intensity", "ratio"):
        globals()[f"R{_n}mm_{_mode}"] = _fixed_factory(_n, _mode)


def _percentile_factory(n, mode):
    op, units = {
        "precipitation": (13, "mm"),
        "days": (15, "days/year"),
        "intensity": (17, "mm/day"),
        "ratio": (20, "1"),
    }[mode]

    def metric(pr, baseline_pr=None, baseline_years=None, *, min_valid_fraction=0.9):
        data = check_data(pr)
        base = _baseline(
            data if baseline_pr is None else check_data(baseline_pr), baseline_years
        )
        for dim in data.dims[1:]:
            if dim not in base.coords or not np.array_equal(
                data.coords[dim], base.coords[dim]
            ):
                raise ValueError("Baseline spatial coordinates must match target")
        if data.dims != base.dims:
            raise ValueError("Baseline dimensions must match target")
        threshold = _threshold(
            base.values, np.zeros(len(base.values), dtype=int), q=n / 100.0, wet=True
        )[0]
        result = _run(
            data,
            op,
            name=f"R{n}mm_{mode}",
            aux=threshold,
            units=units,
            min_valid_fraction=min_valid_fraction,
        )
        result.attrs.update(
            baseline_period=str(tuple(baseline_years)),
            percentile=n,
            quantile_method="median_unbiased",
            min_wet_days_for_statistics=10,
        )
        return result

    metric.__name__ = f"R{n}mm_{mode}"
    return metric


for _n in (90, 95, 99):
    for _mode in ("precipitation", "days", "intensity", "ratio"):
        globals()[f"R{_n}mm_{_mode}"] = _percentile_factory(_n, _mode)


def _temp_factory(name, op, limit=0.0, freq="YS"):
    def calculate(temp, min_valid_fraction):
        return _run(
            check_temperature_data(temp),
            op,
            name=name,
            limit=limit,
            freq=freq,
            units="degC" if op in (7, 8) else "days/year",
            min_valid_fraction=min_valid_fraction,
        )

    if name in ("FD", "TR", "TNx", "TNn"):

        def metric(tn, *, min_valid_fraction=0.9):
            return calculate(tn, min_valid_fraction)
    else:

        def metric(tx, *, min_valid_fraction=0.9):
            return calculate(tx, min_valid_fraction)

    metric.__name__ = name
    # Public parameter names are used by compute_indices and remain compatible.
    variable = "tn" if name in ("FD", "TR", "TNx", "TNn") else "tx"
    metric.__signature__ = inspect.Signature(
        [
            inspect.Parameter(variable, inspect.Parameter.POSITIONAL_OR_KEYWORD),
            inspect.Parameter(
                "min_valid_fraction", inspect.Parameter.KEYWORD_ONLY, default=0.9
            ),
        ]
    )
    return metric


FD = _temp_factory("FD", 9, 0.0)
SU = _temp_factory("SU", 10, 25.0)
ID = _temp_factory("ID", 9, 0.0)
TR = _temp_factory("TR", 10, 20.0)
TXx = _temp_factory("TXx", 7, freq="MS")
TNx = _temp_factory("TNx", 7, freq="MS")
TXn = _temp_factory("TXn", 8, freq="MS")
TNn = _temp_factory("TNn", 8, freq="MS")


def _noleap(data):
    dates, _ = data.time.dates()
    if data.time.calendar == "360_day":
        return data, (dates[:, 1] - 1) * 30 + dates[:, 2] - 1, 360
    keep = ~((dates[:, 1] == 2) & (dates[:, 2] == 29))
    data = data.isel(time=keep)
    dates = dates[keep]
    starts = np.array([0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334])
    return data, starts[dates[:, 1] - 1] + dates[:, 2] - 1, 365


def _temp_percentile(
    temp,
    baseline_years,
    percentile,
    greater,
    name,
    *,
    bootstrap=False,
    spell=False,
    min_valid_fraction=0.9,
):
    if not isinstance(bootstrap, bool):
        raise ValueError("bootstrap must be a boolean")
    original = check_temperature_data(temp)
    base, bd, size = _noleap(_baseline(original, baseline_years))
    target, td, _ = _noleap(original)
    full = _threshold(base.values, bd, ndays=size, radius=2, q=percentile / 100.0)
    op = (16 if greater else 14) if spell else (11 if greater else 12)
    kw = dict(
        name=name,
        window=6 if spell else 1,
        min_valid_fraction=min_valid_fraction,
        units="days/year" if spell else "%",
    )
    result = _run(target, op, aux=full[td], quality=original, **kw)
    if bootstrap:
        by = base.time.labels()[0]
        ty = target.time.labels()[0]
        reference_years = np.unique(by)
        overlap = set(reference_years).intersection(ty)
        if overlap and len(reference_years) < 2:
            raise ValueError(
                "bootstrap requires at least two reference years; use bootstrap=False"
            )
        for year in sorted(overlap):
            own = target.isel(time=ty == year)
            original_year = original.isel(time=original.time.labels()[0] == year)
            replicas = []
            remaining = np.flatnonzero(by != year)
            for donor in reference_years[reference_years != year]:
                sample = np.concatenate([remaining, np.flatnonzero(by == donor)])
                thresholds = _threshold(
                    base.values[sample],
                    bd[sample],
                    ndays=size,
                    radius=2,
                    q=percentile / 100.0,
                )
                replicas.append(
                    _run(
                        own,
                        op,
                        aux=thresholds[td[ty == year]],
                        quality=original_year,
                        **kw,
                    ).values[0]
                )
            # Rust computes the replicate mean and requires all replicas finite.
            replicas = np.stack(replicas)
            mean = _index(
                replicas,
                np.zeros(len(replicas), dtype=int),
                [len(replicas)],
                op=18,
                fraction=1.0,
            )[0]
            result.values[result.coords["year"] == year] = mean
    result.attrs.update(
        baseline_period=str(tuple(baseline_years)),
        percentile=percentile,
        quantile_method="median_unbiased",
        bootstrap=bool(bootstrap),
        leap_day_policy="exclude February 29 except in 360_day calendars",
    )
    return result


def TN10p(tn, baseline_years=(1961, 1990), *, bootstrap=True, min_valid_fraction=0.9):
    return _temp_percentile(
        tn,
        baseline_years,
        10,
        False,
        "TN10p",
        bootstrap=bootstrap,
        min_valid_fraction=min_valid_fraction,
    )


def TX10p(tx, baseline_years=(1961, 1990), *, bootstrap=True, min_valid_fraction=0.9):
    return _temp_percentile(
        tx,
        baseline_years,
        10,
        False,
        "TX10p",
        bootstrap=bootstrap,
        min_valid_fraction=min_valid_fraction,
    )


def TN90p(tn, baseline_years=(1961, 1990), *, bootstrap=True, min_valid_fraction=0.9):
    return _temp_percentile(
        tn,
        baseline_years,
        90,
        True,
        "TN90p",
        bootstrap=bootstrap,
        min_valid_fraction=min_valid_fraction,
    )


def TX90p(tx, baseline_years=(1961, 1990), *, bootstrap=True, min_valid_fraction=0.9):
    return _temp_percentile(
        tx,
        baseline_years,
        90,
        True,
        "TX90p",
        bootstrap=bootstrap,
        min_valid_fraction=min_valid_fraction,
    )


def WSDI(tx, baseline_years=(1961, 1990), *, min_valid_fraction=0.9):
    return _temp_percentile(
        tx,
        baseline_years,
        90,
        True,
        "WSDI",
        spell=True,
        min_valid_fraction=min_valid_fraction,
    )


def CSDI(tn, baseline_years=(1961, 1990), *, min_valid_fraction=0.9):
    return _temp_percentile(
        tn,
        baseline_years,
        10,
        False,
        "CSDI",
        spell=True,
        min_valid_fraction=min_valid_fraction,
    )


def GSL(tg, hemisphere="NH", *, min_valid_fraction=0.9):
    data = check_temperature_data(tg)
    hemi = hemisphere.upper()
    if hemi not in ("NH", "SH"):
        raise ValueError("hemisphere must be NH or SH")
    dates, _ = data.time.dates()
    labels = dates[:, 0] + ((dates[:, 1] >= 7) if hemi == "SH" else 0)
    years, groups = np.unique(labels, return_inverse=True)
    expected = [year_length(y, data.time.calendar) for y in years]
    # Southern reporting year y covers July(y-1)..June(y).
    late = dates[:, 1] <= 6 if hemi == "SH" else dates[:, 1] >= 7
    values = _index(
        data.values, groups, expected, op=19, late=late, fraction=min_valid_fraction
    )
    return Field(
        values,
        ("year", *data.dims[1:]),
        {**{d: data.coords[d] for d in data.dims[1:]}, "year": years},
        {"units": "days/year", "hemisphere": hemi},
        "GSL",
    )


def DTR(tx, tn, *, min_valid_fraction=0.9):
    tx, tn = check_temperature_data(tx), check_temperature_data(tn)
    _aligned(tx, tn)
    return _run(
        tx,
        18,
        aux=tn.values,
        name="DTR",
        freq="MS",
        units="degC",
        min_valid_fraction=min_valid_fraction,
    )


_ALIASES = {
    "Rx1day": "RX1DAY",
    "Rx5day": "RX5DAY",
    "RXdday": "RXnday",
    "R10mm": "R10mm_days",
    "R20mm": "R20mm_days",
    "R95p": "R95mm_precipitation",
    "R99p": "R99mm_precipitation",
    "R95pTOT": "R95mm_precipitation",
    "R99pTOT": "R99mm_precipitation",
}
for _alias, _canonical in _ALIASES.items():
    globals()[_alias] = globals()[_canonical]


def compute_indices(
    data,
    indices=None,
    *,
    baseline_years=None,
    min_valid_fraction=0.9,
    spatial_chunk_size=None,
    index_options=None,
):
    selected = (
        ["PRCPTOT", "R1mm_days", "SDII", "RX1DAY", "RX5DAY", "CDD", "CWD"]
        if indices is None
        else list(indices)
    )
    options = dict(index_options or {})
    if (
        not selected
        or any(n not in _METRICS for n in selected)
        or set(options) - set(selected)
    ):
        raise ValueError("Unknown/empty indices or options for unselected indices")
    if spatial_chunk_size is not None:
        if (
            isinstance(spatial_chunk_size, bool)
            or not isinstance(spatial_chunk_size, int)
            or spatial_chunk_size < 1
        ):
            raise ValueError("spatial_chunk_size must be a positive integer")
        sources = {"pr": data} if isinstance(data, Field) else dict(data)
        first = next(iter(sources.values()))
        if any(f.dims != ("time", "lat", "lon") for f in sources.values()):
            raise ValueError("Chunked input needs time, lat, lon fields")
        _aligned(*sources.values())
        result = {}
        for i in range(0, first.shape[1], spatial_chunk_size):
            for j in range(0, first.shape[2], spatial_chunk_size):
                tile = {
                    k: f.isel(
                        lat=slice(i, i + spatial_chunk_size),
                        lon=slice(j, j + spatial_chunk_size),
                    )
                    for k, f in sources.items()
                }
                values = compute_indices(
                    next(iter(tile.values())) if isinstance(data, Field) else tile,
                    selected,
                    baseline_years=baseline_years,
                    min_valid_fraction=min_valid_fraction,
                    index_options=options,
                )
                for name, value in values.items():
                    if name not in result:
                        output = np.empty((value.shape[0], *first.shape[1:]))
                        result[name] = Field(
                            output,
                            value.dims,
                            {
                                **value.coords,
                                "lat": first.coords["lat"],
                                "lon": first.coords["lon"],
                            },
                            value.attrs,
                            name,
                        )
                    result[name].values[
                        :, i : i + value.shape[1], j : j + value.shape[2]
                    ] = value.values
        return result
    aliases = {
        "pr": PRECIP_NAMES,
        "tx": ("tx", "tasmax", "tmax"),
        "tn": ("tn", "tasmin", "tmin"),
        "tg": ("tg", "tas", "t2m", "tm"),
    }

    def resolve(name):
        if isinstance(data, Field):
            return data
        for candidate in aliases[name]:
            if candidate in data:
                return data[candidate]
        raise ValueError("Missing input for " + name)

    output = {}
    for name in selected:
        fn = globals()[name]
        params = inspect.signature(fn).parameters
        opt = options.get(name, {})
        if (
            not isinstance(opt, dict)
            or set(opt) - set(params)
            or set(opt) & {"pr", "tx", "tn", "tg", "temp", "min_valid_fraction"}
        ):
            raise ValueError("Invalid index_options for " + name)
        if name in ("FD", "TR", "TNx", "TNn"):
            args = [resolve("tn")]
        elif name in ("SU", "ID", "TXx", "TXn"):
            args = [resolve("tx")]
        else:
            args = [resolve(p) for p in params if p in aliases]
        kwargs = dict(opt, min_valid_fraction=min_valid_fraction)
        if "baseline_years" in params and baseline_years is not None:
            kwargs.setdefault("baseline_years", baseline_years)
        output[name] = fn(*args, **kwargs)
    return output


_METRICS = {
    name
    for name in globals()
    if name
    in (
        "PRCPTOT",
        "R1mm_days",
        "SDII",
        "RX1DAY",
        "RX5DAY",
        "RXnday",
        "Rnnmm",
        "CDD",
        "CWD",
        "FD",
        "SU",
        "ID",
        "TR",
        "GSL",
        "TXx",
        "TNx",
        "TXn",
        "TNn",
        "TN10p",
        "TX10p",
        "TN90p",
        "TX90p",
        "WSDI",
        "CSDI",
        "DTR",
    )
    or name.startswith("R")
    and "mm_" in name
} | set(_ALIASES)
