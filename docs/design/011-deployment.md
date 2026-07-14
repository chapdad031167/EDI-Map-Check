# Design 011 — Deployment / "run it as an app"

**Status:** approved — implemented in this PR
**Context:** make MapCheck runnable by non-CLI users, "outside a command prompt."

## The decision

For a Streamlit-based tool the industry standard is **not** to freeze a
double-click binary (PyInstaller fights Streamlit; it's unsupported and
brittle). The standard is to **run the web app as a container / hosted URL**,
keeping the CLI installable on its own. So this ships:

1. a **Dockerfile** that serves the existing Streamlit UI — `docker run -p
   8501:8501 …`, open a browser, no terminal, no local Python;
2. a **`docker compose up`** one-liner for local use;
3. **`$PORT` awareness** so the same image runs on any container host
   (Cloud Run, Render, Railway, Fly.io);
4. a **Docker CI workflow** that builds the image on every push/PR (so the
   Dockerfile can't rot) and publishes to **GHCR** on a version tag;
5. docs for **Streamlit Community Cloud** (free hosted URL) and **pipx** (the
   CLI on its own).

No application code changes — this is packaging only.

## Choices

* **Base image** `python:3.12-slim` (wheels for all deps: pyx12, openpyxl,
  pandas, pyyaml, streamlit — no build toolchain needed). Runs as a non-root
  user; a `HEALTHCHECK` hits Streamlit's `/_stcore/health`.
* **`.streamlit/config.toml`** kept minimal (`headless`, bind `0.0.0.0`, usage
  stats off) — the conventional location, honored by Docker *and* Streamlit
  Cloud. CORS/XSRF left at defaults to avoid Streamlit's re-enable warning.
* **Stateless UI**: no volume is mounted — a validation is per session; the
  history DB is a CLI concern. This keeps the container simple and 12-factor.
* **Out of scope (documented alternative):** a true offline double-click
  desktop build (stlite/Electron, or a native GUI + installer) — heavier and
  not needed once there's a hosted URL.

## Verified

The exact container command
(`streamlit run app.py --server.port=$PORT --server.address=0.0.0.0`) was run
locally: `/_stcore/health` returns `ok`, the app serves `200`, headless config
applies. The image itself builds in CI (the base image can't be pulled inside
the design sandbox); the Docker workflow's build + health smoke-test covers it.
