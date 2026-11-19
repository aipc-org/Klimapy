//! Weighted multi-model reductions, with explicit finite-model coverage.
fn quantile(sample: &[(f64, f64)], p: f64, weighted: bool) -> f64 {
    if !weighted {
        let h = (sample.len() - 1) as f64 * p;
        let i = h.floor() as usize;
        return sample[i].0
            + (sample[(i + 1).min(sample.len() - 1)].0 - sample[i].0) * (h - i as f64);
    }
    let total: f64 = sample.iter().map(|v| v.1).sum();
    let mut sum = 0.0;
    for &(v, w) in sample {
        sum += w;
        if sum >= p * total {
            return v;
        }
    }
    sample.last().unwrap().0
}
/// Per-cell ensemble mean, quantiles, coverage and sign agreement.
/// # Safety
/// data has models*cells, weights has models, optional reference has cells;
/// output has 7*cells writable elements; buffers are live and disjoint.
#[no_mangle]
pub unsafe extern "C" fn kl_ensemble(
    data: *const f64,
    weights: *const f64,
    reference: *const f64,
    output: *mut f64,
    models: usize,
    cells: usize,
    minimum: usize,
    fraction: f64,
    weighted: bool,
) -> i32 {
    let Some(n) = models
        .checked_mul(cells)
        .filter(|&n| n <= isize::MAX as usize / 8)
    else {
        return 1;
    };
    if data.is_null()
        || weights.is_null()
        || output.is_null()
        || models == 0
        || minimum == 0
        || minimum > models
        || cells > isize::MAX as usize / 56
        || !fraction.is_finite()
        || !(0.0..=1.0).contains(&fraction)
    {
        return 1;
    }
    let data = std::slice::from_raw_parts(data, n);
    let weights = std::slice::from_raw_parts(weights, models);
    if weights.iter().any(|w| !w.is_finite() || *w < 0.0) {
        return 1;
    }
    let max = weights.iter().copied().fold(0.0, f64::max);
    if max == 0.0 {
        return 1;
    }
    let weights: Vec<f64> = weights.iter().map(|w| w / max).collect();
    let total: f64 = weights.iter().sum();
    let reference = if reference.is_null() {
        None
    } else {
        Some(std::slice::from_raw_parts(reference, cells))
    };
    let out = std::slice::from_raw_parts_mut(output, cells * 7);
    out.fill(f64::NAN);
    for c in 0..cells {
        let mut sample: Vec<(f64, f64)> = (0..models)
            .filter(|&m| weights[m] > 0.0 && data[m * cells + c].is_finite())
            .map(|m| (data[m * cells + c], weights[m]))
            .collect();
        let valid: f64 = sample.iter().map(|v| v.1).sum();
        out[4 * cells + c] = sample.len() as f64;
        out[5 * cells + c] = valid / total;
        if sample.len() < minimum || valid / total < fraction {
            continue;
        }
        let mut mean = 0.0;
        let mut accumulated = 0.0;
        for &(value, w) in &sample {
            accumulated += w;
            mean += (value - mean) * (w / accumulated);
        }
        if !mean.is_finite() {
            return 3;
        }
        sample.sort_unstable_by(|a, b| a.0.total_cmp(&b.0));
        out[c] = mean;
        out[cells + c] = quantile(&sample, 0.5, weighted);
        out[2 * cells + c] = quantile(&sample, 0.05, weighted);
        out[3 * cells + c] = quantile(&sample, 0.95, weighted);
        if let Some(r) = reference {
            if r[c].is_finite() {
                let positive: f64 = sample.iter().filter(|v| v.0 > r[c]).map(|v| v.1).sum();
                let negative: f64 = sample.iter().filter(|v| v.0 < r[c]).map(|v| v.1).sum();
                out[6 * cells + c] = positive.max(negative) / valid;
            }
        }
    }
    0
}
