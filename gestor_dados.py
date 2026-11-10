import os
import pandas as pd
import requests

os.makedirs("data", exist_ok=True)

final_dataset_path = "data/processed_dataset_2025.csv"

if os.path.exists(final_dataset_path):
    print(f"[INFO] Processed dataset already exists at '{final_dataset_path}'.")
    print("[INFO] Skipping API request and reprocessing.")
    final_dataset = pd.read_csv(final_dataset_path, index_col="timestamp", parse_dates=True)
else:
    df_raw = pd.read_csv("data/ev_charging_dataset.csv")

    df_st013 = df_raw[df_raw["station_id"] == "ST013"][["timestamp", "energy_consumed_kWh"]].copy()

    df_st013["timestamp"] = pd.to_datetime(df_st013["timestamp"])
    df_st013 = df_st013.set_index("timestamp") #dataframe index

    hourly_demand = df_st013.resample("h").sum()

    full_year_index = pd.date_range(start="2025-01-01 00:00:00", end="2025-12-31 23:00:00", freq="h")
    hourly_demand = hourly_demand.reindex(full_year_index, fill_value=0.0)
    hourly_demand.index.name = "timestamp"

    api_url = "https://archive-api.open-meteo.com/v1/archive"
    params = {
        "latitude": 52.2297,
        "longitude": 21.0122,
        "start_date": "2025-01-01",
        "end_date": "2025-12-31",
        "hourly": ["shortwave_radiation", "wind_speed_10m"],
        "timezone": "UTC"
    }

    response = requests.get(api_url, params=params)

    if response.status_code == 200:
        weather_data = response.json()
        df_weather = pd.DataFrame({
            "timestamp": pd.to_datetime(weather_data["hourly"]["time"]),
            "solar_irradiance_W_m2": weather_data["hourly"]["shortwave_radiation"],
            "wind_speed_m_s": weather_data["hourly"]["wind_speed_10m"]
        })
        df_weather = df_weather.set_index("timestamp")
    else:
        raise ConnectionError(f"Open-Meteo API failed with status code: {response.status_code}")

    final_dataset = hourly_demand.join(df_weather, how="inner")

    #save processed load
    hourly_demand.to_csv("data/processed_ev_demand_2025.csv")
    print("Successfully exported 'processed_ev_demand_2025.csv'!")

    df_weather.to_csv("data/processed_weather_2025.csv")
    final_dataset.to_csv(final_dataset_path)

# 7. Print summary and display first 12 hours
print(f"Total hours in dataset: {len(final_dataset)}")
print("\nFirst 12 hours of energy consumption profile:")
print(final_dataset.head(12))