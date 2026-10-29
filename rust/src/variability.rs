//! Temporal grouping and anomaly kernels; labels are prepared once by adapters.

/// # Safety
/// input/output=steps*cells, groups=steps, selected=steps; ngroups is positive.
#[no_mangle]
pub unsafe extern "C" fn seasonal_anomaly(
    input: *const f64,
    groups: *const usize,
    selected: *const u8,
    output: *mut f64,
    steps: usize,
    cells: usize,
    ngroups: usize,
) -> i32 {
    let (Some(n), Some(k)) = (steps.checked_mul(cells), ngroups.checked_mul(cells)) else {
        return 1;
    };
    if input.is_null()
        || groups.is_null()
        || selected.is_null()
        || output.is_null()
        || ngroups == 0
        || n > isize::MAX as usize / 8
        || k > isize::MAX as usize / 8
        || steps > isize::MAX as usize / 8
    {
        return 1;
    }
    let (v, g, sel, out) = (
        std::slice::from_raw_parts(input, n),
        std::slice::from_raw_parts(groups, steps),
        std::slice::from_raw_parts(selected, steps),
        std::slice::from_raw_parts_mut(output, n),
    );
    if g.iter().any(|&i| i >= ngroups) {
        return 1;
    }
    let mut sums = vec![0.0; k];
    let mut counts = vec![0usize; k];
    for t in 0..steps {
        if sel[t] != 0 {
            for i in 0..cells {
                let x = v[t * cells + i];
                if x.is_finite() {
                    let p = g[t] * cells + i;
                    sums[p] += x;
                    counts[p] += 1;
                }
            }
        }
    }
    for t in 0..steps {
        for i in 0..cells {
            let p = g[t] * cells + i;
            out[t * cells + i] = if counts[p] > 0 {
                v[t * cells + i] - sums[p] / counts[p] as f64
            } else {
                f64::NAN
            };
        }
    }
    0
}

/// Population standard deviation per temporal group using Welford accumulation.
/// # Safety
/// input=steps*cells, groups=steps, output=ngroups*cells, buffers disjoint.
#[no_mangle]
pub unsafe extern "C" fn grouped_std(
    input: *const f64,
    groups: *const usize,
    output: *mut f64,
    steps: usize,
    cells: usize,
    ngroups: usize,
) -> i32 {
    let (Some(n), Some(k)) = (steps.checked_mul(cells), ngroups.checked_mul(cells)) else {
        return 1;
    };
    if input.is_null()
        || groups.is_null()
        || output.is_null()
        || n > isize::MAX as usize / 8
        || k > isize::MAX as usize / 8
        || steps > isize::MAX as usize / 8
    {
        return 1;
    }
    let (v, g, out) = (
        std::slice::from_raw_parts(input, n),
        std::slice::from_raw_parts(groups, steps),
        std::slice::from_raw_parts_mut(output, k),
    );
    if g.iter().any(|&i| i >= ngroups) {
        return 1;
    }
    let mut mean = vec![0.0; k];
    let mut count = vec![0usize; k];
    out.fill(0.0);
    for t in 0..steps {
        for i in 0..cells {
            let x = v[t * cells + i];
            if x.is_nan() {
                continue;
            }
            let p = g[t] * cells + i;
            count[p] += 1;
            let delta = x - mean[p];
            mean[p] += delta / count[p] as f64;
            out[p] += delta * (x - mean[p]);
        }
    }
    for i in 0..k {
        out[i] = if count[i] > 0 {
            (out[i] / count[i] as f64).sqrt()
        } else {
            f64::NAN
        };
    }
    0
}

/// Fused variability tile: seasonal anomalies, detrend, yearly std and coverage.
/// # Safety
/// input=steps*cells; season/year/selected=steps; expected=nyears; output=nyears*cells.
#[no_mangle]
pub unsafe extern "C" fn variability_block(
    input: *const f64,
    season: *const usize,
    selected: *const u8,
    year: *const usize,
    expected: *const f64,
    output: *mut f64,
    steps: usize,
    cells: usize,
    nyears: usize,
    min_fraction: f64,
) -> i32 {
    let (Some(n), Some(k)) = (steps.checked_mul(cells), nyears.checked_mul(cells)) else {
        return 1;
    };
    if expected.is_null()
        || year.is_null()
        || output.is_null()
        || n > isize::MAX as usize / 8
        || k > isize::MAX as usize / 8
        || nyears > isize::MAX as usize / 8
        || !min_fraction.is_finite()
        || !(0.0..=1.0).contains(&min_fraction)
    {
        return 1;
    }
    let e = std::slice::from_raw_parts(expected, nyears);
    let y = std::slice::from_raw_parts(year, steps);
    if e.iter().any(|v| !v.is_finite() || *v <= 0.0) || y.iter().any(|&i| i >= nyears) {
        return 1;
    }
    let mut anomaly = vec![0.0; n];
    let mut detrended = vec![0.0; n];
    let code = seasonal_anomaly(
        input,
        season,
        selected,
        anomaly.as_mut_ptr(),
        steps,
        cells,
        366,
    );
    if code != 0 {
        return code;
    }
    let code = super::detrend(anomaly.as_ptr(), detrended.as_mut_ptr(), steps, cells);
    if code != 0 {
        return code;
    }
    let code = grouped_std(detrended.as_ptr(), year, output, steps, cells, nyears);
    if code != 0 {
        return code;
    }
    let mut counts = vec![0usize; k];
    for t in 0..steps {
        for i in 0..cells {
            if detrended[t * cells + i].is_finite() {
                counts[y[t] * cells + i] += 1;
            }
        }
    }
    let out = std::slice::from_raw_parts_mut(output, k);
    for (g, expected_days) in e.iter().enumerate() {
        for i in 0..cells {
            let p = g * cells + i;
            if counts[p] == 0 || (counts[p] as f64) < expected_days * min_fraction {
                out[p] = f64::NAN;
            }
        }
    }
    0
}
