import re
import csv
import shutil
from datetime import datetime

import simulation.runner as sim
from utils.config import (
    BASE_IDF, MOD_IDF, CARBON_INT,
    TEMP_MIN, TEMP_MAX, PMV_MIN, PMV_MAX, PEAK_KW, OUT_DIR,
    HTG_MIN, HTG_MAX, CLG_MIN, CLG_MAX
)
from utils.logger import get_logger

log = get_logger("tools")

_baseline_runs = []
_optimised_runs = []


def tool_run_simulation(use_modified: bool = True):
    return sim.run_simulation(use_modified)


def tool_read_metrics():
    m = sim.get_metrics()
    if m is None:
        return {"error": "No simulation data yet. Run run_simulation first."}
    return m


def tool_parse_errors():
    return {"note": "Check the outputs/ folder for EnergyPlus .err files after each run."}


def tool_get_building_state():
    m = sim.get_metrics()
    if not m:
        return "No simulation data yet."
    s = m["summary"]
    lines = [
        f"Hour {s['sim_hour']:.0f}:00 | Outdoor {s['outdoor_c']}C",
        f"Energy: {s['total_kwh']} kWh | Peak: {s['peak_kw']} kW | Carbon: {s['carbon_kg']} kg CO2",
        "Zones:"
    ]
    for z in m["zones"]:
        lines.append(f"  {z['name']}: {z['temp_c']}C | PMV {z['pmv']:+.2f} | CO2 {z['co2_ppm']} ppm | {z['comfort']}")
    return "\n".join(lines)


def _read_idf():
    MOD_IDF.parent.mkdir(parents=True, exist_ok=True)
    if not MOD_IDF.exists():
        if BASE_IDF.exists():
            shutil.copy2(BASE_IDF, MOD_IDF)
        else:
            raise FileNotFoundError(f"Base IDF not found at {BASE_IDF}. Check your energyplus/ directory.")
    return MOD_IDF.read_text(encoding="utf-8", errors="replace")


def _write_idf(text):
    MOD_IDF.write_text(text, encoding="utf-8")


def tool_reset_idf():
    if not BASE_IDF.exists():
        return {"status": "error", "msg": f"base_model.idf not found at {BASE_IDF}"}
    shutil.copy2(BASE_IDF, MOD_IDF)
    return {"status": "ok", "msg": "IDF reset to baseline"}


def tool_set_heating_setpoint(zone: str, setpoint_c: float):
    setpoint_c = float(setpoint_c)
    sp = max(HTG_MIN, min(HTG_MAX, setpoint_c))
    text = _read_idf()
    text = re.sub(
        r"(HTG-SETP-SCHED.*?Until:\s*18:00,[^\n]*\n\s*)([\d.]+)",
        lambda m: m.group(1) + str(sp),
        text, flags=re.IGNORECASE | re.DOTALL
    )
    _write_idf(text)
    log.info(f"Heating setpoint set to {sp}C (zone={zone})")
    return {"status": "ok", "zone": zone, "heating_sp": sp}


def tool_set_cooling_setpoint(zone: str, setpoint_c: float):
    setpoint_c = float(setpoint_c)
    sp = max(CLG_MIN, min(CLG_MAX, setpoint_c))
    text = _read_idf()
    text = re.sub(
        r"(CLG-SETP-SCHED.*?Until:\s*18:00,[^\n]*\n\s*)([\d.]+)",
        lambda m: m.group(1) + str(sp),
        text, flags=re.IGNORECASE | re.DOTALL
    )
    _write_idf(text)
    log.info(f"Cooling setpoint set to {sp}C (zone={zone})")
    return {"status": "ok", "zone": zone, "cooling_sp": sp}


def tool_set_ventilation_rate(zone: str, ach: float):
    ach = float(ach)
    ach = max(0.3, min(10.0, ach))
    text = _read_idf()
    text = re.sub(
        r"(INFIL_QUARTER_ON_SCHED.*?Until:\s*24:00,[^\n]*\n\s*)([\d.]+)",
        lambda m: m.group(1) + str(round(ach / 4, 4)),
        text, flags=re.IGNORECASE | re.DOTALL
    )
    _write_idf(text)
    return {"status": "ok", "zone": zone, "ach": ach}


def tool_set_lighting_schedule(zone: str, fraction: float):
    fraction = float(fraction)
    fraction = max(0.0, min(1.0, fraction))
    text = _read_idf()
    text = re.sub(
        r"(BLDG_LIGHT_SCH.*?Until:\s*17:00,[^\n]*\n\s*)([\d.]+)",
        lambda m: m.group(1) + str(fraction),
        text, flags=re.IGNORECASE | re.DOTALL
    )
    _write_idf(text)
    return {"status": "ok", "zone": zone, "lighting_fraction": fraction}


def tool_apply_ecm(ecm_name: str):
    ecm = ecm_name.lower()
    if ecm == "setback_night":
        tool_set_heating_setpoint("all", 18.0)
        tool_set_cooling_setpoint("all", 28.0)
    elif ecm == "demand_response":
        tool_set_lighting_schedule("all", 0.7)
        tool_set_cooling_setpoint("all", 26.0)
    elif ecm == "economizer_mode":
        tool_set_ventilation_rate("all", 4.0)
    elif ecm == "optimal_start":
        text = _read_idf()
        text = re.sub(
            r"(HTG-SETP-SCHED.*?)Until:\s*08:00,([^\n]*\n\s*21\.0)",
            lambda m: m.group(1) + "Until: 07:30," + m.group(2),
            text, count=1, flags=re.IGNORECASE | re.DOTALL
        )
        _write_idf(text)
    else:
        return {"status": "error", "msg": f"Unknown ECM: {ecm}. Available: setback_night, demand_response, economizer_mode, optimal_start"}
    log.info(f"ECM applied: {ecm}")
    return {"status": "ok", "ecm": ecm}


def tool_get_setpoints():
    text = _read_idf()
    htg = re.findall(r"HTG-SETP-SCHED.*?Until:\s*18:00,[^\n]*\n\s*([\d.]+)", text, re.DOTALL | re.IGNORECASE)
    clg = re.findall(r"CLG-SETP-SCHED.*?Until:\s*18:00,[^\n]*\n\s*([\d.]+)", text, re.DOTALL | re.IGNORECASE)
    return {
        "heating_sp": float(htg[0]) if htg else None,
        "cooling_sp": float(clg[0]) if clg else None,
    }


def tool_compute_savings(baseline_kwh: float, optimised_kwh: float,
                         baseline_peak_kw: float = 0.0, optimised_peak_kw: float = 0.0):
    saved = max(0.0, baseline_kwh - optimised_kwh)
    pct   = (saved / baseline_kwh * 100) if baseline_kwh > 0 else 0.0
    return {
        "baseline_kwh":       round(baseline_kwh, 3),
        "optimised_kwh":      round(optimised_kwh, 3),
        "energy_savings_kwh": round(saved, 3),
        "energy_savings_pct": round(pct, 2),
        "carbon_saved_kg":    round(saved * CARBON_INT, 4),
        "cost_saved_gbp":     round(saved * 0.28, 2),
        "peak_reduction_kw":  round(max(0, baseline_peak_kw - optimised_peak_kw), 3),
    }


def tool_comfort_report():
    m = sim.get_metrics()
    if not m:
        return {"error": "No data. Run simulation first."}
    zones = m["zones"]
    violations = sum(1 for z in zones if not (PMV_MIN <= z["pmv"] <= PMV_MAX))
    score = (len(zones) - violations) / max(1, len(zones)) * 100
    return {
        "zones":         zones,
        "violations":    violations,
        "comfort_score": round(score, 1),
        "avg_pmv":       round(sum(z["pmv"] for z in zones) / max(1, len(zones)), 3),
        "compliant":     violations == 0,
    }


def tool_peak_demand():
    m = sim.get_metrics()
    if not m:
        return {"error": "No data."}
    peak = m["summary"]["peak_kw"]
    excess = max(0.0, peak - PEAK_KW)
    risk = "HIGH" if excess > 3 else "MEDIUM" if excess > 0 else "LOW"
    return {"peak_kw": peak, "target_kw": PEAK_KW, "excess_kw": round(excess, 2), "risk": risk}


def tool_carbon_report():
    m = sim.get_metrics()
    if not m:
        return {"error": "No data."}
    total = m["summary"]["total_kwh"]
    return {
        "total_kwh":  total,
        "carbon_kg":  round(total * CARBON_INT, 4),
        "trees_eq":   round(total * CARBON_INT / 21.77, 3),
    }


def tool_savings_report():
    if not _baseline_runs or not _optimised_runs:
        return {"msg": "Not enough data yet."}
    bl  = sum(s.total_kwh for s in _baseline_runs)
    opt = sum(s.total_kwh for s in _optimised_runs)
    return tool_compute_savings(bl, opt,
                                max(s.peak_kw for s in _baseline_runs),
                                max(s.peak_kw for s in _optimised_runs))


def record_baseline(snapshot):
    _baseline_runs.append(snapshot)


def record_optimised(snapshot):
    _optimised_runs.append(snapshot)


def export_savings_csv():
    if not _baseline_runs or not _optimised_runs:
        return None
    path = OUT_DIR / f"savings_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    rows = []
    for i, (b, o) in enumerate(zip(_baseline_runs, _optimised_runs), 1):
        saved = max(0, b.total_kwh - o.total_kwh)
        rows.append({
            "cycle":           i,
            "baseline_kwh":    round(b.total_kwh, 3),
            "optimised_kwh":   round(o.total_kwh, 3),
            "savings_kwh":     round(saved, 3),
            "savings_pct":     round(saved / b.total_kwh * 100, 2) if b.total_kwh else 0,
            "opt_avg_temp":    round(o.avg_temp, 2),
            "opt_avg_pmv":     round(o.avg_pmv, 3),
            "carbon_kg":       round(o.carbon_kg, 4),
        })
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)
    log.info(f"Savings CSV exported: {path}")
    return str(path)
