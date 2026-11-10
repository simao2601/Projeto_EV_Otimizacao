from gestor_dados import load_processed_data
import pandas as pd

def calculate_energy_model():
    # 1. Carregar os dados limpos das 8760 horas
    df = load_processed_data()
    
    print("A calcular a produção de energia para 1 kW nominal...")
    
    # --- MODELO SOLAR FOTOVOLTAICO ---
    # Conversão simplificada: Irradiação (W/m2) para Potência (kW) com base em 1 kW nominal
    # Assumimos uma eficiência padrão ou fator de conversão (ex: STC irradiance = 1000 W/m2)
    pv_capacity_kW = 1.0 
    df['pv_power_kW'] = (df['solar_irradiance_W_m2'] / 1000.0) * pv_capacity_kW
    
    # --- MODELO EÓLICO ---
    # Curva de potência típica de uma turbina eólica (simplificada por secções ou cúbica com limites)
    # v_ci (cut-in) = 3 m/s, v_r (rated) = 12 m/s, v_co (cut-out) = 25 m/s
    def wind_power_output(v):
        if v < 3.0 or v > 25.0:
            return 0.0
        elif v >= 12.0:
            return 1.0 # 1 kW nominal atingido
        else:
            # Curva cúbica simplificada entre cut-in e rated
            return 1.0 * ((v - 3.0) / (12.0 - 3.0))**3

    wind_capacity_kW = 1.0
    df['wind_power_kW'] = df['wind_speed_m_s'].apply(wind_power_output) * wind_capacity_kW
    
    print("\nPrimeiras horas do Modelo de Energia (PV e Vento calculados):")
    print(df[['energy_consumed_kWh', 'solar_irradiance_W_m2', 'pv_power_kW', 'wind_speed_m_s', 'wind_power_kW']].head())
    
    return df

if __name__ == "__main__":
    calculate_energy_model()