"""
Phase 3: Optimal sizing of PV, wind turbines and battery storage (BESS)
for EV charging station ST013 (Rzeszow, Poland).

Model: Linear Programming (LP) over 8760 hourly time steps (1 h each).
Solver: HiGHS through PuLP  ->  pip install pulp highspy pandas

Sizing variables
    P_pv     installed PV capacity        [kW]
    P_wind   installed wind capacity      [kW]
    E_bess   battery energy capacity      [kWh]

Hourly variables (t = 0 .. 8759), all >= 0
    grid_import[t]   energy bought from the grid          [kWh]
    export[t]        surplus sold to the grid (net-billing) [kWh]
    curtail[t]       surplus that is wasted               [kWh]
    charge[t]        energy into the battery              [kWh]
    discharge[t]     energy out of the battery            [kWh]
    soc[t]           battery state of charge (end of t)   [kWh]

Objective: minimize the Equivalent Annual Cost (EAC)
    sum_k (CAPEX_k * CRF(r, n_k) + OPEX_k) * Size_k
    + import_price * sum_t grid_import[t]  -  export_price * sum_t export[t]

Constraints (every hour t)
    Energy balance:
        P_pv*pv[t] + P_wind*wind[t] + grid_import[t] + discharge[t]
            == demand[t] + charge[t] + export[t] + curtail[t]
    Battery (cyclic year, hour -1 = last hour):
        soc[t] == soc[t-1] + eta_ch*charge[t] - discharge[t]/eta_dis
        soc_min*E_bess <= soc[t] <= soc_max*E_bess
        charge[t], discharge[t] <= c_rate*E_bess
    Grid limits: grid_import[t] <= grid_import_max, export[t] <= grid_export_max
Optional
    P_pv + P_wind <= max_generation_kW   (50 kW "mikroinstalacja" limit)
    sum grid_import <= (1 - min_self_sufficiency) * sum demand
    Upper bounds on P_pv, P_wind and E_bess

Scenarios run by this script
    1. Net-billing (main): surplus sold at 0.06 EUR/kWh, P_pv + P_wind <= 50 kW.
    2. Self-sufficiency sweep (0-100%): no export payment and no capacity
       limit, to show the cost of supplying the station with renewables.
"""

from dataclasses import dataclass, field, replace
import time
import warnings

import pandas as pd
import pulp

DATA_PATH = "data/energy_model_output.csv"
HOURLY_OUTPUT_PATH = "data/optimization_results_hourly.csv"
SUMMARY_OUTPUT_PATH = "data/optimization_summary.csv"
SWEEP_OUTPUT_PATH = "data/optimization_self_sufficiency_sweep.csv"

REQUIRED_COLUMNS = ["energy_consumed_kWh", "pv_power_kW", "wind_power_kW"]
MIKROINSTALACJA_LIMIT_KW = 50.0
SOLVER_STATUS = {1: "Optimal", 0: "Not Solved", -1: "Infeasible", -2: "Unbounded", -3: "Undefined"}


# ---------------------------------------------------------------------------
# Parameters
# ---------------------------------------------------------------------------

def capital_recovery_factor(rate, years):
    """CRF: converts an upfront investment into an equivalent annual payment."""
    if rate == 0:
        return 1.0 / years
    return rate * (1 + rate) ** years / ((1 + rate) ** years - 1)


@dataclass
class Technology:
    capex: float     # EUR/kW (EUR/kWh for the battery)
    opex: float      # EUR/kW/year (EUR/kWh/year for the battery)
    lifetime: int    # years

    def annual_cost_per_unit(self, discount_rate):
        """Annualized CAPEX + fixed OPEX of 1 kW (or 1 kWh) installed."""
        return self.capex * capital_recovery_factor(discount_rate, self.lifetime) + self.opex


@dataclass
class Parameters:
    """Reference values in EUR (2025 prices, small commercial scale, Poland)."""
    # Technologies
    pv: Technology = field(default_factory=lambda: Technology(capex=750.0, opex=15.0, lifetime=25))
    wind: Technology = field(default_factory=lambda: Technology(capex=3500.0, opex=70.0, lifetime=20))
    bess: Technology = field(default_factory=lambda: Technology(capex=350.0, opex=7.0, lifetime=12))
    discount_rate: float = 0.06

    # Grid
    grid_import_price: float = 0.22          # EUR/kWh (energy + distribution + fees, no VAT)
    grid_export_price: float = 0.0           # EUR/kWh (0 = surplus is not paid)
    grid_import_max_kW: float | None = None  # None = unlimited, 0 = off-grid
    grid_export_max_kW: float | None = None  # None = unlimited

    # Battery operation
    eta_charge: float = 0.95                 # round-trip = 0.95 * 0.95 ~ 0.90
    eta_discharge: float = 0.95
    soc_min: float = 0.10                    # fraction of E_bess
    soc_max: float = 0.90
    c_rate: float = 0.5                      # max power [kW] per kWh of capacity

    # Optional limits
    max_generation_kW: float | None = None   # limit on P_pv + P_wind
    pv_max_kW: float | None = None
    wind_max_kW: float | None = None
    bess_max_kWh: float | None = None
    min_self_sufficiency: float | None = None  # 0.5 = at least 50% of demand not from grid


def net_billing_parameters():
    """Main scenario: net-billing at 0.06 EUR/kWh within the 50 kW mikroinstalacja limit."""
    return Parameters(grid_export_price=0.06, max_generation_kW=MIKROINSTALACJA_LIMIT_KW)


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

def load_data(path=DATA_PATH):
    """Loads the Phase 2 output and checks that it is usable by the model."""
    raw = pd.read_csv(path, index_col="timestamp", parse_dates=True)

    missing = [c for c in REQUIRED_COLUMNS if c not in raw.columns]
    if missing:
        raise ValueError(f"Missing columns in '{path}': {missing}")

    df = raw[REQUIRED_COLUMNS].astype(float)

    if len(df) != 8760:
        warnings.warn(f"Expected 8760 hourly rows, found {len(df)}.")
    if df.isna().any().any():
        raise ValueError("The dataset contains missing values (NaN).")
    if (df < 0).any().any():
        raise ValueError("The dataset contains negative values.")
    if df["pv_power_kW"].max() > 1.2 or df["wind_power_kW"].max() > 1.0 + 1e-9:
        warnings.warn("pv_power_kW / wind_power_kW should be normalized to 1 kW installed.")

    # Mean 10 m wind speed in Poland is about 3-4 m/s; a much higher mean
    # usually means the data is in km/h.
    if "wind_speed_m_s" in raw.columns and raw["wind_speed_m_s"].mean() > 7.0:
        warnings.warn(
            f"Mean wind speed is {raw['wind_speed_m_s'].mean():.1f} m/s, which is unrealistic "
            "at 10 m height. The data may be in km/h."
        )

    return df


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------

def _new_var(prob, name, up=None):
    """Non-negative continuous variable (PuLP 2.x/3.x and 4.x)."""
    if hasattr(prob, "add_variable"):   # PuLP >= 4.0
        return prob.add_variable(name, lowBound=0, upBound=up)
    return pulp.LpVariable(name, lowBound=0, upBound=up)


def _new_var_dict(prob, name, indices, up=None):
    """Dict {t: variable} of non-negative continuous variables."""
    if hasattr(prob, "add_variable_dict"):   # PuLP >= 4.0
        return prob.add_variable_dict(name, indices, lowBound=0, upBound=up)
    return pulp.LpVariable.dicts(name, indices, lowBound=0, upBound=up)


def build_model(df, p):
    """Builds the LP model. Returns the PuLP problem and a dict with its variables."""
    T = range(len(df))
    last = len(df) - 1
    demand = df["energy_consumed_kWh"].tolist()
    pv_cf = df["pv_power_kW"].tolist()
    wind_cf = df["wind_power_kW"].tolist()

    prob = pulp.LpProblem("ST013_PV_Wind_BESS_sizing", pulp.LpMinimize)

    # Sizing variables
    P_pv = _new_var(prob, "P_pv_kW", up=p.pv_max_kW)
    P_wind = _new_var(prob, "P_wind_kW", up=p.wind_max_kW)
    E_bess = _new_var(prob, "E_bess_kWh", up=p.bess_max_kWh)

    # Hourly variables. Without export payment (or off-grid) all surplus is curtailment.
    export_cap = p.grid_export_max_kW
    if p.grid_export_price <= 0 or p.grid_import_max_kW == 0:
        export_cap = 0.0
    grid_import = _new_var_dict(prob, "grid_import", T, up=p.grid_import_max_kW)
    export = _new_var_dict(prob, "export", T, up=export_cap)
    curtail = _new_var_dict(prob, "curtail", T)
    charge = _new_var_dict(prob, "charge", T)
    discharge = _new_var_dict(prob, "discharge", T)
    soc = _new_var_dict(prob, "soc", T)

    # Objective: equivalent annual cost
    a_pv = p.pv.annual_cost_per_unit(p.discount_rate)
    a_wind = p.wind.annual_cost_per_unit(p.discount_rate)
    a_bess = p.bess.annual_cost_per_unit(p.discount_rate)
    prob += (
        a_pv * P_pv + a_wind * P_wind + a_bess * E_bess
        + p.grid_import_price * pulp.lpSum(grid_import.values())
        - p.grid_export_price * pulp.lpSum(export.values())
    ), "equivalent_annual_cost"

    # Hourly constraints
    for t in T:
        prob += (
            pv_cf[t] * P_pv + wind_cf[t] * P_wind + grid_import[t] + discharge[t]
            == demand[t] + charge[t] + export[t] + curtail[t]
        ), f"balance_{t}"

        soc_prev = soc[t - 1] if t > 0 else soc[last]
        prob += (
            soc[t] == soc_prev + p.eta_charge * charge[t] - (1.0 / p.eta_discharge) * discharge[t]
        ), f"soc_dynamics_{t}"

        prob += soc[t] >= p.soc_min * E_bess, f"soc_min_{t}"
        prob += soc[t] <= p.soc_max * E_bess, f"soc_max_{t}"
        prob += charge[t] <= p.c_rate * E_bess, f"charge_power_{t}"
        prob += discharge[t] <= p.c_rate * E_bess, f"discharge_power_{t}"

    # Optional global constraints
    if p.max_generation_kW is not None:
        prob += P_pv + P_wind <= p.max_generation_kW, "max_generation_capacity"

    if p.min_self_sufficiency is not None:
        prob += (
            pulp.lpSum(grid_import.values()) <= (1.0 - p.min_self_sufficiency) * sum(demand)
        ), "min_self_sufficiency"

    variables = {
        "P_pv": P_pv, "P_wind": P_wind, "E_bess": E_bess,
        "grid_import": grid_import, "export": export, "curtail": curtail,
        "charge": charge, "discharge": discharge, "soc": soc,
    }
    return prob, variables


def get_solver(msg=False, time_limit=None):
    """HiGHS if available, otherwise any other solver PuLP can find."""
    highs = pulp.HiGHS(msg=msg, timeLimit=time_limit)
    if highs.available():
        return highs
    available = pulp.listSolvers(onlyAvailable=True)
    if available:
        return pulp.getSolver(available[0], msg=msg)
    raise RuntimeError("No LP solver found. Install HiGHS with: pip install highspy")


def solve_model(prob, msg=False, time_limit=None):
    solver = get_solver(msg=msg, time_limit=time_limit)
    start = time.perf_counter()
    result = prob.solve(solver)
    elapsed = time.perf_counter() - start
    # PuLP 4.x returns a stats object with .status, PuLP 2.x/3.x an int (1 = Optimal).
    code = int(getattr(result, "status", result))
    if code != 1:
        status = SOLVER_STATUS.get(code, f"code {code}")
        hint = ""
        if code == -2:
            hint = (" An export price above the cost of PV/wind energy with no capacity "
                    "limit makes the problem unbounded: set max_generation_kW or grid_export_max_kW.")
        raise RuntimeError(f"Solver did not reach an optimal solution ({status}).{hint}")
    return "Optimal", elapsed


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------

def _value(var):
    """Variable value with solver noise (|v| < 1e-9) removed."""
    v = var.value() or 0.0
    return v if abs(v) > 1e-9 else 0.0


def extract_results(df, variables, p):
    """Returns (summary dict, hourly DataFrame)."""
    T = range(len(df))
    P_pv = _value(variables["P_pv"])
    P_wind = _value(variables["P_wind"])
    E_bess = _value(variables["E_bess"])

    hourly = pd.DataFrame(index=df.index)
    hourly["demand_kWh"] = df["energy_consumed_kWh"]
    hourly["pv_kWh"] = P_pv * df["pv_power_kW"]
    hourly["wind_kWh"] = P_wind * df["wind_power_kW"]
    for name in ["grid_import", "export", "curtail", "charge", "discharge", "soc"]:
        hourly[f"{name}_kWh"] = [_value(variables[name][t]) for t in T]

    demand = hourly["demand_kWh"].sum()
    imported = hourly["grid_import_kWh"].sum()
    exported = hourly["export_kWh"].sum()
    curtailed = hourly["curtail_kWh"].sum()
    generation = hourly["pv_kWh"].sum() + hourly["wind_kWh"].sum()

    cost_pv = P_pv * p.pv.annual_cost_per_unit(p.discount_rate)
    cost_wind = P_wind * p.wind.annual_cost_per_unit(p.discount_rate)
    cost_bess = E_bess * p.bess.annual_cost_per_unit(p.discount_rate)
    cost_grid = imported * p.grid_import_price
    revenue_export = exported * p.grid_export_price
    total = cost_pv + cost_wind + cost_bess + cost_grid - revenue_export
    baseline = demand * p.grid_import_price   # station supplied 100% by the grid

    summary = {
        "PV capacity [kW]": P_pv,
        "Wind capacity [kW]": P_wind,
        "PV + wind capacity [kW]": P_pv + P_wind,
        "Battery capacity [kWh]": E_bess,
        "Battery power [kW]": E_bess * p.c_rate,
        "Initial investment CAPEX [EUR]": P_pv * p.pv.capex + P_wind * p.wind.capex + E_bess * p.bess.capex,
        "Annual cost PV [EUR/yr]": cost_pv,
        "Annual cost wind [EUR/yr]": cost_wind,
        "Annual cost battery [EUR/yr]": cost_bess,
        "Annual cost grid import [EUR/yr]": cost_grid,
        "Annual revenue export [EUR/yr]": revenue_export,
        "Total annual cost [EUR/yr]": total,
        "Grid-only baseline cost [EUR/yr]": baseline,
        "Annual savings vs grid-only [EUR/yr]": baseline - total,
        "Cost per kWh supplied [EUR/kWh]": total / demand if demand > 0 else float("nan"),
        "EV demand [kWh/yr]": demand,
        "Renewable generation [kWh/yr]": generation,
        "Grid import [kWh/yr]": imported,
        "Export [kWh/yr]": exported,
        "Curtailed [kWh/yr]": curtailed,
        "Self-sufficiency [%]": 100 * (1 - imported / demand) if demand > 0 else float("nan"),
        "Self-consumption of generation [%]": (
            100 * (generation - exported - curtailed) / generation if generation > 0 else 0.0
        ),
        "Battery equivalent cycles [1/yr]": hourly["discharge_kWh"].sum() / E_bess if E_bess > 0 else 0.0,
    }
    return summary, hourly


def run_optimization(params=None, data_path=DATA_PATH, df=None, msg=False):
    """Load data (unless df is given), build, solve and extract results."""
    params = params or Parameters()
    if df is None:
        df = load_data(data_path)
    prob, variables = build_model(df, params)
    status, elapsed = solve_model(prob, msg=msg)
    summary, hourly = extract_results(df, variables, params)
    summary["Solver status"] = status
    summary["Solve time [s]"] = elapsed
    return summary, hourly


SWEEP_COLUMNS = [
    "PV capacity [kW]", "Wind capacity [kW]", "Battery capacity [kWh]",
    "Initial investment CAPEX [EUR]", "Total annual cost [EUR/yr]",
    "Cost per kWh supplied [EUR/kWh]", "Curtailed [kWh/yr]",
]


def self_sufficiency_sweep(levels=(0.0, 0.25, 0.5, 0.75, 1.0), params=None, data_path=DATA_PATH, df=None):
    """Optimal system and cost for each minimum self-sufficiency target."""
    base = params or Parameters()
    if df is None:
        df = load_data(data_path)
    rows = []
    for level in levels:
        summary, _ = run_optimization(replace(base, min_self_sufficiency=level), df=df)
        row = {"Self-sufficiency [%]": 100 * level, **{k: summary[k] for k in SWEEP_COLUMNS}}
        row["Within 50 kW limit"] = summary["PV + wind capacity [kW]"] <= MIKROINSTALACJA_LIMIT_KW + 1e-6
        rows.append(row)
    return pd.DataFrame(rows)


def print_summary(summary, title):
    print("--------------------------------------------------")
    print(f">>> {title}")
    print("--------------------------------------------------")
    for key, value in summary.items():
        if isinstance(value, float):
            print(f"{key:<40} {value:>14,.2f}")
        else:
            print(f"{key:<40} {value:>14}")
    print("--------------------------------------------------")


if __name__ == "__main__":
    data = load_data()

    # 1. Main scenario: net-billing within the 50 kW mikroinstalacja limit
    summary, hourly = run_optimization(net_billing_parameters(), df=data)
    print_summary(summary, "NET-BILLING SCENARIO (0.06 EUR/kWh, PV + wind <= 50 kW)")
    hourly.to_csv(HOURLY_OUTPUT_PATH)
    pd.Series(summary, name="value").to_csv(SUMMARY_OUTPUT_PATH, header=True)
    print(f"[SUCCESS] Hourly results exported to '{HOURLY_OUTPUT_PATH}'.")
    print(f"[SUCCESS] Summary exported to '{SUMMARY_OUTPUT_PATH}'.")

    # 2. Sensitivity: cost of each self-sufficiency target
    #    (no export payment, no capacity limit)
    print("\n>>> COST VS SELF-SUFFICIENCY (no export payment, no capacity limit)")
    sweep = self_sufficiency_sweep(df=data)
    print(sweep.round(2).to_string(index=False))
    sweep.to_csv(SWEEP_OUTPUT_PATH, index=False)
    print(f"[SUCCESS] Sweep exported to '{SWEEP_OUTPUT_PATH}'.")
