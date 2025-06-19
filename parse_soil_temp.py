#!/usr/bin/env python
"""Parse the global soil‐temperature GeoTIFF and print quick stats.

Usage
-----
python parse_soil_temp.py [PATH_TO_TIF]
If the path is omitted the script looks for
`SBIO1_Annual_Mean_Temperature_5_15cm.tif` in the current directory.

The script prints raster metadata, global min/mean/max and shows a
quicklook map so you can visually confirm everything is working.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Import matplotlib lazily to avoid font-initialization issues on headless/macOS systems.
try:
    import matplotlib.pyplot as plt  # noqa: WPS433 (external import)
except Exception:  # pragma: no cover – safe fallback in minimal environments
    plt = None  # type: ignore

import numpy as np
import rasterio
from rasterio.plot import show

from soil_temp_lookup import get_soil_temperature

DEFAULT_TIF = "SBIO1_Annual_Mean_Temperature_5_15cm.tif"

def main(tif_path: str | Path = DEFAULT_TIF, *, show_plot: bool = True) -> None:  # noqa: D401
    """Run the analysis given a path to a GeoTIFF.

    Parameters
    ----------
    tif_path
        Path to the GeoTIFF file.
    show_plot
        Whether to display the quick-look plot.  Setting this to ``False``
        avoids importing ``matplotlib`` which can be troublesome on fresh
        macOS or CI setups where the system font cache is not yet initialised.
    """
    # If matplotlib was not imported successfully at module import time,
    # disable plotting instead of trying to re-import (which triggers the
    # UnboundLocalError because `plt` would become a new local variable).
    if show_plot and plt is None:
        print("⚠️  Matplotlib not available – running in stats-only mode (use --no-plot to silence).")
        show_plot = False

    tif = Path(tif_path)
    if not tif.exists():
        print(f"❌ File {tif} not found.\n"
              "Download it from https://zenodo.org/record/4558732 and place it"
              " next to this script, or pass the path as an argument.")
        sys.exit(1)

    # Create a GDAL / PROJ environment context so that Rasterio handles
    # internal data paths correctly – avoids clashes with system installs.
    with rasterio.Env():
        with rasterio.open(tif) as src:
            print("=== Metadata ===")
            for k, v in src.profile.items():
                print(f"{k}: {v}")

            # Read the only band into a 2-D masked NumPy array
            data = src.read(1, masked=True)

            # Basic global statistics – nodata values are masked so we can use
            # the simple nan* reducers from NumPy.
            stats = {
                "min (°C)": np.nanmin(data),
                "mean (°C)": np.nanmean(data),
                "max (°C)": np.nanmax(data),
            }

            print("\n=== Global stats ===")
            for k, v in stats.items():
                print(f"{k:<10} {v:6.2f}")

            if show_plot:
                # Quick-look plot – false-color world map.
                fig, ax = plt.subplots(figsize=(12, 6))  # type: ignore[attr-defined]
                show(
                    data,
                    transform=src.transform,
                    ax=ax,
                    cmap="RdYlBu_r",
                    title="Annual mean soil T (5–15 cm)",
                )
                ax.set_axis_off()
                plt.tight_layout()  # type: ignore[attr-defined]
                plt.show()  # type: ignore[attr-defined]


def _cli() -> None:  # noqa: D401
    """Parse CLI arguments and dispatch to :pyfunc:`main`."""
    import argparse

    parser = argparse.ArgumentParser(description="Inspect a soil-temperature GeoTIFF.")
    parser.add_argument("tif", nargs="?", default=DEFAULT_TIF,
                        help="Path to the raster file (defaults to the global dataset).")
    parser.add_argument("--no-plot", dest="no_plot", action="store_true",
                        help="Skip the quick-look plot – useful on headless systems.")

    args = parser.parse_args()
    main(args.tif, show_plot=not args.no_plot)


if __name__ == "__main__":
    _cli()

print(get_soil_temperature("Paris, France"))       # address
print(get_soil_temperature((48.8584, 2.2945)))     # lat/lon 