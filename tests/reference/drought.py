"""Independent SciPy/NumPy drought reference; only imported in Test1."""

import numpy as np
from scipy.special import gamma as gamma_function
from scipy.stats import fisk, gamma, norm


def standardized(values, months, years, scale, baseline, *, pet=None):
    x = np.asarray(values, dtype=float)
    if pet is not None:
        x = x - pet
    rolling = np.full_like(x, np.nan)
    for t in range(scale - 1, len(x)):
        block = x[t - scale + 1 : t + 1]
        rolling[t] = np.where(np.isfinite(block).all(axis=0), block.sum(axis=0), np.nan)
    out = np.full_like(rolling, np.nan)
    params = np.full((12,) + x.shape[1:] + (4,), np.nan)
    for coordinate in np.ndindex(x.shape[1:]):
        for month in range(1, 13):
            selection = (
                (months == month) & (years >= baseline[0]) & (years <= baseline[1])
            )
            a = rolling[(selection,) + coordinate]
            a = np.sort(a[np.isfinite(a)])
            if len(a) < 20:
                continue
            target = months == month
            query = rolling[(target,) + coordinate]
            if pet is None:
                positive = a[a > 0]
                pzero = np.mean(a == 0)
                mean = positive.mean()
                aux = np.log(mean) - np.log(positive).mean()
                shape = (1 + np.sqrt(1 + 4 * aux / 3)) / (4 * aux)
                spread = mean / shape
                location = 0.0
                cdf = pzero + (1 - pzero) * gamma.cdf(query, shape, scale=spread)
            else:
                # Unbiased survival PWMs, independently written in reverse order.
                n = len(a)
                descending = a[::-1]
                rank = np.arange(n)
                w0 = descending.mean()
                w1 = np.mean(descending * rank / (n - 1))
                w2 = np.mean(descending * rank * (rank - 1) / (n - 1) / (n - 2))
                shape = (2 * w1 - w0) / (6 * w1 - w0 - 6 * w2)
                if not np.isfinite(shape) or shape <= 1:
                    continue
                g = gamma_function(1 + 1 / shape) * gamma_function(1 - 1 / shape)
                spread = (w0 - 2 * w1) * shape / g
                location = w0 - spread * g
                pzero = 0.0
                if location >= a[0]:
                    continue
                cdf = fisk.cdf(query, shape, loc=location, scale=spread)
            out[(target,) + coordinate] = norm.ppf(np.clip(cdf, 1e-10, 1 - 1e-10))
            params[(month - 1,) + coordinate] = (shape, spread, location, pzero)
    return out, params
