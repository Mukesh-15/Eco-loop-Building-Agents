from dataclasses import dataclass, field
from datetime import datetime
from typing import List
import math


@dataclass
class ZoneData:
    name: str
    temp_c: float
    pmv: float
    ppd: float
    co2_ppm: float = 500.0
    humidity: float = 50.0

    @property
    def comfort(self):
        if self.pmv > 1.5:  return "hot"
        if self.pmv > 0.5:  return "warm"
        if self.pmv < -1.5: return "cold"
        if self.pmv < -0.5: return "cool"
        return "comfortable"


@dataclass
class BuildingSnapshot:
    zones: List[ZoneData] = field(default_factory=list)
    hvac_kwh: float = 0.0
    lights_kwh: float = 0.0
    equip_kwh: float = 0.0
    peak_kw: float = 0.0
    outdoor_c: float = 15.0
    carbon_kg: float = 0.0
    sim_hour: float = 12.0
    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def total_kwh(self):
        return self.hvac_kwh + self.lights_kwh + self.equip_kwh

    @property
    def avg_temp(self):
        return sum(z.temp_c for z in self.zones) / len(self.zones) if self.zones else 22.0

    @property
    def avg_pmv(self):
        return sum(z.pmv for z in self.zones) / len(self.zones) if self.zones else 0.0

    def summary(self):
        return {
            "total_kwh": round(self.total_kwh, 3),
            "avg_temp_c": round(self.avg_temp, 2),
            "avg_pmv": round(self.avg_pmv, 3),
            "peak_kw": round(self.peak_kw, 3),
            "carbon_kg": round(self.carbon_kg, 4),
            "outdoor_c": self.outdoor_c,
            "sim_hour": self.sim_hour,
        }
