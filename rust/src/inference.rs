//! Paired regression, lag-one effective sample approximation and FDR.
fn beta_cf(a: f64, b: f64, x: f64) -> Option<f64> {
    let tiny = 1e-300;
    let qab = a + b;
    let qap = a + 1.0;
    let qam = a - 1.0;
    let mut c = 1.0;
    let mut d = 1.0 - qab * x / qap;
    if d.abs() < tiny {
        d = tiny;
    }
    d = 1.0 / d;
    let mut h = d;
    for m in 1..10000 {
        let mf = m as f64;
        let m2 = 2.0 * mf;
        let aa = mf * (b - mf) * x / ((qam + m2) * (a + m2));
        d = 1.0 + aa * d;
        if d.abs() < tiny {
            d = tiny;
        }
        c = 1.0 + aa / c;
        if c.abs() < tiny {
            c = tiny;
        }
        d = 1.0 / d;
        h *= d * c;
        let aa = -(a + mf) * (qab + mf) * x / ((a + m2) * (qap + m2));
        d = 1.0 + aa * d;
        if d.abs() < tiny {
            d = tiny;
        }
        c = 1.0 + aa / c;
        if c.abs() < tiny {
            c = tiny;
        }
        d = 1.0 / d;
        let delta = d * c;
        h *= delta;
        if (delta - 1.0).abs() < 1e-14 {
            return Some(h);
        }
    }
    None
}
fn ibeta(x: f64, a: f64, b: f64) -> Option<f64> {
    if x <= 0.0 {
        return Some(0.0);
    }
    if x >= 1.0 {
        return Some(1.0);
    }
    let factor =
        (libm::lgamma(a + b) - libm::lgamma(a) - libm::lgamma(b) + a * x.ln() + b * (-x).ln_1p())
            .exp();
    let v = if x < (a + 1.0) / (a + b + 2.0) {
        factor * beta_cf(a, b, x)? / a
    } else {
        1.0 - factor * beta_cf(b, a, 1.0 - x)? / b
    };
    Some(v.clamp(0.0, 1.0))
}
fn two_sided(t: f64, df: f64) -> Option<f64> {
    ibeta(df / (df + t * t), df / 2.0, 0.5)
}
fn critical(df: f64, alpha: f64) -> Option<f64> {
    let (mut lo, mut hi) = (0.0, 1.0);
    while two_sided(hi, df)? > alpha {
        hi *= 2.0;
        if hi > 1e12 {
            return None;
        }
    }
    for _ in 0..64 {
        let mid = (lo + hi) * 0.5;
        if two_sided(mid, df)? > alpha {
            lo = mid;
        } else {
            hi = mid;
        }
    }
    Some((lo + hi) * 0.5)
}
fn lag_correlation(a: &[f64]) -> f64 {
    if a.len() < 3 {
        return 0.0;
    }
    let pairs: Vec<(f64, f64)> = a
        .windows(2)
        .filter(|v| v[0].is_finite() && v[1].is_finite())
        .map(|v| (v[0], v[1]))
        .collect();
    if pairs.len() < 2 {
        return 0.0;
    }
    let mx = pairs.iter().map(|v| v.0).sum::<f64>() / pairs.len() as f64;
    let my = pairs.iter().map(|v| v.1).sum::<f64>() / pairs.len() as f64;
    let vx = pairs.iter().map(|v| (v.0 - mx).powi(2)).sum::<f64>();
    let vy = pairs.iter().map(|v| (v.1 - my).powi(2)).sum::<f64>();
    if vx <= 0.0 || vy <= 0.0 {
        return 0.0;
    }
    (pairs.iter().map(|v| (v.0 - mx) * (v.1 - my)).sum::<f64>() / vx.sqrt() / vy.sqrt())
        .clamp(-1.0, 1.0)
}
/// OLS and correlation inference with optional lag-one effective N.
/// # Safety
/// x has steps elements if trend=true else steps*cells; y has steps*cells;
/// output has 9*cells writable elements, all buffers live and disjoint.
#[no_mangle]
pub unsafe extern "C" fn kl_inference(
    x: *const f64,
    y: *const f64,
    output: *mut f64,
    steps: usize,
    cells: usize,
    trend: bool,
    lag1: bool,
    fraction: f64,
    confidence: f64,
) -> i32 {
    let Some(size) = steps
        .checked_mul(cells)
        .filter(|&v| v <= isize::MAX as usize / 8)
    else {
        return 1;
    };
    if x.is_null()
        || y.is_null()
        || output.is_null()
        || cells > isize::MAX as usize / 72
        || !fraction.is_finite()
        || !(0.0..=1.0).contains(&fraction)
        || !confidence.is_finite()
        || confidence <= 0.0
        || confidence >= 1.0
    {
        return 1;
    }
    let x = std::slice::from_raw_parts(x, if trend { steps } else { size });
    let y = std::slice::from_raw_parts(y, size);
    let out = std::slice::from_raw_parts_mut(output, cells * 9);
    out.fill(f64::NAN);
    for c in 0..cells {
        let getx = |t: usize| if trend { x[t] } else { x[t * cells + c] };
        let valid: Vec<usize> = (0..steps)
            .filter(|&t| getx(t).is_finite() && y[t * cells + c].is_finite())
            .collect();
        let n = valid.len();
        out[6 * cells + c] = n as f64;
        if n < 3 || (n as f64) / (steps as f64) < fraction {
            continue;
        }
        let mx = valid.iter().map(|&t| getx(t)).sum::<f64>() / n as f64;
        let my = valid.iter().map(|&t| y[t * cells + c]).sum::<f64>() / n as f64;
        let xx = valid.iter().map(|&t| (getx(t) - mx).powi(2)).sum::<f64>();
        let yy = valid
            .iter()
            .map(|&t| (y[t * cells + c] - my).powi(2))
            .sum::<f64>();
        let xy = valid
            .iter()
            .map(|&t| (getx(t) - mx) * (y[t * cells + c] - my))
            .sum::<f64>();
        if ![mx, my, xx, yy, xy].iter().all(|v| v.is_finite()) {
            return 3;
        }
        if xx <= 0.0 {
            continue;
        }
        let slope = xy / xx;
        let intercept = my - slope * mx;
        let r = if yy > 0.0 {
            (xy / xx.sqrt() / yy.sqrt()).clamp(-1.0, 1.0)
        } else {
            f64::NAN
        };
        let mut residual = vec![f64::NAN; steps];
        let mut source_x = residual.clone();
        let mut source_y = residual.clone();
        let mut rss = 0.0;
        for &t in &valid {
            let e = y[t * cells + c] - (intercept + slope * getx(t));
            residual[t] = e;
            source_x[t] = getx(t);
            source_y[t] = y[t * cells + c];
            rss += e * e;
        }
        let rho = if lag1 {
            if trend {
                lag_correlation(&residual)
            } else {
                lag_correlation(&source_x) * lag_correlation(&source_y)
            }
        } else {
            0.0
        };
        // Only positive persistence reduces N; negative persistence does not inflate it.
        let rho = rho.clamp(0.0, 0.999999);
        let effective = ((n as f64) * (1.0 - rho) / (1.0 + rho)).clamp(3.0, n as f64);
        let df = effective - 2.0;
        let se = (rss / (n - 2) as f64 / xx * ((n - 2) as f64 / df)).sqrt();
        let p = if trend {
            if se == 0.0 {
                if slope == 0.0 {
                    1.0
                } else {
                    0.0
                }
            } else {
                match two_sided((slope / se).abs(), df) {
                    Some(p) => p,
                    None => return 3,
                }
            }
        } else if !r.is_finite() {
            f64::NAN
        } else {
            match two_sided((r.abs() * (df / (1.0 - r * r).max(0.0)).sqrt()).abs(), df) {
                Some(p) => p,
                None => return 3,
            }
        };
        let critical = match critical(df, 1.0 - confidence) {
            Some(v) => v,
            None => return 3,
        };
        for (i, v) in [
            slope,
            intercept,
            r,
            p,
            slope - critical * se,
            slope + critical * se,
            n as f64,
            effective,
            rho,
        ]
        .iter()
        .enumerate()
        {
            out[i * cells + c] = *v;
        }
    }
    0
}
/// Benjamini-Hochberg or Benjamini-Yekutieli adjusted p-values.
/// # Safety
/// p and out have n elements, are live, and do not overlap.
#[no_mangle]
pub unsafe extern "C" fn kl_fdr(p: *const f64, out: *mut f64, n: usize, by: bool) -> i32 {
    if p.is_null() || out.is_null() || n > isize::MAX as usize / 8 {
        return 1;
    }
    let p = std::slice::from_raw_parts(p, n);
    let out = std::slice::from_raw_parts_mut(out, n);
    out.fill(f64::NAN);
    if p.iter().any(|v| v.is_finite() && (*v < 0.0 || *v > 1.0)) {
        return 1;
    }
    let mut indices: Vec<usize> = (0..n).filter(|&i| p[i].is_finite()).collect();
    indices.sort_unstable_by(|&i, &j| p[i].total_cmp(&p[j]));
    let m = indices.len();
    let factor = if by {
        (1..=m).map(|i| 1.0 / i as f64).sum::<f64>()
    } else {
        1.0
    };
    let mut last = 1.0f64;
    for rank in (0..m).rev() {
        let i = indices[rank];
        last = last.min(p[i] * m as f64 / (rank + 1) as f64 * factor);
        out[i] = last;
    }
    0
}
