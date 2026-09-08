"""Streamlit-Oberflaeche des BI-Chatbot-Prototyps.

Start:  streamlit run app.py

Der Demo-Modus laeuft ohne API-Schluessel (regelbasiert) und spielt den
Beispieldialog ab. Der Lokal-Modus nutzt Ollama, der Cloud-Modus eine API.
Die Einstellungen oeffnen sich ueber die Schaltflaeche unten links.
"""
from __future__ import annotations
import copy
import os

import streamlit as st

from bi_chatbot import interpreter as nlu
from bi_chatbot.charts import build_figure
from bi_chatbot.db import load_base_measures
from bi_chatbot import narrative
from bi_chatbot.state import AnalysisContext

# --- Konfiguration aus .env laden ----------------------------------------
# Schluessel gehoeren NICHT in den Quellcode. Sie werden aus der Datei .env
# gelesen (siehe .env.example). Die Datei ist per .gitignore ausgeschlossen.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # dotenv ist optional
    pass

ENV_ANTHROPIC = os.getenv("ANTHROPIC_API_KEY", "")
ENV_OPENAI = os.getenv("OPENAI_API_KEY", "")
# `or` statt Default-Argument: greift auch, wenn die Variable leer gesetzt ist.
ENV_MODEL = os.getenv("BI_MODEL") or "claude-sonnet-5"
ENV_OLLAMA_URL = os.getenv("OLLAMA_BASE_URL") or "http://localhost:11434/v1"
ENV_OLLAMA_MODEL = os.getenv("OLLAMA_MODEL") or "llama3.2:3b"

MODI = ["Demo (ohne API)", "Lokal (Ollama)", "Cloud-API"]

st.set_page_config(page_title="BI-Chatbot · Prototyp", page_icon="📊",
                   layout="wide", initial_sidebar_state="collapsed")

# --- Zustand initialisieren ---------------------------------------------
st.session_state.setdefault("ctx", AnalysisContext())
st.session_state.setdefault("messages", [])
# Verlauf der Auswertung: je Schritt eine Momentaufnahme des Analysekontexts.
# So laesst sich nachvollziehen, wie das Diagramm entstanden ist -- und ein
# frueherer Stand wiederherstellen.
st.session_state.setdefault("verlauf", [])
st.session_state.setdefault("client", None)
# Widget-Zustaende vorbelegen. `setdefault` ersetzt keine bereits vorhandenen
# (womoeglich leeren) Werte -- daher leere Felder aktiv reparieren. Das faengt
# auch alte Sitzungen ab, die noch aus einer frueheren Programmversion stammen.
st.session_state.setdefault("mode", MODI[0])
st.session_state.setdefault("hybrid", True)
for schluessel, vorgabe in [
    ("ollama_url", ENV_OLLAMA_URL),
    ("ollama_model", ENV_OLLAMA_MODEL),
    ("cloud_provider", "anthropic"),
    ("cloud_model", ENV_MODEL),
]:
    if not st.session_state.get(schluessel):
        st.session_state[schluessel] = vorgabe

ctx: AnalysisContext = st.session_state.ctx


def _modus_gewechselt() -> None:
    """Beim Wechsel der Betriebsart eine bestehende Verbindung verwerfen."""
    st.session_state.client = None


# --- Layout: Einstellungsschaltflaeche unten links fixieren --------------
st.markdown("""
<style>
/* Diagramm bleibt beim Scrollen sichtbar */
[data-testid="stColumn"]:nth-of-type(2) > div { position: sticky; top: 3.5rem; }
/* Einstellungen: schwebende Schaltflaeche unten links */
.st-key-settings_fab {
    position: fixed;
    left: 1.5rem;
    bottom: 1.5rem;
    z-index: 1000;
}
.st-key-settings_fab button {
    border-radius: 2rem;
    box-shadow: 0 2px 10px rgba(0,0,0,.18);
}
</style>
""", unsafe_allow_html=True)

# --- Kopf ----------------------------------------------------------------
kopf, status = st.columns([0.7, 0.3])
with kopf:
    st.title("📊 BI-Assistent · Prototyp")
    st.caption("Interaktive Erstellung von Auswertungen im Dialog")
with status:
    modus = st.session_state.mode
    if modus == MODI[0]:
        st.caption("Betriebsart: **Demo** (regelbasiert)")
    elif st.session_state.client is not None:
        st.caption(f"Betriebsart: **{modus}** · ✅ verbunden")
    else:
        st.caption(f"Betriebsart: **{modus}** · ⚠️ nicht verbunden "
                   "(es antwortet der Demo-Modus)")

# WICHTIG: Dieser Block steht bewusst VOR den Spalten. Streamlit verwirft die
# Zustaende von Widgets, die in einem Skriptlauf nicht gerendert werden. Ein
# st.rerun() weiter unten (z.B. beim Wiederherstellen eines Verlaufsschritts)
# bricht den Lauf ab -- stuenden die Einstellungen danach, ginge die gewaehlte
# Betriebsart dabei verloren und fiele auf "Demo" zurueck.
#
# Bewusst `st.popover` statt `st.dialog`: der Inhalt eines Popovers wird bei
# JEDEM Skriptlauf ausgefuehrt (auch geschlossen). Die Position unten links
# kommt aus dem CSS oben, nicht aus der Reihenfolge im Skript.
with st.container(key="settings_fab"):
    with st.popover("⚙️ Einstellungen", width="content"):
        st.radio("Betriebsart", MODI, key="mode", horizontal=True,
                 on_change=_modus_gewechselt)
        modus = st.session_state.mode
        st.divider()

        if modus == "Lokal (Ollama)":
            base_url = st.text_input("Ollama-Endpoint", key="ollama_url")
            model = st.text_input("Modell", key="ollama_model")
            st.caption("Voraussetzung: Ollama läuft und das Modell wurde "
                       f"gezogen, z. B. `ollama pull {model}`. "
                       "Die Daten verlassen den Rechner nicht.")
            if st.button("Verbinden", type="primary", key="connect_local"):
                if not base_url.strip() or not model.strip():
                    st.error("Bitte Endpoint und Modellnamen ausfüllen.")
                else:
                    try:
                        st.session_state.client = nlu.make_local_client(
                            base_url.strip(), model.strip())
                        # Neu laden, damit die Statusanzeige oben sofort stimmt.
                        st.rerun()
                    except Exception as e:  # noqa: BLE001
                        st.error(f"Verbindung fehlgeschlagen: {e}")

        elif modus == "Cloud-API":
            provider = st.selectbox("Anbieter", ["anthropic", "openai"],
                                    key="cloud_provider")
            model = st.text_input("Modell", key="cloud_model")
            env_key = ENV_ANTHROPIC if provider == "anthropic" else ENV_OPENAI
            if env_key:
                st.success("API-Schlüssel aus `.env` geladen.")
                api_key = env_key
            else:
                st.caption("Kein Schlüssel in `.env` – bitte hier eingeben.")
                api_key = st.text_input("API-Schlüssel", type="password",
                                        key="cloud_key")
            if api_key and st.button("Verbinden", type="primary",
                                     key="connect_cloud"):
                if not model.strip():
                    st.error("Bitte einen Modellnamen angeben.")
                else:
                    try:
                        st.session_state.client = nlu.make_client(
                            api_key, provider, model.strip())
                        st.rerun()
                    except Exception as e:  # noqa: BLE001
                        st.error(f"Verbindung fehlgeschlagen: {e}")

        else:
            st.info("Der Demo-Modus arbeitet regelbasiert und benötigt "
                    "weder Schlüssel noch Internetverbindung.")

        if modus != MODI[0] and st.session_state.client is None:
            st.warning("Noch nicht verbunden – es antwortet der Demo-Modus.")

        if modus != MODI[0]:
            st.checkbox(
                "Regeln zuerst (hybrid)", key="hybrid",
                help="Bekannte Befehle werden deterministisch verarbeitet, "
                     "das Sprachmodell springt nur bei freien Formulierungen "
                     "ein. Ausschalten, um ausschliesslich das Modell zu testen.")

        st.divider()
        st.caption("Aktueller Analysekontext")
        st.code(ctx.summary(), language=None)
        if st.button("Analyse zurücksetzen", key="reset_all"):
            st.session_state.ctx = AnalysisContext()
            st.session_state.messages = []
            st.session_state.verlauf = []
            st.rerun()

col_chat, col_chart = st.columns([0.46, 0.54], gap="large")

# --- Diagramm rechts -----------------------------------------------------
with col_chart:
    if ctx.series:
        labels, base = load_base_measures(ctx)
        st.plotly_chart(build_figure(ctx, labels, base), width="stretch")
        st.caption(ctx.summary())
    else:
        st.info("Noch kein Diagramm. Starten Sie den Dialog links.")

    # --- Verlauf der Auswertung ---
    if st.session_state.verlauf:
        with st.expander(f"🕓 Verlauf der Auswertung "
                         f"({len(st.session_state.verlauf)} Schritte)"):
            for eintrag in reversed(st.session_state.verlauf):
                zeile, knopf = st.columns([0.78, 0.22])
                with zeile:
                    st.markdown(
                        f"**{eintrag['nr']}. {eintrag['frage']}**  \n"
                        f"<span style='font-size:0.8em;opacity:.7'>"
                        f"{eintrag['aktion']} · {eintrag['zustand'].summary()}</span>",
                        unsafe_allow_html=True)
                with knopf:
                    if st.button("Wiederherstellen",
                                 key=f"restore_{eintrag['nr']}"):
                        st.session_state.ctx = copy.deepcopy(eintrag["zustand"])
                        st.session_state.messages.append({
                            "role": "assistant",
                            "content": f"Stand von Schritt {eintrag['nr']} "
                                       f"wiederhergestellt."})
                        st.rerun()
                st.divider()

# --- Chat links ----------------------------------------------------------
with col_chat:
    # Feste Hoehe + eigener Scrollbereich: die Seite waechst nicht mit dem
    # Dialog mit, das Diagramm bleibt dadurch immer sichtbar.
    with st.container(height=460):
        if not st.session_state.messages:
            st.caption("Der Dialog erscheint hier.")
        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

    with st.expander("Beispiel-Nachrichten"):
        st.markdown(
            "- Welche Verkaufszahlen gibt es für das Jahr 2025?\n"
            "- Nimm bitte die Umsätze im Inland.\n"
            "- Stelle den Gesamtumsatz nach Monaten dar.\n"
            "- Verwende bitte Säulen statt Linien.\n"
            "- Blende die Kosten als rote Linie ein.\n"
            "- Definiere eine neue Kennzahl „Gewinn“ = Umsatz − Kosten.\n"
            "- Blende eine grüne Linie für den Gewinn ein.\n"
            "- Gruppiere nach Quartalen.\n"
            "- Zeige nur Werktage.\n"
            "- Mach einen Jahresvergleich."
        )

# --- Eingabe -------------------------------------------------------------
if prompt := st.chat_input("Ihre Nachricht…"):
    st.session_state.messages.append({"role": "user", "content": prompt})

    # NLU: Nachricht interpretieren
    client = (st.session_state.client
              if st.session_state.mode != MODI[0] else None)
    try:
        interp = nlu.interpret(prompt, ctx, client,
                               regeln_zuerst=st.session_state.hybrid)
    except Exception as e:  # noqa: BLE001
        interp = nlu.interpret_rule_based(prompt, ctx)
        st.warning(f"LLM-Fehler, Fallback auf Regelwerk: {e}")

    # Kommando ausfuehren (semantische Schicht)
    reply = nlu.apply(interp, ctx)

    # Konkrete Zahlen ergaenzen -- deterministisch aus den geladenen Daten,
    # nicht vom Sprachmodell formuliert. So stimmen Text und Diagramm immer
    # ueberein und es koennen keine Werte erfunden werden.
    if ctx.series:
        try:
            labels_txt, base_txt = load_base_measures(ctx)
            zusammenfassung = narrative.describe(ctx, labels_txt, base_txt)
            if zusammenfassung:
                reply = f"{reply}\n\n{zusammenfassung}"
        except Exception:  # noqa: BLE001 - Text ist optional, Diagramm zaehlt
            pass

    st.session_state.messages.append({"role": "assistant", "content": reply})

    # Momentaufnahme nur sichern, wenn der Befehl den Zustand veraendert hat
    if interp.action not in ("none", "list_data"):
        st.session_state.verlauf.append({
            "nr": len(st.session_state.verlauf) + 1,
            "frage": prompt,
            "aktion": interp.action,
            "zustand": copy.deepcopy(ctx),
        })
    st.rerun()
