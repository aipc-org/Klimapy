//! Spatial reductions, polygon masks and a minimal uncompressed GeoTIFF writer.
use std::ffi::{c_char, CStr};
use std::io::Write;
fn size(n: usize, m: usize) -> Option<usize> {
    n.checked_mul(m).filter(|&n| n <= isize::MAX as usize / 8)
}
/// # Safety
/// data/mask=ny*nx doubles/bytes; lat=ny doubles; output=one writable double.
#[no_mangle]
pub unsafe extern "C" fn kl_spatial_mean(
    data: *const f64,
    lat: *const f64,
    mask: *const u8,
    ny: usize,
    nx: usize,
    weighted: u32,
    zeros: u32,
    output: *mut f64,
) -> i32 {
    let Some(n) = size(ny, nx) else {
        return 1;
    };
    if data.is_null()
        || lat.is_null()
        || mask.is_null()
        || output.is_null()
        || weighted > 1
        || zeros > 1
    {
        return 1;
    }
    let a = std::slice::from_raw_parts(data, n);
    let y = std::slice::from_raw_parts(lat, ny);
    let m = std::slice::from_raw_parts(mask, n);
    if y.iter().any(|v| !v.is_finite() || v.abs() > 90.0) {
        return 1;
    }
    let (mut sum, mut weight) = (0.0, 0.0);
    for (j, latitude) in y.iter().enumerate() {
        let w = if weighted == 1 {
            latitude.to_radians().cos()
        } else {
            1.0
        };
        for i in 0..nx {
            let k = j * nx + i;
            let v = a[k];
            if m[k] != 0 && v.is_finite() && (zeros == 1 || v > 0.0) {
                sum += v * w;
                weight += w;
            }
        }
    }
    *output = if weight > 0.0 { sum / weight } else { f64::NAN };
    0
}
fn inside(x: f64, y: f64, points: &[f64]) -> i32 {
    let n = points.len() / 2;
    let mut hit = false;
    for i in 0..n {
        let j = (i + 1) % n;
        let (a, b, c, d) = (
            points[2 * i],
            points[2 * i + 1],
            points[2 * j],
            points[2 * j + 1],
        );
        let cross = (x - a) * (d - b) - (y - b) * (c - a);
        if cross.abs() <= 1e-12 * (1.0 + (c - a).abs() + (d - b).abs())
            && x >= a.min(c) - 1e-12
            && x <= a.max(c) + 1e-12
            && y >= b.min(d) - 1e-12
            && y <= b.max(d) + 1e-12
        {
            return 2;
        }
        if (b > y) != (d > y) && x < (c - a) * (y - b) / (d - b) + a {
            hit = !hit;
        }
    }
    i32::from(hit)
}
/// # Safety
/// lat=ny,lon=nx; points=2*npoints; rings=nrings+1; polygons=npoly+1; out=ny*nx.
#[no_mangle]
pub unsafe extern "C" fn kl_polygon_mask(
    lat: *const f64,
    ny: usize,
    lon: *const f64,
    nx: usize,
    points: *const f64,
    npoints: usize,
    rings: *const usize,
    nrings: usize,
    polygons: *const usize,
    npoly: usize,
    output: *mut u8,
) -> i32 {
    let Some(n) = size(ny, nx) else {
        return 1;
    };
    if [lat, lon, points].iter().any(|p| p.is_null())
        || rings.is_null()
        || polygons.is_null()
        || output.is_null()
        || size(npoints, 2).is_none()
        || size(nrings + 1, 1).is_none()
        || size(npoly + 1, 1).is_none()
        || npoly == 0
    {
        return 1;
    }
    let y = std::slice::from_raw_parts(lat, ny);
    let x = std::slice::from_raw_parts(lon, nx);
    let xy = std::slice::from_raw_parts(points, 2 * npoints);
    let r = std::slice::from_raw_parts(rings, nrings + 1);
    let p = std::slice::from_raw_parts(polygons, npoly + 1);
    let out = std::slice::from_raw_parts_mut(output, n);
    if r[0] != 0
        || r[nrings] != npoints
        || p[0] != 0
        || p[npoly] != nrings
        || r.windows(2).any(|v| v[1] < v[0] || v[1] - v[0] < 3)
        || p.windows(2).any(|v| v[1] <= v[0])
        || xy.iter().chain(x).chain(y).any(|v| !v.is_finite())
    {
        return 1;
    }
    for (j, &yy) in y.iter().enumerate() {
        for (i, &xx) in x.iter().enumerate() {
            let mut included = false;
            for k in 0..npoly {
                let outer = p[k];
                let state = inside(xx, yy, &xy[2 * r[outer]..2 * r[outer + 1]]);
                if state == 2 {
                    included = true;
                    break;
                }
                if state == 0 {
                    continue;
                }
                let mut hole = false;
                let mut boundary = false;
                for h in outer + 1..p[k + 1] {
                    let s = inside(xx, yy, &xy[2 * r[h]..2 * r[h + 1]]);
                    if s == 2 {
                        boundary = true;
                        break;
                    }
                    if s == 1 {
                        hole = true;
                    }
                }
                if boundary || !hole {
                    included = true;
                    break;
                }
            }
            out[j * nx + i] = u8::from(included);
        }
    }
    0
}
fn bytes_f64(values: &[f64]) -> Vec<u8> {
    values.iter().flat_map(|v| v.to_le_bytes()).collect()
}
fn tag(
    id: u16,
    kind: u16,
    count: u32,
    data: &[u8],
    ifd: &mut Vec<u8>,
    extra: &mut Vec<u8>,
    base: usize,
) {
    ifd.extend(id.to_le_bytes());
    ifd.extend(kind.to_le_bytes());
    ifd.extend(count.to_le_bytes());
    if data.len() <= 4 {
        let mut a = [0u8; 4];
        a[..data.len()].copy_from_slice(data);
        ifd.extend(a);
    } else {
        while (base + extra.len()) % 8 != 0 {
            extra.push(0);
        }
        ifd.extend(((base + extra.len()) as u32).to_le_bytes());
        extra.extend(data);
    }
}
/// Write Float32 WGS84 PixelIsArea GeoTIFF; one uncompressed strip, exclusive file.
/// # Safety
/// path is a NUL-terminated UTF-8 path; data=ny*nx doubles; bounds=4 doubles
/// [west,north,pixel_width,pixel_height], with positive pixel sizes.
#[no_mangle]
pub unsafe extern "C" fn kl_write_tiff(
    path: *const c_char,
    data: *const f64,
    ny: usize,
    nx: usize,
    bounds: *const f64,
) -> i32 {
    let Some(n) = size(ny, nx) else {
        return 1;
    };
    if path.is_null()
        || data.is_null()
        || bounds.is_null()
        || ny == 0
        || nx == 0
        || n > (u32::MAX as usize - 4096) / 4
    {
        return 1;
    }
    let Ok(path) = CStr::from_ptr(path).to_str() else {
        return 1;
    };
    let a = std::slice::from_raw_parts(data, n);
    let b = std::slice::from_raw_parts(bounds, 4);
    if b.iter().any(|v| !v.is_finite()) || b[2] <= 0.0 || b[3] <= 0.0 {
        return 1;
    }
    let entries = 15usize;
    let base = 8 + 2 + entries * 12 + 4;
    let mut ifd = Vec::new();
    let mut extra = Vec::new();
    // All tags are sorted. Strip offset is patched after auxiliary tag data.
    for (id, value) in [(256, nx as u32), (257, ny as u32)] {
        tag(id, 4, 1, &value.to_le_bytes(), &mut ifd, &mut extra, base);
    }
    tag(258, 3, 1, &32u16.to_le_bytes(), &mut ifd, &mut extra, base);
    tag(259, 3, 1, &1u16.to_le_bytes(), &mut ifd, &mut extra, base);
    tag(262, 3, 1, &1u16.to_le_bytes(), &mut ifd, &mut extra, base);
    let strip_position = ifd.len() + 8;
    tag(273, 4, 1, &0u32.to_le_bytes(), &mut ifd, &mut extra, base);
    tag(277, 3, 1, &1u16.to_le_bytes(), &mut ifd, &mut extra, base);
    tag(
        278,
        4,
        1,
        &(ny as u32).to_le_bytes(),
        &mut ifd,
        &mut extra,
        base,
    );
    tag(
        279,
        4,
        1,
        &((n * 4) as u32).to_le_bytes(),
        &mut ifd,
        &mut extra,
        base,
    );
    tag(284, 3, 1, &1u16.to_le_bytes(), &mut ifd, &mut extra, base);
    tag(339, 3, 1, &3u16.to_le_bytes(), &mut ifd, &mut extra, base);
    tag(
        33550,
        12,
        3,
        &bytes_f64(&[b[2], b[3], 0.0]),
        &mut ifd,
        &mut extra,
        base,
    );
    tag(
        33922,
        12,
        6,
        &bytes_f64(&[0.0, 0.0, 0.0, b[0], b[1], 0.0]),
        &mut ifd,
        &mut extra,
        base,
    );
    let keys: [u16; 20] = [
        1, 1, 0, 4, 1024, 0, 1, 2, 1025, 0, 1, 1, 2048, 0, 1, 4326, 2054, 0, 1, 9102,
    ];
    tag(
        34735,
        3,
        20,
        &keys
            .iter()
            .flat_map(|v| v.to_le_bytes())
            .collect::<Vec<_>>(),
        &mut ifd,
        &mut extra,
        base,
    );
    tag(42113, 2, 4, b"nan\0", &mut ifd, &mut extra, base);
    let offset = (base + extra.len()) as u32;
    ifd[strip_position..strip_position + 4].copy_from_slice(&offset.to_le_bytes());
    let result = (|| -> std::io::Result<()> {
        let mut f = std::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(path)?;
        f.write_all(b"II\x2a\0\x08\0\0\0")?;
        f.write_all(&(entries as u16).to_le_bytes())?;
        f.write_all(&ifd)?;
        f.write_all(&0u32.to_le_bytes())?;
        f.write_all(&extra)?;
        for &v in a {
            f.write_all(&(v as f32).to_le_bytes())?;
        }
        f.flush()?;
        Ok(())
    })();
    if result.is_ok() {
        0
    } else {
        2
    }
}
