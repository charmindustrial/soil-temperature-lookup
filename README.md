# Soil Temperature Lookup Tool

Ultra-fast querying of global soil temperatures (5–15 cm depth) from the 
[Zenodo soil-temperature dataset](https://zenodo.org/record/4558732).

## Quick Start

```bash
# 1. Set up environment and install dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. Download the global soil temperature raster (193 MB, one-time)
curl -L -o SBIO1_Annual_Mean_Temperature_5_15cm.tif \
  "https://zenodo.org/record/4558732/files/SBIO1_Annual_Mean_Temperature_5_15cm.tif?download=1"

# 3. Ready to query!
```

## Primary Use Case: Extract Temperature Data for Geographic Regions

### Get all soil temperatures within a bounding box

```python
from soil_temp_lookup import get_soil_temperatures_in_bbox
import numpy as np

# Define a bounding box: (lat_min, lon_min, lat_max, lon_max)
bay_area = (37.0, -123.0, 38.0, -121.5)  # San Francisco Bay Area
temps = get_soil_temperatures_in_bbox(bay_area)

print(f"Array shape: {temps.shape}")                    # e.g., (120, 180) pixels
print(f"Temperature range: {np.nanmin(temps):.1f} to {np.nanmax(temps):.1f}°C")
print(f"Average temperature: {np.nanmean(temps):.1f}°C")

# Work with the data
suitable_areas = temps[(temps > 10) & (temps < 25)]     # Find areas 10-25°C
print(f"Pixels in suitable range: {len(suitable_areas)}")
```

### Command-line batch processing

```python
# Extract multiple regions programmatically
regions = {
    "California Central Valley": (35.0, -122.0, 40.0, -118.0),
    "Great Plains": (35.0, -105.0, 45.0, -95.0),
    "European Farmland": (45.0, -5.0, 55.0, 15.0),
}

for name, bbox in regions.items():
    temps = get_soil_temperatures_in_bbox(bbox)
    if temps is not None:
        print(f"{name}: {np.nanmean(temps):.1f}°C average")
```

## Secondary Use Cases

### Single-point lookups

```bash
# Command line - any street address
python soil_temp_lookup.py "1600 Amphitheatre Parkway, Mountain View, CA"
# {"address": "1600 Amphitheatre Parkway, Mountain View, CA", "soil_temp_c": 17.4}
```

```python
# Python API - coordinates or addresses
from soil_temp_lookup import get_soil_temperature

temp = get_soil_temperature("Paris, France")           # 12.1°C
temp = get_soil_temperature((48.8584, 2.2945))        # same using lat/lon
```

### Analyze the full global dataset

```bash
# View global statistics and preview map
python parse_soil_temp.py
# Shows min/max/mean temperatures and opens a world map visualization
```

## API Reference

### `get_soil_temperatures_in_bbox(bbox, *, masked=False)`

Extract all raster values within a geographic bounding box.

**Parameters:**
- `bbox`: Tuple of `(lat_min, lon_min, lat_max, lon_max)` in degrees
- `masked`: If `True`, returns `numpy.ma.MaskedArray` with nodata pixels masked

**Returns:**
- `numpy.ndarray`: 2D array of temperatures in °C, or `None` if bbox is outside raster

### `get_soil_temperature(address_or_coord)`

Get temperature for a single location.

**Parameters:**
- `address_or_coord`: Street address string or `(lat, lon)` tuple

**Returns:**
- `float`: Temperature in °C, or `None` if location is outside raster

## Data Source

This tool uses the **SBIO1 Annual Mean Temperature (5–15 cm)** layer from:
> Lembrechts et al. (2020). Global maps of soil temperature. *Zenodo*. 
> https://doi.org/10.5281/zenodo.4558732

The global raster has 0.01° resolution (~1 km at the equator) and covers soil temperatures 
at 5–15 cm depth, which is relevant for seed germination, shallow root systems, and 
agricultural planning.

## Performance Notes

- **Bounding box queries**: Fast window reads from the cached raster (~10-100ms)
- **Single-point lookups**: Extremely fast pixel sampling (~1-5ms after first call)  
- **Address geocoding**: Cached via `geopy` with `lru_cache` for repeated queries
- **Memory usage**: Only requested windows are loaded into RAM, not the full 193MB raster
