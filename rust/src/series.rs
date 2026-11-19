//! Streaming calendar reductions and paired model diagnostics.
/// Accumulate finite daily values into caller-owned group state.
///
/// # Safety
/// x has n*cells elements, groups/weights have n, state has ng*cells*4; buffers
/// do not overlap and all writable state remains live throughout the call.
#[no_mangle]
pub unsafe extern "C" fn kl_series_accumulate(
    x: *const f64,
    groups: *const usize,
    weights: *const f64,
    weighted_sum: bool,
    state: *mut f64,
    n: usize,
    cells: usize,
    ng: usize,
) -> i32 {
    let Some(len) = n.checked_mul(cells) else {
        return 1;
    };
    let Some(size) = ng.checked_mul(cells).and_then(|v| v.checked_mul(4)) else {
        return 1;
    };
    if x.is_null()
        || groups.is_null()
        || weights.is_null()
        || state.is_null()
        || len > isize::MAX as usize / 8
        || size > isize::MAX as usize / 8
    {
        return 1;
    }
    let x = std::slice::from_raw_parts(x, len);
    if n > isize::MAX as usize / std::mem::size_of::<usize>() {
        return 1;
    }
    let groups = std::slice::from_raw_parts(groups, n);
    let weights = std::slice::from_raw_parts(weights, n);
    if weights.iter().any(|v| !v.is_finite() || *v <= 0.0) {
        return 1;
    }
    if groups.iter().any(|&g| g >= ng) {
        return 1;
    }
    let s = std::slice::from_raw_parts_mut(state, size);
    for t in 0..n {
        for c in 0..cells {
            let v = x[t * cells + c];
            if v.is_finite() {
                let k = (groups[t] * cells + c) * 4;
                s[k] += if weighted_sum { v * weights[t] } else { v };
                s[k + 1] += weights[t];
                s[k + 2] = s[k + 2].min(v);
                s[k + 3] = s[k + 3].max(v);
            }
        }
    }
    0
}
/// Finalize daily group states using complete-period expected counts.
///
/// # Safety
/// state has ng*cells*4 elements, expected has ng, out has ng*cells;
/// buffers are valid, nonoverlapping, and out is writable.
#[no_mangle]
pub unsafe extern "C" fn kl_series_finish(
    state: *const f64,
    expected: *const f64,
    out: *mut f64,
    ng: usize,
    cells: usize,
    fraction: f64,
    operation: usize,
) -> i32 {
    let Some(size) = ng
        .checked_mul(cells)
        .filter(|&v| v <= isize::MAX as usize / 32)
    else {
        return 1;
    };
    if state.is_null()
        || expected.is_null()
        || out.is_null()
        || !fraction.is_finite()
        || !(0.0..=1.0).contains(&fraction)
        || operation > 3
    {
        return 1;
    }
    let s = std::slice::from_raw_parts(state, size * 4);
    if ng > isize::MAX as usize / 8 {
        return 1;
    }
    let e = std::slice::from_raw_parts(expected, ng);
    if e.iter().any(|v| !v.is_finite() || *v <= 0.0) {
        return 1;
    }
    let out = std::slice::from_raw_parts_mut(out, size);
    for i in 0..size {
        let n = s[i * 4 + 1];
        out[i] = if n == 0.0 || n / e[i / cells] < fraction {
            f64::NAN
        } else {
            match operation {
                0 => s[i * 4] / n,
                1 => s[i * 4],
                2 => s[i * 4 + 2],
                _ => s[i * 4 + 3],
            }
        };
        if out[i].is_infinite() {
            return 3;
        }
    }
    0
}
/// Compute seven paired metrics per column using online moments.
///
/// # Safety
/// model/reference and optional weights have n*cells elements, out has 8*cells;
/// buffers do not overlap and out is writable throughout the call.
#[no_mangle]
pub unsafe extern "C" fn kl_pair_metrics(
    model: *const f64,
    reference: *const f64,
    weights: *const f64,
    out: *mut f64,
    n: usize,
    cells: usize,
    fraction: f64,
) -> i32 {
    let Some(size) = n
        .checked_mul(cells)
        .filter(|&v| v <= isize::MAX as usize / 8)
    else {
        return 1;
    };
    if model.is_null()
        || reference.is_null()
        || out.is_null()
        || cells > isize::MAX as usize / 64
        || !fraction.is_finite()
        || !(0.0..=1.0).contains(&fraction)
    {
        return 1;
    }
    let a = std::slice::from_raw_parts(model, size);
    let b = std::slice::from_raw_parts(reference, size);
    let weights = if weights.is_null() {
        None
    } else {
        Some(std::slice::from_raw_parts(weights, size))
    };
    if weights.is_some_and(|w| w.iter().any(|v| !v.is_finite() || *v < 0.0)) {
        return 1;
    }
    let out = std::slice::from_raw_parts_mut(out, cells * 8);
    for c in 0..cells {
        let (mut count, mut ma, mut mb, mut va, mut vb, mut cov, mut bias, mut abs, mut square) =
            (0usize, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0);
        let mut difference_variance = 0.0;
        let mut weight_sum = 0.0;
        let mut total_weight = 0.0;
        let scale = weights.map_or(1.0, |w| {
            (0..n).map(|t| w[t * cells + c]).fold(0.0, f64::max)
        });
        for t in 0..n {
            let (a, b) = (a[t * cells + c], b[t * cells + c]);
            let w = if scale > 0.0 {
                weights.map_or(1.0, |v| v[t * cells + c] / scale)
            } else {
                0.0
            };
            total_weight += w;
            if w > 0.0 && a.is_finite() && b.is_finite() {
                count += 1;
                weight_sum += w;
                let k = weight_sum / w;
                let da = a - ma;
                let db = b - mb;
                ma += da / k;
                mb += db / k;
                va += w * da * (a - ma);
                vb += w * db * (b - mb);
                cov += w * da * (b - mb);
                let d = a - b;
                let delta = d - bias;
                bias += delta / k;
                difference_variance += w * delta * (d - bias);
                abs += (d.abs() - abs) / k;
                square += (d * d - square) / k;
            }
        }
        if [ma, mb, va, vb, cov, bias, abs, square, difference_variance]
            .iter()
            .any(|v| !v.is_finite())
        {
            return 3;
        }
        for metric in 0..6 {
            out[metric * cells + c] = f64::NAN;
        }
        out[6 * cells + c] = count as f64;
        out[7 * cells + c] = if total_weight > 0.0 {
            weight_sum / total_weight
        } else {
            f64::NAN
        };
        if count == 0 || out[7 * cells + c] < fraction {
            continue;
        }
        out[c] = bias;
        out[cells + c] = abs;
        out[2 * cells + c] = square.sqrt();
        if count >= 2 {
            if va > 0.0 && vb > 0.0 {
                out[3 * cells + c] = ((cov / va.sqrt()) / vb.sqrt()).clamp(-1.0, 1.0);
            }
            if vb > 0.0 {
                out[4 * cells + c] = va.sqrt() / vb.sqrt();
            }
            out[5 * cells + c] = (difference_variance.max(0.0) / weight_sum).sqrt();
        }
    }
    0
}

/// Count finite/missing/infinite/out-of-range values and extrema for QC.
///
/// # Safety
/// x has n elements; out addresses nine initialized writable f64 values, without overlap.
#[no_mangle]
pub unsafe extern "C" fn kl_quality(
    x: *const f64,
    n: usize,
    lower: f64,
    upper: f64,
    out: *mut f64,
) -> i32 {
    if x.is_null()
        || out.is_null()
        || n > isize::MAX as usize / 8
        || lower.is_nan()
        || upper.is_nan()
        || lower > upper
    {
        return 1;
    }
    let x = std::slice::from_raw_parts(x, n);
    let o = std::slice::from_raw_parts_mut(out, 9);
    for &v in x {
        if v.is_nan() {
            o[1] += 1.0;
        } else if v.is_infinite() {
            o[2] += 1.0;
        } else {
            o[0] += 1.0;
            o[3] += f64::from(v < lower);
            o[4] += f64::from(v > upper);
            o[5] += f64::from(v < 0.0);
            o[6] = o[6].min(v);
            o[7] = o[7].max(v);
        }
    }
    let total = o[0] + o[1] + o[2];
    o[8] = if total > 0.0 { o[0] / total } else { f64::NAN };
    0
}
