"""Geometry-only mask benchmark; run in conda Test, label old/new outputs explicitly.

Use --installed for an installed wheel; otherwise set PYTHONPATH=src.
Timings exclude file I/O and do not measure Shapefile decoding or CRS conversion.
"""

import argparse, json, time, hashlib
import numpy as np
from pathlib import Path
import sys

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "tools"))
from test_environment import verify

parser = argparse.ArgumentParser()
parser.add_argument("--installed", action="store_true")
parser.add_argument("--label", required=True)
args = parser.parse_args()
verify(installed=args.installed)
from klimapy.native.geometry import polygon_mask

lat = np.linspace(-12, 12, 300)
lon = np.linspace(-20, 20, 400)
outer = [[-8, -8], [8, -8], [8, 8], [-8, 8], [-8, -8]]
hole = [[-2, -2], [2, -2], [2, 2], [-2, 2], [-2, -2]]
a = np.linspace(0, 2 * np.pi, 65)
circle = np.column_stack([8 * np.cos(a), 8 * np.sin(a)]).tolist()
circle[-1] = circle[0]
rows = {}
for name, rings in [("rectangle_hole", [outer, hole]), ("64_vertex_polygon", [circle])]:
    geom = {"type": "Polygon", "coordinates": rings}
    for _ in range(2):
        polygon_mask(lat, lon, geom)
    samples = []
    for _ in range(7):
        t = time.perf_counter()
        mask = polygon_mask(lat, lon, geom)
        samples.append(time.perf_counter() - t)
    rows[name] = {
        "median_ms": float(np.median(samples) * 1000),
        "samples_s": samples,
        "sha256": hashlib.sha256(mask.tobytes()).hexdigest(),
    }
folder = root / "outputs/geometry-migration"
folder.mkdir(exist_ok=True, parents=True)
(folder / (args.label + ".json")).write_text(json.dumps(rows, indent=2) + "\n")
print(rows)
