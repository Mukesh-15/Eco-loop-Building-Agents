# Eco-Loop Building Agents

Autonomous closed-loop building energy optimisation using EnergyPlus, a local LLM (via Ollama), and MCP-style tool calling.

The system runs a continuous observe-reason-act loop: simulate the building, send the results to an LLM, let the LLM decide what setpoints and energy conservation measures to apply, apply them to the IDF, re-simulate, and measure the savings.

---

## Requirements

- Python 3.10+
- [Ollama](https://ollama.ai), running locally — EnergyPlus is optional; if it isn't installed, the built-in physics fallback solver is used instead

---

## Setup

### 1. Install Python dependencies

```
pip install -r requirements.txt
```

### 2. Install EnergyPlus

For real simulation accuracy, download EnergyPlus 23.x from https://energyplus.net/downloads and note the install path. Without it, the app still runs end-to-end using the built-in fallback solver.

### 3. Get a weather file

If using EnergyPlus, download an EPW weather file for your location from https://climate.onebuilding.org and place it at:

```
energyplus/weather.epw
```

A bundled synthetic weather file is included by default, so this step can be skipped.

### 4. Install and start Ollama

```
ollama pull llama3.2
ollama serve
```

### 5. Configure environment variables

Copy `.env.example` to `.env` and fill in your values:

```
cp .env.example .env
```

Minimum required settings:

```ini
# Path to your EnergyPlus binary (leave blank to always use the fallback solver)
ENERGYPLUS_BINARY=C:\EnergyPlusV23-2-0\energyplus.exe

# Ollama settings
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.2
```

### 6. Run the dashboard

```
python -m streamlit run app.py
```

Open http://localhost:8501 in your browser.

---

## Project Structure

```
eco-loop/
    app.py                     main Streamlit dashboard
    agent/
        eco_agent.py           ReAct LLM agent
        mcp_server.py          MCP tool registry (JSON-RPC)
    tools/
        simulation_tools.py    all agent-callable tools
    simulation/
        runner.py              EnergyPlus subprocess runner + output parser
    models/
        data_models.py         dataclasses for building metrics
    energyplus/
        base_model.idf         baseline 3-zone office building
        weather.epw            bundled synthetic weather (swap in a real EPW if needed)
    prompts/
        system_prompt.txt      LLM system instructions
    utils/
        config.py              configuration
        logger.py               logging setup
    outputs/                   EnergyPlus run outputs + savings CSVs
    logs/                      agent logs
    docs/
        architecture.md        full system architecture documentation
    .env.example                environment variable template
    requirements.txt
```

---

## How It Works

1. Agent resets the IDF to baseline.
2. Runs a simulation (EnergyPlus or fallback solver), collects energy and comfort metrics.
3. Sends building state to the LLM with the system prompt.
4. LLM reasons (ReAct loop) and calls MCP tools to adjust setpoints, lighting, ventilation, and apply ECM bundles.
5. Agent runs the modified simulation and computes savings vs. baseline.
6. Repeat for N cycles.

Available ECMs: `setback_night`, `demand_response`, `economizer_mode`, `optimal_start`

For a deeper look at how the pieces fit together, see [`docs/architecture.md`](docs/architecture.md).
