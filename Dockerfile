# EDI MapCheck — containerized Streamlit app.
#
# Build:  docker build -t edi-mapcheck .
# Run:    docker run --rm -p 8501:8501 edi-mapcheck
# Then open http://localhost:8501 — no terminal, no local Python needed.
#
# Honors $PORT (default 8501) so the same image runs unchanged on Cloud Run,
# Render, Railway, Fly.io, etc.

FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8501

WORKDIR /app

# Install the package (with the UI extra) first, from just the metadata + source
# tree, so this layer caches unless the code changes.
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install ".[ui]"

# App entrypoint script, bundled synthetic examples, and Streamlit config.
COPY app.py ./
COPY examples ./examples
COPY .streamlit ./.streamlit

# Run as an unprivileged user.
RUN useradd --create-home --uid 10001 appuser && chown -R appuser /app
USER appuser

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os,urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:'+os.environ.get('PORT','8501')+'/_stcore/health',timeout=4).read()==b'ok' else 1)"

# Shell form so ${PORT} is expanded at runtime.
CMD streamlit run app.py --server.port=${PORT} --server.address=0.0.0.0
