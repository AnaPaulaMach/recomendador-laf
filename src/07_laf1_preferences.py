"""
07_laf1_preferences.py â€” Preferencias del usuario para LAF 1.

El usuario indica quÃ© aspectos de CALIDAD le importan para elegir un producto.
No hay presupuesto acÃ¡ â€” eso viene despuÃ©s en LAF 2.

Flujo:
    streamlit run src/07_laf1_preferences.py
    â†’ guarda prefs_laf1.json
    â†’ correr src/08_laf1_generate.py para generar el programa LAF 1
"""

import json, os
from pathlib import Path
import streamlit as st
from dotenv import load_dotenv
from domain_config import artifact_path, load_domain_config

load_dotenv()
REPO_ROOT = Path(__file__).resolve().parents[1]
DOMAIN = load_domain_config()
PREFS_FILE = artifact_path("prefs_laf1", ".json", DOMAIN)


def display_label(label: str) -> str:
    """Muestra etiquetas de sliders con inicial mayúscula."""
    text = str(label or "").strip()
    return text[:1].upper() + text[1:] if text else text


ASPECTS = {
    key: (display_label(meta["label"]), meta.get("icon", ""))
    for key, meta in DOMAIN["quality_aspects"].items()
}

defaults = {k: 0.5 for k in ASPECTS}
if os.path.exists(PREFS_FILE):
    try:
        saved = json.load(open(PREFS_FILE, encoding="utf-8"))
        defaults.update({k: saved[k] for k in ASPECTS if k in saved})
    except Exception:
        pass

ui = DOMAIN["ui"]
st.set_page_config(page_title=ui.get("laf1_page_title", "Preferencias de calidad"), layout="centered")
st.title(ui.get("laf1_title", "Preferencias de calidad"))
st.caption(ui.get(
    "laf1_caption",
    "Indica que tan importante es cada aspecto para vos. El sistema va a recomendar productos segun estas preferencias."
))

prefs = {}
for key, (label, _) in ASPECTS.items():
    prefs[key] = st.slider(
        label,
        min_value=0.0, max_value=1.0,
        value=float(defaults[key]),
        step=0.05, key=key,
        help="0 = no me importa Â· 1 = es lo mÃ¡s importante"
    )

st.divider()

ranked = sorted(prefs.items(), key=lambda x: -x[1])
top = [f"**{ASPECTS[k][0]}**" for k, v in ranked[:3] if v > 0.3]
if top:
    st.markdown("Lo que mÃ¡s te importa: " + ", ".join(top))

if st.button("Continuar â†’", type="primary", use_container_width=True):
    with open(PREFS_FILE, "w", encoding="utf-8") as f:
        json.dump(prefs, f, ensure_ascii=False, indent=2)
    st.success("âœ… Preferencias guardadas.")
    st.info(ui.get("laf1_next_info", "Ahora corre `python src/08_laf1_generate.py` para ver el ranking de productos."))
    st.code(json.dumps(prefs, ensure_ascii=False, indent=2), language="json")

