"""ETCCDI 子包导出入口。"""

from . import ETCCDI
from .ETCCDI import (
    compute_indices,
    check_data,
    PRCPTOT,
    R1mm_days,
    SDII,
    RX1DAY,
    RX5DAY,
    CDD,
    CWD,
    R10mm_precipitation,
    R10mm_days,
    R10mm_intensity,
    R10mm_ratio,
    R20mm_precipitation,
    R20mm_days,
    R20mm_intensity,
    R20mm_ratio,
    R25mm_precipitation,
    R25mm_days,
    R25mm_intensity,
    R25mm_ratio,
    R50mm_precipitation,
    R50mm_days,
    R50mm_intensity,
    R50mm_ratio,
    select_baseline_period,
    R95mm_precipitation,
    R95mm_ratio,
    R95mm_days,
    R95mm_intensity,
    R99mm_precipitation,
    R99mm_ratio,
    R99mm_days,
    R99mm_intensity,
    R90mm_precipitation,
    R90mm_ratio,
    R90mm_days,
    R90mm_intensity,
    check_temperature_data,
    FD,
    SU,
    ID,
    TR,
    GSL,
    TXx,
    TNx,
    TXn,
    TNn,
    TN10p,
    TX10p,
    TN90p,
    TX90p,
    WSDI,
    CSDI,
    DTR,
)

__all__ = ['ETCCDI', 'check_data', 'PRCPTOT', 'R1mm_days', 'SDII', 'RX1DAY', 'RX5DAY', 'CDD', 'CWD', 'R10mm_precipitation', 'R10mm_days', 'R10mm_intensity', 'R10mm_ratio', 'R20mm_precipitation', 'R20mm_days', 'R20mm_intensity', 'R20mm_ratio', 'R25mm_precipitation', 'R25mm_days', 'R25mm_intensity', 'R25mm_ratio', 'R50mm_precipitation', 'R50mm_days', 'R50mm_intensity', 'R50mm_ratio', 'select_baseline_period', 'R95mm_precipitation', 'R95mm_ratio', 'R95mm_days', 'R95mm_intensity', 'R99mm_precipitation', 'R99mm_ratio', 'R99mm_days', 'R99mm_intensity', 'R90mm_precipitation', 'R90mm_ratio', 'R90mm_days', 'R90mm_intensity', 'check_temperature_data', 'FD', 'SU', 'ID', 'TR', 'GSL', 'TXx', 'TNx', 'TXn', 'TNn', 'TN10p', 'TX10p', 'TN90p', 'TX90p', 'WSDI', 'CSDI', 'DTR']

__all__.append("compute_indices")


# Canonical ETCCDI spellings and generic parameterized precipitation metrics.
from .ETCCDI import RXnday, RXdday, Rnnmm, Rx1day, Rx5day, R10mm, R20mm, R95p, R99p, R95pTOT, R99pTOT
__all__ += ["RXnday", "RXdday", "Rnnmm", "Rx1day", "Rx5day", "R10mm", "R20mm", "R95p", "R99p", "R95pTOT", "R99pTOT"]
