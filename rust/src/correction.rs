//! Quantile transfer fitting and low-harmonic climatology smoothing.
use std::f64::consts::TAU;
use std::ffi::c_void;
struct Transfer {
    t: Vec<f64>,
    c: Vec<f64>,
    n: i32,
    xlo: f64,
    xhi: f64,
    ylo: f64,
    yhi: f64,
}
fn ok(n: usize) -> bool {
    n <= isize::MAX as usize / 8
}
fn percentile(a: &[f64], q: f64) -> f64 {
    let h = (a.len() - 1) as f64 * q;
    let j = h.floor() as usize;
    a[j] + (a[(j + 1).min(a.len() - 1)] - a[j]) * (h - j as f64)
}
/// # Safety
/// model/obs arrays contain nm/no valid doubles; error is writable.
#[no_mangle]
pub unsafe extern "C" fn kl_transfer_new(
    model: *const f64,
    nm: usize,
    obs: *const f64,
    no: usize,
    nquant: usize,
    error: *mut i32,
) -> *mut c_void {
    if error.is_null() {
        return std::ptr::null_mut();
    }
    *error = 1;
    if model.is_null() || obs.is_null() || !ok(nm) || !ok(no) || nquant < 4 {
        return std::ptr::null_mut();
    }
    let clean = |v: &[f64]| {
        let mut a: Vec<f64> = v
            .iter()
            .filter(|x| x.is_finite())
            .map(|x| x.max(0.0))
            .collect();
        a.sort_unstable_by(f64::total_cmp);
        a
    };
    let a = clean(std::slice::from_raw_parts(model, nm));
    let b = clean(std::slice::from_raw_parts(obs, no));
    if a.len().min(b.len()) < 20 {
        *error = 2;
        return std::ptr::null_mut();
    }
    let m = nquant.min(20.max(a.len().min(b.len()) / 25));
    if m > 1_000_000 {
        return std::ptr::null_mut();
    }
    let mut x: Vec<f64> = (0..m)
        .map(|i| percentile(&a, 0.02 + 0.96 * i as f64 / (m - 1) as f64))
        .collect();
    let y: Vec<f64> = (0..m)
        .map(|i| percentile(&b, 0.02 + 0.96 * i as f64 / (m - 1) as f64))
        .collect();
    for j in 1..m {
        if x[j] <= x[j - 1] {
            x[j] = x[j - 1] + 1e-10;
        }
    }
    if x.windows(2).any(|w| w[1] <= w[0]) {
        return std::ptr::null_mut();
    }
    // Match UnivariateSpline's initial workspace, not splrep's full nest.
    // Workspace size changes the adaptive knot path even at the same s.
    let mut nest = (m / 2).max(8) as i32;
    let mut lwrk = (m * 4 + nest as usize * 16) as i32;
    let (mut n, mut ier) = (0i32, 0i32);
    let mut fp = 0.0;
    let (mut t, mut c, mut wrk, mut iwrk) = (
        vec![0.0; nest as usize],
        vec![0.0; nest as usize],
        vec![0.0; lwrk as usize],
        vec![0i32; nest as usize],
    );
    let w = vec![1.0; m];
    crate::fitpack::curfit_(
        &0,
        &(m as i32),
        x.as_ptr(),
        y.as_ptr(),
        w.as_ptr(),
        &x[0],
        &x[m - 1],
        &3,
        &(0.8 * m as f64),
        &nest,
        &mut n,
        t.as_mut_ptr(),
        c.as_mut_ptr(),
        &mut fp,
        wrk.as_mut_ptr(),
        &lwrk,
        iwrk.as_mut_ptr(),
        &mut ier,
    );
    if ier == 1 {
        nest = (m + 4) as i32;
        lwrk = (m * 4 + nest as usize * 16) as i32;
        t.resize(nest as usize, 0.0);
        c.resize(nest as usize, 0.0);
        iwrk.resize(nest as usize, 0);
        // SciPy 1.18 UnivariateSpline's resized wrapper initializes fresh
        // work arrays. Refit with full storage to reproduce that knot policy.
        wrk = vec![0.0; lwrk as usize];
        iwrk.fill(0);
        crate::fitpack::curfit_(
            &0,
            &(m as i32),
            x.as_ptr(),
            y.as_ptr(),
            w.as_ptr(),
            &x[0],
            &x[m - 1],
            &3,
            &(0.8 * m as f64),
            &nest,
            &mut n,
            t.as_mut_ptr(),
            c.as_mut_ptr(),
            &mut fp,
            wrk.as_mut_ptr(),
            &lwrk,
            iwrk.as_mut_ptr(),
            &mut ier,
        );
    }
    if (ier > 0 && ier != 2 && ier != 3)
        || n < 8
        || n > nest
        || c[..n as usize].iter().any(|v| !v.is_finite())
    {
        *error = if ier > 0 { 100 + ier } else { 3 };
        return std::ptr::null_mut();
    }
    *error = if ier > 0 { 100 + ier } else { 0 };
    Box::into_raw(Box::new(Transfer {
        t,
        c,
        n,
        xlo: x[0],
        xhi: x[m - 1],
        ylo: y[0],
        yhi: y[m - 1],
    }))
    .cast()
}
/// # Safety
/// live transfer handle; input/output=len doubles and disjoint.
#[no_mangle]
pub unsafe extern "C" fn kl_transfer_apply(
    handle: *const c_void,
    input: *const f64,
    output: *mut f64,
    len: usize,
) -> i32 {
    if handle.is_null() || input.is_null() || output.is_null() || !ok(len) {
        return 1;
    }
    let p = &*handle.cast::<Transfer>();
    let v = std::slice::from_raw_parts(input, len);
    let out = std::slice::from_raw_parts_mut(output, len);
    out.fill(f64::NAN);
    let mut indices = Vec::new();
    for (i, &x) in v.iter().enumerate() {
        if x < p.xlo {
            out[i] = p.ylo;
        } else if x > p.xhi {
            out[i] = p.yhi;
        } else if x.is_finite() {
            indices.push(i);
        }
    }
    indices.sort_unstable_by(|&i, &j| v[i].total_cmp(&v[j]));
    if !indices.is_empty() {
        if indices.len() > i32::MAX as usize {
            return 1;
        }
        let x: Vec<f64> = indices.iter().map(|&i| v[i]).collect();
        let mut y = vec![0.0; x.len()];
        let mut ier = 0;
        crate::fitpack::splev_(
            p.t.as_ptr(),
            &p.n,
            p.c.as_ptr(),
            &3,
            x.as_ptr(),
            y.as_mut_ptr(),
            &(x.len() as i32),
            &mut ier,
        );
        if ier != 0 {
            return 3;
        }
        for (&i, &z) in indices.iter().zip(&y) {
            out[i] = z;
        }
    }
    for x in out {
        if !x.is_nan() {
            *x = if *x < 1e-10 { 0.0 } else { *x };
        }
    }
    0
}
/// # Safety
/// handle was created by kl_transfer_new and freed exactly once.
#[no_mangle]
pub unsafe extern "C" fn kl_transfer_free(handle: *mut c_void) {
    if !handle.is_null() {
        drop(Box::from_raw(handle.cast::<Transfer>()));
    }
}

/// Fill internal missing days linearly, retain low Fourier modes, restore NaNs.
/// # Safety
/// input/output=steps*cells doubles, disjoint and valid for the duration.
#[no_mangle]
pub unsafe extern "C" fn kl_smooth(
    input: *const f64,
    output: *mut f64,
    steps: usize,
    cells: usize,
    harmonics: usize,
) -> i32 {
    let Some(n) = steps.checked_mul(cells) else {
        return 1;
    };
    if input.is_null() || output.is_null() || !ok(n) || steps == 0 || harmonics > steps / 2 {
        return 1;
    }
    let v = std::slice::from_raw_parts(input, n);
    let out = std::slice::from_raw_parts_mut(output, n);
    out.fill(f64::NAN);
    let cos: Vec<Vec<f64>> = (1..=harmonics)
        .map(|k| {
            (0..steps)
                .map(|t| (TAU * k as f64 * t as f64 / steps as f64).cos())
                .collect()
        })
        .collect();
    let sin: Vec<Vec<f64>> = (1..=harmonics)
        .map(|k| {
            (0..steps)
                .map(|t| (TAU * k as f64 * t as f64 / steps as f64).sin())
                .collect()
        })
        .collect();
    for c in 0..cells {
        let valid: Vec<usize> = (0..steps)
            .filter(|&t| v[t * cells + c].is_finite())
            .collect();
        if valid.is_empty() {
            continue;
        }
        let mut filled = vec![0.0; steps];
        let mut j = 0;
        for (t, x) in filled.iter_mut().enumerate() {
            while j + 1 < valid.len() && valid[j + 1] <= t {
                j += 1;
            }
            *x = if t <= valid[0] {
                v[valid[0] * cells + c]
            } else if j + 1 == valid.len() {
                v[valid[j] * cells + c]
            } else {
                let (lo, hi) = (valid[j], valid[j + 1]);
                let f = (t - lo) as f64 / (hi - lo) as f64;
                v[lo * cells + c] * (1.0 - f) + v[hi * cells + c] * f
            };
        }
        let mean = filled.iter().sum::<f64>() / steps as f64;
        let coefficients: Vec<(f64, f64)> = (0..harmonics)
            .map(|k| {
                let factor = if (k + 1) * 2 == steps { 1.0 } else { 2.0 } / steps as f64;
                (
                    filled.iter().zip(&cos[k]).map(|(x, w)| x * w).sum::<f64>() * factor,
                    filled.iter().zip(&sin[k]).map(|(x, w)| x * w).sum::<f64>() * factor,
                )
            })
            .collect();
        for t in 0..steps {
            if v[t * cells + c].is_finite() {
                out[t * cells + c] = (mean
                    + coefficients
                        .iter()
                        .enumerate()
                        .map(|(k, (a, b))| a * cos[k][t] + b * sin[k][t])
                        .sum::<f64>())
                .max(0.0);
            }
        }
    }
    0
}

#[cfg(test)]
mod tests {
    #[test]
    fn storage_exhaustion_preserves_retry_status() {
        let m = 20i32;
        let nest = 8i32;
        let x: Vec<f64> = (0..m).map(|i| i as f64).collect();
        let y: Vec<f64> = x.iter().map(|x| (x * 2.0).sin() * 10.0).collect();
        let w = vec![1.0; m as usize];
        let mut t = vec![0.0; nest as usize];
        let mut c = t.clone();
        let lwrk = m * 4 + nest * 16;
        let mut wrk = vec![0.0; lwrk as usize];
        let mut iwrk = vec![0i32; nest as usize];
        let (mut n, mut ier) = (0, 0);
        let mut fp = 0.0;
        unsafe {
            crate::fitpack::curfit_(
                &0,
                &m,
                x.as_ptr(),
                y.as_ptr(),
                w.as_ptr(),
                &x[0],
                &x[19],
                &3,
                &0.1,
                &nest,
                &mut n,
                t.as_mut_ptr(),
                c.as_mut_ptr(),
                &mut fp,
                wrk.as_mut_ptr(),
                &lwrk,
                iwrk.as_mut_ptr(),
                &mut ier,
            );
        }
        assert_eq!(ier, 1, "caller must be allowed to increase knot storage");
    }
}
