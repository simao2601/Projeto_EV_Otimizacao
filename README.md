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

## How to Use (For Team Members)
To load the prepared 8760-hour dataset into your module (Energy or Optimization), simply import the loader function:

```python
from gestor_dados import load_processed_data

# Load the ready-to-use pandas DataFrame
df = load_processed_data()