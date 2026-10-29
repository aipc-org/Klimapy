"""Independent Test1 references for migration; never imported by production.

Uses NumPy/SciPy/xarray definitions rather than Klimapy helpers or Rust outputs.
"""

import numpy as np
from scipy.interpolate import UnivariateSpline


def transfer(model, observed, query, n_quantiles=50):
    a = np.maximum(np.asarray(model)[np.isfinite(model)], 0.0)
    b = np.maximum(np.asarray(observed)[np.isfinite(observed)], 0.0)
    if min(len(a), len(b)) < 20:
        return np.asarray(query).copy()
    count = min(n_quantiles, max(20, int(min(len(a), len(b)) / 25)))
    q = np.linspace(0.02, 0.98, count)
    x, y = np.quantile(a, q), np.quantile(b, q)
    for i in range(1, len(x)):
        if x[i] <= x[i - 1]:
            x[i] = x[i - 1] + 1e-10
    spline = UnivariateSpline(x, y, k=3, s=0.8 * len(x))
    query = np.asarray(query)
    result = np.where(query < x[0], y[0], np.where(query > x[-1], y[-1], spline(query)))
    result = np.maximum(result, 0.0)
    return np.where(result < 1e-10, 0.0, result)


def smooth(values, harmonics=3):
    shape = values.shape
    flat = np.asarray(values, dtype=float).reshape(len(values), -1).copy()
    missing = ~np.isfinite(flat)
    t = np.arange(len(flat))
    for c in range(flat.shape[1]):
        valid = ~missing[:, c]
        flat[:, c] = np.interp(t, t[valid], flat[valid, c]) if valid.any() else 0.0
    frequency = np.fft.rfft(flat, axis=0)
    frequency[harmonics + 1 :] = 0.0
    result = np.maximum(np.fft.irfft(frequency, n=len(flat), axis=0), 0.0)
    result[missing] = np.nan
    return result.reshape(shape).astype("float32")


def temp_threshold(values, years, month, day, percentile, exclude=None, donor=None):
    # Fixed noleap calendar slots; Gregorian February 29 is removed before calls.
    starts = np.array([0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334])
    doy = starts[month - 1] + day - 1
    sel = np.flatnonzero(
        np.ones(len(years), bool) if exclude is None else years != exclude
    )
    if donor is not None:
        sel = np.concatenate([sel, np.flatnonzero(years == donor)])
    output = []
    for d in range(365):
        distance = np.abs(doy[sel] - d)
        sample = values[sel[np.minimum(distance, 365 - distance) <= 2]]
        output.append(
            np.nanquantile(sample, percentile / 100.0, axis=0, method="median_unbiased")
        )
    return np.stack(output), doy


def temp_metric(field, percentile, greater, *, bootstrap=False, spell=False):
    years = field.time.dt.year.values
    months, days = field.time.dt.month.values, field.time.dt.day.values
    keep = ~((months == 2) & (days == 29))
    values, years, months, days = (
        field.values[keep],
        years[keep],
        months[keep],
        days[keep],
    )
    threshold, doy = temp_threshold(values, years, months, days, percentile)
    output = []
    for year in np.unique(years):
        mask = years == year
        samples = (
            [None] if not bootstrap else [y for y in np.unique(years) if y != year]
        )
        replicas = []
        for donor in samples:
            th = (
                threshold
                if donor is None
                else temp_threshold(
                    values, years, months, days, percentile, exclude=year, donor=donor
                )[0]
            )
            selected = (
                values[mask] > th[doy[mask]]
                if greater
                else values[mask] < th[doy[mask]]
            )
            valid = np.isfinite(values[mask]) & np.isfinite(th[doy[mask]])
            if not spell:
                result = (
                    np.sum(selected & valid, axis=0) / np.sum(valid, axis=0) * 100.0
                )
            else:
                a = selected.reshape(selected.shape[0], -1)
                result = np.zeros(a.shape[1])
                for c in range(a.shape[1]):
                    changes = np.diff(np.r_[False, a[:, c], False].astype(int))
                    lengths = np.flatnonzero(changes == -1) - np.flatnonzero(
                        changes == 1
                    )
                    result[c] = lengths[lengths >= 6].sum()
                result = result.reshape(selected.shape[1:])
            replicas.append(result)
        output.append(np.mean(replicas, axis=0))
    return np.stack(output)


def gsl(field, hemisphere="NH"):
    years, months = field.time.dt.year.values, field.time.dt.month.values
    reporting = years + (months >= 7) if hemisphere == "SH" else years
    output = []
    for year in np.unique(reporting):
        selected = reporting == year
        values = field.values[selected]
        late = months[selected] <= 6 if hemisphere == "SH" else months[selected] >= 7
        # Validation uses complete northern years; partial SH periods are NaN.
        expected = 366 if year % 4 == 0 else 365
        result = np.full(values.shape[1:], np.nan)
        for c in np.ndindex(result.shape):
            v = values[(slice(None), *c)]
            if np.isfinite(v).sum() < 0.9 * expected:
                continue
            warm = np.flatnonzero(
                np.convolve((v > 5).astype(int), np.ones(6, dtype=int), "valid") == 6
            )
            if not len(warm):
                result[c] = 0.0
                continue
            start = warm[0]
            cold = (v < 5) & late & (np.arange(len(v)) > start)
            end = np.flatnonzero(
                np.convolve(cold.astype(int), np.ones(6, dtype=int), "valid") == 6
            )
            if len(end):
                result[c] = end[0] - start
        output.append(result)
    return np.stack(output)
