import pandas as pd
from gestor_dados import load_processed_data

def calculate_energy_model():
    """
    Calculates solar PV and wind power output for 1 kW nominal capacity.
    """
    
    # Load dataset from Phase 1 module
    df = load_processed_data()
    
    # Print introductory section header
    print("--------------------------------------------------")
    print(">>> CALCULATING ENERGY MODEL (1 kW NOMINAL) ...")
    print("--------------------------------------------------")
    
    # Set target nominal solar capacity to 1 kW
    pv_capacity_kW = 1.0 
    
    # Convert solar irradiance (W/m2) into kW using STC reference (1000 W/m2)
    df['pv_power_kW'] = (df['solar_irradiance_W_m2'] / 1000.0) * pv_capacity_kW
    
    # Define function to map wind speed to generated power
    def wind_power_output(v):
        # Return 0 kW if wind speed is below cut-in (3 m/s) or above cut-out (25 m/s)
        if v < 3.0 or v > 25.0:
            return 0.0
        # Return 1 kW max power if wind speed reaches rated speed (12 m/s)
        elif v >= 12.0:
            return 1.0 
        # Calculate cubic power curve for intermediate wind speeds between 3 and 12 m/s
        else:
            return 1.0 * ((v - 3.0) / (12.0 - 3.0))**3

    # Set target nominal wind capacity to 1 kW
    wind_capacity_kW = 1.0
    
    # Apply wind power function row by row to create new column
    df['wind_power_kW'] = df['wind_speed_m_s'].apply(wind_power_output) * wind_capacity_kW
    
    # Print completion status and dataset summary message
    print("\n[SUCCESS] Full annual energy model (8760 hours) calculated successfully.")
    print(f"Total rows in DataFrame: {len(df)}")
    print("Showing preview of the first 5 hours:\n")
    
    # Print preview of the first 5 rows
    print(df[['energy_consumed_kWh', 'solar_irradiance_W_m2', 'pv_power_kW', 'wind_speed_m_s', 'wind_power_kW']].head(5))
    
    # Print informative note about full dataset availability in memory
    print("\nNote: The complete 8760-hour time-series is stored in the returned DataFrame.")
    print("--------------------------------------------------")
    
    # Return full calculated dataframe
    return df

# Check if script is run directly
if __name__ == "__main__":
    # Execute energy model function
    calculate_energy_model()