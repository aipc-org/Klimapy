"""Run native CN05.1 checks in Test and independent references in Test1.

No source data or result arrays enter Git. The default region is a documented
6x8 land tile for 2019-2020; this is a real-data regression, not a full-grid audit.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def native(data, output, installed=False):
    from test_environment import verify

    verify(installed=installed)
    import numpy as np
    from klimapy.native import (
        Field,
        read_field,
        detrend,
        runs,
        grouped_std,
        seasonal_anomaly,
        annual_variability,
        svd,
        eof,
        SpatialPlan,
    )
    from klimapy.PrecipitationVariability import compute_precip_variability

    fields = [
        read_field(
            data / f"逐日/Pre/CN05.1_Pre_{year}_daily_025x025.nc",
            "pre",
            indexers={"lat": slice(68, 74), "lon": slice(155, 163)},
        )
        for year in (2019, 2020)
    ]
    metadata = []
    for year, f in zip((2019, 2020), fields):
        source = data / f"逐日/Pre/CN05.1_Pre_{year}_daily_025x025.nc"
        digest = hashlib.sha256()
        with source.open("rb") as stream:
            for chunk in iter(lambda: stream.read(8 * 1024**2), b""):
                digest.update(chunk)
        metadata.append(
            {
                "path": str(source.resolve()),
                "sha256": digest.hexdigest(),
                "variable_attrs": f.attrs,
            }
        )
    values = np.concatenate([f.values for f in fields])
    times = np.concatenate([f.time.dates()[1] for f in fields])
    coordinate_attrs = {
        **fields[0].coordinate_attrs,
        "time": {"units": "days since 0001-01-01", "calendar": "proleptic_gregorian"},
    }
    field = Field(
        values,
        fields[0].dims,
        {**fields[0].coords, "time": times},
        {"units": "mm/day"},
        "pre",
        coordinate_attrs,
    )
    years, days, _ = field.time.labels()
    selected = years == 2019
    unique = np.unique(years)
    detrended = detrend(values)
    anomaly = seasonal_anomaly(values, days, selected)
    std, _ = grouped_std(values, years)
    annual, _ = annual_variability(values, years, days, baseline_years=(2019, 2020))
    high = compute_precip_variability(
        field, baseline_years=(2019, 2020), spatial_chunk_size=3
    )
    np.testing.assert_allclose(high.values, annual, rtol=1e-12, atol=1e-12)
    _, singular, _ = svd(values.reshape(len(values), -1))
    modes = eof(values, lat=field.coords["lat"], n_modes=3)
    target_lat = (field.coords["lat"][:-1] + field.coords["lat"][1:]) / 2
    target_lon = (field.coords["lon"][:-1] + field.coords["lon"][1:]) / 2
    with SpatialPlan(
        field.coords["lat"], field.coords["lon"], target_lat, target_lon, bilinear=True
    ) as plan:
        interpolated = plan.apply(values)
    dry = np.stack([runs(values[years == year] < 1) for year in unique])
    output.mkdir(parents=True, exist_ok=True)
    from cn05_migration_checks import native_checks

    extra = native_checks(data, output, field, metadata)
    np.savez_compressed(
        output / "native.npz",
        **extra,
        values=values,
        years=years,
        days=days,
        detrend=detrended,
        anomaly=anomaly,
        std=std,
        annual=annual,
        singular=singular,
        eigen=modes.eigenvalues,
        fraction=modes.variance_fraction,
        reconstruction=modes.reconstruct(),
        interpolated=interpolated,
        dry=dry,
    )
    report = {
        "scope": "2019-2020, lat indices 68:74, lon indices 155:163",
        "shape": list(values.shape),
        "units": "mm/day",
        "units_source": "explicit user-side convention; CN05.1 long_name states precipitation,mm/day; units attribute absent",
        "inputs": metadata,
        "native_python": sys.executable,
        "native_package": __import__("klimapy").__file__,
        "backend": __import__("klimapy").backend_info(),
        "coordinate_attrs": fields[0].coordinate_attrs,
        "git_head": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "git_status": subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=ROOT, text=True
        ).splitlines(),
    }
    (output / "provenance.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def reference(data, output):
    if Path(sys.prefix).name != "Test1":
        raise RuntimeError("Reference comparisons must use Test1")
    import importlib.metadata
    import numpy as np
    import scipy.linalg
    import scipy.signal
    from scipy.interpolate import RegularGridInterpolator
    import xarray as xr
    from eofs.standard import Eof
    import xclim.indices as xci

    # Klimapy is intentionally not imported in this process.
    pieces = []
    for year in (2019, 2020):
        with xr.open_dataset(
            data / f"逐日/Pre/CN05.1_Pre_{year}_daily_025x025.nc", engine="netcdf4"
        ) as ds:
            pieces.append(ds["pre"].isel(lat=slice(68, 74), lon=slice(155, 163)).load())
    field = xr.concat(pieces, dim="time").astype("float64")
    field.attrs["units"] = "mm/day"
    values = field.values
    years = field.time.dt.year.values
    monthdays = field.time.dt.strftime("%m-%d")
    baseline = field.isel(time=years == 2019)
    climate = baseline.groupby(baseline.time.dt.strftime("%m-%d")).mean("time")
    # Explicit absent leap-day baseline yields NaN rather than interpolation.
    climate = climate.reindex(strftime=np.unique(monthdays.values))
    anomaly = values - climate.sel(strftime=monthdays).values
    full_climate = field.groupby(monthdays).mean("time")
    full_anomaly = values - full_climate.sel(strftime=monthdays).values
    detrended = scipy.signal.detrend(values, axis=0, type="linear")
    annual_detrended = scipy.signal.detrend(full_anomaly, axis=0, type="linear")
    unique = np.unique(years)
    annual = np.stack(
        [np.std(annual_detrended[years == y], axis=0, ddof=0) for y in unique]
    )
    std = np.stack([np.std(values[years == y], axis=0, ddof=0) for y in unique])
    weights = np.sqrt(np.cos(np.deg2rad(field.lat.values)))[:, None]
    solver = Eof(values, weights=weights, center=True, ddof=1)
    reconstruction = solver.reconstructedField(3) + values.mean(axis=0)
    yy, xx = np.meshgrid(
        (field.lat.values[:-1] + field.lat.values[1:]) / 2,
        (field.lon.values[:-1] + field.lon.values[1:]) / 2,
        indexing="ij",
    )
    points = np.column_stack([yy.ravel(), xx.ravel()])
    interpolation = RegularGridInterpolator(
        (field.lat.values, field.lon.values), np.moveaxis(values, 0, -1)
    )(points)
    interpolation = np.moveaxis(interpolation.reshape(*yy.shape, len(values)), -1, 0)
    expected = {
        "values": values,
        "detrend": detrended,
        "anomaly": anomaly,
        "std": std,
        "annual": annual,
        "singular": scipy.linalg.svdvals(values.reshape(len(values), -1)),
        "eigen": solver.eigenvalues(neigs=3),
        "fraction": solver.varianceFraction(neigs=3),
        "reconstruction": reconstruction,
        "interpolated": interpolation,
        "dry": xci.maximum_consecutive_dry_days(
            field, thresh="1 mm/day", freq="YS"
        ).values,
    }
    from cn05_migration_checks import reference_checks

    expected.update(reference_checks(data, output, field))
    results = []
    with np.load(output / "native.npz") as actual:
        for name, expected_values in expected.items():
            observed = actual[name]
            if observed.shape != expected_values.shape:
                raise AssertionError(
                    f"{name}: shape differs: {observed.shape} != {expected_values.shape}"
                )
            # NetCDF SD outputs and intermediate harmonics are Float32. Bound
            # their accumulated rounding explicitly; double kernels stay strict.
            rtol = atol = (
                float(8 * np.finfo(np.float32).eps) if name.startswith("sd_") else 1e-8
            )
            np.testing.assert_allclose(
                observed,
                expected_values,
                rtol=rtol,
                atol=atol,
                equal_nan=True,
                err_msg=name,
            )
            finite = np.isfinite(observed) & np.isfinite(expected_values)
            error = (
                float(
                    np.max(
                        np.abs(
                            observed[finite].astype(float)
                            - expected_values[finite].astype(float)
                        )
                    )
                )
                if finite.any()
                else None
            )
            results.append(
                {
                    "check": name,
                    "status": "passed",
                    "max_abs_error": error,
                    "shape": list(observed.shape),
                    "rtol": rtol,
                    "atol": atol,
                }
            )
    report = {
        "reference_python": sys.executable,
        "versions": {
            name: importlib.metadata.version(name)
            for name in ["numpy", "scipy", "xarray", "xclim", "eofs", "netCDF4"]
        },
        "checks": results,
        "checks_run": len(results),
        "scope": "CN05.1 spatial tile covering migrated production features; not a full-grid/full-dataset audit",
    }
    if "klimapy" in sys.modules:
        raise RuntimeError("Reference process unexpectedly imported Klimapy")
    (output / "comparison.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=ROOT / "data/CN05.1/汇总")
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/cn05-comparison")
    parser.add_argument("--stage", choices=["native", "reference"])
    parser.add_argument("--installed", action="store_true")
    args = parser.parse_args()
    if args.stage == "native":
        native(args.data.resolve(), args.output.resolve(), args.installed)
    elif args.stage == "reference":
        reference(args.data.resolve(), args.output.resolve())
    else:
        args.output.mkdir(parents=True, exist_ok=True)
        args.output = Path(tempfile.mkdtemp(prefix="run-", dir=args.output.resolve()))
        print("Real-data report directory:", args.output, flush=True)
        conda = os.environ.get("CONDA_EXE", "/opt/miniconda3/bin/conda")
        for environment, stage in [("Test", "native"), ("Test1", "reference")]:
            env = dict(
                os.environ,
                PYTHONNOUSERSITE="1",
                PYTHONPATH=str(ROOT / "src")
                if stage == "native" and not args.installed
                else "",
                MPLCONFIGDIR="/tmp/klimapy-comparison-mpl",
                NUMBA_CACHE_DIR="/tmp/klimapy-comparison-numba",
            )
            subprocess.run(
                [
                    conda,
                    "run",
                    "-n",
                    environment,
                    "python",
                    str(Path(__file__).resolve()),
                    "--stage",
                    stage,
                    "--data",
                    str(args.data.resolve()),
                    "--output",
                    str(args.output.resolve()),
                    *(["--installed"] if args.installed else []),
                ],
                check=True,
                env=env,
                cwd=ROOT,
            )


if __name__ == "__main__":
    main()
