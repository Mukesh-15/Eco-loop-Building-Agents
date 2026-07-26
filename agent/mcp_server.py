import inspect
import json
import traceback

from tools.simulation_tools import (
    tool_run_simulation, tool_read_metrics, tool_parse_errors, tool_get_building_state,
    tool_reset_idf, tool_set_heating_setpoint, tool_set_cooling_setpoint,
    tool_set_ventilation_rate, tool_set_lighting_schedule, tool_apply_ecm, tool_get_setpoints,
    tool_compute_savings, tool_comfort_report, tool_peak_demand, tool_carbon_report, tool_savings_report,
)
from utils.logger import get_logger

log = get_logger("mcp")

TOOLS = {
    "run_simulation":        tool_run_simulation,
    "read_metrics":          tool_read_metrics,
    "parse_errors":          tool_parse_errors,
    "get_building_state":    tool_get_building_state,
    "reset_idf":             tool_reset_idf,
    "set_heating_setpoint":  tool_set_heating_setpoint,
    "set_cooling_setpoint":  tool_set_cooling_setpoint,
    "set_ventilation_rate":  tool_set_ventilation_rate,
    "set_lighting_schedule": tool_set_lighting_schedule,
    "apply_ecm":             tool_apply_ecm,
    "get_setpoints":         tool_get_setpoints,
    "compute_savings":       tool_compute_savings,
    "comfort_report":        tool_comfort_report,
    "peak_demand":           tool_peak_demand,
    "carbon_report":         tool_carbon_report,
    "savings_report":        tool_savings_report,
}


def _build_schema(fn):
    sig = inspect.signature(fn)
    props = {}
    for name, p in sig.parameters.items():
        ann = p.annotation
        t = {str: "string", int: "integer", float: "number", bool: "boolean"}.get(ann, "string")
        props[name] = {"type": t}
    return {
        "name": fn.__name__.replace("tool_", ""),
        "description": (fn.__doc__ or fn.__name__).strip()[:200],
        "parameters": {"type": "object", "properties": props},
    }


TOOL_SCHEMAS = [_build_schema(fn) for fn in TOOLS.values()]


def _coerce_args(fn, args: dict) -> dict:
    """Ollama's tool-calling doesn't reliably respect the declared JSON schema
    types - numbers and booleans often arrive as strings (e.g. use_modified='true',
    optimised_kwh='223.195'). Left uncoerced this causes two real bugs:
      1. `'false'` is truthy in Python, so a string-valued bool silently does the
         opposite of what was asked (e.g. always running the modified IDF).
      2. Arithmetic on string numbers ("223.195" - "247.957") raises a TypeError
         and aborts the tool call.
    Coerce every argument to the type declared in the tool function's signature
    before calling it, so tools stay simple and don't each need their own casts.
    """
    sig = inspect.signature(fn)
    coerced = {}
    for name, value in args.items():
        param = sig.parameters.get(name)
        ann = param.annotation if param is not None else inspect.Parameter.empty
        if ann is inspect.Parameter.empty or not isinstance(value, str):
            coerced[name] = value
            continue
        try:
            if ann is bool:
                coerced[name] = value.strip().lower() in ("true", "1", "yes", "on")
            elif ann is float:
                coerced[name] = float(value)
            elif ann is int:
                coerced[name] = int(float(value))
            else:
                coerced[name] = value
        except (TypeError, ValueError):
            coerced[name] = value  # let the tool itself raise a clear error
    return coerced


def call(name: str, args: dict) -> dict:
    fn = TOOLS.get(name)
    if fn is None:
        return {"result": None, "error": f"Tool '{name}' not found. Available: {list(TOOLS.keys())}"}
    try:
        result = fn(**_coerce_args(fn, args))
        log.info(f"tool {name} -> ok")
        return {"result": result, "error": None}
    except Exception as e:
        log.error(f"tool {name} failed: {e}")
        return {"result": None, "error": str(e)}


def list_tools():
    return TOOL_SCHEMAS


def run_http_server(host="127.0.0.1", port=8765):
    """Expose tools over HTTP JSON-RPC 2.0 for external LLM clients."""
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", 0))).decode()
            req  = json.loads(body)
            name = req.get("params", {}).get("name", "")
            args = req.get("params", {}).get("arguments", {})
            out  = call(name, args)
            resp = json.dumps({"jsonrpc": "2.0", "id": req.get("id"), "result": out}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(resp)

        def do_GET(self):
            resp = json.dumps({"tools": list_tools()}, indent=2).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(resp)

    print(f"MCP server running at http://{host}:{port}")
    HTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    run_http_server()
