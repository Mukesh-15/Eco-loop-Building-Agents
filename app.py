import warnings
warnings.filterwarnings("ignore")

import threading

import plotly.graph_objects as go
import plotly.io as pio
pio.json.config.default_engine = "json"
from plotly.subplots import make_subplots
import streamlit as st


_fragment = getattr(st, "fragment", None) or st.experimental_fragment

st.set_page_config(page_title="Eco-Loop | Building Agents", page_icon=None, layout="wide")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
.block-container { padding: 1.2rem 2rem; background: #0a0f1e; }
.metric-card {
  background: rgba(255,255,255,0.04);
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 12px; padding: 18px; text-align: center;
}
.metric-label { font-size: 0.75rem; color: #64748b; text-transform: uppercase; letter-spacing: 1px; }
.metric-value { font-size: 1.9rem; font-weight: 700; color: #f8fafc; margin: 6px 0; }
.metric-sub   { font-size: 0.8rem; }
.green  { color: #4ade80; }
.yellow { color: #fbbf24; }
.red    { color: #f87171; }
.trace-box {
  background: #0d1117;
  border: 1px solid rgba(255,255,255,0.07);
  border-radius: 10px; padding: 14px;
  height: 360px; overflow-y: auto;
  font-family: 'Courier New', monospace; font-size: 0.78rem;
}
.t-thought { color: #93c5fd; }
.t-action  { color: #86efac; }
.t-obs     { color: #fde68a; }
.t-summary { color: #c084fc; font-weight: 600; }
.t-cycle   { color: #38bdf8; font-weight: 700;
             border-top: 1px solid rgba(255,255,255,0.08);
             padding-top: 6px; margin-top: 6px; }
.t-error   { color: #f87171; }
.pill {
  display: inline-block; padding: 3px 10px; border-radius: 20px;
  font-size: 0.76rem; font-weight: 600; margin: 2px;
}
.pill-comfortable { background: rgba(74,222,128,0.12); color: #4ade80; border: 1px solid rgba(74,222,128,0.25); }
.pill-warm  { background: rgba(251,191,36,0.12);  color: #fbbf24; border: 1px solid rgba(251,191,36,0.25); }
.pill-cool  { background: rgba(96,165,250,0.12);  color: #60a5fa; border: 1px solid rgba(96,165,250,0.25); }
.pill-hot   { background: rgba(248,113,113,0.12); color: #f87171; border: 1px solid rgba(248,113,113,0.25); }
.pill-cold  { background: rgba(147,197,253,0.12); color: #93c5fd; }
.stButton > button {
  background: linear-gradient(135deg, #065f3f, #0d7a52) !important;
  color: white !important; border: none !important;
  border-radius: 8px !important; font-weight: 600 !important;
}
[data-testid="stSidebar"] { background: #0d1117 !important; }
</style>
""", unsafe_allow_html=True)


def init():
    defaults = {
        "running": False, "stopped": False, "cycle": 0,
        "events": [], "results": [],
        "chart": {"cycles": [], "bl": [], "opt": [], "pct": [], "temp": [], "pmv": [], "peak": []},
        "metrics": None, "savings": None,
        "error_msg": None, "_prev_running": False,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

init()


def agent_thread(n_cycles: int):
    try:
        from agent.eco_agent import EcoAgent, Event
    except Exception as e:
        st.session_state.error_msg = str(e)
        st.session_state.running = False
        return

    def on_event(ev: Event):
        st.session_state.events.append({"type": ev.type, "content": ev.content, "ts": ev.ts})

    agent = EcoAgent(on_event=on_event)

    for i in range(1, n_cycles + 1):
        if st.session_state.stopped:
            break
        st.session_state.cycle = i
        result = agent.run_cycle(i)
        st.session_state.results.append(result)

        bl_s  = (result["baseline"].get("summary")  or {}) if isinstance(result.get("baseline"), dict) else {}
        opt_s = (result["optimised"].get("summary") or {}) if isinstance(result.get("optimised"), dict) else {}
        sav   = result.get("savings") or {}

        cd = st.session_state.chart
        cd["cycles"].append(i)
        cd["bl"].append(bl_s.get("total_kwh", 0))
        cd["opt"].append(opt_s.get("total_kwh", 0))
        cd["pct"].append(sav.get("energy_savings_pct", 0))
        cd["temp"].append(opt_s.get("avg_temp_c", 0))
        cd["pmv"].append(opt_s.get("avg_pmv", 0))
        cd["peak"].append(opt_s.get("peak_kw", 0))
        st.session_state.metrics = opt_s
        st.session_state.savings = sav

    st.session_state.running = False
    st.session_state.stopped = False


# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("## Configuration")
    cycles = st.slider("Number of Cycles", 1, 20, 5)
    st.markdown("---")
    st.markdown("**Comfort Targets**")
    st.markdown("- Temperature: 21-24C\n- PMV: -0.5 to +0.5\n- Peak demand: < 15 kW\n- Energy savings: >= 15%")


# ── Header ────────────────────────────────────────────────────────────────────

st.markdown("""
<div style="background:linear-gradient(135deg,#0d7a52,#0a1628);
            border-radius:14px;padding:22px 28px;
            margin-bottom:18px;border:1px solid rgba(13,122,82,0.3)">
  <h1 style="color:#4ade80;margin:0;font-size:2rem;font-weight:700">
    Eco-Loop Building Agents
  </h1>
  <p style="color:#94a3b8;margin-top:4px">
    EnergyPlus + LLM + MCP - Autonomous closed-loop building energy optimisation
  </p>
</div>
""", unsafe_allow_html=True)

if st.session_state.error_msg:
    st.error(f"Agent error: {st.session_state.error_msg}")


# ── Controls ──────────────────────────────────────────────────────────────────

c1, c2, c3, prog_col = st.columns([1.5, 1.5, 1.5, 5])

with c1:
    start = st.button("Start Loop", disabled=st.session_state.running, use_container_width=True)
with c2:
    stop  = st.button("Stop",       disabled=not st.session_state.running, use_container_width=True)
with c3:
    reset = st.button("Reset",      disabled=st.session_state.running, use_container_width=True)

if start and not st.session_state.running:
    st.session_state.running   = True
    st.session_state.error_msg = None
    t = threading.Thread(target=agent_thread, args=(cycles,), daemon=True)
    from streamlit.runtime.scriptrunner import add_script_run_ctx
    add_script_run_ctx(t)
    t.start()

if stop:
    st.session_state.stopped = True

if reset:
    for k in list(st.session_state.keys()):
        del st.session_state[k]
    init()
    st.rerun()


# ── Live dashboard (auto-refreshes itself only, not the whole page) ───────────

def _live_dashboard():
    with prog_col:
        if st.session_state.running:
            pct = st.session_state.cycle / max(cycles, 1)
            st.progress(pct, text=f"Cycle {st.session_state.cycle} of {cycles} running...")
        elif st.session_state.results:
            st.progress(1.0, text=f"Completed {len(st.session_state.results)} cycles")
        else:
            st.caption("Configure settings in the sidebar and click Start Loop.")

    # ── Metric Cards ──────────────────────────────────────────────────────
    st.markdown("<br>", unsafe_allow_html=True)

    m = st.session_state.metrics or {}
    s = st.session_state.savings or {}

    def card(col, label, value, sub="", color="green"):
        col.markdown(f"""<div class="metric-card">
          <div class="metric-label">{label}</div>
          <div class="metric-value">{value}</div>
          <div class="metric-sub {color}">{sub}</div>
        </div>""", unsafe_allow_html=True)

    cols = st.columns(6)

    t_val = m.get("avg_temp_c")
    card(cols[0], "Avg Zone Temp",
         f"{t_val}C" if t_val else "--",
         "in range" if t_val and 21 <= t_val <= 24 else "out of range",
         "green" if t_val and 21 <= t_val <= 24 else "yellow")

    pmv = m.get("avg_pmv")
    card(cols[1], "PMV",
         f"{pmv:+.2f}" if pmv is not None else "--",
         "comfortable" if pmv is not None and -0.5 <= pmv <= 0.5 else "discomfort",
         "green" if pmv is not None and -0.5 <= pmv <= 0.5 else "yellow")

    card(cols[2], "Total Energy",
         f"{m.get('total_kwh', '--')} kWh" if m else "-- kWh",
         f"saved {s.get('energy_savings_kwh', 0):.2f} kWh" if s else "no data",
         "green")

    pk = m.get("peak_kw")
    card(cols[3], "Peak Demand",
         f"{pk} kW" if pk is not None else "-- kW",
         "under 15kW" if pk and pk < 15 else "above limit",
         "green" if pk and pk < 15 else "red")

    card(cols[4], "Carbon",
         f"{m.get('carbon_kg', '--')} kg" if m else "-- kg",
         "kg CO2 this cycle", "green")

    pct_val = s.get("energy_savings_pct", 0)
    card(cols[5], "Savings",
         f"{pct_val:.1f}%" if s else "--%",
         "target met" if pct_val >= 15 else f"{15-pct_val:.1f}% below target",
         "green" if pct_val >= 15 else "yellow")

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Charts ────────────────────────────────────────────────────────────
    LAYOUT = dict(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        height=260, margin=dict(l=45, r=15, t=35, b=35),
        font=dict(color="#94a3b8", family="Inter"),
        xaxis=dict(gridcolor="rgba(255,255,255,0.05)"),
        yaxis=dict(gridcolor="rgba(255,255,255,0.05)"),
        legend=dict(bgcolor="rgba(0,0,0,0.3)"),
    )
    cd = st.session_state.chart

    ch1, ch2 = st.columns(2)
    with ch1:
        fig = go.Figure()
        if cd["cycles"]:
            fig.add_trace(go.Scatter(
                x=cd["cycles"], y=cd["bl"], name="Baseline",
                line=dict(color="#f87171", width=2, dash="dash"), mode="lines+markers"))
            fig.add_trace(go.Scatter(
                x=cd["cycles"], y=cd["opt"], name="Optimised",
                line=dict(color="#4ade80", width=2), mode="lines+markers",
                fill="tonexty", fillcolor="rgba(74,222,128,0.06)"))
        fig.update_layout(**LAYOUT, title=dict(text="Energy Consumption (kWh)", font=dict(color="#94a3b8")))
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    with ch2:
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        if cd["cycles"]:
            fig.add_trace(go.Scatter(
                x=cd["cycles"], y=cd["temp"], name="Avg Temp (C)",
                line=dict(color="#60a5fa", width=2), mode="lines+markers"), secondary_y=False)
            fig.add_trace(go.Scatter(
                x=cd["cycles"], y=cd["pmv"], name="PMV",
                line=dict(color="#fbbf24", width=2), mode="lines+markers"), secondary_y=True)
            fig.add_hrect(y0=21, y1=24, fillcolor="rgba(74,222,128,0.05)", line_width=0, secondary_y=False)
        fig.update_layout(**LAYOUT, title=dict(text="Thermal Comfort", font=dict(color="#94a3b8")))
        fig.update_yaxes(title_text="Temp (C)", secondary_y=False)
        fig.update_yaxes(title_text="PMV", range=[-3, 3], secondary_y=True)
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    ch3, ch4 = st.columns(2)
    with ch3:
        fig = go.Figure()
        if cd["cycles"]:
            colors = ["#4ade80" if v >= 15 else "#fbbf24" if v >= 5 else "#f87171" for v in cd["pct"]]
            fig.add_trace(go.Bar(
                x=cd["cycles"], y=cd["pct"], marker_color=colors,
                text=[f"{v:.1f}%" for v in cd["pct"]], textposition="outside",
                textfont=dict(color="#94a3b8")))
            fig.add_hline(y=15, line_dash="dash", line_color="#4ade80",
                          annotation_text="15% target", annotation_font_color="#4ade80")
        fig.update_layout(**LAYOUT, title=dict(text="Savings per Cycle (%)", font=dict(color="#94a3b8")))
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    with ch4:
        fig = go.Figure()
        if cd["cycles"]:
            fig.add_trace(go.Scatter(
                x=cd["cycles"], y=cd["peak"], name="Peak kW",
                line=dict(color="#a78bfa", width=2), mode="lines+markers",
                fill="tozeroy", fillcolor="rgba(167,139,250,0.07)"))
            fig.add_hline(y=15, line_dash="dash", line_color="#f87171",
                          annotation_text="15kW limit", annotation_font_color="#f87171")
        fig.update_layout(**LAYOUT, title=dict(text="Peak Demand (kW)", font=dict(color="#94a3b8")))
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    # ── Agent Trace + Savings ────────────────────────────────────────────
    tr_col, sv_col = st.columns([3, 2])

    type_css = {
        "thought":     "t-thought",
        "action":      "t-action",
        "observation": "t-obs",
        "summary":     "t-summary",
        "cycle_start": "t-cycle",
        "error":       "t-error",
    }

    with tr_col:
        st.markdown("**Agent Reasoning Trace**")
        lines = []
        for ev in st.session_state.events[-60:]:
            css = type_css.get(ev["type"], "t-thought")
            # Full LLM thoughts/summaries are shown in full (the trace box
            # scrolls); only very long tool-result payloads are capped so a
            # single verbose JSON blob can't dominate the panel.
            cap = 4000 if ev["type"] in ("thought", "summary", "error", "cycle_start") else 1200
            txt = ev["content"][:cap].replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")
            lines.append(
                f'<div class="{css}">'
                f'<span style="color:#475569;font-size:0.7rem">[{ev["ts"]}]</span> {txt}'
                f'</div>'
            )
        body = "\n".join(lines) if lines else '<div style="color:#475569">Waiting for agent...</div>'
        st.markdown(f'<div class="trace-box">{body}</div>', unsafe_allow_html=True)

    with sv_col:
        st.markdown("**Cumulative Savings**")
        if st.session_state.results:
            total_bl  = sum(
                (r["baseline"].get("summary")  or {}).get("total_kwh", 0)
                for r in st.session_state.results if isinstance(r.get("baseline"), dict)
            )
            total_opt = sum(
                (r["optimised"].get("summary") or {}).get("total_kwh", 0)
                for r in st.session_state.results if isinstance(r.get("optimised"), dict)
            )
            total_sav = max(0.0, total_bl - total_opt)
            total_pct = (total_sav / total_bl * 100) if total_bl > 0 else 0.0

            st.markdown(f"""
            <div style="background:linear-gradient(135deg,rgba(74,222,128,0.1),rgba(56,189,248,0.06));
                        border:1px solid rgba(74,222,128,0.2);border-radius:12px;
                        padding:20px;text-align:center;margin-bottom:16px">
              <div style="font-size:2.8rem;font-weight:800;color:#4ade80">{total_pct:.1f}%</div>
              <div style="color:#64748b;font-size:0.85rem">total energy saved vs baseline</div>
            </div>
            """, unsafe_allow_html=True)

            a, b = st.columns(2)
            a.metric("kWh Saved",   f"{total_sav:.2f}")
            b.metric("CO2 Reduced", f"{total_sav * 0.233:.3f} kg")
            c, d = st.columns(2)
            c.metric("Cost Saved",  f"GBP {total_sav * 0.28:.2f}")
            d.metric("Cycles Done", str(st.session_state.cycle))

            if st.button("Export Savings CSV"):
                from tools.simulation_tools import export_savings_csv
                path = export_savings_csv()
                if path:
                    st.success(f"Saved: {path}")
                else:
                    st.warning("Not enough data to export. Run more cycles first.")
        else:
            st.markdown(
                '<div style="color:#475569;text-align:center;padding:40px 20px">'
                'Savings data will appear after cycles complete.'
                '</div>',
                unsafe_allow_html=True
            )

    # ── Zone Status ───────────────────────────────────────────────────────
    st.markdown("**Zone Status**")
    import simulation.runner as sr
    if sr.last_snapshot and sr.last_snapshot.zones:
        pills = " ".join(
            f'<span class="pill pill-{z.comfort}">'
            f'{z.name} - {z.temp_c}C - PMV {z.pmv:+.2f}'
            f'</span>'
            for z in sr.last_snapshot.zones
        )
        st.markdown(f"<div style='margin:6px 0'>{pills}</div>", unsafe_allow_html=True)
    else:
        st.caption("Zone data will appear after the first simulation run.")

    st.markdown("<br>", unsafe_allow_html=True)

    # Stop self-refreshing once a run finishes, and do exactly one full-page
    # rerun so the Start/Stop/Reset buttons above (outside this fragment)
    # go back to their normal enabled/disabled state.
    if st.session_state.running:
        st.session_state._prev_running = True
    elif st.session_state._prev_running:
        st.session_state._prev_running = False
        st.rerun()


# Only auto-refresh (and only this fragment, not the whole page - this is
# what stops the header/sidebar/buttons from flickering) while a loop is
# actually running.
_refresh_interval = 1 if st.session_state.running else None
_fragment(run_every=_refresh_interval)(_live_dashboard)()
