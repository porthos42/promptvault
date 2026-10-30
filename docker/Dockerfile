# syntax=docker/dockerfile:1
# Build from the repo root:  docker build -f docker/Dockerfile -t promptvault .

FROM node:22-slim AS web
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# vite.config.ts writes to ../backend/src/promptvault/static
RUN mkdir -p /app/backend/src/promptvault && npm run build

FROM python:3.12-slim AS app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    PV_HOST=0.0.0.0 PV_PORT=8080 PV_DATA_DIR=/data
WORKDIR /app
COPY backend/pyproject.toml ./pyproject.toml
COPY backend/src ./src
COPY --from=web /app/backend/src/promptvault/static ./src/promptvault/static
RUN pip install . && rm -rf /app/src /app/pyproject.toml \
    && useradd --uid 10001 --no-create-home --home-dir /data promptvault \
    && mkdir /data && chown promptvault /data
USER promptvault
VOLUME /data
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8080/api/v1/health', timeout=3)"
CMD ["promptvault", "serve"]
