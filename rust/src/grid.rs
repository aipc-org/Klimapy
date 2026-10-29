//! Immutable spatial plans. One call processes an entire (batch, lat, lon) block.
use std::ffi::c_void;

struct Plan {
    source: usize,
    rows: Vec<Vec<(usize, f64)>>,
    normalize: bool,
}

fn monotonic(a: &[f64], minimum: usize) -> bool {
    a.len() >= minimum
        && a.iter().all(|v| v.is_finite())
        && (a.windows(2).all(|w| w[0] < w[1]) || a.windows(2).all(|w| w[0] > w[1]))
}
fn bounds(a: &[f64]) -> Vec<(f64, f64)> {
    (0..a.len())
        .map(|i| {
            let left = if i == 0 {
                a[0] - (a[1] - a[0]) / 2.0
            } else {
                (a[i - 1] + a[i]) / 2.0
            };
            let right = if i + 1 == a.len() {
                a[i] + (a[i] - a[i - 1]) / 2.0
            } else {
                (a[i] + a[i + 1]) / 2.0
            };
            (left.min(right), left.max(right))
        })
        .collect()
}
fn memberships(a: &[f64], b: &[(f64, f64)]) -> Vec<Vec<usize>> {
    let max = b.iter().map(|v| v.1).fold(f64::NEG_INFINITY, f64::max);
    b.iter()
        .map(|&(lo, hi)| {
            a.iter()
                .enumerate()
                .filter_map(|(i, &v)| (v >= lo && (v < hi || (v == hi && hi == max))).then_some(i))
                .collect()
        })
        .collect()
}
fn neighbors(a: &[f64], v: f64) -> (usize, usize, f64) {
    let descending = a[0] > a[a.len() - 1];
    let index = |i: usize| if descending { a.len() - 1 - i } else { i };
    let (mut lo, mut hi) = (0, a.len());
    while lo < hi {
        let mid = lo + (hi - lo) / 2;
        if a[index(mid)] < v {
            lo = mid + 1;
        } else {
            hi = mid;
        }
    }
    let k = lo.saturating_sub(1).min(a.len() - 2);
    let (i, j) = (index(k), index(k + 1));
    (i, j, (v - a[i]) / (a[j] - a[i]))
}

/// Build a coarse (mode=0) or extrapolating bilinear (mode=1) plan.
/// # Safety
/// Coordinate buffers must contain the stated lengths; error points to one i32.
#[no_mangle]
pub unsafe extern "C" fn grid_plan_new(
    slat: *const f64,
    nlat: usize,
    slon: *const f64,
    nlon: usize,
    tlat: *const f64,
    mlat: usize,
    tlon: *const f64,
    mlon: usize,
    mode: u32,
    error: *mut i32,
) -> *mut c_void {
    if error.is_null() {
        return std::ptr::null_mut();
    }
    *error = 1;
    if slat.is_null()
        || slon.is_null()
        || tlat.is_null()
        || tlon.is_null()
        || [nlat, nlon, mlat, mlon]
            .iter()
            .any(|&n| n > isize::MAX as usize / 8)
        || nlat.checked_mul(nlon).is_none()
        || mlat.checked_mul(mlon).is_none()
        || mode > 1
    {
        return std::ptr::null_mut();
    }
    let (y, x, ty, tx) = (
        std::slice::from_raw_parts(slat, nlat),
        std::slice::from_raw_parts(slon, nlon),
        std::slice::from_raw_parts(tlat, mlat),
        std::slice::from_raw_parts(tlon, mlon),
    );
    if !monotonic(y, if mode == 1 { 2 } else { 1 })
        || !monotonic(x, if mode == 1 { 2 } else { 1 })
        || !monotonic(ty, if mode == 0 { 2 } else { 1 })
        || !monotonic(tx, if mode == 0 { 2 } else { 1 })
    {
        return std::ptr::null_mut();
    }
    let mut rows = Vec::with_capacity(mlat * mlon);
    if mode == 0 {
        let ym = memberships(y, &bounds(ty));
        let xm = memberships(x, &bounds(tx));
        for ys in &ym {
            for xs in &xm {
                let mut row = Vec::new();
                for &i in ys {
                    for &j in xs {
                        row.push((i * nlon + j, y[i].to_radians().cos()));
                    }
                }
                rows.push(row);
            }
        }
    } else {
        for &v in ty {
            for &u in tx {
                let (i, k, fy) = neighbors(y, v);
                let (j, l, fx) = neighbors(x, u);
                rows.push(vec![
                    (i * nlon + j, (1.0 - fy) * (1.0 - fx)),
                    (i * nlon + l, (1.0 - fy) * fx),
                    (k * nlon + j, fy * (1.0 - fx)),
                    (k * nlon + l, fy * fx),
                ]);
            }
        }
    }
    *error = 0;
    Box::into_raw(Box::new(Plan {
        source: nlat * nlon,
        rows,
        normalize: mode == 0,
    }))
    .cast()
}

/// # Safety
/// handle is a live plan; input/output hold batch*source/target elements and do not overlap.
#[no_mangle]
pub unsafe extern "C" fn grid_plan_apply(
    handle: *const c_void,
    input: *const f64,
    output: *mut f64,
    batch: usize,
) -> i32 {
    if handle.is_null() || input.is_null() || output.is_null() {
        return 1;
    }
    let plan = &*handle.cast::<Plan>();
    let (Some(n), Some(m)) = (
        batch.checked_mul(plan.source),
        batch.checked_mul(plan.rows.len()),
    ) else {
        return 1;
    };
    if n > isize::MAX as usize / 8 || m > isize::MAX as usize / 8 {
        return 1;
    }
    let src = std::slice::from_raw_parts(input, n);
    let dst = std::slice::from_raw_parts_mut(output, m);
    for b in 0..batch {
        for (r, row) in plan.rows.iter().enumerate() {
            let (mut sum, mut total) = (0.0, 0.0);
            for &(i, w) in row {
                if w == 0.0 {
                    continue;
                }
                let v = src[b * plan.source + i];
                if plan.normalize && !v.is_finite() {
                    continue;
                }
                sum += v * w;
                total += w;
            }
            dst[b * plan.rows.len() + r] = if plan.normalize {
                if total > 0.0 {
                    sum / total
                } else {
                    f64::NAN
                }
            } else {
                sum
            };
        }
    }
    0
}
/// # Safety
/// handle must have been returned by grid_plan_new and must be freed exactly once.
#[no_mangle]
pub unsafe extern "C" fn grid_plan_free(handle: *mut c_void) {
    if !handle.is_null() {
        drop(Box::from_raw(handle.cast::<Plan>()));
    }
}

/// Compute dry-aware ratios in a time block; coarse and days describe the climatology.
/// # Safety
/// Valid nonoverlapping buffers: values/output=steps*cells, coarse=ndays*cells, days=steps.
#[no_mangle]
pub unsafe extern "C" fn precip_ratios(
    values: *const f64,
    coarse: *const f64,
    days: *const usize,
    output: *mut f64,
    steps: usize,
    cells: usize,
    ndays: usize,
    minimum: f64,
    low: f64,
    high: f64,
) -> i32 {
    let (Some(n), Some(c)) = (steps.checked_mul(cells), ndays.checked_mul(cells)) else {
        return 1;
    };
    if [values, coarse, output.cast_const()]
        .iter()
        .any(|p| p.is_null())
        || days.is_null()
        || n > isize::MAX as usize / 8
        || c > isize::MAX as usize / 8
        || steps > isize::MAX as usize / 8
        || !minimum.is_finite()
        || minimum <= 0.0
        || !low.is_finite()
        || !high.is_finite()
        || low < 0.0
        || high < low
    {
        return 1;
    }
    let (v, clim, d, out) = (
        std::slice::from_raw_parts(values, n),
        std::slice::from_raw_parts(coarse, c),
        std::slice::from_raw_parts(days, steps),
        std::slice::from_raw_parts_mut(output, n),
    );
    if d.iter().any(|&i| i >= ndays) {
        return 1;
    }
    for t in 0..steps {
        for i in 0..cells {
            let x = v[t * cells + i];
            let denom = clim[d[t] * cells + i];
            out[t * cells + i] = if !x.is_finite() || !denom.is_finite() {
                f64::NAN
            } else if x <= 0.0 {
                0.0
            } else {
                (x.max(minimum) / denom.max(minimum)).clamp(low, high)
            };
        }
    }
    0
}

/// Fused SD block: ratios, interpolation and fine-grid reconstruction.
/// # Safety
/// handle is a bilinear plan. values=steps*source, coarse=ndays*source,
/// fine=ndays*target, days=steps, output=steps*target; buffers are valid and disjoint.
#[no_mangle]
pub unsafe extern "C" fn downscale_block(
    handle: *const c_void,
    values: *const f64,
    coarse: *const f64,
    fine: *const f64,
    days: *const usize,
    output: *mut f64,
    steps: usize,
    ndays: usize,
    minimum: f64,
    low: f64,
    high: f64,
) -> i32 {
    if handle.is_null() || fine.is_null() || output.is_null() {
        return 1;
    }
    let p = &*handle.cast::<Plan>();
    if p.normalize {
        return 1;
    }
    let (Some(n), Some(m), Some(c)) = (
        steps.checked_mul(p.source),
        steps.checked_mul(p.rows.len()),
        ndays.checked_mul(p.rows.len()),
    ) else {
        return 1;
    };
    if [n, m, c].iter().any(|&n| n > isize::MAX as usize / 8) {
        return 1;
    }
    let mut relative = vec![0.0; n];
    let code = precip_ratios(
        values,
        coarse,
        days,
        relative.as_mut_ptr(),
        steps,
        p.source,
        ndays,
        minimum,
        low,
        high,
    );
    if code != 0 {
        return code;
    }
    let code = grid_plan_apply(handle, relative.as_ptr(), output, steps);
    if code != 0 {
        return code;
    }
    let f = std::slice::from_raw_parts(fine, c);
    let d = std::slice::from_raw_parts(days, steps);
    let out = std::slice::from_raw_parts_mut(output, m);
    for t in 0..steps {
        for i in 0..p.rows.len() {
            let v = out[t * p.rows.len() + i] * f[d[t] * p.rows.len() + i];
            out[t * p.rows.len() + i] = if v.is_nan() { v } else { v.max(0.0) };
        }
    }
    0
}

/// # Safety
/// values=steps*cells, days=steps, sums/counts=ndays*cells. days -1 are skipped.
#[no_mangle]
pub unsafe extern "C" fn climate_accumulate(
    values: *const f64,
    days: *const isize,
    sums: *mut f64,
    counts: *mut i32,
    steps: usize,
    cells: usize,
    ndays: usize,
) -> i32 {
    let (Some(n), Some(c)) = (steps.checked_mul(cells), ndays.checked_mul(cells)) else {
        return 1;
    };
    if values.is_null()
        || days.is_null()
        || sums.is_null()
        || counts.is_null()
        || n > isize::MAX as usize / 8
        || c > isize::MAX as usize / 8
        || steps > isize::MAX as usize / 8
    {
        return 1;
    }
    let (v, d, s, k) = (
        std::slice::from_raw_parts(values, n),
        std::slice::from_raw_parts(days, steps),
        std::slice::from_raw_parts_mut(sums, c),
        std::slice::from_raw_parts_mut(counts, c),
    );
    if d.iter().any(|&x| x < -1 || x >= ndays as isize) {
        return 1;
    }
    for t in 0..steps {
        if d[t] < 0 {
            continue;
        }
        for i in 0..cells {
            let value = v[t * cells + i];
            let index = d[t] as usize * cells + i;
            if value.is_finite() {
                let Some(count) = k[index].checked_add(1) else {
                    return 1;
                };
                s[index] += value;
                k[index] = count;
            }
        }
    }
    0
}
