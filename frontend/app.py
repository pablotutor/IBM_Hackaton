"""
SmartProc Copilot — Frontend Streamlit
Chat de compras con panel de razonamiento en tiempo real.
"""

import json
import os
import sys

# Fix macOS / PyTorch antes de cualquier otro import
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
os.environ.setdefault("OMP_NUM_THREADS", "1")

# Asegurar que el proyecto esté en el path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

import streamlit as st

# ── Configuración de página ───────────────────────────────────────────────────

st.set_page_config(
    page_title="SmartProc Copilot",
    page_icon="🏭",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Estilos CSS ───────────────────────────────────────────────────────────────

st.markdown("""
<style>
/* Tool call cards */
.tool-card {
    border-radius: 8px;
    padding: 10px 14px;
    margin: 6px 0;
    font-size: 0.88em;
    border-left: 4px solid;
}
.tool-catalog    { background: #e8f4fd; border-color: #1a73e8; }
.tool-contract   { background: #e6f4ea; border-color: #34a853; }
.tool-quota      { background: #fef7e0; border-color: #f9ab00; }
.tool-price      { background: #f3e8fd; border-color: #9c27b0; }

/* Status badges */
.badge-ok       { background:#34a853; color:white; padding:2px 8px; border-radius:10px; font-size:0.78em; }
.badge-warn     { background:#f9ab00; color:white; padding:2px 8px; border-radius:10px; font-size:0.78em; }
.badge-error    { background:#ea4335; color:white; padding:2px 8px; border-radius:10px; font-size:0.78em; }

/* Recommendation box */
.rec-box {
    border-radius: 10px;
    padding: 16px 20px;
    margin: 10px 0;
    border-left: 5px solid;
}
.rec-ok     { background:#e6f4ea; border-color:#34a853; }
.rec-warn   { background:#fef7e0; border-color:#f9ab00; }
.rec-error  { background:#fce8e6; border-color:#ea4335; }
</style>
""", unsafe_allow_html=True)

# ── Constantes ────────────────────────────────────────────────────────────────

TOOL_META = {
    "catalog_search":      {"icon": "🔍", "label": "Catálogo",      "css": "tool-catalog"},
    "contract_lookup":     {"icon": "📄", "label": "Contrato",      "css": "tool-contract"},
    "quota_status":        {"icon": "⚖️",  "label": "Cuota",         "css": "tool-quota"},
    "price_benchmark":     {"icon": "💰", "label": "Precio",        "css": "tool-price"},
    "sustainability_score":{"icon": "🌱", "label": "ESG",           "css": "tool-catalog"},
}

BUYERS = {
    "buyer_mad_001": "Ana García — Madrid Norte",
    "buyer_mad_002": "Carlos Ruiz — Madrid Sur",
    "buyer_bcn_001": "Marta Puig — Barcelona",
    "buyer_vlc_001": "José Martínez — Valencia",
    "buyer_svq_001": "Laura Fernández — Sevilla",
}

EXAMPLE_PROMPTS = [
    "Necesito comprar 10.000 metros de cable de fibra óptica monomodo 24 hilos para despliegue en Madrid. El proveedor que me ofrece es Corning a 3,20 EUR/m. ¿Lo apruebas?",
    "Quiero pedir 200 ONTs Huawei GPON para nuevas altas de abonados FTTH en Barcelona.",
    "Necesito 5 unidades de RRU 5G NR 64T64R para nuevos emplazamientos de Ericsson. Presupuesto por unidad: 21.000 EUR.",
    "Compra urgente: 500 metros cable fibra drop FTTH 2 hilos para acometidas abonados. Proveedor nuevo no homologado.",
    "Solicito 2 servidores HPE ProLiant DL380 Gen10 para el CPD de Madrid. Precio ofertado: 9.500 EUR/ud.",
]

# ── Session state ─────────────────────────────────────────────────────────────

if "messages" not in st.session_state:
    st.session_state.messages = []
if "tool_logs" not in st.session_state:
    st.session_state.tool_logs = {}  # msg_idx → list of tool call info
if "agent_ready" not in st.session_state:
    st.session_state.agent_ready = False

# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("🏭 SmartProc Copilot")
    st.caption("Asistente de compras IA para Telco")
    st.divider()

    st.subheader("👤 Comprador activo")
    buyer_id = st.selectbox(
        "Selecciona comprador",
        options=list(BUYERS.keys()),
        format_func=lambda k: BUYERS[k],
        label_visibility="collapsed",
    )

    st.divider()
    st.subheader("💡 Ejemplos rápidos")
    for i, example in enumerate(EXAMPLE_PROMPTS):
        if st.button(f"Ejemplo {i+1}", key=f"ex_{i}", use_container_width=True):
            st.session_state["pending_prompt"] = example

    st.divider()
    if st.button("🗑️ Limpiar conversación", use_container_width=True):
        st.session_state.messages = []
        st.session_state.tool_logs = {}
        st.rerun()

    st.divider()
    st.caption(f"Endpoint: `{os.getenv('OLLAMA_CLOUD_ENDPOINT','localhost:11434')}`")
    st.caption(f"Buyer: `{buyer_id}`")

# ── Header principal ──────────────────────────────────────────────────────────

col_title, col_status = st.columns([3, 1])
with col_title:
    st.title("🏭 SmartProc Copilot")
    st.caption("Agente IA para optimización de compras en Telco · Detecta duplicados · Valida contratos · Controla cuotas · Benchmarks de precio")

with col_status:
    endpoint = os.getenv("OLLAMA_CLOUD_ENDPOINT", "http://localhost:11434")
    try:
        import requests
        r = requests.get(f"{endpoint}/api/tags", timeout=2)
        if r.status_code == 200:
            st.success("Ollama ✓")
        else:
            st.warning("Ollama ?")
    except Exception:
        st.error("Ollama ✗")

st.divider()

# ── Helpers de renderizado ────────────────────────────────────────────────────

def render_tool_card(tool_name: str, inputs: dict, output_str: str | dict | None):
    meta = TOOL_META.get(tool_name, {"icon": "🔧", "label": tool_name, "css": "tool-catalog"})
    if isinstance(output_str, dict):
        output = output_str
    elif output_str:
        try:
            output = json.loads(output_str)
        except (json.JSONDecodeError, ValueError):
            output = {"status": "error", "message": str(output_str)}
    else:
        output = None

    with st.expander(f"{meta['icon']} **{meta['label']}** — `{tool_name}`", expanded=False):
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Parámetros**")
            st.json(inputs, expanded=False)
        with c2:
            if output is None:
                st.info("Ejecutando…")
            elif output.get("status") == "error":
                st.error(output.get("message", "Error desconocido"))
            else:
                st.markdown("**Resultados clave**")
                _render_tool_summary(tool_name, output)


def _render_tool_summary(tool_name: str, data: dict):
    if tool_name == "catalog_search":
        if data.get("results"):
            top = data["results"][0]
            st.markdown(f"**{top['sku']}** — {top['name']}")
            st.markdown(f"Similitud: `{top['similarity_score']}` · {top['unit_price_eur']:.2f} EUR/{top['uom']}")
        if data.get("duplicate_warning"):
            st.warning(f"⚠️ {data['duplicates_detected']} duplicados detectados")

    elif tool_name == "contract_lookup":
        for c in data.get("contracts", []):
            st.markdown(f"**{c['contract_id']}** · vigente hasta `{c['validity_end']}`")
            for s in c.get("suppliers", []):
                st.markdown(f"- {s['name']}: objetivo `{s['market_share_pct']}`")

    elif tool_name == "quota_status":
        status = data.get("status_vs_target", "")
        badge = (
            '<span class="badge-ok">ON TRACK</span>' if status == "on_track"
            else '<span class="badge-warn">OVER</span>' if status == "over"
            else '<span class="badge-error">UNDER</span>' if status == "under"
            else f'<span class="badge-warn">{status}</span>'
        )
        st.markdown(
            f"**{data.get('supplier')}** · {data.get('current_share_pct')} actual "
            f"vs {data.get('target_share_pct')} objetivo &nbsp;{badge}",
            unsafe_allow_html=True,
        )
        st.caption(data.get("recommendation", ""))

    elif tool_name == "price_benchmark":
        cat_p = data.get("catalog_price_eur", 0)
        fair_p = data.get("estimated_fair_price_eur", 0)
        total  = data.get("total_estimated_eur", 0)
        disc   = data.get("discount_percentage", 0)
        conf   = data.get("confidence", 0)
        rng    = data.get("current_market_range", {})

        delta_pct = ((cat_p - fair_p) / fair_p * 100) if fair_p > 0 else 0
        c1, c2, c3 = st.columns(3)
        c1.metric("Precio catálogo",   f"{cat_p:.4f} EUR")
        c2.metric("Precio justo",       f"{fair_p:.4f} EUR",
                  delta=f"{delta_pct:+.1f}% vs catálogo")
        c3.metric("Total estimado",     f"{total:,.0f} EUR")
        st.caption(
            f"Rango mercado: [{rng.get('min',0):.3f} – {rng.get('median',0):.3f} – {rng.get('max',0):.3f}] · "
            f"Descuento volumen: {disc}% · Confianza ML: {conf:.0%}"
        )
        if data.get("price_alert"):
            st.warning(data["price_alert"])


def render_message(msg: dict):
    with st.chat_message(msg["role"]):
        # Tool calls del agente (si los hay)
        if msg["role"] == "assistant" and msg.get("tool_calls"):
            with st.container():
                st.markdown("**🔄 Herramientas ejecutadas**")
                for tc in msg["tool_calls"]:
                    render_tool_card(tc["tool"], tc.get("inputs", {}), tc.get("output"))
                st.divider()

        st.markdown(msg["content"])


# ── Renderizar historial ──────────────────────────────────────────────────────

for msg in st.session_state.messages:
    render_message(msg)

# ── Input de usuario (o ejemplo pendiente) ────────────────────────────────────

pending = st.session_state.pop("pending_prompt", None)
user_input = st.chat_input("Describe la solicitud de compra…") or pending

if user_input:
    # Mostrar mensaje del usuario
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    # Ejecutar agente con streaming
    with st.chat_message("assistant"):
        tool_calls_acc = []   # [{tool, inputs, output?}]
        response_text  = ""

        from agents import run_agent_streaming

        # ── Fase 1: streaming con barra de estado ─────────────────────────
        status_placeholder = st.empty()
        error_text = None

        try:
            with status_placeholder.status("🔄 Analizando solicitud…", expanded=True) as st_status:
                for event in run_agent_streaming(user_input, buyer_id):

                    if event["type"] == "tool_start":
                        name = event["tool"]
                        meta = TOOL_META.get(name, {"icon": "🔧", "label": name})
                        st_status.write(f"{meta['icon']} Ejecutando **{meta['label']}**…")
                        tool_calls_acc.append({"tool": name, "inputs": event["inputs"]})

                    elif event["type"] == "tool_end":
                        name = event["tool"]
                        meta = TOOL_META.get(name, {"icon": "🔧", "label": name})
                        for entry in reversed(tool_calls_acc):
                            if entry["tool"] == name and "output" not in entry:
                                entry["output"] = event["output"]
                                break
                        st_status.write(f"✅ {meta['label']} completada")

                    elif event["type"] == "agent_token":
                        response_text = event["token"]

                    elif event["type"] == "done":
                        response_text  = event.get("final_response", response_text)
                        tool_calls_acc = event.get("tool_calls_log", tool_calls_acc)

                st_status.update(label="✅ Análisis completado", state="complete", expanded=False)

        except Exception as e:
            err_str = str(e)
            if "502" in err_str:
                hint = (
                    "El endpoint de Ollama Cloud devuelve 502 (Bad Gateway). "
                    "Comprueba que el servicio remoto está levantado o prueba más tarde."
                )
            elif "500" in err_str:
                hint = (
                    "Error interno del servidor (500) en Ollama Cloud. "
                    "Se reintentó automáticamente 3 veces. Puede ser un pico de carga — vuelve a enviar el mensaje."
                )
            else:
                hint = (
                    f"Comprueba que Ollama está corriendo en "
                    f"`{os.getenv('OLLAMA_CLOUD_ENDPOINT', 'localhost:11434')}`."
                )
            error_text = f"⚠️ Error al conectar con el agente: `{err_str}`\n\n{hint}"
            status_placeholder.empty()

        # ── Fase 2: renderizar cards + respuesta de una vez ───────────────
        if error_text:
            st.error(error_text)
            response_text = error_text
        else:
            if tool_calls_acc:
                st.markdown("**🔄 Herramientas ejecutadas**")
                for tc in tool_calls_acc:
                    render_tool_card(tc["tool"], tc.get("inputs", {}), tc.get("output"))
                st.divider()

            if response_text:
                st.markdown(response_text)
            else:
                st.warning("El modelo no generó respuesta de texto.")

        # Guardar en historial
        st.session_state.messages.append({
            "role":       "assistant",
            "content":    response_text or "_(Sin respuesta del modelo)_",
            "tool_calls": tool_calls_acc,
        })
