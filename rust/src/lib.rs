/// Detrend independent columns of a contiguous (time, cells) float64 array.
///
/// # Safety
/// Input and output must address `steps * cells` valid f64 elements, must not
/// overlap, and must remain alive for the call. Output must be writable.
#[no_mangle]
pub unsafe extern "C" fn detrend(
    input: *const f64,
    output: *mut f64,
    steps: usize,
    cells: usize,
) -> i32 {
    let Some(len) = steps.checked_mul(cells) else {
        return 1;
    };
    if input.is_null() || output.is_null() || len > isize::MAX as usize / 8 {
        return 1;
    }
    let source = std::slice::from_raw_parts(input, len);
    let result = std::slice::from_raw_parts_mut(output, len);
    result.fill(f64::NAN);
    for cell in 0..cells {
        let (mut count, mut sum_t, mut sum_y) = (0usize, 0.0, 0.0);
        for t in 0..steps {
            let y = source[t * cells + cell];
            if !y.is_nan() {
                count += 1;
                sum_t += t as f64;
                sum_y += y;
            }
        }
        if count < 2 {
            continue;
        }
        let mean_t = sum_t / count as f64;
        let mean_y = sum_y / count as f64;
        let (mut tt, mut ty) = (0.0, 0.0);
        for t in 0..steps {
            let y = source[t * cells + cell];
            if !y.is_nan() {
                let dt = t as f64 - mean_t;
                tt += dt * dt;
                ty += dt * (y - mean_y);
            }
        }
        let slope = ty / tt;
        let intercept = mean_y - slope * mean_t;
        for t in 0..steps {
            result[t * cells + cell] = source[t * cells + cell] - (slope * t as f64 + intercept);
        }
    }
    0
}

/// Reduce time-major boolean columns. mode=0: longest run; mode=1: days in runs.
/// # Safety
/// Buffers must contain steps*cells input bytes and cells writable output doubles,
/// respectively, and must not overlap.
#[no_mangle]
pub unsafe extern "C" fn runs(
    input: *const u8,
    output: *mut f64,
    steps: usize,
    cells: usize,
    min_run: usize,
    mode: u32,
) -> i32 {
    let Some(len) = steps.checked_mul(cells) else {
        return 1;
    };
    if input.is_null()
        || output.is_null()
        || len > isize::MAX as usize
        || cells > isize::MAX as usize / 8
        || mode > 1
    {
        return 1;
    }
    let data = std::slice::from_raw_parts(input, len);
    let out = std::slice::from_raw_parts_mut(output, cells);
    for (cell, value) in out.iter_mut().enumerate() {
        let (mut current, mut longest, mut total) = (0usize, 0usize, 0usize);
        for t in 0..steps {
            if data[t * cells + cell] != 0 {
                current += 1;
                longest = longest.max(current);
            } else {
                if current >= min_run {
                    total += current;
                }
                current = 0;
            }
        }
        if current >= min_run {
            total += current;
        }
        *value = if mode == 0 { longest } else { total } as f64;
    }
    0
}

/// Fit slope / mean * 1000 for each annual column, preserving NaN propagation.
/// # Safety
/// years: n doubles; input: n*cells doubles; output: cells doubles. No overlap.
#[no_mangle]
pub unsafe extern "C" fn relative_trend(
    input: *const f64,
    years: *const f64,
    output: *mut f64,
    n: usize,
    cells: usize,
) -> i32 {
    let Some(len) = n.checked_mul(cells) else {
        return 1;
    };
    if input.is_null()
        || years.is_null()
        || output.is_null()
        || len > isize::MAX as usize / 8
        || n > isize::MAX as usize / 8
        || cells > isize::MAX as usize / 8
    {
        return 1;
    }
    let values = std::slice::from_raw_parts(input, len);
    let x = std::slice::from_raw_parts(years, n);
    let out = std::slice::from_raw_parts_mut(output, cells);
    out.fill(f64::NAN);
    if n < 2 {
        return 0;
    }
    let mx = x.iter().sum::<f64>() / n as f64;
    let xx = x.iter().map(|v| (v - mx).powi(2)).sum::<f64>();
    for (cell, result) in out.iter_mut().enumerate() {
        let mean = (0..n).map(|t| values[t * cells + cell]).sum::<f64>() / n as f64;
        if mean == 0.0 {
            continue;
        }
        let xy = (0..n)
            .map(|t| (x[t] - mx) * (values[t * cells + cell] - mean))
            .sum::<f64>();
        *result = xy / xx / mean * 1000.0;
    }
    0
}

/// Match Python's center-selected, cosine-weighted BCSD coarse-grid reduction.
/// # Safety
/// source: nlat*nlon doubles; weights: nlat doubles; masks: tlat*nlat and
/// tlon*nlon bytes; output: tlat*tlon doubles. Valid disjoint buffers required.
#[no_mangle]
pub unsafe extern "C" fn regrid(
    source: *const f64,
    weights: *const f64,
    lat_mask: *const u8,
    lon_mask: *const u8,
    output: *mut f64,
    nlat: usize,
    nlon: usize,
    tlat: usize,
    tlon: usize,
) -> i32 {
    let sizes = [
        nlat.checked_mul(nlon),
        tlat.checked_mul(nlat),
        tlon.checked_mul(nlon),
        tlat.checked_mul(tlon),
    ];
    if sizes
        .iter()
        .any(|n| n.is_none_or(|v| v > isize::MAX as usize / 8))
        || nlat > isize::MAX as usize / 8
        || source.is_null()
        || weights.is_null()
        || lat_mask.is_null()
        || lon_mask.is_null()
        || output.is_null()
    {
        return 1;
    }
    let data = std::slice::from_raw_parts(source, sizes[0].unwrap());
    let w = std::slice::from_raw_parts(weights, nlat);
    let lat = std::slice::from_raw_parts(lat_mask, sizes[1].unwrap());
    let lon = std::slice::from_raw_parts(lon_mask, sizes[2].unwrap());
    let out = std::slice::from_raw_parts_mut(output, sizes[3].unwrap());
    out.fill(f64::NAN);
    for i in 0..tlat {
        // Python slices between the first and last selected source centers.
        let rows = &lat[i * nlat..(i + 1) * nlat];
        let Some(first_row) = rows.iter().position(|v| *v != 0) else {
            continue;
        };
        let last_row = rows.iter().rposition(|v| *v != 0).unwrap();
        for j in 0..tlon {
            let cols = &lon[j * nlon..(j + 1) * nlon];
            let Some(first_col) = cols.iter().position(|v| *v != 0) else {
                continue;
            };
            let last_col = cols.iter().rposition(|v| *v != 0).unwrap();
            let (mut sum, mut total) = (0.0, 0.0);
            for row in first_row..=last_row {
                for col in first_col..=last_col {
                    let v = data[row * nlon + col];
                    if !v.is_nan() {
                        sum += v * w[row];
                        total += w[row];
                    }
                }
            }
            if total > 0.0 {
                out[i * tlon + j] = sum / total;
            }
        }
    }
    0
}
