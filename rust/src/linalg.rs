//! Real compact SVD through faer; EOF preprocessing/reconstruction stay in Rust.

use faer::Mat;

type Factors = (Vec<f64>, Vec<f64>, Vec<f64>);

pub(crate) fn decompose(a: &[f64], rows: usize, cols: usize) -> Result<Factors, i32> {
    let k = rows.min(cols);
    if k == 0 {
        return Ok((vec![], vec![], vec![]));
    }
    let scale = a.iter().fold(0.0_f64, |x, y| x.max(y.abs()));
    let matrix = Mat::from_fn(rows, cols, |i, j| {
        if scale == 0.0 {
            0.0
        } else {
            a[i * cols + j] / scale
        }
    });
    decompose_matrix(matrix, scale)
}
fn decompose_matrix(matrix: Mat<f64>, scale: f64) -> Result<Factors, i32> {
    let (rows, cols) = (matrix.nrows(), matrix.ncols());
    let k = rows.min(cols);
    // Prevent a solver panic from crossing the public extern C entry points.
    let factors = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| matrix.thin_svd()))
        .map_err(|_| 6)?
        .map_err(|_| 2)?;
    let mut u = vec![0.0; rows * k];
    let mut vt = vec![0.0; k * cols];
    let mut s = vec![0.0; k];
    for j in 0..k {
        s[j] = factors.S()[j] * scale;
        if !s[j].is_finite() {
            return Err(3);
        }
        for i in 0..rows {
            u[i * k + j] = factors.U()[(i, j)];
        }
        for i in 0..cols {
            vt[j * cols + i] = factors.V()[(i, j)];
        }
    }
    // Fix signs deterministically; repeated singular subspaces still admit rotations.
    for j in 0..k {
        let pivot = (0..cols)
            .max_by(|&a, &b| vt[j * cols + a].abs().total_cmp(&vt[j * cols + b].abs()))
            .unwrap();
        if vt[j * cols + pivot] < 0.0 {
            for i in 0..rows {
                u[i * k + j] = -u[i * k + j];
            }
            for i in 0..cols {
                vt[j * cols + i] = -vt[j * cols + i];
            }
        }
    }
    Ok((u, s, vt))
}

/// Real compact SVD, row-major input/output: U=(m,k), s=(k), Vt=(k,n).
/// # Safety
/// Valid disjoint buffers of the stated lengths; k=min(m,n); all input values finite.
#[no_mangle]
pub unsafe extern "C" fn kl_svd(
    input: *const f64,
    rows: usize,
    cols: usize,
    u: *mut f64,
    s: *mut f64,
    vt: *mut f64,
    tol: f64,
    sweeps: usize,
) -> i32 {
    let Some(n) = rows.checked_mul(cols) else {
        return 1;
    };
    if input.is_null()
        || u.is_null()
        || s.is_null()
        || vt.is_null()
        || n > isize::MAX as usize / 8
        || !tol.is_finite()
        || tol != 1e-12
        || sweeps != 100
    {
        return 1;
    }
    let a = std::slice::from_raw_parts(input, n);
    if a.iter().any(|x| !x.is_finite()) {
        return 1;
    }
    match decompose(a, rows, cols) {
        Ok((left, values, right)) => {
            std::ptr::copy_nonoverlapping(left.as_ptr(), u, left.len());
            std::ptr::copy_nonoverlapping(values.as_ptr(), s, values.len());
            std::ptr::copy_nonoverlapping(right.as_ptr(), vt, right.len());
            0
        }
        Err(code) => code,
    }
}

/// Area-weighted EOF; outputs compact modes in original physical units.
/// Missing columns must be all-NaN; intermittent NaNs are rejected, not imputed.
/// # Safety
/// input=steps*cells, weights/mean=cells; pcs=steps*capacity,
/// patterns=capacity*cells, singular/eigen/fraction=capacity; written points to usize.
/// capacity is min(steps,cells) when requested=0, otherwise requested.
#[no_mangle]
pub unsafe extern "C" fn kl_eof(
    input: *const f64,
    weights: *const f64,
    steps: usize,
    cells: usize,
    requested: usize,
    center: u32,
    ddof: usize,
    tol: f64,
    sweeps: usize,
    pcs: *mut f64,
    patterns: *mut f64,
    singular: *mut f64,
    eigen: *mut f64,
    fraction: *mut f64,
    mean: *mut f64,
    written: *mut usize,
    total: *mut f64,
) -> i32 {
    let Some(n) = steps.checked_mul(cells) else {
        return 1;
    };
    if input.is_null()
        || weights.is_null()
        || pcs.is_null()
        || patterns.is_null()
        || singular.is_null()
        || eigen.is_null()
        || fraction.is_null()
        || mean.is_null()
        || written.is_null()
        || total.is_null()
        || n > isize::MAX as usize / 8
        || cells > isize::MAX as usize / 8
        || steps <= ddof
        || steps < 2
        || cells == 0
        || center > 1
        || !tol.is_finite()
        || tol != 1e-12
        || sweeps != 100
    {
        return 1;
    }
    let (a, w, mu) = (
        std::slice::from_raw_parts(input, n),
        std::slice::from_raw_parts(weights, cells),
        std::slice::from_raw_parts_mut(mean, cells),
    );
    if a.iter().any(|x| x.is_infinite()) || w.iter().any(|x| !x.is_finite() || *x < 0.0) {
        return 1;
    }
    mu.fill(f64::NAN);
    let mut valid = Vec::new();
    for i in 0..cells {
        if w[i] == 0.0 {
            continue;
        }
        let count = (0..steps).filter(|&t| a[t * cells + i].is_finite()).count();
        if count == 0 {
            continue;
        }
        if count != steps {
            return 4;
        }
        mu[i] = if center == 1 {
            (0..steps).map(|t| a[t * cells + i] / steps as f64).sum()
        } else {
            0.0
        };
        valid.push(i);
    }
    if valid.is_empty() {
        return 5;
    }
    let rank = steps.min(valid.len());
    let keep = if requested == 0 { rank } else { requested };
    if keep > rank {
        return 1;
    }
    // Construct the solver's column-major matrix directly, avoiding a second
    // full time-by-space anomaly buffer and repeated square roots.
    let roots: Vec<f64> = valid.iter().map(|&i| w[i].sqrt()).collect();
    let mut scale = 0.0_f64;
    for t in 0..steps {
        for (j, &i) in valid.iter().enumerate() {
            let x = (a[t * cells + i] - mu[i]) * roots[j];
            if !x.is_finite() {
                return 3;
            }
            scale = scale.max(x.abs());
        }
    }
    let matrix = Mat::from_fn(steps, valid.len(), |t, j| {
        if scale == 0.0 {
            0.0
        } else {
            (a[t * cells + valid[j]] - mu[valid[j]]) * roots[j] / scale
        }
    });
    let (u, s, vt) = match decompose_matrix(matrix, scale) {
        Ok(v) => v,
        Err(c) => return c,
    };
    let denom = (steps - ddof) as f64;
    let total_variance: f64 = s.iter().map(|x| (x / denom.sqrt()).powi(2)).sum();
    if !total_variance.is_finite() {
        return 3;
    }
    *total = total_variance;
    *written = keep;
    let outpcs = std::slice::from_raw_parts_mut(pcs, steps * keep);
    let eof = std::slice::from_raw_parts_mut(patterns, keep * cells);
    eof.fill(f64::NAN);
    let ss = std::slice::from_raw_parts_mut(singular, keep);
    let ev = std::slice::from_raw_parts_mut(eigen, keep);
    let vf = std::slice::from_raw_parts_mut(fraction, keep);
    for mode in 0..keep {
        ss[mode] = s[mode];
        ev[mode] = (s[mode] / denom.sqrt()).powi(2);
        vf[mode] = if total_variance > 0.0 {
            ev[mode] / total_variance
        } else {
            0.0
        };
        for t in 0..steps {
            outpcs[t * keep + mode] = u[t * rank + mode] * s[mode];
        }
        for (j, &i) in valid.iter().enumerate() {
            eof[mode * cells + i] = vt[mode * valid.len() + j] / w[i].sqrt();
        }
    }
    0
}

/// # Safety
/// pcs=steps*modes, patterns=modes*cells, mean=cells, output=steps*cells, buffers disjoint.
#[no_mangle]
pub unsafe extern "C" fn kl_eof_reconstruct(
    pcs: *const f64,
    patterns: *const f64,
    mean: *const f64,
    output: *mut f64,
    steps: usize,
    modes: usize,
    cells: usize,
    add_mean: u32,
) -> i32 {
    let (Some(n), Some(p), Some(e)) = (
        steps.checked_mul(cells),
        steps.checked_mul(modes),
        modes.checked_mul(cells),
    ) else {
        return 1;
    };
    if pcs.is_null()
        || patterns.is_null()
        || mean.is_null()
        || output.is_null()
        || add_mean > 1
        || [n, p, e, cells]
            .iter()
            .any(|&n| n > isize::MAX as usize / 8)
    {
        return 1;
    }
    let (pc, pat, mu, out) = (
        std::slice::from_raw_parts(pcs, p),
        std::slice::from_raw_parts(patterns, e),
        std::slice::from_raw_parts(mean, cells),
        std::slice::from_raw_parts_mut(output, n),
    );
    for t in 0..steps {
        for i in 0..cells {
            out[t * cells + i] = if mu[i].is_nan() {
                f64::NAN
            } else if add_mean == 1 {
                mu[i]
            } else {
                0.0
            };
        }
    }
    for t in 0..steps {
        for k in 0..modes {
            for i in 0..cells {
                out[t * cells + i] += pc[t * modes + k] * pat[k * cells + i];
            }
        }
    }
    0
}
