//! Group reductions and type-8 quantiles for native ETCCDI interfaces.

fn size_ok(a: usize, b: usize) -> bool {
    a.checked_mul(b)
        .is_some_and(|n| n <= isize::MAX as usize / 8)
}

fn quantile(sample: &mut [f64], q: f64) -> f64 {
    if sample.is_empty() {
        return f64::NAN;
    }
    sample.sort_unstable_by(f64::total_cmp);
    let h =
        ((sample.len() as f64 + 1.0 / 3.0) * q - 2.0 / 3.0).clamp(0.0, (sample.len() - 1) as f64);
    let lo = h.floor() as usize;
    let hi = (lo + 1).min(sample.len() - 1);
    sample[lo] + (sample[hi] - sample[lo]) * (h - lo as f64)
}

/// Type-8 quantiles by circular seasonal window, or one wet-day sample.
/// # Safety
/// input=steps*cells, days=steps, selected=steps, output=ndays*cells.
#[no_mangle]
pub unsafe extern "C" fn kl_threshold(
    input: *const f64,
    days: *const usize,
    selected: *const u8,
    output: *mut f64,
    steps: usize,
    cells: usize,
    ndays: usize,
    radius: usize,
    q: f64,
    wet: u32,
) -> i32 {
    if input.is_null()
        || days.is_null()
        || selected.is_null()
        || output.is_null()
        || !size_ok(steps, cells)
        || !size_ok(ndays, cells)
        || !size_ok(steps, 1)
        || ![1, 360, 365].contains(&ndays)
        || radius >= ndays
        || !(0.0..=1.0).contains(&q)
        || wet > 1
    {
        return 1;
    }
    let v = std::slice::from_raw_parts(input, steps * cells);
    let d = std::slice::from_raw_parts(days, steps);
    let sel = std::slice::from_raw_parts(selected, steps);
    let out = std::slice::from_raw_parts_mut(output, ndays * cells);
    if d.iter().any(|&i| i >= ndays) {
        return 1;
    }
    for day in 0..ndays {
        let indices: Vec<usize> = (0..steps)
            .filter(|&t| {
                let distance = d[t].abs_diff(day);
                sel[t] != 0 && distance.min(ndays - distance) <= radius
            })
            .collect();
        for c in 0..cells {
            let mut sample: Vec<f64> = indices
                .iter()
                .filter_map(|&t| {
                    let x = v[t * cells + c];
                    (x.is_finite() && (wet == 0 || x >= 1.0)).then_some(x)
                })
                .collect();
            out[day * cells + c] = if sample.len() < if wet == 1 { 10 } else { 1 } {
                f64::NAN
            } else {
                quantile(&mut sample, q)
            };
        }
    }
    0
}

/// Grouped indices: sum/count/intensity/ratio, rolling max, runs, extrema,
/// temperature percentages/spells, paired mean difference and growing season.
/// # Safety
/// input,aux=steps*cells; groups,late=steps; expected=ngroups; out=ngroups*cells.
#[no_mangle]
pub unsafe extern "C" fn kl_index(
    input: *const f64,
    aux: *const f64,
    groups: *const usize,
    late: *const u8,
    expected: *const f64,
    output: *mut f64,
    steps: usize,
    cells: usize,
    ngroups: usize,
    op: u32,
    threshold: f64,
    window: usize,
    fraction: f64,
) -> i32 {
    if [input, aux, expected].iter().any(|p| p.is_null())
        || output.is_null()
        || groups.is_null()
        || late.is_null()
        || !size_ok(steps, cells)
        || !size_ok(ngroups, cells)
        || !size_ok(steps, 1)
        || !size_ok(ngroups, 1)
        || ngroups == 0
        || window == 0
        || op > 20
        || !threshold.is_finite()
        || !(0.0..=1.0).contains(&fraction)
    {
        return 1;
    }
    let (v, a, g, l, e, out) = (
        std::slice::from_raw_parts(input, steps * cells),
        std::slice::from_raw_parts(aux, steps * cells),
        std::slice::from_raw_parts(groups, steps),
        std::slice::from_raw_parts(late, steps),
        std::slice::from_raw_parts(expected, ngroups),
        std::slice::from_raw_parts_mut(output, ngroups * cells),
    );
    if g.iter().any(|&i| i >= ngroups)
        || e.iter().any(|&x| !x.is_finite() || x <= 0.0)
        || g.windows(2).any(|w| w[0] > w[1])
    {
        return 1;
    }
    out.fill(f64::NAN);
    let mut blocks = vec![Vec::new(); ngroups];
    for (t, &group) in g.iter().enumerate() {
        blocks[group].push(t);
    }
    for (group, indices) in blocks.iter().enumerate() {
        for c in 0..cells {
            let mut count = 0usize;
            let (mut sum, mut total) = (0.0, 0.0);
            let (mut hits, mut denom, mut run, mut longest, mut spell) =
                (0usize, 0usize, 0usize, 0usize, 0usize);
            let mut extreme = if op == 8 {
                f64::INFINITY
            } else {
                f64::NEG_INFINITY
            };
            let (mut start, mut end) = (None, None);
            let (mut warm, mut cold) = (0usize, 0usize);
            let mut last = None;
            for &t in indices {
                if last.is_some_and(|p| t != p + 1) {
                    run = 0;
                    warm = 0;
                    cold = 0;
                }
                last = Some(t);
                let x = v[t * cells + c];
                let b = a[t * cells + c];
                let valid = x.is_finite() && (op != 18 || b.is_finite());
                if valid {
                    count += 1;
                    total += x;
                }
                let condition = match op {
                    0..=3 => valid && x >= threshold,
                    5 => valid && x < threshold,
                    6 => valid && x >= threshold,
                    9 => valid && x < threshold,
                    10 => valid && x > threshold,
                    11 | 13 | 15 | 17 | 20 => {
                        valid && b.is_finite() && x > b && (op < 13 || x >= 1.0)
                    }
                    12 | 14 => valid && b.is_finite() && x < b,
                    16 => valid && b.is_finite() && x > b,
                    _ => false,
                };
                if condition {
                    hits += 1;
                    sum += x;
                    run += 1;
                    longest = longest.max(run);
                } else {
                    if run >= window {
                        spell += run;
                    }
                    run = 0;
                }
                if valid && b.is_finite() {
                    denom += 1;
                }
                if op == 7 && valid {
                    extreme = extreme.max(x);
                }
                if op == 8 && valid {
                    extreme = extreme.min(x);
                }
                if op == 4 && t + 1 >= window {
                    let segment = &v[(t + 1 - window) * cells..(t + 1) * cells];
                    let mut rolling = 0.0;
                    let mut complete = true;
                    for row in segment.chunks_exact(cells) {
                        if row[c].is_finite() {
                            rolling += row[c];
                        } else {
                            complete = false;
                            break;
                        }
                    }
                    if complete {
                        extreme = extreme.max(rolling);
                    }
                }
                if op == 18 && valid {
                    sum += x - b;
                }
                if op == 19 {
                    warm = if valid && x > 5.0 { warm + 1 } else { 0 };
                    if start.is_none() && warm >= 6 {
                        start = Some(t + 1 - 6);
                    }
                    cold = if valid && x < 5.0 && l[t] != 0 && start.is_some_and(|s| t > s) {
                        cold + 1
                    } else {
                        0
                    };
                    if end.is_none() && cold >= 6 {
                        end = Some(t + 1 - 6);
                    }
                }
            }
            if run >= window {
                spell += run;
            }
            if count == 0 || (count as f64) < e[group] * fraction {
                continue;
            }
            let result = match op {
                0 | 13 => sum,
                1 | 9 | 10 | 15 => hits as f64,
                2 | 17 => {
                    if hits > 0 {
                        sum / hits as f64
                    } else {
                        f64::NAN
                    }
                }
                3 | 20 => {
                    if total > 0.0 {
                        sum / total
                    } else {
                        f64::NAN
                    }
                }
                4 | 7 | 8 => {
                    if extreme.is_finite() {
                        extreme
                    } else {
                        f64::NAN
                    }
                }
                5 | 6 => longest as f64,
                11 | 12 => {
                    if denom > 0 {
                        100.0 * hits as f64 / denom as f64
                    } else {
                        f64::NAN
                    }
                }
                14 | 16 => spell as f64,
                18 => sum / count as f64,
                19 => match (start, end) {
                    (None, _) => 0.0,
                    (Some(s), Some(z)) => (z.saturating_sub(s)) as f64,
                    _ => f64::NAN,
                },
                _ => f64::NAN,
            };
            // A missing reference threshold invalidates the result rather than
            // turning a no-reference series into a zero rainfall total/count.
            out[group * cells + c] = if matches!(op, 13 | 15 | 17 | 20) && denom == 0 {
                f64::NAN
            } else {
                result
            };
        }
    }
    0
}

/// Unit conversion and finite masking; metadata supplies scale and offset.
/// # Safety
/// input/output contain len disjoint doubles.
#[no_mangle]
pub unsafe extern "C" fn kl_affine(
    input: *const f64,
    output: *mut f64,
    len: usize,
    scale: f64,
    offset: f64,
) -> i32 {
    if input.is_null()
        || output.is_null()
        || !size_ok(len, 1)
        || !scale.is_finite()
        || !offset.is_finite()
    {
        return 1;
    }
    let source = std::slice::from_raw_parts(input, len);
    let target = std::slice::from_raw_parts_mut(output, len);
    for (out, &x) in target.iter_mut().zip(source) {
        *out = if x.is_finite() {
            x * scale + offset
        } else {
            f64::NAN
        };
    }
    0
}

/// # Safety
/// sums/counts/output hold len f64/i32/f64 elements; output disjoint.
#[no_mangle]
pub unsafe extern "C" fn kl_climate_mean(
    sums: *const f64,
    counts: *const i32,
    output: *mut f64,
    len: usize,
) -> i32 {
    if sums.is_null() || counts.is_null() || output.is_null() || !size_ok(len, 1) {
        return 1;
    }
    let s = std::slice::from_raw_parts(sums, len);
    let c = std::slice::from_raw_parts(counts, len);
    let out = std::slice::from_raw_parts_mut(output, len);
    for i in 0..len {
        out[i] = if c[i] > 0 {
            s[i] / c[i] as f64
        } else {
            f64::NAN
        };
    }
    0
}
