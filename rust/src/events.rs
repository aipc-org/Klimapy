//! Threshold event catalogues with explicit break and gap semantics.
/// Scan events, first with null output to obtain row count, then with capacity.
/// # Safety
/// x has steps*cells elements, breaks has steps; count is writable; a nonnull
/// output has capacity*8 writable f64 elements, disjoint from all inputs.
#[no_mangle]
pub unsafe extern "C" fn kl_events(
    x: *const f64,
    breaks: *const u8,
    output: *mut f64,
    count: *mut usize,
    steps: usize,
    cells: usize,
    capacity: usize,
    threshold: f64,
    mode: usize,
    minimum: usize,
    max_gap: usize,
) -> i32 {
    let Some(n) = steps
        .checked_mul(cells)
        .filter(|&v| v <= isize::MAX as usize / 8)
    else {
        return 1;
    };
    if x.is_null()
        || breaks.is_null()
        || count.is_null()
        || !threshold.is_finite()
        || mode > 4
        || minimum == 0
        || capacity > isize::MAX as usize / 64
    {
        return 1;
    }
    let x = std::slice::from_raw_parts(x, n);
    let breaks = std::slice::from_raw_parts(breaks, steps);
    let out = if output.is_null() {
        None
    } else {
        Some(std::slice::from_raw_parts_mut(output, capacity * 8))
    };
    let mut out = out;
    let mut rows = 0;
    for c in 0..cells {
        let (mut first, mut last, mut active, mut sum, mut peak, mut gap) =
            (0usize, 0usize, 0usize, 0.0, 0.0f64, 0usize);
        for t in 0..=steps {
            let value = if t < steps {
                x[t * cells + c]
            } else {
                f64::NAN
            };
            let boundary = t == steps || !value.is_finite() || (t > 0 && breaks[t] != 0);
            let hit = if !value.is_finite() {
                false
            } else {
                match mode {
                    0 => value < threshold,
                    1 => value <= threshold,
                    2 => value > threshold,
                    3 => value >= threshold,
                    _ => value > 0.5,
                }
            };
            if active > 0 && (boundary || (!hit && gap >= max_gap)) {
                if active >= minimum {
                    if let Some(ref mut output) = out {
                        if rows >= capacity {
                            return 1;
                        }
                        let row = &mut output[rows * 8..rows * 8 + 8];
                        row.copy_from_slice(&[
                            c as f64,
                            first as f64,
                            last as f64,
                            active as f64,
                            sum,
                            peak,
                            (last - first + 1 - active) as f64,
                            sum / active as f64,
                        ]);
                    }
                    rows += 1;
                }
                active = 0;
                sum = 0.0;
                peak = 0.0;
                gap = 0;
            }
            if t == steps {
                break;
            }
            if hit {
                if active == 0 {
                    first = t;
                }
                last = t;
                active += 1;
                gap = 0;
                let intensity = if mode == 4 {
                    1.0
                } else if mode < 2 {
                    threshold - value
                } else {
                    value - threshold
                };
                sum += intensity;
                peak = peak.max(intensity);
                if !sum.is_finite() {
                    return 3;
                }
            } else if active > 0 {
                gap += 1;
            }
        }
    }
    *count = rows;
    0
}

/// Form a compound boolean condition from several threshold criteria.
/// # Safety
/// x has criteria*cells values; thresholds/modes have criteria elements;
/// output has cells writable values, disjoint from inputs.
#[no_mangle]
pub unsafe extern "C" fn kl_compound(
    x: *const f64,
    thresholds: *const f64,
    modes: *const usize,
    output: *mut f64,
    criteria: usize,
    cells: usize,
) -> i32 {
    let Some(n) = criteria
        .checked_mul(cells)
        .filter(|&v| v <= isize::MAX as usize / 8)
    else {
        return 1;
    };
    if x.is_null() || thresholds.is_null() || modes.is_null() || output.is_null() || criteria == 0 {
        return 1;
    }
    let x = std::slice::from_raw_parts(x, n);
    let thresholds = std::slice::from_raw_parts(thresholds, criteria);
    let modes = std::slice::from_raw_parts(modes, criteria);
    if thresholds.iter().any(|v| !v.is_finite()) || modes.iter().any(|&m| m > 3) {
        return 1;
    }
    let out = std::slice::from_raw_parts_mut(output, cells);
    for c in 0..cells {
        let (mut all, mut valid) = (true, true);
        for k in 0..criteria {
            let v = x[k * cells + c];
            let t = thresholds[k];
            if !v.is_finite() {
                valid = false;
                break;
            }
            all &= match modes[k] {
                0 => v < t,
                1 => v <= t,
                2 => v > t,
                _ => v >= t,
            };
        }
        out[c] = if valid { f64::from(all) } else { f64::NAN };
    }
    0
}
