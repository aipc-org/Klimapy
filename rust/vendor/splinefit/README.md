# Vendored pure-Rust FITPACK

Source: splinefit 0.4.1, `src/dierckx.rs`, with the single control-flow patch described below.
Upstream: https://github.com/harbik/splinefit
Package: https://crates.io/crates/splinefit/0.4.1
License: MIT OR Apache-2.0; both notices are retained here.

Crate archive SHA256: bf5bbc8791000d76d15c2fc2116a86c39fa81e72caf3794085833edc48a5506c
Original source SHA256: fcb60a7cd5c8abf9805c5e54237c34a60f05cb24476dcc2f35dff771476fa24c

Only the standalone numerical engine is included, with no crate dependencies,
Python bindings, Fortran build or online build step. Klimapy calls curfit/splev
from its Rust transfer-function adapter. This external source is not attributed
to Klimapy's contributors. Keep upstream notices and record any future patches.

## Local patch

Restore the FITPACK return before Part 2 when Part 1 has exhausted knot storage,
returned an interpolation/polynomial result, or already met the smoothing target.
The upstream Rust translation otherwise enters p-finding with a positive residual
and can overwrite the storage status `ier=1`, preventing workspace continuation.
The adapter reproduces UnivariateSpline's initial `max(m/2, 2*(k+1))` workspace,
then enlarges it on `ier=1` and restarts with fresh workspace, matching the
SciPy 1.18.1 UnivariateSpline wrapper used by Test1. Older SciPy continuation
policies may choose a different admissible knot sequence. This is exercised by CN05.1 BC-vs-SciPy comparisons.
The original source hash above is retained for reproducible patch inspection.
