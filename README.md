# EV Charging Station Optimization Project

## Overview

This repository contains the software modules for the **Renewable Micro-installations in EV Charging Stations** project (Topic 2). The goal is to build an optimization algorithm that sizes Photovoltaic (PV) panels, Wind Turbines, and Battery Storage to support an electric vehicle charging station over an 8760-hour annual simulation.

## Project Structure

```
.
├── gestor_dados.py            # Phase 1: data pipeline (ETL)
├── energy_model.py            # Phase 2: PV and wind energy conversion model
├── requirements.txt           # Python dependencies
├── README.md
└── data/
    ├── ev_charging_dataset.csv          # Raw dataset (all stations)
    ├── processed_ev_demand_2025.csv     # Hourly EV demand of station ST013
    ├── processed_weather_2025.csv       # Hourly weather data (Open-Meteo)
    ├── processed_dataset_2025.csv       # Phase 1 output (demand + weather, 8760 rows)
    └── energy_model_output.csv          # Phase 2 output (Phase 1 + PV and wind power, 8760 rows)
```

## Getting Started

1. Install the dependencies:

```bash
pip install -r requirements.txt
```

2. Make sure the raw dataset is at `data/ev_charging_dataset.csv`.
3. Run the pipeline in order:

```bash
python gestor_dados.py
python energy_model.py
```

Note: `gestor_dados.py` skips the processing (and the API request) if `data/processed_dataset_2025.csv` already exists. To regenerate it, delete that file first. The processed files are already included in the repository, so it is not necessary to run the scripts just to start working on Phase 3.

## Phase 1: Data Management

The data module (`gestor_dados.py`) is responsible for the ETL (Extract, Transform, Load) pipeline. It isolates the most active station (**ST013**) from the raw dataset and fetches real-world weather data for a representative location in Poland using the Open-Meteo API.

### Dataset Structure

The processed dataset (`data/processed_dataset_2025.csv`) contains exactly 8760 rows (one for each hour of the year 2025) with the following features:

* `timestamp`: Hourly index (YYYY-MM-DD HH:MM:SS)
* `energy_consumed_kWh`: The EV charging load required by station ST013.
* `solar_irradiance_W_m2`: Shortwave solar radiation for PV modeling.
* `wind_speed_m_s`: Wind speed at 10m height for Wind Turbine modeling.

### How to Use (For Team Members)

To load the prepared 8760-hour dataset into your module (Energy or Optimization), simply import the loader function:

```python
from gestor_dados import load_processed_data

# Load the ready-to-use pandas DataFrame
df = load_processed_data()
```

### Data Processing Details

* **Demand:** the raw charging sessions of station ST013 are aggregated (summed) per hour. Hours without any recorded session are filled with `0.0` kWh so that the series covers the full year (2025-01-01 00:00 to 2025-12-31 23:00).
* **Weather:** requested from the Open-Meteo Archive API for Warsaw, Poland (latitude 52.2297, longitude 21.0122), with `timezone=UTC` and `wind_speed_unit=ms` (the API default is km/h, so the unit is set explicitly).
* **Timestamps:** the weather data is in UTC. The demand timestamps are used exactly as they appear in the raw dataset (no timezone conversion is applied).

## Phase 2: Energy Conversion Model (`energy_model.py`)

This module processes the 8760-hour annual meteorological and demand dataset to calculate hourly electrical power generation for standard 1 kW nominal capacities.

### Mathematical Models & Logic

* **Solar Photovoltaic (PV) Model:** Converts solar irradiance ($W/m^2$) into electrical power ($kW$) using Standard Test Conditions (STC reference = $1000 W/m^2$).
* **Wind Turbine Model:** Applies a piecewise cubic power curve based on wind speed ($m/s$) with strict operational safety thresholds:
  * **Cut-in speed (< 3.0 m/s):** $0.0\text{ kW}$ (insufficient wind)
  * **Rated speed (≥ 12.0 m/s):** $1.0\text{ kW}$ (maximum nominal power)
  * **Cut-out limit (> 25.0 m/s):** $0.0\text{ kW}$ (storm protection safety shut-down)
  * **Intermediate speeds (3.0 to 12.0 m/s):** Cubic interpolation curve.

### Usage Example

```python
from energy_model import calculate_energy_model

# Loads dataset, computes PV & wind power, and returns the full 8760h DataFrame
df = calculate_energy_model()
```

### Output File (`data/energy_model_output.csv`)

`calculate_energy_model()` also exports the complete result to `data/energy_model_output.csv` (8760 rows, indexed by `timestamp`) with the following columns:

| Column | Unit | Description |
|---|---|---|
| `energy_consumed_kWh` | kWh | EV charging demand of station ST013 in that hour |
| `solar_irradiance_W_m2` | W/m² | Shortwave solar radiation |
| `wind_speed_m_s` | m/s | Wind speed at 10 m height |
| `pv_power_kW` | kW | PV output **per 1 kW installed** |
| `wind_power_kW` | kW | Wind turbine output **per 1 kW installed** |

**How to scale the production:** both `pv_power_kW` and `wind_power_kW` are normalized for 1 kW of installed capacity. The real production of a system is:

```python
pv_production_kW = pv_capacity_kW * df["pv_power_kW"]
wind_production_kW = wind_capacity_kW * df["wind_power_kW"]
```

Since the time step is 1 hour, a power of 1 kW during one hour corresponds to 1 kWh, so the production values can be compared directly with `energy_consumed_kWh`.

### Modeling Assumptions and Limitations

* **Wind height:** wind speed is taken at 10 m (`wind_speed_10m`) and used directly in the power curve, without extrapolation to the turbine hub height. Real turbines operate at higher altitudes where wind is stronger, so wind production is likely underestimated.
* **PV losses:** the PV model assumes no losses (temperature, inverter, cabling, soiling), i.e. a performance ratio of 1.0, and uses horizontal shortwave radiation (no panel tilt or orientation). Real PV production would be lower than modeled.
* **Wind turbine:** a single generic power curve (cut-in 3 m/s, rated 12 m/s, cut-out 25 m/s) is used, with no losses.
* **Location and year:** weather data is for Warsaw (2025) as a representative location in Poland, while the charging data belongs to station ST013.

## Phase 3: Optimization and Costs

This phase consumes the data from the previous phases, either the in-memory DataFrame returned by `calculate_energy_model()` or the CSV `data/energy_model_output.csv`, to apply economic optimization algorithms and to size the battery storage system (together with the PV and wind capacities).

## Team Workflow

* Run `git pull` before starting to work, and again before each `git push`.
* To avoid merge conflicts, each phase should be developed in its own files (for example, Phase 3 in a new module such as `optimizer.py`).
* Do not edit the output of a previous phase by hand: change the corresponding module and regenerate the data.