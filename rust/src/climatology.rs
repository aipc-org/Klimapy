//! Coverage-aware finalization of streamed daily climate accumulators.
/// # Safety
/// Input arrays contain groups*cells sums/counts, groups expected counts, and
/// output has groups*cells writable values. Buffers must not overlap.
#[no_mangle]
pub unsafe extern "C" fn kl_climatology_finalize(
    sums: *const f64,
    counts: *const i32,
    expected: *const usize,
    output: *mut f64,
    groups: usize,
    cells: usize,
    fraction: f64,
) -> i32 {
    let Some(n) = groups.checked_mul(cells) else {
        return 1;
    };
    if sums.is_null()
        || counts.is_null()
        || expected.is_null()
        || output.is_null()
        || groups == 0
        || cells == 0
        || n > isize::MAX as usize / 8
        || !fraction.is_finite()
        || !(0.0..=1.0).contains(&fraction)
    {
        return 1;
    }
    let s = std::slice::from_raw_parts(sums, n);
    let c = std::slice::from_raw_parts(counts, n);
    let e = std::slice::from_raw_parts(expected, groups);
    let out = std::slice::from_raw_parts_mut(output, n);
    for (g, &expected_count) in e.iter().enumerate() {
        let start = g * cells;
        let end = start + cells;
        for ((&sum, &count), result) in s[start..end]
            .iter()
            .zip(&c[start..end])
            .zip(&mut out[start..end])
        {
            *result = if count > 0
                && expected_count > 0
                && count as f64 >= fraction * expected_count as f64
            {
                sum / count as f64
            } else {
                f64::NAN
            };
        }
    }
    0
}
