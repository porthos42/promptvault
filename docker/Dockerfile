# syntax=docker/dockerfile:1
# Production image for Prompt Vault. Build from the repo root:
#   docker build -f docker/Dockerfile -t promptvault .
# Build args:
#   EXTRAS       pip extras to install (default "xlsx"; "xlsx,postgres" adds the PostgreSQL driver,
#                "" gives the smallest image)
#   PV_REVISION  git commit, reported by /api/v1/version and the OCI revision label
#   PV_VERSION   image version label
# Base images are pinned by major.minor; dependabot (docker ecosystem) proposes updates.

ARG PYTHON_VERSION=3.12
ARG NODE_VERSION=22

# ---- 1. frontend (architecture independent, so it always runs on the build platform)
FROM --platform=$BUILDPLATFORM node:${NODE_VERSION}-slim AS web
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# vite.config.ts writes to ../backend/src/promptvault/static
RUN mkdir -p /app/backend/src/promptvault && npm run build

# ---- 2. wheels: the app (with UI + seed library) and all of its dependencies
FROM python:${PYTHON_VERSION}-slim AS wheels
ARG EXTRAS="xlsx"
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
# backend/hatch_build.py bundles the seed library from the sibling folder /seed (../seed)
COPY backend/pyproject.toml backend/README.md backend/LICENSE backend/hatch_build.py ./
COPY backend/src ./src
COPY seed /seed
COPY --from=web /app/backend/src/promptvault/static ./src/promptvault/static
RUN pip wheel --wheel-dir /wheels ".${EXTRAS:+[$EXTRAS]}"

# ---- 3. runtime: only the installed wheels, no build tools, no source tree, no pip
FROM python:${PYTHON_VERSION}-slim AS runtime
ARG EXTRAS="xlsx"
ARG PV_REVISION=unknown
ARG PV_VERSION=dev
LABEL org.opencontainers.image.title="Prompt Vault" \
      org.opencontainers.image.description="Self-hosted, searchable prompt engineering library" \
      org.opencontainers.image.source="https://github.com/porthos42/promptvault" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.revision="${PV_REVISION}" \
      org.opencontainers.image.version="${PV_VERSION}"
# PV_HOST binds all interfaces inside the container; publish the port on loopback only (no auth in v1)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PV_HOST=0.0.0.0 \
    PV_PORT=8080 \
    PV_DATA_DIR=/data \
    PV_REVISION=${PV_REVISION}
RUN --mount=type=bind,from=wheels,source=/wheels,target=/wheels \
    pip install --no-cache-dir --no-index --find-links=/wheels "prompt-vault${EXTRAS:+[$EXTRAS]}" \
    # uvicorn[standard] pulls uvloop, watchfiles and websockets (~19 MB): the server runs fine on
    # asyncio, nothing here uses websockets, and --reload is a development feature
    && python -m pip uninstall -y uvloop watchfiles websockets \
    && python -m pip uninstall -y pip setuptools wheel \
    && useradd --uid 10001 --user-group --no-create-home --home-dir /data --shell /usr/sbin/nologin promptvault \
    && mkdir /data && chown promptvault:promptvault /data
USER promptvault
WORKDIR /data
VOLUME /data
EXPOSE 8080
STOPSIGNAL SIGTERM
# no curl in the slim image: use the interpreter. start-period covers migrations + seeding.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD ["python", "-c", "import urllib.request as u; u.urlopen('http://localhost:8080/api/v1/health', timeout=3)"]
CMD ["promptvault", "serve"]
