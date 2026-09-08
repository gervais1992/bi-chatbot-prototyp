# syntax=docker/dockerfile:1
# ---------------------------------------------------------------------------
# BI-Chatbot-Prototyp -- Container-Abbild
#
# Bauen:    docker build -t bi-chatbot .
# Starten:  docker run -p 8501:8501 bi-chatbot
# Bequemer: docker compose up   (siehe docker-compose.yml)
# ---------------------------------------------------------------------------
FROM python:3.12-slim

# Reproduzierbare, saubere Python-Umgebung
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Abhaengigkeiten zuerst: diese Schicht wird nur neu gebaut, wenn sich
# requirements.txt aendert -- spart bei jedem Code-Update viel Bauzeit.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Anwendungscode
COPY app.py create_data.py check_data.py schema.sql ./
COPY bi_chatbot/ ./bi_chatbot/
COPY tests/ ./tests/

# Demo-Datenbank bereits beim Bauen erzeugen: der Container startet dadurch
# sofort. Der feste Zufallsstartwert macht das Ergebnis reproduzierbar.
RUN python create_data.py

# Nicht als root laufen lassen
RUN useradd --create-home --uid 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8501

# Streamlit muss im Container an alle Schnittstellen binden, sonst ist die
# Anwendung von aussen nicht erreichbar.
ENV STREAMLIT_SERVER_ADDRESS=0.0.0.0 \
    STREAMLIT_SERVER_PORT=8501 \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health')" || exit 1

CMD ["streamlit", "run", "app.py"]
