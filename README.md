# EV Charging Station Optimization Project

## Overview

This repository contains the software modules for the **Renewable Micro-installations in EV Charging Stations** project (Topic 2). The goal is to build an optimization algorithm that sizes Photovoltaic (PV) panels, Wind Turbines, and Battery Storage to support an electric vehicle charging station over an 8760-hour annual simulation.

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