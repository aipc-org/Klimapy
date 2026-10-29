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
    if steps == 0 || cells == 0 {
        return 0;
    }
    // Scan contiguous time rows; retain only O(cells) regression state.
    let mut count = vec![0usize; cells];
    let mut mean_t = vec![0.0; cells];
    let mut mean_y = vec![0.0; cells];
    for t in 0..steps {
        for cell in 0..cells {
            let y = source[t * cells + cell];
            if !y.is_nan() {
                count[cell] += 1;
                mean_t[cell] += t as f64;
                mean_y[cell] += y;
            }
        }
    }
    for cell in 0..cells {
        if count[cell] >= 2 {
            mean_t[cell] /= count[cell] as f64;
            mean_y[cell] /= count[cell] as f64;
        }
    }
    let mut tt = vec![0.0; cells];
    let mut ty = vec![0.0; cells];
    for t in 0..steps {
        for cell in 0..cells {
            let y = source[t * cells + cell];
            if !y.is_nan() && count[cell] >= 2 {
                let dt = t as f64 - mean_t[cell];
                tt[cell] += dt * dt;
                ty[cell] += dt * (y - mean_y[cell]);
            }
        }
    }
    for cell in 0..cells {
        if count[cell] >= 2 {
            ty[cell] /= tt[cell];
            mean_y[cell] -= ty[cell] * mean_t[cell];
        }
    }
    for t in 0..steps {
        for cell in 0..cells {
            if count[cell] >= 2 {
                result[t * cells + cell] =
                    source[t * cells + cell] - (ty[cell] * t as f64 + mean_y[cell]);
            }
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

mod grid;
mod netcdf;

/// Version the ABI so stale local binaries cannot silently run different semantics.
#[no_mangle]
pub extern "C" fn klimapy_abi_version() -> u32 {
    5
}
mod linalg;
mod variability;

mod indices;
mod remap;
#[rustfmt::skip]
#[allow(dead_code)]
#[path = "../vendor/splinefit/dierckx.rs"]
mod fitpack;
mod correction;
mod spatial_tools;

mod climatology;
