//! Native NetCDF I/O. libnetcdf is loaded at runtime; no Python NetCDF/xarray dependency.
use std::ffi::{c_char, c_int, c_void, CStr, CString};
use std::sync::{Mutex, OnceLock};

#[cfg(unix)]
mod dynamic {
    use super::*;
    #[cfg_attr(target_os = "linux", link(name = "dl"))]
    extern "C" {
        fn dlopen(path: *const c_char, flags: c_int) -> *mut c_void;
        fn dlsym(h: *mut c_void, n: *const c_char) -> *mut c_void;
    }
    pub unsafe fn open(p: *const c_char) -> *mut c_void {
        dlopen(p, 2)
    }
    pub unsafe fn symbol(h: *mut c_void, n: *const c_char) -> *mut c_void {
        dlsym(h, n)
    }
}
#[cfg(windows)]
mod dynamic {
    use super::*;
    #[link(name = "kernel32")]
    extern "system" {
        fn LoadLibraryA(p: *const c_char) -> *mut c_void;
        fn GetProcAddress(h: *mut c_void, n: *const c_char) -> *mut c_void;
    }
    pub unsafe fn open(p: *const c_char) -> *mut c_void {
        LoadLibraryA(p)
    }
    pub unsafe fn symbol(h: *mut c_void, n: *const c_char) -> *mut c_void {
        GetProcAddress(h, n)
    }
}
macro_rules! api {
    ($($field:ident: $ty:ty => $symbol:literal),* $(,)?) => {
        struct Api {$($field:$ty,)*}
        impl Api {unsafe fn load(path:*const c_char)->Result<Self,()> {
            let h=dynamic::open(path);if h.is_null(){return Err(());}
            Ok(Self {$($field:{let p=dynamic::symbol(h,concat!($symbol,"\0").as_ptr().cast());
                if p.is_null(){return Err(());} std::mem::transmute::<*mut c_void,$ty>(p)},)*})
        }}
    }
}
api! {
    open: unsafe extern "C" fn(*const c_char,c_int,*mut c_int)->c_int => "nc_open",
    create: unsafe extern "C" fn(*const c_char,c_int,*mut c_int)->c_int => "nc_create",
    close: unsafe extern "C" fn(c_int)->c_int => "nc_close",
    group: unsafe extern "C" fn(c_int,*const c_char,*mut c_int)->c_int => "nc_inq_grp_full_ncid",
    varid: unsafe extern "C" fn(c_int,*const c_char,*mut c_int)->c_int => "nc_inq_varid",
    nvars: unsafe extern "C" fn(c_int,*mut c_int)->c_int => "nc_inq_nvars",
    varname: unsafe extern "C" fn(c_int,c_int,*mut c_char)->c_int => "nc_inq_varname",
    var: unsafe extern "C" fn(c_int,c_int,*mut c_char,*mut c_int,*mut c_int,*mut c_int,*mut c_int)->c_int => "nc_inq_var",
    dim: unsafe extern "C" fn(c_int,c_int,*mut c_char,*mut usize)->c_int => "nc_inq_dim",
    attname: unsafe extern "C" fn(c_int,c_int,c_int,*mut c_char)->c_int => "nc_inq_attname",
    att: unsafe extern "C" fn(c_int,c_int,*const c_char,*mut c_int,*mut usize)->c_int => "nc_inq_att",
    get_text: unsafe extern "C" fn(c_int,c_int,*const c_char,*mut c_char)->c_int => "nc_get_att_text",
    get_strings: unsafe extern "C" fn(c_int,c_int,*const c_char,*mut *mut c_char)->c_int => "nc_get_att_string",
    free_strings: unsafe extern "C" fn(usize,*mut *mut c_char)->c_int => "nc_free_string",
    get_att: unsafe extern "C" fn(c_int,c_int,*const c_char,*mut f64)->c_int => "nc_get_att_double",
    get: unsafe extern "C" fn(c_int,c_int,*const usize,*const usize,*mut f64)->c_int => "nc_get_vara_double",
    fill: unsafe extern "C" fn(c_int,c_int,*mut c_int,*mut c_void)->c_int => "nc_inq_var_fill",
    def_dim: unsafe extern "C" fn(c_int,*const c_char,usize,*mut c_int)->c_int => "nc_def_dim",
    dimid: unsafe extern "C" fn(c_int,*const c_char,*mut c_int)->c_int => "nc_inq_dimid",
    def_var: unsafe extern "C" fn(c_int,*const c_char,c_int,c_int,*const c_int,*mut c_int)->c_int => "nc_def_var",
    deflate: unsafe extern "C" fn(c_int,c_int,c_int,c_int,c_int)->c_int => "nc_def_var_deflate",
    put_text: unsafe extern "C" fn(c_int,c_int,*const c_char,usize,*const c_char)->c_int => "nc_put_att_text",
    put_att: unsafe extern "C" fn(c_int,c_int,*const c_char,c_int,usize,*const f64)->c_int => "nc_put_att_double",
    enddef: unsafe extern "C" fn(c_int)->c_int => "nc_enddef",
    redef: unsafe extern "C" fn(c_int)->c_int => "nc_redef",
    put: unsafe extern "C" fn(c_int,c_int,*const usize,*const usize,*const f64)->c_int => "nc_put_vara_double",
    error: unsafe extern "C" fn(c_int)->*const c_char => "nc_strerror",
}
static API: OnceLock<Api> = OnceLock::new();
static LOCK: Mutex<()> = Mutex::new(());
const INVALID: i32 = -10000;
const UNAVAILABLE: i32 = -10001;
macro_rules! locked {
    ($a:ident) => {
        let _guard = LOCK.lock().unwrap_or_else(|e| e.into_inner());
        let Some($a) = API.get() else {
            return UNAVAILABLE;
        };
    };
}
macro_rules! check {
    ($e:expr) => {
        let code = $e;
        if code != 0 {
            return code;
        }
    };
}

unsafe fn resolve(a: &Api, id: c_int, path: *const c_char) -> Result<(c_int, c_int), c_int> {
    if path.is_null() {
        return Err(INVALID);
    }
    let s = CStr::from_ptr(path).to_bytes();
    if s.is_empty() {
        return Ok((id, -1));
    }
    let mut group = id;
    let name = if let Some(pos) = s.iter().rposition(|&b| b == b'/') {
        if pos > 0 {
            let prefix = CString::new(&s[..pos]).map_err(|_| INVALID)?;
            let code = (a.group)(id, prefix.as_ptr(), &mut group);
            if code != 0 {
                return Err(code);
            }
        }
        CString::new(&s[pos + 1..]).map_err(|_| INVALID)?
    } else {
        CString::new(s).map_err(|_| INVALID)?
    };
    let mut var = 0;
    let code = (a.varid)(group, name.as_ptr(), &mut var);
    if code != 0 {
        Err(code)
    } else {
        Ok((group, var))
    }
}
macro_rules! resolved {
    ($a:ident,$id:expr,$path:expr,$g:ident,$v:ident) => {
        let ($g, $v) = match resolve($a, $id, $path) {
            Ok(v) => v,
            Err(c) => return c,
        };
    };
}
unsafe fn scalar(a: &Api, id: i32, var: i32, name: &[u8]) -> Result<Option<f64>, i32> {
    let (mut kind, mut n) = (0, 0);
    let code = (a.att)(id, var, name.as_ptr().cast(), &mut kind, &mut n);
    if code == -43 {
        return Ok(None);
    }
    if code != 0 {
        return Err(code);
    }
    if n != 1 || kind == 2 || kind == 12 {
        return Err(INVALID);
    }
    let mut value = 0.0;
    let code = (a.get_att)(id, var, name.as_ptr().cast(), &mut value);
    if code != 0 {
        Err(code)
    } else if !value.is_finite() {
        Err(INVALID)
    } else {
        Ok(Some(value))
    }
}

/// # Safety
/// path is a NUL-terminated shared-library path. Library handles remain live for process lifetime.
#[no_mangle]
pub unsafe extern "C" fn kl_nc_init(path: *const c_char) -> i32 {
    let _guard = LOCK.lock().unwrap_or_else(|e| e.into_inner());
    if API.get().is_some() {
        return 0;
    }
    if path.is_null() {
        return INVALID;
    }
    match Api::load(path) {
        Ok(a) => {
            let _ = API.set(a);
            0
        }
        Err(_) => UNAVAILABLE,
    }
}
/// # Safety
/// path is NUL terminated; output points to one writable i32. mode: 0 read, 1 create NetCDF4.
#[no_mangle]
pub unsafe extern "C" fn kl_nc_open(path: *const c_char, mode: i32, output: *mut i32) -> i32 {
    locked!(a);
    if path.is_null() || output.is_null() {
        return INVALID;
    }
    match mode {
        0 => (a.open)(path, 0, output),
        1 => (a.create)(path, 0x1000 | 0x0004, output),
        _ => INVALID,
    }
}
/// # Safety
/// id is an open handle owned by the caller and closed exactly once.
#[no_mangle]
pub unsafe extern "C" fn kl_nc_close(id: i32) -> i32 {
    locked!(a);
    (a.close)(id)
}
/// # Safety
/// output points to one i32; group is NUL-terminated (empty for root).
#[no_mangle]
pub unsafe extern "C" fn kl_nc_count(id: i32, group: *const c_char, output: *mut i32) -> i32 {
    locked!(a);
    if group.is_null() || output.is_null() {
        return INVALID;
    }
    let mut g = id;
    if !CStr::from_ptr(group).to_bytes().is_empty() {
        check!((a.group)(id, group, &mut g));
    }
    (a.nvars)(g, output)
}
/// # Safety
/// group is NUL-terminated, output holds 257 bytes; index is a valid local variable id.
#[no_mangle]
pub unsafe extern "C" fn kl_nc_name(
    id: i32,
    group: *const c_char,
    index: i32,
    output: *mut c_char,
) -> i32 {
    locked!(a);
    if group.is_null() || output.is_null() {
        return INVALID;
    }
    let mut g = id;
    if !CStr::from_ptr(group).to_bytes().is_empty() {
        check!((a.group)(id, group, &mut g));
    }
    (a.varname)(g, index, output)
}
/// # Safety
/// path is NUL-terminated; dims/kind/natts each address one i32.
#[no_mangle]
pub unsafe extern "C" fn kl_nc_info(
    id: i32,
    path: *const c_char,
    dims: *mut i32,
    kind: *mut i32,
    natts: *mut i32,
) -> i32 {
    locked!(a);
    if dims.is_null() || kind.is_null() || natts.is_null() {
        return INVALID;
    }
    resolved!(a, id, path, g, v);
    (a.var)(
        g,
        v,
        std::ptr::null_mut(),
        kind,
        dims,
        std::ptr::null_mut(),
        natts,
    )
}
/// # Safety
/// name holds 257 bytes, length addresses one usize, axis is within variable rank.
#[no_mangle]
pub unsafe extern "C" fn kl_nc_dimension(
    id: i32,
    path: *const c_char,
    axis: i32,
    name: *mut c_char,
    length: *mut usize,
) -> i32 {
    locked!(a);
    if name.is_null() || length.is_null() {
        return INVALID;
    }
    resolved!(a, id, path, g, v);
    let mut n = 0;
    check!((a.var)(
        g,
        v,
        std::ptr::null_mut(),
        std::ptr::null_mut(),
        &mut n,
        std::ptr::null_mut(),
        std::ptr::null_mut()
    ));
    if axis < 0 || axis >= n {
        return INVALID;
    }
    let mut ids = vec![0; n as usize];
    check!((a.var)(
        g,
        v,
        std::ptr::null_mut(),
        std::ptr::null_mut(),
        std::ptr::null_mut(),
        ids.as_mut_ptr(),
        std::ptr::null_mut()
    ));
    (a.dim)(g, ids[axis as usize], name, length)
}
/// # Safety
/// path is NUL terminated; name holds 257 bytes, kind/length are writable scalars.
#[no_mangle]
pub unsafe extern "C" fn kl_nc_attribute(
    id: i32,
    path: *const c_char,
    index: i32,
    name: *mut c_char,
    kind: *mut i32,
    length: *mut usize,
) -> i32 {
    locked!(a);
    if name.is_null() || kind.is_null() || length.is_null() {
        return INVALID;
    }
    resolved!(a, id, path, g, v);
    check!((a.attname)(g, v, index, name));
    (a.att)(g, v, name, kind, length)
}
/// # Safety
/// name/path NUL terminated, output capacity must match prior attribute inquiry (bytes or doubles).
#[no_mangle]
pub unsafe extern "C" fn kl_nc_get_attribute(
    id: i32,
    path: *const c_char,
    name: *const c_char,
    output: *mut c_void,
    text: i32,
) -> i32 {
    locked!(a);
    if name.is_null() || output.is_null() {
        return INVALID;
    }
    resolved!(a, id, path, g, v);
    if text == 1 {
        (a.get_text)(g, v, name, output.cast())
    } else {
        (a.get_att)(g, v, name, output.cast())
    }
}
/// # Safety
/// path NUL terminated; start/count contain rank values, output holds product(count) doubles.
#[no_mangle]
pub unsafe extern "C" fn kl_nc_read(
    id: i32,
    path: *const c_char,
    start: *const usize,
    count: *const usize,
    output: *mut f64,
) -> i32 {
    locked!(a);
    if start.is_null() || count.is_null() || output.is_null() {
        return INVALID;
    }
    resolved!(a, id, path, g, v);
    let (mut rank, mut kind) = (0, 0);
    check!((a.var)(
        g,
        v,
        std::ptr::null_mut(),
        &mut kind,
        &mut rank,
        std::ptr::null_mut(),
        std::ptr::null_mut()
    ));
    if kind == 2 || kind > 11 {
        return INVALID;
    }
    // Unsigned reinterpretation of packed signed arrays needs explicit implementation.
    let mut flag = [0u8; 16];
    let mut flag_n = 0;
    if (a.att)(
        g,
        v,
        c"_Unsigned".as_ptr(),
        std::ptr::null_mut(),
        &mut flag_n,
    ) == 0
    {
        if flag_n > flag.len() {
            return INVALID;
        }
        check!((a.get_text)(
            g,
            v,
            c"_Unsigned".as_ptr(),
            flag.as_mut_ptr().cast()
        ));
        if flag[..flag_n].eq_ignore_ascii_case(b"true") {
            return INVALID;
        }
    }
    let counts = std::slice::from_raw_parts(count, rank as usize);
    let Some(n) = counts.iter().try_fold(1usize, |a, &b| a.checked_mul(b)) else {
        return INVALID;
    };
    if n > isize::MAX as usize / 8 {
        return INVALID;
    }
    check!((a.get)(g, v, start, count, output));
    let mut missing = Vec::new();
    for name in [c"_FillValue", c"missing_value"] {
        let (mut k, mut len) = (0, 0);
        if (a.att)(g, v, name.as_ptr(), &mut k, &mut len) == 0 {
            if k == 2 || k == 12 || len > 1_000_000 {
                return INVALID;
            }
            let mut vals = vec![0.0; len];
            check!((a.get_att)(g, v, name.as_ptr(), vals.as_mut_ptr()));
            missing.extend(vals);
        }
    }
    let (mut nofill, mut raw) = (0, [0u64; 2]);
    if (a.fill)(g, v, &mut nofill, raw.as_mut_ptr().cast()) == 0 && nofill == 0 {
        let p = raw.as_ptr();
        let fill = match kind {
            1 => *p.cast::<i8>() as f64,
            3 => *p.cast::<i16>() as f64,
            4 => *p.cast::<i32>() as f64,
            5 => *p.cast::<f32>() as f64,
            6 => *p.cast::<f64>(),
            7 => *p.cast::<u8>() as f64,
            8 => *p.cast::<u16>() as f64,
            9 => *p.cast::<u32>() as f64,
            10 => *p.cast::<i64>() as f64,
            11 => *p as f64,
            _ => return INVALID,
        };
        missing.push(fill);
    }
    let scale = match scalar(a, g, v, b"scale_factor\0") {
        Ok(v) => v.unwrap_or(1.0),
        Err(c) => return c,
    };
    let offset = match scalar(a, g, v, b"add_offset\0") {
        Ok(v) => v.unwrap_or(0.0),
        Err(c) => return c,
    };
    let mut lower = match scalar(a, g, v, b"valid_min\0") {
        Ok(v) => v.unwrap_or(f64::NEG_INFINITY),
        Err(c) => return c,
    };
    let mut upper = match scalar(a, g, v, b"valid_max\0") {
        Ok(v) => v.unwrap_or(f64::INFINITY),
        Err(c) => return c,
    };
    let (mut range_type, mut range_len) = (0, 0);
    let code = (a.att)(
        g,
        v,
        c"valid_range".as_ptr(),
        &mut range_type,
        &mut range_len,
    );
    if code == 0 {
        if range_len != 2 || range_type == 2 || range_type == 12 {
            return INVALID;
        }
        let mut range = [0.0; 2];
        check!((a.get_att)(
            g,
            v,
            c"valid_range".as_ptr(),
            range.as_mut_ptr()
        ));
        if !range.iter().all(|x| x.is_finite()) || range[0] > range[1] {
            return INVALID;
        }
        lower = range[0];
        upper = range[1];
    } else if code != -43 {
        return code;
    }
    for x in std::slice::from_raw_parts_mut(output, n) {
        *x = if !x.is_finite() || missing.contains(x) || *x < lower || *x > upper {
            f64::NAN
        } else {
            *x * scale + offset
        };
    }

    0
}
/// # Safety
/// name is NUL-terminated; length>0. Existing dimensions must match exactly.
#[no_mangle]
pub unsafe extern "C" fn kl_nc_def_dim(id: i32, name: *const c_char, length: usize) -> i32 {
    locked!(a);
    if name.is_null() || length == 0 {
        return INVALID;
    }
    let code = (a.redef)(id);
    if code != 0 && code != -39 {
        return code;
    }
    let mut dim = 0;
    if (a.dimid)(id, name, &mut dim) == 0 {
        let mut old = 0;
        check!((a.dim)(id, dim, std::ptr::null_mut(), &mut old));
        return if old == length { 0 } else { INVALID };
    }
    (a.def_dim)(id, name, length, &mut dim)
}
/// # Safety
/// name/dimensions NUL terminated. dimensions is comma-separated; rank<=32.
#[no_mangle]
pub unsafe extern "C" fn kl_nc_def_var(
    id: i32,
    name: *const c_char,
    dimensions: *const c_char,
    kind: i32,
    compression: i32,
) -> i32 {
    locked!(a);
    if name.is_null()
        || dimensions.is_null()
        || ![3, 5, 6].contains(&kind)
        || !(0..=9).contains(&compression)
    {
        return INVALID;
    }
    let code = (a.redef)(id);
    if code != 0 && code != -39 {
        return code;
    }
    let mut ids = Vec::new();
    let dims = CStr::from_ptr(dimensions).to_bytes();
    if !dims.is_empty() {
        for d in dims.split(|&b| b == b',') {
            let Ok(s) = CString::new(d) else {
                return INVALID;
            };
            let mut dim = 0;
            check!((a.dimid)(id, s.as_ptr(), &mut dim));
            ids.push(dim);
        }
    }
    if ids.len() > 32 {
        return INVALID;
    }
    let mut var = 0;
    check!((a.def_var)(
        id,
        name,
        kind,
        ids.len() as i32,
        ids.as_ptr(),
        &mut var
    ));
    if kind == 5 || kind == 6 {
        check!((a.put_att)(
            id,
            var,
            c"_FillValue".as_ptr(),
            kind,
            1,
            &f64::NAN
        ));
    }
    if compression > 0 {
        check!((a.deflate)(id, var, 1, 1, compression));
    }
    0
}
/// # Safety
/// NUL-terminated variable/attribute names. output contains length bytes (text=1) or doubles.
#[no_mangle]
pub unsafe extern "C" fn kl_nc_put_attribute(
    id: i32,
    path: *const c_char,
    name: *const c_char,
    values: *const c_void,
    length: usize,
    text: i32,
) -> i32 {
    locked!(a);
    if name.is_null() || values.is_null() {
        return INVALID;
    }
    resolved!(a, id, path, g, v);
    let code = (a.redef)(g);
    if code != 0 && code != -39 {
        return code;
    }
    if text == 1 {
        (a.put_text)(g, v, name, length, values.cast())
    } else {
        let kind = if CStr::from_ptr(name).to_bytes() == b"_FillValue" {
            let mut k = 0;
            check!((a.var)(
                g,
                v,
                std::ptr::null_mut(),
                &mut k,
                std::ptr::null_mut(),
                std::ptr::null_mut(),
                std::ptr::null_mut()
            ));
            k
        } else {
            6
        };
        (a.put_att)(g, v, name, kind, length, values.cast())
    }
}
/// # Safety
/// Names NUL terminated; start/count have rank entries, values has product(count) doubles.
#[no_mangle]
pub unsafe extern "C" fn kl_nc_write(
    id: i32,
    path: *const c_char,
    start: *const usize,
    count: *const usize,
    values: *const f64,
) -> i32 {
    locked!(a);
    if start.is_null() || count.is_null() || values.is_null() {
        return INVALID;
    }
    resolved!(a, id, path, g, v);
    let code = (a.enddef)(g);
    if code != 0 && code != -38 {
        return code;
    }
    (a.put)(g, v, start, count, values)
}
/// # Safety
/// Returns a static NUL-terminated description, valid until process exit.
#[no_mangle]
pub unsafe extern "C" fn kl_nc_error(code: i32) -> *const c_char {
    if code == INVALID {
        return c"Unsupported NetCDF operation, encoding, dimensions or type".as_ptr();
    }
    if code == UNAVAILABLE {
        return c"Native libnetcdf unavailable: set KLIMAPY_NETCDF_LIBRARY to its shared-library path".as_ptr();
    }
    match API.get() {
        Some(a) => (a.error)(code),
        None => c"libnetcdf not initialized".as_ptr(),
    }
}

/// # Safety
/// Names are NUL terminated; length points to a usize; output holds capacity bytes.
/// A null output queries the byte length of the indexed NC_STRING attribute value.
#[no_mangle]
pub unsafe extern "C" fn kl_nc_string_attribute(
    id: i32,
    path: *const c_char,
    name: *const c_char,
    index: usize,
    output: *mut c_char,
    capacity: usize,
    length: *mut usize,
) -> i32 {
    locked!(a);
    if name.is_null() || length.is_null() {
        return INVALID;
    }
    resolved!(a, id, path, g, v);
    let (mut kind, mut n) = (0, 0);
    check!((a.att)(g, v, name, &mut kind, &mut n));
    if kind != 12 || n > 1_000_000 || index >= n {
        return INVALID;
    }
    let mut strings = vec![std::ptr::null_mut(); n];
    check!((a.get_strings)(g, v, name, strings.as_mut_ptr()));
    let bytes = if strings[index].is_null() {
        &[][..]
    } else {
        CStr::from_ptr(strings[index]).to_bytes()
    };
    *length = bytes.len();
    let code = if output.is_null() {
        0
    } else if capacity < bytes.len() {
        INVALID
    } else {
        std::ptr::copy_nonoverlapping(bytes.as_ptr(), output.cast(), bytes.len());
        0
    };
    let cleanup = (a.free_strings)(n, strings.as_mut_ptr());
    if code != 0 {
        code
    } else {
        cleanup
    }
}
