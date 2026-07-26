import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).parent.parent

BASE_IDF = ROOT / "energyplus" / "base_model.idf"
MOD_IDF  = ROOT / "energyplus" / "modified_model.idf"
WEATHER  = ROOT / "energyplus" / "weather.epw"
OUT_DIR  = ROOT / "outputs"
LOG_DIR  = ROOT / "logs"

OUT_DIR.mkdir(exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)

# EnergyPlus binary path
EP_BINARY = os.getenv("ENERGYPLUS_BINARY", "energyplus")

# LLM settings (local Ollama only)
OLLAMA_URL   = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")

# Comfort targets per ASHRAE 55
TEMP_MIN   = float(os.getenv("TEMP_MIN", "21.0"))
TEMP_MAX   = float(os.getenv("TEMP_MAX", "24.0"))
PMV_MIN    = float(os.getenv("PMV_MIN", "-0.5"))
PMV_MAX    = float(os.getenv("PMV_MAX", "0.5"))
PEAK_KW    = float(os.getenv("PEAK_KW", "15.0"))
CARBON_INT = 0.233   # kg CO2/kWh, UK grid average

# Setpoint safety limits
HTG_MIN, HTG_MAX = 16.0, 23.0
CLG_MIN, CLG_MAX = 22.0, 30.0

SIM_TIMEOUT = int(os.getenv("SIM_TIMEOUT_SECONDS", "300"))
MAX_CYCLES  = int(os.getenv("MAX_LOOP_ITERATIONS", "10"))
