"""BCSD 一体化入口及旧导入路径；计算实现位于同一子包下的 BiasCorrection 和 SpatialDownscaling。"""

import logging

from .bias_correction import (
    BC,
    close_result,
)
from .bias_correction import (
    create_cdf_spline as create_cdf_spline,
)

logger = logging.getLogger(__name__)

from ..._core.common import (
    DEBUG_CHECK as DEBUG_CHECK,
)
from ..._core.common import (
    DEBUG_PRINT_SAMPLES as DEBUG_PRINT_SAMPLES,
)
from ..._core.common import (
    MAX_RATIO as MAX_RATIO,
)
from ..._core.common import (
    MIN_PRECIP as MIN_PRECIP,
)
from ..._core.common import (
    MIN_RATIO as MIN_RATIO,
)
from ..._core.common import (
    N_QUANTILES as N_QUANTILES,
)
from ..._core.common import (
    WINDOW_SIZE as WINDOW_SIZE,
)
from ..._core.common import (
    _safe_max as _safe_max,
)
from ..._core.common import (
    _safe_mean as _safe_mean,
)
from ..._core.common import (
    _safe_min as _safe_min,
)
from ..._core.common import (
    calculate_bounds as calculate_bounds,
)
from ..._core.common import (
    calculate_doy as calculate_doy,
)
from ..._core.common import (
    cftime_to_datetime as cftime_to_datetime,
)
from ..._core.common import (
    convert_precip_to_mm_day as convert_precip_to_mm_day,
)
from ..._core.common import (
    detect_calendar_type as detect_calendar_type,
)
from ..._core.common import (
    get_precip_var_name as get_precip_var_name,
)
from ..._core.common import (
    parse_cftime_date as parse_cftime_date,
)
from ..._core.common import (
    print_array_diagnostics as print_array_diagnostics,
)
from .spatial_downscaling import (
    SD,
)
from .spatial_downscaling import (
    area_weighted_regrid as area_weighted_regrid,
)
from .spatial_downscaling import (
    fft_smooth_three_harmonics as fft_smooth_three_harmonics,
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
    variable="pr",
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
        **dict(bc_options or {}, strict=strict, variable=variable),
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
        "variable": variable,
        "diagnostics": sd_result["diagnostics"],
    }


BCSD = bcsd
