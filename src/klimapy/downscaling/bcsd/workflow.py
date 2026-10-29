"""BCSD 一体化入口及旧导入路径；计算实现位于同一子包下的 BiasCorrection 和 SpatialDownscaling。"""

from .bias_correction import BC, create_cdf_spline, close_result
import logging

logger = logging.getLogger(__name__)

from .spatial_downscaling import SD, area_weighted_regrid, fft_smooth_three_harmonics
from ..._core.common import (
    WINDOW_SIZE,
    N_QUANTILES,
    MIN_PRECIP,
    MAX_RATIO,
    MIN_RATIO,
    DEBUG_CHECK,
    DEBUG_PRINT_SAMPLES,
    calculate_bounds,
    get_precip_var_name,
    convert_precip_to_mm_day,
    cftime_to_datetime,
    parse_cftime_date,
    detect_calendar_type,
    calculate_doy,
    _safe_min,
    _safe_max,
    _safe_mean,
    print_array_diagnostics,
)


def bcsd(
    obs_path,
    gcm_hist_path,
    gcm_fut_path,
    model_name,
    output_dir,
    ref_start_year,
    ref_end_year,
    *,
    strict=False,
    bc_options=None,
    sd_options=None,
):
    """
    BCSD完整流程：先BC后SD
    """
    logger.info(f"\n处理模式: {model_name}")
    logger.info("=" * 60)

    # 第一步：偏差校正 (BC)
    bc_result = BC(
        obs_path=obs_path,
        gcm_hist_path=gcm_hist_path,
        gcm_fut_path=gcm_fut_path,
        model_name=model_name,
        ref_start_year=ref_start_year,
        ref_end_year=ref_end_year,
        **dict(bc_options or {}, strict=strict),
    )

    if not bc_result:
        logger.info(f"✗ {model_name} BC失败，停止处理")
        return None

    # 第二步：空间降尺度 (SD)
    try:
        sd_result = SD(
            obs_path=obs_path,
            bc_result=bc_result,
            output_dir=output_dir,
            ref_start_year=ref_start_year,
            ref_end_year=ref_end_year,
            **dict(sd_options or {}, strict=strict),
        )
    finally:
        close_result(bc_result, remove_work_files=True)

    if not sd_result:
        logger.info(f"✗ {model_name} SD失败")
        return None

    logger.info(f"✓ {model_name} BCSD完整流程完成！")
    logger.info("=" * 60)

    return {
        "model_name": model_name,
        "hist_bcsd_path": sd_result["hist_bcsd_path"],
        "fut_bcsd_path": sd_result["fut_bcsd_path"],
    }


BCSD = bcsd
