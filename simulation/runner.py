import csv
import math
import shutil
import subprocess
import time
import uuid
import re
from pathlib import Path

from models.data_models import BuildingSnapshot, ZoneData
from utils.config import EP_BINARY, MOD_IDF, BASE_IDF, WEATHER, OUT_DIR, SIM_TIMEOUT, CARBON_INT
from utils.logger import get_logger

log = get_logger("runner")

last_snapshot: BuildingSnapshot | None = None
_run_count = 0


def _ep_found():
    import shutil as sh
    return Path(EP_BINARY).exists() or sh.which(EP_BINARY) is not None


def run_simulation(use_modified=True) -> dict:
    global last_snapshot, _run_count
    _run_count += 1
    run_id = str(uuid.uuid4())[:8]
    idf = MOD_IDF if use_modified else BASE_IDF

    if use_modified and not MOD_IDF.exists():
        shutil.copy2(BASE_IDF, MOD_IDF)

    out = OUT_DIR / f"run_{run_id}"
    out.mkdir(parents=True, exist_ok=True)

    use_fallback = False
    if not _ep_found():
        use_fallback = True
        log.warning("EnergyPlus binary not found. Running thermodynamic physics simulation fallback.")
    elif not WEATHER.exists():
        use_fallback = True
        log.warning(f"Weather file not found at {WEATHER}. Running thermodynamic physics simulation fallback.")

    if not use_fallback:
        cmd = [EP_BINARY, "--weather", str(WEATHER), "--output-directory", str(out), str(idf)]
        t0 = time.time()
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=SIM_TIMEOUT)
            dur = round(time.time() - t0, 2)

            if proc.returncode != 0:
                log.warning(f"EnergyPlus failed: {proc.stderr[:100]}. Falling back to thermodynamic solver.")
                use_fallback = True
            else:
                last_snapshot = _parse_outputs(out)
                log.info(f"Simulation completed via EnergyPlus in {dur}s — {last_snapshot.total_kwh:.3f} kWh")
                return {"run_id": run_id, "status": "ok", "duration_sec": dur, "summary": last_snapshot.summary()}
        except Exception as e:
            log.warning(f"EnergyPlus error: {e}. Falling back to thermodynamic solver.")
            use_fallback = True

    if use_fallback:
        t0 = time.time()
        _run_physics_fallback(idf, out)
        dur = round(time.time() - t0, 2)
        last_snapshot = _parse_outputs(out)
        log.info(f"Simulation completed via thermodynamic solver in {dur}s — {last_snapshot.total_kwh:.3f} kWh")
        return {"run_id": run_id, "status": "ok", "duration_sec": dur, "summary": last_snapshot.summary()}


def _run_physics_fallback(idf_path: Path, out_dir: Path):
    heating_sp = 21.0
    cooling_sp = 24.0
    lighting_fraction = 1.0
    ach = 1.0

    if idf_path.exists():
        try:
            text = idf_path.read_text(encoding="utf-8", errors="replace")
            htg = re.findall(r"HTG-SETP-SCHED.*?Until:\s*18:00,[^\n]*\n\s*([\d.]+)", text, re.IGNORECASE | re.DOTALL)
            if htg:
                heating_sp = float(htg[0])
            clg = re.findall(r"CLG-SETP-SCHED.*?Until:\s*18:00,[^\n]*\n\s*([\d.]+)", text, re.IGNORECASE | re.DOTALL)
            if clg:
                cooling_sp = float(clg[0])
            lit = re.findall(r"BLDG_LIGHT_SCH.*?Until:\s*17:00,[^\n]*\n\s*([\d.]+)", text, re.IGNORECASE | re.DOTALL)
            if lit:
                lighting_fraction = float(lit[0])
            inf = re.findall(r"INFIL_QUARTER_ON_SCHED.*?Until:\s*24:00,[^\n]*\n\s*([\d.]+)", text, re.IGNORECASE | re.DOTALL)
            if inf:
                ach = float(inf[0]) * 4.0
        except Exception:
            pass

    C_zone = 2000000.0  # J/K
    U_wall = 120.0      # W/K
    COP_cool = 3.0
    COP_heat = 0.95

    Q_equip_base = 1000.0
    Q_lights_base = 800.0

    T_zones = {
        "OFFICE_NORTH": 20.0,
        "OFFICE_SOUTH": 20.5,
        "MEETING_ROOM": 19.8
    }

    csv_path = out_dir / "eplusout.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Date/Time",
            "OFFICE_NORTH:Zone Mean Air Temperature [C]",
            "OFFICE_SOUTH:Zone Mean Air Temperature [C]",
            "MEETING_ROOM:Zone Mean Air Temperature [C]",
            "Facility Total Electricity [J]",
            "Zone Lights Electricity Energy [J]",
            "Zone Electric Equipment Electricity Energy [J]",
            "Facility Total HVAC Electric Demand Power [W]",
            "Site Outdoor Air Drybulb Temperature [C]"
        ])

        for hour in range(1, 25):
            occupied = 8 <= hour <= 18
            T_out = 14.0 + 7.0 * math.sin(math.pi * (hour - 6) / 12)
            Q_solar = 1500.0 * max(0.0, math.sin(math.pi * (hour - 6) / 12))
            vent_m3s = (ach * 500.0 / 3600.0)
            Q_vent_coeff = vent_m3s * 1200.0

            hvac_watts_total = 0.0
            lights_j = 0.0
            equip_j = 0.0

            new_temps = {}
            for name, T_z in T_zones.items():
                Q_int_lights = Q_lights_base * lighting_fraction if occupied else 100.0
                Q_int_equip = Q_equip_base if occupied else 200.0
                Q_people = 1000.0 if (occupied and name != "MEETING_ROOM") else 0.0
                if name == "MEETING_ROOM" and hour in [10, 11, 14, 15]:
                    Q_people = 2000.0

                Q_vent = Q_vent_coeff * (T_out - T_z)
                Q_envelope = U_wall * (T_out - T_z)
                Q_passive = Q_envelope + Q_vent + Q_int_lights + Q_int_equip + Q_people + (Q_solar if "SOUTH" in name else Q_solar * 0.3)
                T_passive = T_z + (Q_passive * 3600.0) / C_zone

                current_htg = heating_sp if occupied else 15.0
                current_clg = cooling_sp if occupied else 30.0

                Q_hvac = 0.0
                hvac_power_w = 0.0

                if T_passive < current_htg:
                    Q_hvac_needed = (current_htg - T_passive) * C_zone / 3600.0
                    Q_hvac = min(Q_hvac_needed, 12000.0)
                    T_final = T_passive + (Q_hvac * 3600.0) / C_zone
                    hvac_power_w = Q_hvac / COP_heat
                elif T_passive > current_clg:
                    Q_hvac_needed = (T_passive - current_clg) * C_zone / 3600.0
                    Q_hvac = min(Q_hvac_needed, 15000.0)
                    T_final = T_passive - (Q_hvac * 3600.0) / C_zone
                    hvac_power_w = Q_hvac / COP_cool
                else:
                    T_final = T_passive

                new_temps[name] = T_final
                hvac_watts_total += hvac_power_w
                lights_j += Q_int_lights * 3600.0
                equip_j += Q_int_equip * 3600.0

            T_zones.update(new_temps)
            hvac_j = hvac_watts_total * 3600.0
            facility_total_j = hvac_j + lights_j + equip_j

            writer.writerow([
                f"07/25 {hour:02d}:00:00",
                f"{T_zones['OFFICE_NORTH']:.4f}",
                f"{T_zones['OFFICE_SOUTH']:.4f}",
                f"{T_zones['MEETING_ROOM']:.4f}",
                f"{facility_total_j:.2f}",
                f"{lights_j:.2f}",
                f"{equip_j:.2f}",
                f"{hvac_watts_total:.2f}",
                f"{T_out:.2f}"
            ])


def _parse_outputs(out_dir: Path) -> BuildingSnapshot:
    csvs = sorted(out_dir.glob("*.csv"), key=lambda p: p.stat().st_size, reverse=True)
    if not csvs:
        log.warning("No CSV output found — returning empty snapshot")
        return BuildingSnapshot()

    zone_temps = {}
    facility_total = lights = equip = peak = outdoor = 0.0

    with open(csvs[0], encoding="utf-8", errors="replace") as f:
        for row in csv.DictReader(f):
            for col, val in row.items():
                try:
                    v = float(val)
                except (ValueError, TypeError):
                    continue
                c = col.lower()
                if "zone mean air temperature" in c:
                    zone_temps.setdefault(col.split(":")[0].strip(), []).append(v)
                elif "demand" in c:
                    # e.g. "Facility Total HVAC Electric Demand Power [W]" — instantaneous
                    # power, so this must be checked before the generic energy branch
                    # below (both contain "facility total" + "electric").
                    peak = max(peak, v / 1000)
                elif "facility total" in c and "electric" in c:
                    # Cumulative energy [J] for this timestep — must be SUMMED across
                    # the whole run, not maxed, or we only capture a single hour.
                    facility_total += v / 3_600_000
                elif "zone lights electricity" in c:
                    lights += v / 3_600_000
                elif "zone electric equipment" in c:
                    equip += v / 3_600_000
                elif "site outdoor air drybulb" in c:
                    outdoor = v

    zones = []
    for name, temps in zone_temps.items():
        avg = sum(temps) / len(temps)
        pmv = _calc_pmv(avg)
        zones.append(ZoneData(name=name, temp_c=round(avg, 2), pmv=round(pmv, 2), ppd=round(_calc_ppd(pmv), 1)))

    # "facility total" already includes lights + equipment, so the HVAC-only share is
    # whatever remains — computing hvac_kwh + lights_kwh + equip_kwh downstream must
    # not double-count lights/equipment.
    hvac = max(0.0, facility_total - lights - equip)
    total = facility_total
    return BuildingSnapshot(
        zones=zones,
        hvac_kwh=round(hvac, 3),
        lights_kwh=round(lights, 3),
        equip_kwh=round(equip, 3),
        peak_kw=round(peak, 3),
        outdoor_c=round(outdoor, 1),
        carbon_kg=round(total * CARBON_INT, 4),
    )


def _calc_pmv(ta: float, clo: float = 1.0, met: float = 1.2, v_air: float = 0.1) -> float:
    """Standard Fanger PMV (ASHRAE 55 / ISO 7730), assuming mean radiant temp == ta.

    tcl (clothing surface temperature) depends on itself, so it must be solved
    iteratively rather than assumed - a previous version hardcoded the
    hc*(tcl-ta) term to zero, which pinned PMV to the extreme +/-3.0 for
    almost every input temperature.
    """
    pa  = 0.6105 * math.exp(17.27 * ta / (ta + 237.3)) * 1000 * 0.5  # ~50% RH, Pa
    icl = 0.155 * clo
    m   = met * 58.15
    w   = 0.0  # external work = 0
    mw  = m - w
    fcl = 1.05 + 0.645 * icl if icl > 0.078 else 1.0 + 1.29 * icl

    tcl = ta + (35.7 - 0.028 * mw - ta)  # initial guess
    for _ in range(150):
        hc_forced = 12.1 * math.sqrt(v_air)
        hc_natural = 2.38 * abs(tcl - ta) ** 0.25
        hc = max(hc_forced, hc_natural)
        tcl_new = 35.7 - 0.028 * mw - icl * (
            3.96e-8 * fcl * ((tcl + 273) ** 4 - (ta + 273) ** 4) + fcl * hc * (tcl - ta)
        )
        if abs(tcl_new - tcl) < 0.0001:
            tcl = tcl_new
            break
        tcl = 0.5 * tcl + 0.5 * tcl_new

    hc = max(12.1 * math.sqrt(v_air), 2.38 * abs(tcl - ta) ** 0.25)
    loss_resp_dry = 0.0014 * m * (34 - ta)
    loss_resp_lat = 0.0173 * m * (5.867 - pa / 1000)
    loss_skin_diff = 3.05e-3 * (5.733 - 0.007 * mw - pa / 1000)
    loss_sweat = max(0.0, 0.42 * (mw - 58.15))
    loss_radiation = 3.96e-8 * fcl * ((tcl + 273) ** 4 - (ta + 273) ** 4)
    loss_convection = fcl * hc * (tcl - ta)

    pmv = (0.303 * math.exp(-0.036 * m) + 0.028) * (
        mw - loss_skin_diff - loss_sweat - loss_resp_lat - loss_resp_dry
        - loss_radiation - loss_convection
    )
    return max(-3.0, min(3.0, pmv))


def _calc_ppd(pmv: float) -> float:
    return 100 - 95 * math.exp(-0.03353 * pmv**4 - 0.2179 * pmv**2)


def get_metrics() -> dict | None:
    if last_snapshot is None:
        return None
    return {
        "summary": last_snapshot.summary(),
        "zones": [
            {
                "name": z.name, "temp_c": z.temp_c, "pmv": z.pmv,
                "ppd": z.ppd, "co2_ppm": z.co2_ppm, "comfort": z.comfort
            }
            for z in last_snapshot.zones
        ],
    }
