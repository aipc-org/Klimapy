//! Rectilinear remapping; all weight construction/evaluation lives in Rust.
use std::ffi::c_void;

#[repr(C)]
pub struct Grid {
    pub y: *const f64,
    pub ny: usize,
    pub x: *const f64,
    pub nx: usize,
    pub yb: *const f64,
    pub xb: *const f64,
}
struct Plan {
    ny: usize,
    nx: usize,
    yc: Vec<f64>,
    xc: Vec<f64>,
    mode: u32,
    rows: Vec<Vec<(usize, f64, f64, f64)>>,
    valid: Vec<bool>,
}
fn checked(n: usize, m: usize) -> bool {
    n.checked_mul(m)
        .is_some_and(|v| v <= isize::MAX as usize / 8)
}
unsafe fn axes(g: &Grid) -> Option<(&[f64], &[f64])> {
    if g.y.is_null() || g.x.is_null() || g.ny == 0 || g.nx == 0 || !checked(g.ny, g.nx) {
        return None;
    }
    let y = std::slice::from_raw_parts(g.y, g.ny);
    let x = std::slice::from_raw_parts(g.x, g.nx);
    if y.iter().chain(x).any(|v| !v.is_finite())
        || y.windows(2).chain(x.windows(2)).any(|w| w[1] <= w[0])
    {
        return None;
    }
    Some((y, x))
}
fn bracket(axis: &[f64], v: f64, width: usize) -> usize {
    axis.partition_point(|&a| a < v)
        .saturating_sub(1)
        .min(axis.len() - width)
}
fn sphere(y: f64, x: f64) -> [f64; 3] {
    let (a, b) = (y.to_radians(), x.to_radians());
    [a.cos() * b.cos(), a.cos() * b.sin(), a.sin()]
}

/// Create an immutable plan. mode=1 bilinear,2 nearest,3 patch,4/5 conservative.
/// # Safety
/// Grid pointers/arrays must be readable with declared lengths; error writable.
#[no_mangle]
pub unsafe extern "C" fn kl_remap_new(
    source: *const Grid,
    target: *const Grid,
    mode: u32,
    error: *mut i32,
) -> *mut c_void {
    if error.is_null() {
        return std::ptr::null_mut();
    }
    *error = 1;
    if source.is_null() || target.is_null() || !(1..=5).contains(&mode) {
        return std::ptr::null_mut();
    }
    let (s, t) = (&*source, &*target);
    let (Some((sy, sx)), Some((ty, tx))) = (axes(s), axes(t)) else {
        return std::ptr::null_mut();
    };
    let min = if mode == 3 {
        3
    } else if mode == 1 {
        2
    } else {
        1
    };
    if sy.len() < min || sx.len() < min {
        return std::ptr::null_mut();
    }
    let mut p = Plan {
        ny: s.ny,
        nx: s.nx,
        yc: sy.to_vec(),
        xc: sx.to_vec(),
        mode,
        rows: Vec::new(),
        valid: Vec::new(),
    };
    let mut bounds = None;
    if mode >= 4 {
        if s.yb.is_null() || s.xb.is_null() || t.yb.is_null() || t.xb.is_null() {
            return std::ptr::null_mut();
        }
        let syb = std::slice::from_raw_parts(s.yb, s.ny + 1);
        let sxb = std::slice::from_raw_parts(s.xb, s.nx + 1);
        let tyb = std::slice::from_raw_parts(t.yb, t.ny + 1);
        let txb = std::slice::from_raw_parts(t.xb, t.nx + 1);
        if [syb, sxb, tyb, txb]
            .iter()
            .any(|a| a.iter().any(|v| !v.is_finite()) || a.windows(2).any(|w| w[1] <= w[0]))
        {
            return std::ptr::null_mut();
        }
        let yb: Vec<f64> = syb.iter().map(|v| v.to_radians().sin()).collect();
        let xb: Vec<f64> = sxb.iter().map(|v| v.to_radians()).collect();
        let oy: Vec<f64> = tyb.iter().map(|v| v.to_radians().sin()).collect();
        let ox: Vec<f64> = txb.iter().map(|v| v.to_radians()).collect();
        p.yc = yb.windows(2).map(|w| (w[0] + w[1]) / 2.0).collect();
        p.xc = xb.windows(2).map(|w| (w[0] + w[1]) / 2.0).collect();
        bounds = Some((yb, xb, oy, ox));
    }
    for (j, &y) in ty.iter().enumerate() {
        for (i, &x) in tx.iter().enumerate() {
            let mut row = Vec::new();
            let mut valid = y >= sy[0] && y <= sy[s.ny - 1] && x >= sx[0] && x <= sx[s.nx - 1];
            if let Some((yb, xb, oy, ox)) = &bounds {
                let (ya, yz, xa, xz) = (oy[j], oy[j + 1], ox[i], ox[i + 1]);
                let area = (yz - ya) * (xz - xa);
                let mut total = 0.0;
                for a in 0..s.ny {
                    let (loy, hiy) = (ya.max(yb[a]), yz.min(yb[a + 1]));
                    if hiy <= loy {
                        continue;
                    }
                    for b in 0..s.nx {
                        let (lox, hix) = (xa.max(xb[b]), xz.min(xb[b + 1]));
                        if hix <= lox {
                            continue;
                        }
                        let w = (hiy - loy) * (hix - lox) / area;
                        row.push((
                            a * s.nx + b,
                            w,
                            w * ((lox + hix) / 2.0 - p.xc[b]),
                            w * ((loy + hiy) / 2.0 - p.yc[a]),
                        ));
                        total += w;
                    }
                }
                valid = (total - 1.0).abs() <= 1e-12 + 1e-10;
            } else if mode == 2 {
                let dest = sphere(y, x);
                let mut best = (f64::INFINITY, 0usize);
                for (a, &yy) in sy.iter().enumerate() {
                    for (b, &xx) in sx.iter().enumerate() {
                        let pos = sphere(yy, xx);
                        let distance = (0..3).map(|k| (pos[k] - dest[k]).powi(2)).sum::<f64>();
                        if distance < best.0 {
                            best = (distance, a * s.nx + b);
                        }
                    }
                }
                row.push((best.1, 1.0, 0.0, 0.0));
            } else if valid && mode == 1 {
                let a = bracket(sy, y, 2);
                let b = bracket(sx, x, 2);
                let fy = (y - sy[a]) / (sy[a + 1] - sy[a]);
                let fx = (x - sx[b]) / (sx[b + 1] - sx[b]);
                for (k, w) in [
                    (a * s.nx + b, (1.0 - fy) * (1.0 - fx)),
                    (a * s.nx + b + 1, (1.0 - fy) * fx),
                    ((a + 1) * s.nx + b, fy * (1.0 - fx)),
                    ((a + 1) * s.nx + b + 1, fy * fx),
                ] {
                    if w.abs() > 1e-14 {
                        row.push((k, w, 0.0, 0.0));
                    }
                }
            } else if valid && mode == 3 {
                let a = bracket(sy, y, 3);
                let b = bracket(sx, x, 3);
                let mut design = Vec::with_capacity(54);
                for r in 0..3 {
                    for c in 0..3 {
                        let dx = (sx[b + c] - x) / (sx[b + 2] - sx[b]);
                        let dy = (sy[a + r] - y) / (sy[a + 2] - sy[a]);
                        design.extend([1.0, dx, dy, dx * dy, dx * dx, dy * dy]);
                    }
                }
                let Ok((u, singular, vt)) = crate::linalg::decompose(&design, 9, 6, 1e-14, 100)
                else {
                    return std::ptr::null_mut();
                };
                for k in 0..9 {
                    let w = (0..6)
                        .filter(|&q| singular[q] > singular[0] * 1e-15)
                        .map(|q| vt[q * 6] * u[k * 6 + q] / singular[q])
                        .sum::<f64>();
                    if w.abs() > 1e-14 {
                        row.push(((a + k / 3) * s.nx + b + k % 3, w, 0.0, 0.0));
                    }
                }
            }
            p.rows.push(row);
            p.valid.push(valid);
        }
    }
    *error = 0;
    Box::into_raw(Box::new(p)).cast()
}

fn gradient(v: &[f64], p: &Plan, r: usize, c: usize, vertical: bool) -> f64 {
    let (ny, nx, y, x) = (p.ny, p.nx, p.yc.as_slice(), p.xc.as_slice());
    let (n, k, axis) = if vertical { (ny, r, y) } else { (nx, c, x) };
    if n == 1 {
        return 0.0;
    }
    let at = |i: usize| {
        if vertical {
            v[i * nx + c]
        } else {
            v[r * nx + i]
        }
    };
    if k == 0 {
        return (at(1) - at(0)) / (axis[1] - axis[0]);
    }
    if k == n - 1 {
        return (at(k) - at(k - 1)) / (axis[k] - axis[k - 1]);
    }
    let a = axis[k] - axis[k - 1];
    let b = axis[k + 1] - axis[k];
    -b / (a * (a + b)) * at(k - 1) + (b - a) / (a * b) * at(k) + a / (b * (a + b)) * at(k + 1)
}

/// # Safety
/// handle must be live; input=batch*source cells; output=batch*target cells.
#[no_mangle]
pub unsafe extern "C" fn kl_remap_apply(
    handle: *const c_void,
    input: *const f64,
    output: *mut f64,
    batch: usize,
) -> i32 {
    if handle.is_null() || input.is_null() || output.is_null() {
        return 1;
    }
    let p = &*handle.cast::<Plan>();
    let n = p.ny * p.nx;
    let m = p.rows.len();
    if !checked(batch, n) || !checked(batch, m) {
        return 1;
    }
    let v = std::slice::from_raw_parts(input, batch * n);
    let out = std::slice::from_raw_parts_mut(output, batch * m);
    for k in 0..batch {
        let a = &v[k * n..(k + 1) * n];
        for (j, row) in p.rows.iter().enumerate() {
            let mut sum = 0.0;
            let mut valid = p.valid[j];
            for &(c, w, mx, my) in row {
                if !a[c].is_finite() {
                    valid = false;
                    break;
                }
                sum += w * a[c];
                if p.mode == 5 {
                    let gx = gradient(a, p, c / p.nx, c % p.nx, false);
                    let gy = gradient(a, p, c / p.nx, c % p.nx, true);
                    if gx.is_finite() {
                        sum += mx * gx;
                    }
                    if gy.is_finite() {
                        sum += my * gy;
                    }
                }
            }
            out[k * m + j] = if valid { sum } else { f64::NAN };
        }
    }
    0
}

/// # Safety
/// handle was returned by kl_remap_new and is freed exactly once.
#[no_mangle]
pub unsafe extern "C" fn kl_remap_free(handle: *mut c_void) {
    if !handle.is_null() {
        drop(Box::from_raw(handle.cast::<Plan>()));
    }
}
