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
    for cell in 0..cells {
        let (mut count, mut sum_t, mut sum_y) = (0usize, 0.0, 0.0);
        for t in 0..steps {
            let y = source[t * cells + cell];
            if !y.is_nan() {
                count += 1;
                sum_t += t as f64;
                sum_y += y;
            }
        }
        if count < 2 {
            continue;
        }
        let mean_t = sum_t / count as f64;
        let mean_y = sum_y / count as f64;
        let (mut tt, mut ty) = (0.0, 0.0);
        for t in 0..steps {
            let y = source[t * cells + cell];
            if !y.is_nan() {
                let dt = t as f64 - mean_t;
                tt += dt * dt;
                ty += dt * (y - mean_y);
            }
        }
        let slope = ty / tt;
        let intercept = mean_y - slope * mean_t;
        for t in 0..steps {
            result[t * cells + cell] = source[t * cells + cell] - (slope * t as f64 + intercept);
        }
    }
    0
}
