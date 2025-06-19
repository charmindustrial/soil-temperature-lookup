#!/usr/bin/env python
"""Lookup annual mean soil temperature (5–15 cm) for a street address.

The module exposes a single convenience function :pyfunc:`get_soil_temperature`
which can be imported in other programs, and a small CLI that you can run from
shell:

    python soil_temp_lookup.py "1600 Amphitheatre Parkway, Mountain View, CA"

The implementation is *fast* because:

1.  The global GeoTIFF is opened **once** and kept in an in-memory cache so
    subsequent queries don't pay the costly GDAL open penalty.
2.  Address → (lat, lon) geocoding results are memoised via
    :pyfunc:`functools.lru_cache` (configurable size).
3.  We sample a *single* pixel with :pyfunc:`rasterio.DatasetReader.sample` – no
    full-raster reads.
4.  If the raster is not in geographic CRS (EPSG:4326) we transparently wrap
    it in a lightweight in-memory :pyclass:`rasterio.vrt.WarpedVRT`, avoiding
    the overhead of writing temporary files.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Final, Tuple

import numpy as np
import rasterio
from rasterio.vrt import WarpedVRT
from rasterio.warp import transform

try:
    # Lazy import so that users without geopy can still import the module
    # for direct lon/lat queries.
    from geopy.geocoders import Nominatim  # type: ignore
except ModuleNotFoundError:  # pragma: no cover – optional dependency
    Nominatim = None  # type: ignore

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------

DEFAULT_TIF: Final[str] = "SBIO1_Annual_Mean_Temperature_5_15cm.tif"
_GEOLOCATOR_CACHE: Final[dict[str, "Nominatim"]] = {}

# -----------------------------------------------------------------------------
# Internal helpers
# -----------------------------------------------------------------------------

def _get_dataset(path: str | Path = DEFAULT_TIF) -> rasterio.DatasetReader:
    """Return a cached, ready-to-use Rasterio dataset (possibly warped to EPSG:4326)."""
    p = str(Path(path).expanduser().resolve())
    ds = _get_dataset.cache_get(p)  # type: ignore[attr-defined]
    if ds is not None:
        return ds  # type: ignore[return-value]

    base = rasterio.open(p)
    if base.crs is None:
        raise RuntimeError("Raster has no CRS – cannot locate coordinates.")

    if base.crs.to_epsg() != 4326:
        base = WarpedVRT(base, crs="EPSG:4326")  # lightweight virtual reprojection
    _get_dataset.cache_set(p, base)  # type: ignore[attr-defined]
    return base


# Monkey-patch simple cache helpers instead of functools.lru_cache (we need to
# store mutable DatasetReader objects that are not hashable).
_get_dataset._cache = {}  # type: ignore[attr-defined]


def _get_dataset_cache_get(key):  # type: ignore[no-self-use]
    return _get_dataset._cache.get(key)


def _get_dataset_cache_set(key, value):  # type: ignore[no-self-use]
    _get_dataset._cache[key] = value


# Attach helpers to function object so they're in the same namespace.
_get_dataset.cache_get = _get_dataset_cache_get  # type: ignore[attr-defined]
_get_dataset.cache_set = _get_dataset_cache_set  # type: ignore[attr-defined]


@lru_cache(maxsize=2048)
def _geocode(address: str) -> Tuple[float, float]:
    """Geocode *address* to (lat, lon) using Nominatim with aggressive caching."""
    if Nominatim is None:  # pragma: no cover – optional dependency missing
        raise RuntimeError("geopy is required for address lookup. Install via `pip install geopy`."
                           )
    if "nominatim" not in _GEOLOCATOR_CACHE:
        _GEOLOCATOR_CACHE["nominatim"] = Nominatim(user_agent="soil-temp-lookup")  # type: ignore[assignment]

    loc = _GEOLOCATOR_CACHE["nominatim"].geocode(address, timeout=5)  # type: ignore[index]
    if loc is None:
        raise ValueError(f"Address not found: {address!r}")
    return loc.latitude, loc.longitude


# -----------------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------------

def get_soil_temperature(
    address_or_coord: str | Tuple[float, float],
    *,
    tif_path: str | Path = DEFAULT_TIF,
) -> float | None:
    """Return the soil temperature (°C) for *address_or_coord*.

    Parameters
    ----------
    address_or_coord
        Either a free-form street address (e.g. ``"Paris, France"``) or a
        ``(lat, lon)`` tuple.
    tif_path
        Path to the GeoTIFF raster.  Defaults to the global dataset shipped
        with the repository.

    Returns
    -------
    float | None
        Temperature in °C, or *None* if the location falls outside the raster
        or is a nodata pixel.
    """
    if isinstance(address_or_coord, str):
        lat, lon = _geocode(address_or_coord)
    else:
        lat, lon = address_or_coord

    ds = _get_dataset(tif_path)

    # Rasterio expects (lon, lat) order for geographic CRS.
    sample_iter = ds.sample([(lon, lat)])
    try:
        value = next(sample_iter)[0]
    except StopIteration:  # improbable
        return None

    # Handle nodata / masked values.
    if ds.nodata is not None and np.isclose(value, ds.nodata):
        return None
    if np.isnan(value):
        return None
    return float(value)


# ------------- NEW PUBLIC API -------------------------------------------------

def get_soil_temperatures_in_bbox(
    bbox: Tuple[float, float, float, float],
    *,
    tif_path: str | Path = DEFAULT_TIF,
    masked: bool = False,
) -> np.ndarray | None:
    """Return all soil-temperature pixel values that fall inside *bbox*.

    Parameters
    ----------
    bbox
        Bounding box given as ``(lat_min, lon_min, lat_max, lon_max)``.
        (This is the common "south, west, north, east" order.)
    tif_path
        Path to the GeoTIFF raster (defaults to the dataset shipped with the
        repository).
    masked
        If *True*, the returned array is a :pyclass:`numpy.ma.MaskedArray` with
        nodata pixels masked out.  If *False* (default) nodata pixels are
        converted to *NaN* and a plain :class:`numpy.ndarray` is returned.

    Returns
    -------
    numpy.ndarray | numpy.ma.MaskedArray | None
        2-D array of pixel values covering the bounding box (rows × cols), or
        *None* if the requested area lies completely outside the raster or all
        intersecting pixels are nodata.
    """
    # Unpack and normalise bbox (south, west, north, east → lat/lon ordering)
    lat_min, lon_min, lat_max, lon_max = bbox
    south, west, north, east = lat_min, lon_min, lat_max, lon_max

    ds = _get_dataset(tif_path)

    # Quick reject if the bbox does not intersect the raster at all.
    if east < ds.bounds.left or west > ds.bounds.right or \
       north < ds.bounds.bottom or south > ds.bounds.top:
        return None

    from rasterio.windows import from_bounds, Window

    # Build a read window (expressed in pixel coordinates).
    window = from_bounds(
        west, south, east, north,
        transform=ds.transform,
    ).round_offsets().round_lengths()

    # Clip the window to the dataset extent in case *boundless* stretched it.
    full_window = Window(0, 0, ds.width, ds.height)
    window = window.intersection(full_window)

    if window.width <= 0 or window.height <= 0:  # nothing to read
        return None

    data = ds.read(1, window=window, masked=True)  # read as MaskedArray

    # Shortcut: if everything is nodata just return None.
    if data.mask.all():
        return None

    if masked:
        return data  # user wants the mask preserved

    # Otherwise convert masked values to NaN and return ndarray.
    filled = data.filled(np.nan).astype(float)
    return filled


# -----------------------------------------------------------------------------
# Command-line interface
# -----------------------------------------------------------------------------

if __name__ == "__main__":  # pragma: no cover – CLI entry-point
    import argparse, json, sys

    parser = argparse.ArgumentParser(description="Return mean soil temperature for a street address.")
    parser.add_argument("address", help="The street address to look up.")
    parser.add_argument("--tif", default=DEFAULT_TIF, help="Custom path to the raster file.")

    ns = parser.parse_args()
    try:
        temp = get_soil_temperature(ns.address, tif_path=ns.tif)
    except Exception as exc:  # broad catch to make CLI UX nice
        print(f"❌ {exc}", file=sys.stderr)
        sys.exit(1)

    print(json.dumps({"address": ns.address, "soil_temp_c": temp})) 