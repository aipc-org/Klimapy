# Native optimization, 1.3.3

This release keeps the existing Rust engine, native NetCDF C runtime and NumPy-only
Python dependency boundary. C++/Fortran libraries are permitted when measurement
and distribution support justify them. No production SciPy adapter was added.

## Implemented

- `Variable.read(key=..., dtype="float32")`, `read_field(..., dtype="float32")`,
  `FileCollection.iter_blocks(..., dtype="float32")` and `read(dtype="float32")`
  expose explicit decoded float32 reads. Defaults remain float64. Source float32
  is read directly through `nc_get_vara_float`; validity and packing are evaluated
  in double precision before one final cast. Other storage types use a temporary
  double buffer for correctness. Coordinates and time bounds remain float64.
- Collection iterators open each file once, reuse variable metadata, and copy
  validated spatial coordinates/attribute dictionaries into output Fields.
  Each live iterator retains at most one file. Exhaustion, exceptions or explicit
  generator `close()` release it; callers stopping early should close generators.
- A balanced three-dimensional index replaces exhaustive spherical nearest-point
  searches, retaining squared chord distance and first row-major ownership on
  equal computed distances. Conservative plans binary-search ordered bounds to
  enumerate only candidate overlaps. Coverage and second-order moments retain
  the existing definitions.
- EOF constructs the scaled solver matrix directly, eliminating one full
  time-by-valid-space anomaly buffer. Full SVD returns its already-owned output
  arrays without another Python copy. Computation still uses a complete thin SVD.
- Harmonic smoothing and drought reuse per-call workspaces across cells/months.
  No rolling-sum order, fit definition or missing-value rule changes.

## Measurements and decisions

Raw results: `benchmarks/results/optimization-2026-11-20.json`.
Five warmed runs, median, Linux x86-64, 20 logical CPUs, OpenBLAS/OMP threads=1.
Native comparisons load the preserved 1.3.2 library and current library through
common wrappers. Timings exclude process startup. They are synthetic measurements,
not full CN05.1 file or dataset speedups.

| Case | Before | After | Interpretation |
| --- | ---: | ---: | --- |
| Nearest plan, 180×240 → 45×60 | 967.54 ms | 5.80 ms | 166.9× plan construction |
| Conservative plan, same grids | 5.35 ms | 0.74 ms | 7.22× plan construction |
| Collection, 16 blocks | 39.77 ms | 24.96 ms | 1.59×; prior per-block reopen vs reuse |
| Synthetic file read, float64 vs float32 | 34.08 ms | 23.16 ms | 1.47×; output 42.19 vs 21.09 MiB |
| File read + mean, float64 vs float32 | 27.55 ms | 23.20 ms | 1.19×; equal double-precision sums/means |
| Harmonic smoothing, 366×2500 | 15.29 ms | 12.72 ms | 1.20× |
| Drought, 600×900, scale=3 | 1084.32 ms | 1083.34 ms | effectively unchanged; bitwise equal outputs/diagnostics |
| EOF, 730×384, 10 modes | 46.78 ms | 46.25 ms | effectively unchanged |

Separate processes on a 128×20000 EOF matrix measured peak RSS of 141560 KiB
before and 120812 KiB after (~14.7% lower); leading singular-value sums agree.
The removed buffer itself is 19.53 MiB. RSS includes Python/NumPy and the solver.
Reproduce using `benchmarks/optimization_memory.py [baseline-library]` in separate
Test processes. For timings use `benchmarks/optimization.py --baseline-library
/path/to/baseline.so --output /tmp/result.json` with `PYTHONPATH=src` and thread
variables set before Python starts.

NumPy's native LAPACK SVD reference took 37.81 ms versus current faer 45.32 ms
on 730×384; maximum singular-value difference was 2.92e-13. This modest single-shape
advantage does not establish the benefit or cross-platform cost of replacing the
solver. A partial or randomized solver also needs accuracy/convergence policy and
independent distribution validation. Those remain follow-up work; the release
retains exact dense semantics and does not claim truncated-solver scaling.

Persistent sparse weight files, alternative sparse storage, automatic chunk/cache
selection, broader float32 kernels and parallel batch scans are evaluated follow-ups,
not implemented features. Plan construction now has large demonstrated gains;
existing immutable plan reuse already avoids repeated construction. Automatic I/O
or thread policies need compressed-file and memory-budget benchmarks. Shared
workspaces yield a smaller, deterministic change without altering numerical order.

## Acceptance

Source: 117 native tests; 130 independent Test/Test1 checks on the documented
CN05.1 2019–2020, 6×8 spatial tile. Added references verify collection float32
values and means independently. No full-grid/39 GB regression is claimed.
Installed-wheel and public-release status are recorded in the taskbook.
EOF/constant/overflow/missing masks, packed and default-fill reads, spherical
nearest versus brute force, irregular conservative overlap versus explicit area
integration, and iterator ownership are covered by native tests.
