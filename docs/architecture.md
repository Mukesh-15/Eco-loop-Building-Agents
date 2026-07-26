# Eco-Loop System Architecture

## Overview

Eco-Loop is a Physical AI Proof-of-Concept (PoC) that transforms a building from a passive energy consumer into an **active, self-correcting agent** capable of continuous, real-time optimisation. It pairs EnergyPlus (physics-based building simulation) with an open-source LLM via the Model Context Protocol (MCP) to create a fully autonomous closed-loop control pipeline.

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                      STREAMLIT DASHBOARD                           │
│  Live Charts │ Agent Trace │ Savings Dashboard │ Loop Controls     │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
                ┌──────────▼──────────┐
                │     ECO AGENT       │
                │  (ReAct Loop)       │
                │  eco_agent.py       │
                │                     │
                │  1. OBSERVE         │
                │  2. REASON (LLM)    │
                │  3. ACT (MCP tools) │
                │  4. VERIFY          │
                └──────────┬──────────┘
                           │
            ┌──────────────▼──────────────┐
            │        MCP SERVER           │
            │    (JSON-RPC 2.0)           │
            │    mcp_server.py            │
            │                             │
            │  ┌──────────┬───────────┐  │
            │  │ SIM TOOLS│ IDF TOOLS │  │
            │  │          │           │  │
            │  │ANALYSIS  │ COMFORT   │  │
            │  │ TOOLS    │ TOOLS     │  │
            └──┴────┬─────┴─────┬─────┘
                    │           │
         ┌──────────▼──┐   ┌────▼──────────┐
         │  ENERGYPLUS  │   │  IDF EDITOR   │
         │  RUNNER      │   │  (idf_tools)  │
         │  runner.py   │   │               │
         │              │   │ Setpoints,    │
         │  Real / Mock │   │ Schedules,    │
         └──────┬───────┘   │ ECM Bundles   │
                │           └───────────────┘
         ┌──────▼───────┐
         │  OUTPUT      │
         │  PARSER      │
         │  parser.py   │
         │              │
         │ CSV / ESO    │
         │ → Metrics    │
         └──────────────┘
```

---

## Component Details

### 1. Simulation Engine — EnergyPlus

| Component | File | Description |
|---|---|---|
| `EnergyPlusRunner` | `simulation/runner.py` | Subprocess runner; auto-detects EP binary; falls back to mock |
| `EnergyPlusParser` | `simulation/parser.py` | Parses CSV/ESO outputs into `BuildingMetrics`; implements Fanger PMV |
| `base_model.idf` | `energyplus/base_model.idf` | 3-zone small office building (OFFICE_NORTH, OFFICE_SOUTH, MEETING_ROOM) |
| `modified_model.idf` | `energyplus/modified_model.idf` | Runtime copy; modified by agent actions each cycle |

**Building Model Spec:**
- Total conditioned area: ~511 m² (3 zones × ~170 m²)
- HVAC: IdealLoadsAirSystem (per zone)
- Thermostat: DualSetpoint (heating/cooling)
- Location: London Heathrow (51.48°N)
- Constructions: Metal + insulation + concrete block walls; U=2.1 W/m²K glazing

### 2. Cognitive Engine — LLM + MCP

| Component | File | Description |
|---|---|---|
| `EcoAgent` | `agent/eco_agent.py` | ReAct-style agent; supports Groq/Ollama/Mock backends |
| `MCPServer` | `agent/mcp_server.py` | JSON-RPC 2.0 tool dispatcher; exposes 15 tools |
| `system_prompt.txt` | `prompts/system_prompt.txt` | Full agent instructions with targets, tools, and ReAct protocol |

**LLM Backend Priority:**
1. **Groq API** (cloud; `GROQ_API_KEY` required) — recommended for demos
2. **Ollama** (local; `ollama serve` required) — offline operation
3. **Mock** (deterministic; no API) — CI/testing

### 3. Tool Architecture (MCP Tools)

```
Simulation Tools          IDF Control Tools         Analysis Tools
─────────────────         ──────────────────        ───────────────
run_simulation            reset_idf                 compute_savings
read_current_metrics      set_heating_setpoint      thermal_comfort_report
parse_simulation_errors   set_cooling_setpoint      carbon_footprint
get_context_for_llm       set_ventilation_rate      peak_demand_analysis
                          set_lighting_schedule     get_global_savings_report
                          get_current_setpoints
                          apply_ecm_bundle
```

### 4. Closed-Loop Control Flow

```
For each cycle N:

  1. reset_idf()                     ← Reset to baseline
  2. run_simulation(baseline=True)   ← Measure baseline energy
  3. LLM: read_current_metrics()     ← Observe
  4. LLM: REASON about violations    ← Think
  5. LLM: set_heating_setpoint(...)  ← Act
  6. LLM: set_cooling_setpoint(...)  ← Act
  7. LLM: apply_ecm_bundle(...)      ← Act
  8. LLM: thermal_comfort_report()   ← Verify
  9. run_simulation(optimised=True)  ← Measure optimised
  10. compute_savings(bl, opt)       ← Quantify gain
  11. Update dashboard charts         ← Display
  ↓
  Repeat cycle N+1
```

### 5. Prompt Engineering Strategy

**System Prompt Design:**
- Explicit comfort targets (PMV -0.5 to +0.5, temp 21-24°C)
- Safety constraints enumerated as hard rules (NEVER/ALWAYS)
- Decision tree for ECM selection based on outdoor temp / occupancy
- Explicit ReAct output format (THOUGHT/ACTION/OBSERVATION/SUMMARY)

**Context Management:**
- Rolling 6-message history window to prevent context overflow
- Per-cycle state injection via `get_context_for_llm()` tool
- Tool results truncated to 1000 chars to manage latency

**Prompt Latency Management:**
- Tool calls batched where possible (multi-action per LLM turn)
- `MAX_REACT_STEPS = 8` caps per-cycle LLM calls
- Groq `llama-3.1-8b-instant` achieves <2s/call on average

### 6. Energy Conservation Measures (ECMs)

| ECM | Trigger Condition | Actions |
|---|---|---|
| `optimal_start` | Occupancy approaching | Advance HVAC warm-up 30 min |
| `economizer_mode` | Outdoor < Indoor temp | Raise ventilation ACH to 4.0 |
| `setback_night` | Unoccupied hours | Heating → 18°C, Cooling → 28°C |
| `demand_response` | Peak demand > 15 kW | Lighting × 0.7, Cooling SP + 2°C |
| Custom setpoints | PMV/temp out of range | Incremental ±1-2°C adjustment |

### 7. Data Models

```python
BuildingMetrics          # Per-cycle simulation output
  └── ZoneMetrics[]      # Per-zone: temp, PMV, PPD, CO2

ControlAction            # Single agent decision
AgentDecision            # Full reasoning cycle result
SimulationResult         # EnergyPlus run outcome
SavingsReport            # Cumulative optimisation summary
ToolCall / ToolResult    # MCP protocol types
```

---

## Running the System

```bash
# Install dependencies
pip install -r requirements.txt

# Option A: Mock mode (no EnergyPlus, no API key needed)
MOCK_MODE=true streamlit run app.py

# Option B: With Groq LLM
GROQ_API_KEY=gsk_... streamlit run app.py

# Option C: With local Ollama
ollama serve &
ollama pull mistral
LLM_BACKEND=ollama streamlit run app.py

# Option D: Full EnergyPlus
# Install EnergyPlus 23.x from https://energyplus.net/downloads
ENERGYPLUS_BINARY=C:\EnergyPlusV23-2-0\energyplus.exe streamlit run app.py
```

---

## Output Files

| File | Description |
|---|---|
| `outputs/savings_report_*.csv` | Per-cycle savings data export |
| `outputs/run_*/` | EnergyPlus output directories |
| `logs/eco_loop_*.jsonl` | Structured JSON agent logs |
| `energyplus/modified_model.idf` | Last-modified IDF for inspection |
