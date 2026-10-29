"""Streaming long-form CSV export using only the standard library."""

import csv
import math
import os
from pathlib import Path
import tempfile
import numpy as np
from ..native.field import Field


def to_csv(field, path, *, missing_value="", value_column=None):
    """Export one row per cell, dimension coordinates first and value last.

    Preserve dimension order and coordinate values, including numeric CF time.
    Use missing_value for nonfinite values. Refuse to replace an existing path.
    """
    if not isinstance(field, Field):
        raise TypeError("Expected a klimapy.native.Field")
    column = field.name if value_column is None else value_column
    if not isinstance(column, str) or not column or column in field.dims:
        raise ValueError("Value column must be nonempty and distinct from dimensions")
    if field.values.dtype.kind not in "fiu":
        raise ValueError("CSV export expects real numeric values")
    target = Path(path)
    if target.exists():
        raise FileExistsError(str(target))
    descriptor, staging = tempfile.mkstemp(prefix=".klimapy-csv-", dir=target.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow([*field.dims, column])
            for index in np.ndindex(field.shape):
                values = [field.coords[d][i].item() for d, i in zip(field.dims, index)]
                value = field.values[index].item()
                writer.writerow(
                    [*values, value if math.isfinite(value) else missing_value]
                )
        # Atomic exclusive publication; no check-then-replace overwrite race.
        os.link(staging, target)
        return str(target)
    finally:
        Path(staging).unlink(missing_ok=True)
