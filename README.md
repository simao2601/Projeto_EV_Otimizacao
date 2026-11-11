# EV Charging Station Optimization Project

## Overview

This repository contains the software modules for the **Renewable Micro-installations in EV Charging Stations** project (Topic 2). The goal is to build an optimization algorithm that sizes Photovoltaic (PV) panels, Wind Turbines, and Battery Storage to support an electric vehicle charging station over an 8760-hour annual simulation.

## Project Structure

```
.
├── gestor_dados.py            # Phase 1: data pipeline (ETL)
├── energy_model.py            # Phase 2: PV and wind energy conversion model
├── optimizer.py               # Phase 3: PV, wind and battery sizing optimization (LP)
├── requirements.txt           # Python dependencies
├── README.md
└── data/
    ├── ev_charging_dataset.csv          # Raw dataset (all stations)
    ├── processed_ev_demand_2025.csv     # Hourly EV demand of station ST013
    ├── processed_weather_2025.csv       # Hourly weather data (Open-Meteo)
    ├── processed_dataset_2025.csv       # Phase 1 output (demand + weather, 8760 rows)
    ├── energy_model_output.csv          # Phase 2 output (Phase 1 + PV and wind power, 8760 rows)
    ├── optimization_results_hourly.csv          # Phase 3 output (created by optimizer.py)
    ├── optimization_summary.csv                 # Phase 3 output (created by optimizer.py)
    └── optimization_self_sufficiency_sweep.csv  # Phase 3 output (created by optimizer.py)
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
python optimizer.py
```

Note: `gestor_dados.py` skips the processing (and the API request) if `data/processed_dataset_2025.csv` already exists. To regenerate it, delete that file first. The processed files are already included in the repository, so it is not necessary to run the first two scripts just to run the optimization.

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

## Phase 3: Optimization and Costs (`optimizer.py`)

This module reads `data/energy_model_output.csv` and finds the PV capacity, wind capacity and battery capacity that minimize the total annual cost of supplying station ST013. The problem is a **Linear Program (LP)** over the 8760 hours of the year, built with [PuLP](https://coin-or.github.io/pulp/) and solved with [HiGHS](https://highs.dev/) (about 52 000 variables and constraints, solved in a few seconds).

### Decision Variables

* **Sizing:** installed PV capacity $P_{pv}$ (kW), installed wind capacity $P_{wind}$ (kW) and battery capacity $E_{bess}$ (kWh).
* **Hourly operation** (for every hour $t$, all $\geq 0$): grid import $g^{imp}_t$, export to the grid $g^{exp}_t$, curtailed surplus $c_t$, battery charge $ch_t$, battery discharge $dis_t$ and state of charge $soc_t$ (kWh).

### Objective Function

Minimize the **Equivalent Annual Cost (EAC)**, which spreads each investment over its lifetime and adds the yearly operation:

$$\min \; a_{pv} P_{pv} + a_{wind} P_{wind} + a_{bess} E_{bess} + \pi^{imp} \sum_t g^{imp}_t - \pi^{exp} \sum_t g^{exp}_t$$

where $a_k = CAPEX_k \cdot CRF(r, n_k) + OPEX_k$ is the annual cost of 1 kW (or 1 kWh) of technology $k$, and $CRF(r, n) = \frac{r(1+r)^n}{(1+r)^n - 1}$ is the capital recovery factor for a discount rate $r$ and a lifetime of $n$ years.

### Constraints

* **Energy balance (every hour):** $P_{pv} \cdot pv_t + P_{wind} \cdot wind_t + g^{imp}_t + dis_t = demand_t + ch_t + g^{exp}_t + c_t$
* **Battery state of charge:** $soc_t = soc_{t-1} + \eta_{ch} \cdot ch_t - dis_t / \eta_{dis}$. The year is cyclic (the battery ends the year with the same charge it started with), so there is no free initial energy.
* **State of charge limits:** $SoC_{min} \cdot E_{bess} \leq soc_t \leq SoC_{max} \cdot E_{bess}$
* **Battery power limits:** $ch_t \leq C_{rate} \cdot E_{bess}$ and $dis_t \leq C_{rate} \cdot E_{bess}$
* **Optional:** maximum generation capacity $P_{pv} + P_{wind} \leq 50$ kW (Polish *mikroinstalacja* limit), minimum self-sufficiency $\sum_t g^{imp}_t \leq (1 - f_{min}) \sum_t demand_t$, grid import and export limits (`grid_import_max_kW=0` simulates an off-grid station) and upper bounds on each capacity.

### Default Parameters

All values are set in the `Parameters` class. The costs are reference estimates (EUR, 2025 prices, small commercial installations) and should be replaced by values with a cited source in the final report.

| Parameter | Default value | Field in `Parameters` |
|---|---|---|
| PV: CAPEX / OPEX / lifetime | 750 €/kW / 15 €/kW/year / 25 years | `pv` |
| Wind (small turbines): CAPEX / OPEX / lifetime | 3500 €/kW / 70 €/kW/year / 20 years | `wind` |
| Battery (LFP, with inverter): CAPEX / OPEX / lifetime | 350 €/kWh / 7 €/kWh/year / 12 years | `bess` |
| Discount rate | 6% | `discount_rate` |
| Grid import price | 0.22 €/kWh | `grid_import_price` |
| Grid export price | 0 €/kWh (0.06 €/kWh in the net-billing scenario) | `grid_export_price` |
| Battery charge / discharge efficiency | 0.95 / 0.95 (about 90% round trip) | `eta_charge`, `eta_discharge` |
| Battery state of charge limits | 10% to 90% | `soc_min`, `soc_max` |
| Battery C-rate | 0.5 (kW per kWh of capacity) | `c_rate` |
| Maximum PV + wind capacity | no limit (50 kW in the net-billing scenario) | `max_generation_kW` |

### Scenarios

Running `python optimizer.py` solves two cases:

1. **Net-billing (main scenario):** surplus energy is sold to the grid at 0.06 €/kWh, and the installed PV + wind capacity is limited to 50 kW to comply with the Polish *mikroinstalacja* legislation.
2. **Cost vs self-sufficiency (sensitivity analysis):** the model is solved for minimum self-sufficiency targets of 0%, 25%, 50%, 75% and 100% (share of the EV demand not bought from the grid). This sweep uses no export payment and no capacity limit, so it shows the cost of supplying the station with its own renewable energy. The output table also indicates which solutions fit within the 50 kW limit.

### Usage Example

```python
from dataclasses import replace
from optimizer import Parameters, net_billing_parameters, run_optimization, self_sufficiency_sweep

# Main scenario: returns a summary dict and an hourly DataFrame
summary, hourly = run_optimization(net_billing_parameters())
print(summary["PV capacity [kW]"], summary["Total annual cost [EUR/yr]"])

# Custom scenarios
summary, hourly = run_optimization(Parameters(grid_import_max_kW=0))   # off-grid station
summary, hourly = run_optimization(replace(net_billing_parameters(), grid_export_price=0.05))

# Cost vs self-sufficiency table (pandas DataFrame)
sweep = self_sufficiency_sweep()
```

### Output Files

| File | Content |
|---|---|
| `data/optimization_summary.csv` | Net-billing scenario: installed capacities, investment, annual costs and indicators (self-sufficiency, export, curtailment, battery cycles, savings compared with buying all energy from the grid) |
| `data/optimization_results_hourly.csv` | Net-billing scenario: hourly operation (demand, PV and wind production, grid import, export, curtailment, battery charge, discharge and state of charge) |
| `data/optimization_self_sufficiency_sweep.csv` | Optimal system and cost for each self-sufficiency target |

### Modeling Assumptions and Limitations

* **Perfect foresight:** the model knows the demand and the weather of the whole year in advance, so the battery operation is the best possible one. Real operation would be somewhat worse.
* **Continuous sizes:** capacities are not rounded to commercial panel, turbine or battery sizes. Discrete sizes would need integer variables (MILP).
* **Flat prices:** a single import price and a single export price are used, without time-of-use tariffs, contracted power charges or hourly market prices.
* **No degradation:** PV and battery degradation are not modeled. Battery replacement is included only through its 12-year lifetime in the annual cost.
* **Unbounded problem:** if the export price is higher than the cost of the energy produced by PV or wind, the optimal solution would be to install an infinite capacity. For this reason, a paid export always needs a capacity limit (`max_generation_kW` or `grid_export_max_kW`).
* **Input data:** the results inherit the assumptions of Phases 1 and 2 (wind at 10 m height, PV without losses). `load_data()` warns if the mean wind speed looks like km/h instead of m/s.

## Team Workflow

* Run `git pull` before starting to work, and again before each `git push`.
* To avoid merge conflicts, each phase should be developed in its own files (for example, Phase 3 in a new module such as `optimizer.py`).
* Do not edit the output of a previous phase by hand: change the corresponding module and regenerate the data.