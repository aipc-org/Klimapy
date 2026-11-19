//! Monthly gamma SPI and three-parameter log-logistic SPEI.
fn normal_quantile(p: f64) -> f64 {
    let (mut lo, mut hi) = (-9.0, 9.0);
    for _ in 0..64 {
        let mid = (lo + hi) * 0.5;
        if 0.5 * libm::erfc(-mid / std::f64::consts::SQRT_2) < p {
            lo = mid;
        } else {
            hi = mid;
        }
    }
    (lo + hi) * 0.5
}
fn gamma_cdf(a: f64, x: f64) -> Option<f64> {
    if x <= 0.0 {
        return Some(0.0);
    }
    let factor = (-x + a * x.ln() - libm::lgamma(a)).exp();
    if x < a + 1.0 {
        let mut term = 1.0 / a;
        let mut sum = term;
        for i in 1..10000 {
            term *= x / (a + i as f64);
            sum += term;
            if term.abs() < sum.abs() * 1e-14 {
                return Some((sum * factor).clamp(0.0, 1.0));
            }
        }
    } else {
        let tiny = 1e-300;
        let mut b = x + 1.0 - a;
        let mut c = 1.0 / tiny;
        let mut d = 1.0 / b;
        let mut h = d;
        for i in 1..10000 {
            let an = -(i as f64) * (i as f64 - a);
            b += 2.0;
            d = an * d + b;
            if d.abs() < tiny {
                d = tiny;
            }
            c = b + an / c;
            if c.abs() < tiny {
                c = tiny;
            }
            d = 1.0 / d;
            let delta = d * c;
            h *= delta;
            if (delta - 1.0).abs() < 1e-14 {
                return Some((1.0 - factor * h).clamp(0.0, 1.0));
            }
        }
    }
    None
}
/// Calculate monthly standardized drought fields and calibration diagnostics.
/// # Safety
/// pr and optional pet have n*cells elements; months/calibration have n;
/// expected has 12; output has n*cells; diagnostics has 12*cells*6 elements.
/// All buffers are live and writable outputs are disjoint from inputs.
#[no_mangle]
pub unsafe extern "C" fn kl_drought(
    pr: *const f64,
    pet: *const f64,
    months: *const usize,
    calibration: *const u8,
    expected: *const f64,
    out: *mut f64,
    diagnostics: *mut f64,
    n: usize,
    cells: usize,
    scale: usize,
    minimum: usize,
    coverage: f64,
    clip: f64,
) -> i32 {
    let Some(size) = n
        .checked_mul(cells)
        .filter(|&v| v <= isize::MAX as usize / 8)
    else {
        return 1;
    };
    let Some(ds) = cells
        .checked_mul(72)
        .filter(|&v| v <= isize::MAX as usize / 8)
    else {
        return 1;
    };
    if pr.is_null()
        || months.is_null()
        || calibration.is_null()
        || expected.is_null()
        || out.is_null()
        || diagnostics.is_null()
        || scale == 0
        || minimum < 8
        || !coverage.is_finite()
        || !(0.0..=1.0).contains(&coverage)
        || !clip.is_finite()
        || clip <= 0.0
        || clip >= 0.5
        || n > isize::MAX as usize / std::mem::size_of::<usize>()
    {
        return 1;
    }
    let x = std::slice::from_raw_parts(pr, size);
    let pet = if pet.is_null() {
        None
    } else {
        Some(std::slice::from_raw_parts(pet, size))
    };
    if x.iter()
        .chain(pet.unwrap_or(&[]))
        .any(|v| v.is_finite() && *v < 0.0)
    {
        return 2;
    }
    let months = std::slice::from_raw_parts(months, n);
    let selected = std::slice::from_raw_parts(calibration, n);
    if months.iter().any(|&m| m >= 12) {
        return 1;
    }
    let expected = std::slice::from_raw_parts(expected, 12);
    if expected.iter().any(|v| !v.is_finite() || *v <= 0.0) {
        return 1;
    }
    let o = std::slice::from_raw_parts_mut(out, size);
    o.fill(f64::NAN);
    let diag = std::slice::from_raw_parts_mut(diagnostics, ds);
    diag.fill(f64::NAN);
    for c in 0..cells {
        let mut rolling = vec![f64::NAN; n];
        for (t, value) in rolling.iter_mut().enumerate().skip(scale.saturating_sub(1)) {
            let mut sum = 0.0;
            let mut valid = true;
            for j in t + 1 - scale..=t {
                let a = x[j * cells + c];
                let b = pet.map_or(0.0, |p| p[j * cells + c]);
                if !a.is_finite() || !b.is_finite() {
                    valid = false;
                    break;
                }
                sum += a - b;
            }
            if valid {
                if !sum.is_finite() {
                    return 3;
                }
                *value = sum;
            }
        }
        for (month, &expected_count) in expected.iter().enumerate() {
            let mut sample: Vec<f64> = (0..n)
                .filter(|&t| selected[t] != 0 && months[t] == month && rolling[t].is_finite())
                .map(|t| rolling[t])
                .collect();
            let k = (month * cells + c) * 6;
            diag[k] = sample.len() as f64;
            diag[k + 1] = 1.0;
            if sample.len() < minimum || (sample.len() as f64) / expected_count < coverage {
                continue;
            }
            sample.sort_unstable_by(f64::total_cmp);
            let (shape, spread, location, pzero);
            if pet.is_none() {
                let positive: Vec<f64> = sample.iter().copied().filter(|&v| v > 0.0).collect();
                pzero = 1.0 - positive.len() as f64 / sample.len() as f64;
                if positive.len() < 8 {
                    diag[k + 1] = 2.0;
                    continue;
                }
                let mean = positive.iter().sum::<f64>() / positive.len() as f64;
                let a = mean.ln()
                    - positive.iter().map(|v| v.ln()).sum::<f64>() / positive.len() as f64;
                if a <= 1e-12 || !a.is_finite() {
                    diag[k + 1] = 2.0;
                    continue;
                }
                shape = (1.0 + (1.0 + 4.0 * a / 3.0).sqrt()) / (4.0 * a);
                spread = mean / shape;
                location = 0.0;
            } else {
                let len = sample.len();
                let mut b = [0.0; 3];
                for (i, &v) in sample.iter().enumerate() {
                    b[0] += v / len as f64;
                    b[1] += v * (i as f64) / (len - 1) as f64 / len as f64;
                    b[2] += v * (i as f64) * (i as f64 - 1.0)
                        / (len - 1) as f64
                        / (len - 2) as f64
                        / len as f64;
                }
                let l2 = 2.0 * b[1] - b[0];
                let l3 = 6.0 * b[2] - 6.0 * b[1] + b[0];
                let tau = l3 / l2;
                if l2 <= 0.0 || !tau.is_finite() || tau <= 1e-8 || tau >= 1.0 {
                    diag[k + 1] = 2.0;
                    continue;
                }
                shape = 1.0 / tau;
                let g = std::f64::consts::PI / shape / (std::f64::consts::PI / shape).sin();
                spread = l2 * shape / g;
                location = b[0] - l2 * shape;
                pzero = 0.0;
                if location >= sample[0] {
                    diag[k + 1] = 3.0;
                    continue;
                }
            }
            if !shape.is_finite() || !spread.is_finite() || spread <= 0.0 || !location.is_finite() {
                diag[k + 1] = 2.0;
                continue;
            }
            diag[k + 1] = 0.0;
            diag[k + 2] = shape;
            diag[k + 3] = spread;
            diag[k + 4] = location;
            diag[k + 5] = pzero;
            for t in 0..n {
                if months[t] != month || !rolling[t].is_finite() {
                    continue;
                }
                let probability = if pet.is_none() {
                    match gamma_cdf(shape, rolling[t] / spread) {
                        Some(f) => pzero + (1.0 - pzero) * f,
                        None => {
                            diag[k + 1] = 4.0;
                            continue;
                        }
                    }
                } else if rolling[t] <= location {
                    0.0
                } else {
                    let z = shape * ((rolling[t] - location) / spread).ln();
                    if z >= 0.0 {
                        1.0 / (1.0 + (-z).exp())
                    } else {
                        let e = z.exp();
                        e / (1.0 + e)
                    }
                };
                o[t * cells + c] = normal_quantile(probability.clamp(clip, 1.0 - clip));
            }
        }
    }
    0
}
