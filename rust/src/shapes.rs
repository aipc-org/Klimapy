//! Geometry-only Shapefile input. Attributes and CRS interpretation stay outside this reader.
use geo::{Area, Contains, LineString, MultiPolygon, Polygon, Validation};
use shapefile::{PolygonRing, Shape};
use std::ffi::{c_char, CStr, CString};

fn organize(rings: Vec<(bool, LineString<f64>)>) -> Result<MultiPolygon<f64>, String> {
    let mut polygons: Vec<Polygon<f64>> = rings
        .iter()
        .filter(|(outer, _)| *outer)
        .map(|(_, ring)| Polygon::new(ring.clone(), vec![]))
        .collect();
    for (_, hole) in rings.into_iter().filter(|(outer, _)| !*outer) {
        let owner = polygons
            .iter()
            .enumerate()
            .filter(|(_, p)| p.contains(&hole))
            .min_by(|(_, a), (_, b)| a.unsigned_area().total_cmp(&b.unsigned_area()))
            .map(|(i, _)| i)
            .ok_or("Interior ring has no containing exterior")?;
        polygons[owner].interiors_push(hole);
    }
    let result = MultiPolygon(polygons);
    if result.0.is_empty() || !result.is_valid() {
        return Err("Invalid polygon topology or ring coordinates".into());
    }
    Ok(result)
}

fn read(path: &str) -> Result<serde_json::Value, String> {
    let shapes = shapefile::read_shapes(path).map_err(|e| e.to_string())?;
    let mut output = Vec::new();
    for shape in shapes {
        macro_rules! rings {
            ($polygon:expr) => {
                $polygon
                    .rings()
                    .iter()
                    .map(|ring| {
                        let outer = matches!(ring, PolygonRing::Outer(_));
                        let line = LineString::from(
                            ring.points().iter().map(|p| (p.x, p.y)).collect::<Vec<_>>(),
                        );
                        (outer, line)
                    })
                    .collect::<Vec<_>>()
            };
        }
        let rings = match shape {
            Shape::NullShape => continue,
            Shape::Polygon(p) => rings!(p),
            Shape::PolygonM(p) => rings!(p),
            Shape::PolygonZ(p) => rings!(p),
            _ => return Err("Spatial masks require Polygon/PolygonM/PolygonZ shapes".into()),
        };
        for polygon in organize(rings)?.0 {
            let mut coordinates = Vec::new();
            for line in std::iter::once(polygon.exterior()).chain(polygon.interiors()) {
                coordinates.push(line.0.iter().map(|p| [p.x, p.y]).collect::<Vec<_>>());
            }
            output.push(coordinates);
        }
    }
    if output.is_empty() {
        return Err("Shapefile contains no polygon geometry".into());
    }
    Ok(serde_json::json!({"type":"MultiPolygon", "coordinates":output}))
}

/// Return an owned UTF-8 JSON string; use kl_shape_json_free exactly once.
/// # Safety
/// path must point to a valid NUL-terminated UTF-8 string.
#[no_mangle]
pub unsafe extern "C" fn kl_shape_json(path: *const c_char) -> *mut c_char {
    if path.is_null() {
        return std::ptr::null_mut();
    }
    let result = std::panic::catch_unwind(|| {
        let path = CStr::from_ptr(path).to_str().map_err(|e| e.to_string())?;
        read(path)
    })
    .unwrap_or_else(|_| Err("Shapefile reader failed internally".into()));
    let value = match result {
        Ok(v) => v,
        Err(e) => serde_json::json!({"error":e}),
    };
    CString::new(value.to_string())
        .expect("JSON escapes NUL characters")
        .into_raw()
}

/// # Safety
/// pointer must be returned by kl_shape_json and must not have been freed.
#[no_mangle]
pub unsafe extern "C" fn kl_shape_json_free(pointer: *mut c_char) {
    if !pointer.is_null() {
        drop(CString::from_raw(pointer));
    }
}
