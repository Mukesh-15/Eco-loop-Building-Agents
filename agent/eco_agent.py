# Each cycle: observe building state -> reason with LLM -> call MCP tools -> verify results.

import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, List

import agent.mcp_server as mcp
from utils.config import ROOT, OLLAMA_URL, OLLAMA_MODEL   # LLM backend: local Ollama. Set OLLAMA_MODEL / OLLAMA_BASE_URL in .env file.
from utils.logger import get_logger
from tools.simulation_tools import record_baseline, record_optimised
import simulation.runner as sim_runner

log = get_logger("agent")
SYSTEM_PROMPT = open(ROOT / "prompts" / "system_prompt.txt", encoding="utf-8").read()


@dataclass
class Event:
    type: str    # thought | action | observation | summary | cycle_start | error
    content: str
    ts: str = field(default_factory=lambda: datetime.now().strftime("%H:%M:%S"))


def _call_ollama(messages, tools=None):
    import urllib.request
    payload_dict = {
        "model": OLLAMA_MODEL,
        "messages": messages,
        "stream": False,
        "options": {
            "temperature": 0.2
        }
    }
    if tools:
        payload_dict["tools"] = [
            {"type": "function", "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["parameters"],
            }}
            for t in tools
        ]
    payload = json.dumps(payload_dict).encode("utf-8")
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    import urllib.error
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            body = json.loads(r.read())
    except urllib.error.HTTPError as e:
        err_text = e.read().decode()
        try:
            err_json = json.loads(err_text)
            err_msg = err_json.get("error", err_text)
        except Exception:
            err_msg = err_text
        raise RuntimeError(f"Ollama error: {err_msg}. Please run 'ollama pull {OLLAMA_MODEL}' in your terminal.") from e
    except urllib.error.URLError as e:
        raise RuntimeError(
            f"Could not reach Ollama at {OLLAMA_URL}. Is 'ollama serve' running? ({e.reason})"
        ) from e
    msg = body.get("message", {})
    out = {
        "role": "assistant",
        "content": msg.get("content")
    }
    if msg.get("tool_calls"):
        out["tool_calls"] = []
        for tc in msg["tool_calls"]:
            func = tc.get("function", {})
            args = func.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    pass
            out["tool_calls"].append({
                "id": tc.get("id", f"call_{int(time.time())}"),
                "type": "function",
                "function": {
                    "name": func.get("name"),
                    "arguments": args
                }
            })
    return out


def _llm(messages, tools=None):
    # Small pacing delay so we don't hammer the local Ollama server with
    # back-to-back requests inside the 8-step ReAct loop.
    time.sleep(1.5)
    return _call_ollama(messages, tools)


class EcoAgent:
    def __init__(self, on_event: Callable[[Event], None] = None):
        self.on_event = on_event or (lambda e: None)
        self.history = []

    def emit(self, etype, content):
        self.on_event(Event(type=etype, content=content))
        log.info(f"[{etype}] {content[:120]}")

    def run_cycle(self, cycle_num: int) -> dict:
        self.emit("cycle_start", f"Cycle {cycle_num} started")
        tools = mcp.list_tools()

        self.emit("action", "Running baseline simulation...")
        bl_result = mcp.call("run_simulation", {"use_modified": False})
        bl = bl_result.get("result") or {}

        if bl.get("status") in ("error", "failed", "timeout"):
            self.emit("error", f"Baseline simulation failed: {bl.get('error', 'unknown error')}")
            return {"cycle": cycle_num, "baseline": bl, "optimised": {}, "savings": {}}

        if sim_runner.last_snapshot:
            record_baseline(sim_runner.last_snapshot)

        self.emit("observation", f"Baseline: {(bl.get('summary') or {}).get('total_kwh', '?')} kWh")

        state = mcp.call("get_building_state", {}).get("result", "No data.")
        user_msg = {
            "role": "user",
            "content": (
                f"Cycle {cycle_num}. Current building state:\n\n{state}\n\n"
                "Analyse the data, identify what is outside comfort targets, "
                "and apply the most effective energy conservation measures. "
                "Keep PMV between -0.5 and +0.5, temperatures between 21-24C. "
                "Use your tools autonomously."
            ),
        }
        messages = [{"role": "system", "content": SYSTEM_PROMPT}] + self.history[-6:] + [user_msg]

        for step in range(8):
            try:
                resp = _llm(messages, tools)
            except Exception as e:
                self.emit("error", f"LLM call failed at step {step+1}: {e}")
                break

            messages.append(resp)

            if resp.get("content"):
                self.emit("thought", resp["content"])

            tool_calls = resp.get("tool_calls", [])
            if not tool_calls:
                self.emit("summary", resp.get("content", "Agent finished reasoning."))
                break

            for tc in tool_calls:
                if "function" in tc:
                    name = tc["function"]["name"]
                    raw_args = tc["function"]["arguments"]
                    args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
                else:
                    name = tc.get("name")
                    args = tc.get("arguments", {})
                self.emit("action", f"{name}({self._fmt(args)})")
                result = mcp.call(name, args)
                payload = result.get("result") if result.get("result") is not None else result.get("error", "error")
                out_str = json.dumps(payload, indent=2)[:800]
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id", ""),
                    "name": name,
                    "content": out_str,
                })
                self.emit("observation", f"{name}: {out_str[:300]}")

        self.emit("action", "Running optimised simulation...")
        opt_result = mcp.call("run_simulation", {"use_modified": True})
        opt = opt_result.get("result") or {}

        if opt.get("status") in ("error", "failed", "timeout"):
            self.emit("error", f"Optimised simulation failed: {opt.get('error', '')}")
        elif sim_runner.last_snapshot:
            record_optimised(sim_runner.last_snapshot)

        bl_kwh  = (bl.get("summary") or {}).get("total_kwh", 0.0)
        opt_kwh = (opt.get("summary") or {}).get("total_kwh", 0.0)
        savings_result = mcp.call("compute_savings", {
            "baseline_kwh": float(bl_kwh),
            "optimised_kwh": float(opt_kwh),
        })
        savings = savings_result.get("result") or {}

        pct = savings.get("energy_savings_pct", 0)
        kwh = savings.get("energy_savings_kwh", 0)
        self.emit("summary", f"Cycle {cycle_num} complete: {pct:.1f}% saved ({kwh:.2f} kWh)")

        self.history.append({"role": "assistant", "content": f"Cycle {cycle_num} result: {savings}"})
        return {"cycle": cycle_num, "baseline": bl, "optimised": opt, "savings": savings}

    @staticmethod
    def _fmt(args):
        return ", ".join(f"{k}={v!r}" for k, v in args.items())[:80]
