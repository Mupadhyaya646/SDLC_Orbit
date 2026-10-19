# syntax=docker/dockerfile:1.7
# ---- 1) build the dashboard -------------------------------------------------
# npm must resolve through Lilly's Artifactory (Lilly-NPM). Supply the .npmrc as a
# BuildKit secret; it is never written into an image layer:
#   docker build --secret id=npmrc,src=$HOME/.npmrc --secret id=pip_conf,src=$HOME/.config/pip/pip.conf .
FROM node:22-slim AS ui
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json ./
RUN --mount=type=secret,id=npmrc,target=/root/.npmrc npm ci
COPY frontend/ ./
# vite.config.ts writes to ../sdlc_orbit/static, i.e. /sdlc_orbit/static in this stage
RUN --mount=type=secret,id=npmrc,target=/root/.npmrc npm run build

# ---- 2) the API -------------------------------------------------------------
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8000

COPY requirements.txt ./
# pip must resolve through Artifactory (Lilly-Python); the pip.conf is a build secret.
RUN --mount=type=secret,id=pip_conf,target=/etc/pip.conf pip install --no-cache-dir -r requirements.txt

COPY sdlc_orbit/ ./sdlc_orbit/
COPY migrations/ ./migrations/
COPY --from=ui /sdlc_orbit/static ./sdlc_orbit/static

RUN addgroup --system --gid 1001 appgroup && adduser --system --uid 1001 --gid 1001 appuser && chown -R appuser:appgroup /app
USER appuser
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/healthz',timeout=5).status==200 else 1)"

CMD ["uvicorn", "sdlc_orbit.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
