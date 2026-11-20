"""Additional real-data checks used by compare_cn05's separated environments."""

import json
import sys
from pathlib import Path

import numpy as np


def native_checks(data, output, precipitation, provenance=None):
    from klimapy.BCSD.BiasCorrection import BC, close_result
    from klimapy.BCSD.SpatialDownscaling import SD
    from klimapy.Interpolation import interpolate
    from klimapy.Supporting_Tools import calculate_spatial_mean, nc_to_tiff

    from klimapy import ETCCDI as et
    from klimapy.native import Dataset, Field, read_field
    from klimapy.native.correction import Transfer, smooth
    from klimapy.native.geometry import polygon_mask

    results = {}
    # Exercise direct float32 accumulation on the documented real-data tile.
    from klimapy._backends.rust import climate_accumulate, climate_mean
    values32 = np.asarray(precipitation.values, dtype=np.float32)
    sums = np.zeros((1, *values32.shape[1:]), dtype=np.float64)
    counts = np.zeros(sums.shape, dtype=np.int32)
    for begin in range(0, len(values32), 37):
        block = values32[begin:begin + 37]
        climate_accumulate(block, np.zeros(len(block), dtype=np.intp), sums, counts)
    results["time_mean_float32"] = climate_mean(sums, counts)[0]
    from klimapy.native import open_collection
    from klimapy.statistics import aggregate, evaluate
    from klimapy.statistics import ensemble_statistics, event_catalog

    ensemble = ensemble_statistics({
        str(i): Field(precipitation.values + i, precipitation.dims,
                      precipitation.coords, precipitation.attrs,
                      precipitation.name, precipitation.coordinate_attrs)
        for i in (0, 2, 8)
    })
    for key in ("mean", "median", "p05", "p95"):
        results["ensemble_cn05_" + key] = ensemble[key].values
    records = event_catalog(precipitation, threshold=1, min_duration=2)["records"]
    results["events_cn05"] = np.asarray([
        [*r["grid_indices"].values(), r["start_index"], r["end_index"],
         r["active_steps"], r["intensity_sum"]] for r in records
    ], dtype=float).reshape(-1, 6)

    pieces = []
    for number, selection in enumerate((slice(0, 365), slice(365, None))):
        path = output / f"collection-part-{number}.nc"
        precipitation.isel(time=selection).to_netcdf(path)
        pieces.append(path)
    collection = open_collection(pieces[::-1], precipitation.name)
    for frequency in ("monthly", "seasonal", "annual"):
        results["aggregate_" + frequency] = aggregate(
            collection, frequency=frequency, time_chunk_size=37
        ).values
    results["collection_values"] = collection.read().values
    results["collection_float32_values"] = collection.read(dtype="float32").values
    sums32 = np.zeros((1, *precipitation.shape[1:]), dtype=np.float64)
    counts32 = np.zeros(sums32.shape, dtype=np.int32)
    for field32 in collection.iter_blocks(37, dtype="float32"):
        climate_accumulate(field32.values, np.zeros(len(field32.values), dtype=np.intp), sums32, counts32)
    results["collection_float32_mean"] = climate_mean(sums32, counts32)[0]
    model = Field(
        precipitation.values * 0.8 + 1,
        precipitation.dims,
        precipitation.coords,
        precipitation.attrs,
        precipitation.name,
        precipitation.coordinate_attrs,
    )
    for name, field in evaluate(model, precipitation).items():
        results["evaluation_" + name] = field.values
    monthly = aggregate(precipitation, frequency="monthly")
    results["monthly_to_annual"] = aggregate(
        monthly, frequency="annual", input_frequency="monthly"
    ).values
    results["monthly_to_seasonal"] = aggregate(
        monthly, frequency="seasonal", input_frequency="monthly"
    ).values
    from klimapy.native import quality_report
    from klimapy.recipe import run_recipe

    qc = quality_report(collection, valid_min=0, valid_max=100, time_chunk_size=41)
    results["qc_summary"] = np.asarray(
        [
            qc[k] if qc[k] is not None else np.nan
            for k in (
                "finite",
                "nan",
                "infinite",
                "below_valid_min",
                "above_valid_max",
                "negative",
                "minimum",
                "maximum",
                "finite_fraction",
            )
        ]
    )
    results["monthly_cf_bounds"] = monthly.time_bounds
    plan = {
        "schema_version": 1,
        "output_dir": "recipe-result",
        "steps": [
            {
                "id": "raw",
                "operation": "load",
                "paths": [p.name for p in pieces],
                "variable": precipitation.name,
            },
            {
                "id": "monthly",
                "operation": "aggregate",
                "source": "raw",
                "parameters": {"frequency": "monthly"},
            },
        ],
    }
    config = output / "recipe.json"
    config.write_text(json.dumps(plan), encoding="utf-8")
    record = run_recipe(config)
    if record["status"] != "passed" or record["steps"][1]["parents"] != ["raw"]:
        raise AssertionError("Recipe provenance failed")
    results["recipe_monthly"] = read_field(
        output / "recipe-result/monthly-value.nc"
    ).values
    lat = precipitation.coords["lat"]
    lon = precipitation.coords["lon"]
    # Fixture areas on the CN05 0.25-degree spherical grid, not a production
    # area-generation algorithm; Test1 independently reconstructs the weights.
    areas = (
        6371000.0**2
        * np.deg2rad(0.25)
        * (np.sin(np.deg2rad(lat + 0.125)) - np.sin(np.deg2rad(lat - 0.125)))[:, None]
        * np.ones((1, len(lon)))
    )
    area = Field(areas, ("lat", "lon"), {"lat": lat, "lon": lon}, {"units": "m2"})
    for name, field in evaluate(
        model, precipitation, dims=("lat", "lon"), cell_area=area
    ).items():
        results["area_evaluation_" + name] = field.values
    from klimapy.native.field import _date, month_lengths
    from klimapy.statistics import spei, spi

    source = data / "逐月/Pre/CN05.1_Pre_1961_2018_month_025x025.nc"
    monthly_precip = read_field(
        source, "pre", indexers={"lat": slice(68, 74), "lon": slice(155, 163)}
    )
    dates = np.asarray(
        [
            _date(int(v), monthly_precip.time.calendar)
            for v in monthly_precip.time.serial()
        ]
    )
    lengths = np.asarray(
        [
            month_lengths(int(y), monthly_precip.time.calendar)[int(m) - 1]
            for y, m, _ in dates
        ]
    )
    # Explicit regression-fixture unit interpretation from provider long_name:
    # monthly mean mm/day rates -> calendar-month mm amounts. Production SPI
    # never guesses these units from names.
    monthly_precip.values = monthly_precip.values * lengths[:, None, None]
    # Provider bounds end at the start of the final day rather than next-month
    # start. This fixture explicitly treats the labelled provider product as
    # complete monthly means; do not edit the source file or silently normalize
    # arbitrary user bounds in production.
    monthly_precip.time_bounds = None
    monthly_precip.coordinate_attrs["time"].pop("bounds", None)
    monthly_precip.attrs = {
        "units": "mm",
        "source_interpretation": "provider long_name mm/day, monthly mean times calendar days",
    }
    if provenance is not None:
        import hashlib

        digest = hashlib.sha256()
        with source.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        provenance.append(
            {
                "path": str(source.resolve()),
                "sha256": digest.hexdigest(),
                "explicit_unit_interpretation": monthly_precip.attrs[
                    "source_interpretation"
                ],
            }
        )
    results["spi3_cn05"] = spi(
        monthly_precip, scale=3, baseline_years=(1981, 2010)
    ).values
    results["spi12_cn05"] = spi(
        monthly_precip, scale=12, baseline_years=(1981, 2010)
    ).values
    q = (np.arange(40) + 0.5) / 40
    balance = np.repeat(-30 + 20 * (q / (1 - q)) ** 0.5, 12)
    coords = {
        "time": [(1981 + i // 12) * 10000 + (i % 12 + 1) * 100 + 15 for i in range(480)]
    }
    rainfall = Field(
        100 + balance,
        ("time",),
        coords,
        {"units": "mm"},
        "pr",
        {"time": {"calendar": "proleptic_gregorian"}},
    )
    demand = Field(
        np.full(480, 100.0),
        ("time",),
        coords,
        {"units": "mm", "method": "synthetic_constant_PET_for_validation"},
        "pet",
        rainfall.coordinate_attrs,
    )
    results["spei3_synthetic_pet"] = spei(
        rainfall, demand, scale=3, baseline_years=(1981, 2020)
    ).values
    names = ["PRCPTOT", "R1mm_days", "SDII", "RX1DAY", "RX5DAY", "CDD", "CWD"]
    names += [
        f"R{n}mm_{kind}"
        for n in (10, 20, 25, 50, 90, 95, 99)
        for kind in ("precipitation", "days", "intensity", "ratio")
    ]
    for name in names:
        kwargs = (
            {"baseline_years": (2019, 2020)}
            if name.startswith(("R90mm", "R95mm", "R99mm"))
            else {}
        )
        results["index_" + name] = getattr(et, name)(precipitation, **kwargs).values
    results["rx5_monthly"] = et.RX5DAY(precipitation, freq="MS").values
    temperature = {}
    for directory, variable, key in [
        ("Tmax", "tmax", "tx"),
        ("Tmin", "tmin", "tn"),
        ("Tm", "tm", "tg"),
    ]:
        pieces = [
            read_field(
                data / f"逐日/{directory}/CN05.1_{directory}_{year}_daily_025x025.nc",
                variable,
                indexers={"lat": slice(68, 74), "lon": slice(155, 163)},
            )
            for year in (2020, 2021)
        ]
        if provenance is not None:
            import hashlib

            for year, piece in zip((2020, 2021), pieces):
                path = (
                    data
                    / f"逐日/{directory}/CN05.1_{directory}_{year}_daily_025x025.nc"
                )
                digest = hashlib.sha256()
                with path.open("rb") as stream:
                    for block in iter(lambda: stream.read(8 * 1024**2), b""):
                        digest.update(block)
                provenance.append(
                    {
                        "path": str(path.resolve()),
                        "sha256": digest.hexdigest(),
                        "variable_attrs": piece.attrs,
                        "coordinate_attrs": piece.coordinate_attrs,
                        "explicit_units_for_comparison": "degC",
                    }
                )
        times = np.concatenate([p.time.dates()[1] for p in pieces])
        temperature[key] = Field(
            np.concatenate([p.values for p in pieces]),
            ("time", "lat", "lon"),
            {**pieces[0].coords, "time": times},
            {"units": "degC"},
            variable,
            {
                "time": {
                    "units": "days since 0001-01-01",
                    "calendar": "proleptic_gregorian",
                }
            },
        )
    for name, key in [
        ("FD", "tn"),
        ("TR", "tn"),
        ("SU", "tx"),
        ("ID", "tx"),
        ("TXx", "tx"),
        ("TXn", "tx"),
        ("TNx", "tn"),
        ("TNn", "tn"),
    ]:
        results["temp_" + name] = getattr(et, name)(temperature[key]).values
    results["temp_DTR"] = et.DTR(temperature["tx"], temperature["tn"]).values
    results["temp_GSL"] = et.GSL(temperature["tg"]).values
    results["temp_GSL_SH"] = et.GSL(temperature["tg"], "SH").values
    for name, key in [
        ("TX10p", "tx"),
        ("TX90p", "tx"),
        ("TN10p", "tn"),
        ("TN90p", "tn"),
    ]:
        for bootstrap in (False, True):
            results[f"temp_{name}_bootstrap_{bootstrap}"] = getattr(et, name)(
                temperature[key], (2020, 2021), bootstrap=bootstrap
            ).values
    results["temp_WSDI"] = et.WSDI(temperature["tx"], (2020, 2021)).values
    results["temp_CSDI"] = et.CSDI(temperature["tn"], (2020, 2021)).values
    lat, lon = precipitation.coords["lat"], precipitation.coords["lon"]
    from klimapy.downscaling.bcsd import reconstruct_minimum, temperature_range
    from klimapy.native import Downscaler

    temperature_obs = temperature["tg"]
    hist_temp = temperature_obs.isel(time=slice(0, 366))
    future_temp = temperature_obs.isel(time=slice(366, None))
    hist_model = Field(
        hist_temp.values - 2,
        hist_temp.dims,
        hist_temp.coords,
        hist_temp.attrs,
        "tas",
        hist_temp.coordinate_attrs,
    )
    future_model = Field(
        future_temp.values - 2,
        future_temp.dims,
        future_temp.coords,
        future_temp.attrs,
        "tas",
        future_temp.coordinate_attrs,
    )
    temp_correction = BC(
        temperature_obs,
        hist_model,
        future_model,
        "temperature",
        2020,
        2020,
        variable="tas",
        strict=True,
    )
    try:
        results["temperature_bc_history"] = temp_correction[
            "corrected_hist_tas"
        ].values.copy()
        results["temperature_bc_future"] = temp_correction[
            "corrected_fut_tas"
        ].values.copy()
        scaled = SD(
            temperature_obs,
            temp_correction,
            output / "temperature-sd",
            2020,
            2020,
            strict=True,
        )
        results["temperature_sd_history"] = read_field(
            scaled["hist_bcsd_path"], "tas"
        ).values
        results["temperature_sd_future"] = read_field(
            scaled["fut_bcsd_path"], "tas"
        ).values
    finally:
        close_result(temp_correction, remove_work_files=True)
    dtr = temperature_range(temperature["tx"], temperature["tn"])
    results["temperature_dtr"] = dtr.values
    results["temperature_reconstructed_minimum"] = reconstruct_minimum(
        temperature["tx"], dtr
    ).values
    climate = smooth(temperature_obs.values[:366], nonnegative=False)
    coarse = climate[:, ::2, ::2]
    block = temperature_obs.values[:17, ::2, ::2]
    with Downscaler(
        temperature_obs.coords["lat"][::2],
        temperature_obs.coords["lon"][::2],
        temperature_obs.coords["lat"],
        temperature_obs.coords["lon"],
        coarse,
        climate,
        additive=True,
        nonnegative=False,
    ) as plan:
        results["temperature_additive_remap"] = plan.apply(block, np.arange(17))
    first = precipitation.isel(time=0)
    target = {"lat": (lat[:-1] + lat[1:]) / 2, "lon": (lon[:-1] + lon[1:]) / 2}
    for method in (
        "none",
        "bilinear",
        "nearest",
        "patch",
        "conservative",
        "conservative_2nd",
    ):
        destination = (
            None
            if method == "none"
            else {k: v + 0.01 for k, v in target.items()}
            if method == "nearest"
            else target
        )
        results["remap_" + method] = interpolate(first, destination, method).values
    for method in ("arithmetic", "weighted", "area_weighted"):
        results["mean_" + method] = np.asarray(
            calculate_spatial_mean(first, method, include_zeros=True)
        )
    polygon = {
        "type": "Polygon",
        "coordinates": [
            [
                [109.0, 32.0],
                [110.0, 32.0],
                [110.0, 32.75],
                [109.0, 32.75],
                [109.0, 32.0],
            ]
        ],
    }
    results["polygon_mask"] = polygon_mask(lat, lon, polygon)
    # Exercise native vector file decoding, not just in-memory geometry. A VRT
    # assigns an explicit WGS84 layer CRS over the known region polygon.
    region = output / "region.geojson"
    region.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {"type": "Feature", "properties": {}, "geometry": polygon}
                ],
            }
        ),
        encoding="utf-8",
    )
    vector = output / "region.vrt"
    vector.write_text(
        '<OGRVRTDataSource><OGRVRTLayer name="region">'
        '<SrcDataSource relativeToVRT="1">region.geojson</SrcDataSource>'
        "<SrcLayer>region</SrcLayer><LayerSRS>EPSG:4326</LayerSRS>"
        "</OGRVRTLayer></OGRVRTDataSource>",
        encoding="utf-8",
    )
    results["polygon_vector_mask"] = polygon_mask(lat, lon, vector)
    # Geometry-only Shapefile written independently of the Rust reader.
    import struct

    shp = output / "region.shp"
    vertices = [
        (109.0, 32.0),
        (109.0, 32.75),
        (110.0, 32.75),
        (110.0, 32.0),
        (109.0, 32.0),
    ]
    body = struct.pack("<i4d2ii", 5, 109.0, 32.0, 110.0, 32.75, 1, 5, 0)
    body += b"".join(struct.pack("<2d", *point) for point in vertices)
    header = struct.pack(">7i", 9994, 0, 0, 0, 0, 0, (108 + len(body)) // 2)
    header += struct.pack(
        "<2i8d", 1000, 5, 109.0, 32.0, 110.0, 32.75, 0.0, 0.0, 0.0, 0.0
    )
    shp.write_bytes(header + struct.pack(">2i", 1, len(body) // 2) + body)
    shp.with_suffix(".prj").write_text(
        'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563]],PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433],AUTHORITY["EPSG","4326"]]'
    )
    results["polygon_shapefile_mask"] = polygon_mask(lat, lon, shp)

    results["mean_clipped"] = np.asarray(
        calculate_spatial_mean(first, "weighted", include_zeros=True, shp=polygon)
    )
    # Direct transfer: varied real samples plus a known synthetic multiplicative
    # distortion. This tests fitting; no claim of independent model validation.
    train = precipitation.values[:, 0, 0]
    query = precipitation.values[:80, 0, 1]
    with Transfer(train * 0.8, train) as transfer:
        results["transfer_real"] = transfer(query)
    results["smooth_real"] = smooth(precipitation.values[:366])
    # Full path: CN05 observation grid, generated coarse model with explicit .8
    # multiplicative bias; historical 2019, future 2020. Keep generated files out of Git.
    history = precipitation.isel(
        time=slice(0, 365), lat=slice(None, None, 2), lon=slice(None, None, 3)
    )
    future = precipitation.isel(
        time=slice(365, None), lat=slice(None, None, 2), lon=slice(None, None, 3)
    )
    for f in (history, future):
        f.values = f.values * 0.8
    history.to_netcdf(output / "model_history.nc")
    future.to_netcdf(output / "model_future.nc")
    precipitation.to_netcdf(output / "observations.nc")
    correction = BC(
        output / "observations.nc",
        output / "model_history.nc",
        output / "model_future.nc",
        "cn05",
        2019,
        2019,
        strict=True,
        work_dir=output / "buffers",
    )
    try:
        results["bc_history"] = correction["corrected_hist_pr"].values.copy()
        results["bc_future"] = correction["corrected_fut_pr"].values.copy()
        downscaled = SD(
            output / "observations.nc",
            correction,
            output / "bcsd",
            2019,
            2019,
            strict=True,
            time_chunk_size=31,
            spatial_chunk_size=2,
        )
        for period, key in [("history", "hist_bcsd_path"), ("future", "fut_bcsd_path")]:
            with Dataset(downscaled[key]) as ds:
                results["sd_" + period] = ds["pr"][...]
    finally:
        close_result(correction, remove_work_files=True)
    # One actual CN05 day is exported, with independent TIFF inspection in Test1.
    single = precipitation.isel(time=slice(0, 1))
    single.to_netcdf(output / "one_day.nc")
    results["geotiff_pixels"] = single.values[0, ::-1].astype("float32")
    nc_to_tiff(output / "one_day.nc", output / "geotiff", variable=single.name)
    return results


def reference_checks(data, output, precipitation):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests/reference"))
    import migration as ref
    import xarray as xr
    import xclim.indices as xci
    from scipy.interpolate import RegularGridInterpolator
    from scipy.linalg import pinv
    from scipy.spatial import cKDTree

    results = {}
    with np.errstate(invalid="ignore"):
        results["time_mean_float32"] = np.nanmean(
            np.asarray(precipitation.values, dtype=np.float32), axis=0, dtype=np.float64
        )
    ensemble = np.stack([precipitation.values + i for i in (0, 2, 8)])
    results["ensemble_cn05_mean"] = ensemble.mean(axis=0)
    for key, q in (("median", .5), ("p05", .05), ("p95", .95)):
        results["ensemble_cn05_" + key] = np.quantile(ensemble, q, axis=0)
    events = []
    for cell in np.ndindex(precipitation.shape[1:]):
        column = precipitation.values[(slice(None),) + cell]
        active = np.isfinite(column) & (column < 1)
        changes = np.diff(np.r_[False, active, False].astype(int))
        for start, end in zip(np.flatnonzero(changes == 1), np.flatnonzero(changes == -1)):
            if end - start >= 2:
                events.append([*cell, start, end - 1, end - start,
                               np.sum(1 - column[start:end])])
    results["events_cn05"] = np.asarray(events, dtype=float).reshape(-1, 6)
    from drought import standardized

    monthly_source = xr.open_dataset(
        data / "逐月/Pre/CN05.1_Pre_1961_2018_month_025x025.nc"
    )
    try:
        pr_month = (
            monthly_source["pre"].isel(lat=slice(68, 74), lon=slice(155, 163)).load()
        )
        monthly_amount = (
            pr_month.values * pr_month.time.dt.days_in_month.values[:, None, None]
        )
        for scale in (3, 12):
            results[f"spi{scale}_cn05"] = standardized(
                monthly_amount,
                pr_month.time.dt.month.values,
                pr_month.time.dt.year.values,
                scale,
                (1981, 2010),
            )[0]
    finally:
        monthly_source.close()
    q = (np.arange(40) + 0.5) / 40
    balance = np.repeat(-30 + 20 * (q / (1 - q)) ** 0.5, 12)
    results["spei3_synthetic_pet"] = standardized(
        100 + balance,
        np.tile(np.arange(1, 13), 40),
        np.repeat(np.arange(1981, 2021), 12),
        3,
        (1981, 2020),
        pet=np.full(480, 100.0),
    )[0]
    values = precipitation.values
    results["collection_values"] = values
    results["collection_float32_values"] = np.asarray(values, dtype=np.float32)
    results["collection_float32_mean"] = np.nanmean(np.asarray(values, dtype=np.float32), axis=0, dtype=np.float64)
    for frequency, rule in (
        ("monthly", "MS"),
        ("seasonal", "QS-DEC"),
        ("annual", "YS"),
    ):
        grouped = precipitation.resample(time=rule)
        means = grouped.mean("time")
        counts = grouped.count("time")
        if frequency == "monthly":
            expected = means.time.dt.days_in_month
        else:
            import pandas as pd

            width = 3 if frequency == "seasonal" else 12
            expected = xr.DataArray(
                [
                    (
                        pd.Timestamp(t) + pd.DateOffset(months=width) - pd.Timestamp(t)
                    ).days
                    for t in means.time.values
                ],
                dims="time",
                coords={"time": means.time},
            )
        results["aggregate_" + frequency] = means.where(counts / expected >= 0.9).values
    paired_model = precipitation * 0.8 + 1
    difference = paired_model - precipitation
    results["evaluation_bias"] = difference.mean("time").values
    results["evaluation_mae"] = abs(difference).mean("time").values
    results["evaluation_rmse"] = np.sqrt((difference**2).mean("time")).values
    results["evaluation_correlation"] = xr.corr(
        paired_model, precipitation, dim="time"
    ).values
    results["evaluation_std_ratio"] = (
        paired_model.std("time") / precipitation.std("time")
    ).values
    results["evaluation_centered_rmse"] = difference.std("time").values
    results["evaluation_n_valid"] = difference.count("time").values
    monthly = precipitation.resample(time="MS").mean("time")
    for frequency, rule, width in (("annual", "YS", 12), ("seasonal", "QS-DEC", 3)):
        days = monthly.time.dt.days_in_month
        numerator = (monthly * days).resample(time=rule).sum("time")
        represented = days.where(monthly.notnull()).resample(time=rule).sum("time")
        import pandas as pd

        expected = xr.DataArray(
            [
                (pd.Timestamp(t) + pd.DateOffset(months=width) - pd.Timestamp(t)).days
                for t in numerator.time.values
            ],
            dims="time",
            coords={"time": numerator.time},
        )
        results["monthly_to_" + frequency] = (
            (numerator / represented).where(represented / expected >= 0.9).values
        )
    finite_values = values[np.isfinite(values)]
    results["qc_summary"] = np.asarray(
        [
            np.isfinite(values).sum(),
            np.isnan(values).sum(),
            np.isinf(values).sum(),
            (finite_values < 0).sum(),
            (finite_values > 100).sum(),
            (finite_values < 0).sum(),
            finite_values.min(),
            finite_values.max(),
            np.isfinite(values).mean(),
        ]
    )
    import pandas as pd

    dates = monthly.time.values
    results["monthly_cf_bounds"] = np.asarray(
        [
            [
                pd.Timestamp(t).to_pydatetime().toordinal() - 1,
                (pd.Timestamp(t) + pd.DateOffset(months=1)).to_pydatetime().toordinal()
                - 1,
            ]
            for t in dates
        ],
        dtype=float,
    )
    results["recipe_monthly"] = monthly.values
    lat = precipitation.lat.values
    # sin(north)-sin(south) = 2*cos(center)*sin(half_width).
    areas = (
        6371000.0**2
        * np.deg2rad(0.25)
        * 2
        * np.cos(np.deg2rad(lat))
        * np.sin(np.deg2rad(0.125))
    )
    weights = xr.DataArray(
        areas, dims="lat", coords={"lat": precipitation.lat}
    ).broadcast_like(precipitation)
    valid = np.isfinite(paired_model) & np.isfinite(precipitation)
    w = weights.where(valid, 0)
    dims = ("lat", "lon")
    denominator = w.sum(dims)

    def weighted(x):
        return (x.where(valid, 0) * w).sum(dims) / denominator

    ma, mb = weighted(paired_model), weighted(precipitation)
    va, vb = weighted((paired_model - ma) ** 2), weighted((precipitation - mb) ** 2)
    area_metrics = {
        "bias": weighted(difference),
        "mae": weighted(abs(difference)),
        "rmse": np.sqrt(weighted(difference**2)),
        "correlation": weighted((paired_model - ma) * (precipitation - mb))
        / np.sqrt(va * vb),
        "std_ratio": np.sqrt(va / vb),
        "centered_rmse": np.sqrt(
            weighted(((paired_model - ma) - (precipitation - mb)) ** 2)
        ),
    }
    coverage = denominator / weights.sum(dims)
    for name, value in area_metrics.items():
        results["area_evaluation_" + name] = value.where(coverage >= 0.9).values
    results["area_evaluation_n_valid"] = valid.sum(dims).values
    results["area_evaluation_valid_weight_fraction"] = coverage.values
    annual = precipitation.groupby("time.year")
    wet = precipitation >= 1
    wet_total = precipitation.where(wet, 0).groupby("time.year").sum("time").values
    wet_days = wet.groupby("time.year").sum("time").values
    results.update(
        index_PRCPTOT=wet_total,
        index_R1mm_days=wet_days,
        index_SDII=wet_total / wet_days,
        index_RX1DAY=xci.max_1day_precipitation_amount(precipitation, freq="YS").values,
        index_RX5DAY=xci.max_n_day_precipitation_amount(
            precipitation, window=5, freq="YS"
        ).values,
        index_CDD=xci.maximum_consecutive_dry_days(
            precipitation, thresh="1 mm/day", freq="YS"
        ).values,
        index_CWD=xci.maximum_consecutive_wet_days(
            precipitation, thresh="1 mm/day", freq="YS"
        ).values,
    )
    for n in (10, 20, 25, 50, 90, 95, 99):
        cutoff = (
            n
            if n < 90
            else precipitation.where(wet).quantile(
                n / 100, dim="time", method="median_unbiased"
            )
        )
        condition = (
            precipitation >= cutoff if n < 90 else (precipitation > cutoff) & wet
        )
        amount = (
            precipitation.where(condition, 0).groupby("time.year").sum("time").values
        )
        count = condition.groupby("time.year").sum("time").values
        with np.errstate(invalid="ignore", divide="ignore"):
            intensity = np.where(count > 0, amount / count, np.nan)
        ratio = amount / annual.sum("time").values
        for kind, v in [
            ("precipitation", amount),
            ("days", count),
            ("intensity", intensity),
            ("ratio", ratio),
        ]:
            results[f"index_R{n}mm_{kind}"] = v
    results["rx5_monthly"] = (
        precipitation.rolling(time=5, min_periods=5)
        .sum()
        .resample(time="MS")
        .max("time")
        .values
    )
    temperature = {}
    for directory, variable, key in [
        ("Tmax", "tmax", "tx"),
        ("Tmin", "tmin", "tn"),
        ("Tm", "tm", "tg"),
    ]:
        pieces = []
        for year in (2020, 2021):
            with xr.open_dataset(
                data / f"逐日/{directory}/CN05.1_{directory}_{year}_daily_025x025.nc"
            ) as ds:
                pieces.append(
                    ds[variable]
                    .isel(lat=slice(68, 74), lon=slice(155, 163))
                    .load()
                    .astype(float)
                )
        temperature[key] = xr.concat(pieces, dim="time")
        temperature[key].attrs["units"] = "degC"
    for name, key, op, value in [
        ("FD", "tn", "lt", 0),
        ("TR", "tn", "gt", 20),
        ("SU", "tx", "gt", 25),
        ("ID", "tx", "lt", 0),
    ]:
        a = temperature[key]
        results["temp_" + name] = (
            ((a < value) if op == "lt" else (a > value))
            .groupby("time.year")
            .sum("time")
            .values
        )
    for name, key, method in [
        ("TXx", "tx", "max"),
        ("TXn", "tx", "min"),
        ("TNx", "tn", "max"),
        ("TNn", "tn", "min"),
    ]:
        results["temp_" + name] = getattr(
            temperature[key].resample(time="MS"), method
        )().values
    results["temp_DTR"] = (
        (temperature["tx"] - temperature["tn"]).resample(time="MS").mean().values
    )
    results["temp_GSL"] = ref.gsl(temperature["tg"])
    results["temp_GSL_SH"] = ref.gsl(temperature["tg"], "SH")
    for name, key, p, greater in [
        ("TX10p", "tx", 10, False),
        ("TX90p", "tx", 90, True),
        ("TN10p", "tn", 10, False),
        ("TN90p", "tn", 90, True),
    ]:
        for bootstrap in (False, True):
            results[f"temp_{name}_bootstrap_{bootstrap}"] = ref.temp_metric(
                temperature[key], p, greater, bootstrap=bootstrap
            )
    results["temp_WSDI"] = ref.temp_metric(temperature["tx"], 90, True, spell=True)
    results["temp_CSDI"] = ref.temp_metric(temperature["tn"], 10, False, spell=True)
    lat, lon = precipitation.lat.values, precipitation.lon.values
    first = values[0]
    ty, tx = (lat[:-1] + lat[1:]) / 2, (lon[:-1] + lon[1:]) / 2
    yy, xx = np.meshgrid(ty, tx, indexing="ij")
    points = np.column_stack([yy.ravel(), xx.ravel()])
    results["remap_none"] = first
    results["remap_bilinear"] = RegularGridInterpolator((lat, lon), first)(
        points
    ).reshape(yy.shape)

    def sphere(y, x):
        y, x = np.deg2rad(y), np.deg2rad(x)
        return np.column_stack(
            [np.cos(y) * np.cos(x), np.cos(y) * np.sin(x), np.sin(y)]
        )

    sy, sx = np.meshgrid(lat, lon, indexing="ij")
    nearest = cKDTree(sphere(sy.ravel(), sx.ravel())).query(
        sphere(yy.ravel() + 0.01, xx.ravel() + 0.01)
    )[1]
    results["remap_nearest"] = first.ravel()[nearest].reshape(yy.shape)
    patch = np.empty(yy.shape)
    for j, i in np.ndindex(yy.shape):
        r = min(max(np.searchsorted(lat, ty[j]) - 1, 0), len(lat) - 3)
        c = min(max(np.searchsorted(lon, tx[i]) - 1, 0), len(lon) - 3)
        a, b = np.meshgrid(lat[r : r + 3], lon[c : c + 3], indexing="ij")
        dy, dx = (
            (a.ravel() - ty[j]) / np.ptp(lat[r : r + 3]),
            (b.ravel() - tx[i]) / np.ptp(lon[c : c + 3]),
        )
        design = np.column_stack([np.ones(9), dx, dy, dx * dy, dx * dx, dy * dy])
        patch[j, i] = pinv(design)[0] @ first[r : r + 3, c : c + 3].ravel()
    results["remap_patch"] = patch

    # Exact overlap integrals in (longitude,sin(latitude)) coordinates.
    def edges(a):
        return np.r_[
            a[0] - (a[1] - a[0]) / 2, (a[:-1] + a[1:]) / 2, a[-1] + (a[-1] - a[-2]) / 2
        ]

    yb, xb = np.sin(np.deg2rad(edges(lat))), np.deg2rad(edges(lon))
    oy, ox = np.sin(np.deg2rad(edges(ty))), np.deg2rad(edges(tx))
    yc, xc = (yb[:-1] + yb[1:]) / 2, (xb[:-1] + xb[1:]) / 2
    gy, gx = np.gradient(first, yc, xc)
    conservative = np.zeros(yy.shape)
    second = np.zeros(yy.shape)
    for j, i in np.ndindex(yy.shape):
        area = (oy[j + 1] - oy[j]) * (ox[i + 1] - ox[i])
        for r, c in np.ndindex(first.shape):
            a, b = max(yb[r], oy[j]), min(yb[r + 1], oy[j + 1])
            d, e = max(xb[c], ox[i]), min(xb[c + 1], ox[i + 1])
            if b <= a or e <= d:
                continue
            w = (b - a) * (e - d) / area
            conservative[j, i] += w * first[r, c]
            second[j, i] += w * (
                first[r, c]
                + gx[r, c] * ((d + e) / 2 - xc[c])
                + gy[r, c] * ((a + b) / 2 - yc[r])
            )
    results["remap_conservative"], results["remap_conservative_2nd"] = (
        conservative,
        second,
    )
    area_weights = np.broadcast_to(np.cos(np.deg2rad(lat))[:, None], first.shape)
    results["mean_arithmetic"] = np.asarray(np.mean(first))
    results["mean_weighted"] = results["mean_area_weighted"] = np.asarray(
        np.average(first, weights=area_weights)
    )
    mask = (sy >= 32) & (sy <= 32.75) & (sx >= 109) & (sx <= 110)
    results["polygon_mask"] = mask
    results["polygon_vector_mask"] = mask
    results["polygon_shapefile_mask"] = mask
    results["mean_clipped"] = np.asarray(
        np.average(first[mask], weights=area_weights[mask])
    )
    results["transfer_real"] = ref.transfer(
        values[:, 0, 0] * 0.8, values[:, 0, 0], values[:80, 0, 1]
    )
    results["smooth_real"] = ref.smooth(values[:366])
    # Independent signed-temperature quantile transfer and additive SD.
    observed_temp = temperature["tg"].values
    model_temp = observed_temp - 2
    day_labels = temperature["tg"].time.dt.dayofyear.values.copy()
    day_labels[366:] += temperature["tg"].time.dt.month.values[366:] >= 3
    corrected_temp = np.empty_like(observed_temp)
    for j, i in np.ndindex(observed_temp.shape[1:]):
        for day in range(1, 367):
            distance = np.abs(day_labels[:366] - day)
            train = np.minimum(distance, 366 - distance) <= 15
            select = day_labels == day
            corrected_temp[select, j, i] = ref.transfer(
                model_temp[:366, j, i][train],
                observed_temp[:366, j, i][train],
                model_temp[select, j, i],
                nonnegative=False,
            )
    results["temperature_bc_history"] = corrected_temp[:366]
    results["temperature_bc_future"] = corrected_temp[366:]
    results["temperature_sd_history"] = corrected_temp[:366].astype("float32")
    results["temperature_sd_future"] = corrected_temp[366:].astype("float32")
    results["temperature_dtr"] = (temperature["tx"] - temperature["tn"]).values
    results["temperature_reconstructed_minimum"] = temperature["tn"].values
    climate_temp = ref.smooth(observed_temp[:366], nonnegative=False)
    anomaly = observed_temp[:17, ::2, ::2] - climate_temp[:17, ::2, ::2]
    ty, tx = np.meshgrid(
        temperature["tg"].lat.values, temperature["tg"].lon.values, indexing="ij"
    )
    target_points = np.column_stack((ty.ravel(), tx.ravel()))
    mapped = np.asarray(
        [
            RegularGridInterpolator(
                (temperature["tg"].lat.values[::2], temperature["tg"].lon.values[::2]),
                values,
                bounds_error=False,
                fill_value=None,
            )(target_points).reshape(ty.shape)
            for values in anomaly
        ]
    )
    results["temperature_additive_remap"] = (mapped + climate_temp[:17]).astype(
        "float32"
    )
    # Independently reproduce the documented BC/SD algorithm on the same tile.
    cy, cx = lat[::2], lon[::3]

    def coarsen(v):
        boundsy, boundsx = edges(cy), edges(cx)
        out = np.empty((*v.shape[:-2], len(cy), len(cx)))
        for j, i in np.ndindex((len(cy), len(cx))):
            selected = (
                (sy >= boundsy[j])
                & (sy < (boundsy[j + 1] if j < len(cy) - 1 else boundsy[j + 1] + 1e-12))
                & (sx >= boundsx[i])
                & (sx < (boundsx[i + 1] if i < len(cx) - 1 else boundsx[i + 1] + 1e-12))
            )
            out[..., j, i] = np.average(
                v[..., selected], weights=area_weights[selected], axis=-1
            )
        return out

    observed = coarsen(values[:365])
    hist = values[:365, ::2, ::3] * 0.8
    future = values[365:, ::2, ::3] * 0.8
    doy = precipitation.time.dt.dayofyear.values[:365]
    corrected = []
    for v, labels in [
        (hist, doy),
        (future, precipitation.time.dt.dayofyear.values[365:]),
    ]:
        output_array = np.empty_like(v)
        for j, i in np.ndindex(hist.shape[1:]):
            for day in range(1, 367):
                # Rust calendar mapping uses a leap template for Gregorian,
                # so common-year dates after February receive +1.
                refmonth = precipitation.time.dt.month.values[:365]
                refday = doy + (refmonth >= 3)
                distance = np.abs(refday - day)
                sample = np.minimum(distance, 366 - distance) <= 15
                target_day = labels.copy()
                if len(v) == 365:
                    target_day += precipitation.time.dt.month.values[:365] >= 3
                take = target_day == day
                output_array[take, j, i] = ref.transfer(
                    hist[sample, j, i], observed[sample, j, i], v[take, j, i]
                )
        corrected.append(output_array)
    results["bc_history"], results["bc_future"] = corrected
    climate = np.full((366, *first.shape), np.nan)
    refmonth = precipitation.time.dt.month.values[:365]
    refday = doy + (refmonth >= 3)
    for d in np.unique(refday):
        climate[d - 1] = np.mean(values[:365][refday == d], axis=0)
    climate = ref.smooth(climate).astype(float)
    coarse = coarsen(climate)
    dest = np.column_stack([sy.ravel(), sx.ravel()])
    for name, v, offset in [
        ("history", corrected[0], 0),
        ("future", corrected[1], 365),
    ]:
        months = precipitation.time.dt.month.values[offset : offset + len(v)]
        labels = precipitation.time.dt.dayofyear.values[offset : offset + len(v)].copy()
        if name == "history":
            labels += months >= 3
        out = np.empty((len(v), *first.shape))
        for t, d in enumerate(labels - 1):
            q = np.maximum(coarse[d], 1e-4)
            ratio = np.where(
                v[t] <= 0.0, 0.0, np.clip(np.maximum(v[t], 1e-4) / q, 0.1, 10.0)
            )
            mapped = RegularGridInterpolator(
                (cy, cx), ratio, bounds_error=False, fill_value=None
            )(dest).reshape(first.shape)
            out[t] = np.maximum(mapped * climate[d], 0.0)
        results["sd_" + name] = out.astype("float32")
    # Read Rust GeoTIFF through native GDAL, independent of the writer.
    import ctypes as ct
    from ctypes.util import find_library

    gdal = ct.CDLL(find_library("gdal"))
    gdal.GDALAllRegister()
    gdal.GDALOpen.argtypes, gdal.GDALOpen.restype = [ct.c_char_p, ct.c_int], ct.c_void_p
    gdal.GDALGetRasterBand.argtypes, gdal.GDALGetRasterBand.restype = (
        [ct.c_void_p, ct.c_int],
        ct.c_void_p,
    )
    gdal.GDALRasterIO.argtypes, gdal.GDALRasterIO.restype = (
        [
            ct.c_void_p,
            ct.c_int,
            ct.c_int,
            ct.c_int,
            ct.c_int,
            ct.c_int,
            ct.c_void_p,
            ct.c_int,
            ct.c_int,
            ct.c_int,
            ct.c_int,
            ct.c_int,
        ],
        ct.c_int,
    )
    gdal.GDALClose.argtypes = [ct.c_void_p]
    handle = gdal.GDALOpen(str(next((output / "geotiff").glob("*.tiff"))).encode(), 0)
    if not handle:
        raise RuntimeError("Independent GDAL could not open GeoTIFF")
    try:
        a = np.empty(first.shape, dtype="float32")
        code = gdal.GDALRasterIO(
            gdal.GDALGetRasterBand(handle, 1),
            0,
            0,
            0,
            a.shape[1],
            a.shape[0],
            a.ctypes.data,
            a.shape[1],
            a.shape[0],
            6,
            0,
            0,
        )
        if code:
            raise RuntimeError("Independent GDAL raster read failed")
        results["geotiff_pixels"] = a
    finally:
        gdal.GDALClose(handle)
    return results
