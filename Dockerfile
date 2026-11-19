# One image for every app service: web (the CMD), bot, scheduler and migrate (compose.yaml
# picks the command). Runs as an unprivileged user on a read-only root; compose adds the init
# process and a /tmp tmpfs.
#
# Targets: `runtime` (the default, last, and what is published) has only what production runs.
# `dev` adds devtools/ and fixtures/: the dev control API and the dev seed, for compose.dev.yaml
# and compose.test.yaml. `test` is the unit suite's: the same locked dependencies plus the dev
# group, then the code and tests. The layers are ordered so a code change rebuilds only the last
# one: dependencies first, from pyproject.toml and uv.lock alone.
# Bases are pinned by digest as well as tag; Dependabot moves both.

# Build stage: uv resolves the locked dependencies into /opt/venv.
FROM python:3.13.18-slim-trixie@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90 AS build

COPY --from=ghcr.io/astral-sh/uv:0.13.7@sha256:96f40d3904aad8d0bd010539001d36c8e2188b981e1334471a90c4a1d93bb490 /uv /usr/local/bin/uv

ENV UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app
COPY pyproject.toml uv.lock ./
# Score OCR is optional and large (onnxruntime, numpy, pillow). Build with
# `--build-arg INSTALL_OCR=true` to read report screenshots, then turn on the server's Score OCR
# setting in the admin.
ARG INSTALL_OCR=false
RUN --mount=type=cache,target=/root/.cache/uv \
    if [ "$INSTALL_OCR" = "true" ]; then \
        uv sync --frozen --no-dev --group ocr --no-install-project; \
    else \
        uv sync --frozen --no-dev --no-install-project; \
    fi


# The app and its virtualenv. No uv, pip, caches or compilers.
FROM python:3.13.18-slim-trixie@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90 AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

# Debian's security fixes published since the base image was built, so a rebuild picks them up
# without waiting for a new python tag. Then no pip: nothing installs packages at runtime, and
# its vendored libraries (urllib3, msgpack, ...) would only be more to scan and patch. The app's
# virtualenv never had one.
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip uninstall --yes --no-cache-dir pip \
    && rm -rf /usr/local/lib/python3.13/ensurepip \
    && useradd --uid 1000 --user-group --no-create-home --shell /usr/sbin/nologin app

COPY --from=build /opt/venv /opt/venv
WORKDIR /app
# Owned by root: the app can read its code but not rewrite it, even if it is compromised. Only
# what production runs; .dockerignore's allowlist also lets in the dev target's folders.
COPY manage.py pyproject.toml ./
COPY bot/ bot/
COPY config/ config/
COPY league/ league/
COPY presets/ presets/
COPY scoreocr/ scoreocr/
# Static files and bytecode are built here, because the running containers can't write. web
# serves the static files (WhiteNoise).
RUN DEBUG=true python manage.py collectstatic --noinput \
    && python -m compileall -q -j 0 bot config league scoreocr manage.py

USER app

EXPOSE 8000
# One worker is plenty for the admin and the dashboard. Lifespan is off because Django's ASGI
# handler doesn't speak it. Proxy headers are trusted only from FORWARDED_ALLOW_IPS (uvicorn's
# default: 127.0.0.1); compose sets it for the edge.
CMD ["uvicorn", "config.asgi:application", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers", "--lifespan", "off", "--timeout-graceful-shutdown", "20"]


# Dev and test stacks: the same, plus the dev control API (devtools, which settings only installs
# with DEV_CONTROL, itself refused without DEBUG) and the dev fixtures.
FROM base AS dev
USER root
COPY devtools/ devtools/
COPY fixtures/ fixtures/
RUN python -m compileall -q -j 0 devtools
USER app


# The unit suite's dependencies: the build stage's virtualenv plus the dev group, so only what the
# dev group adds is installed here.
FROM build AS test-venv
ARG INSTALL_OCR=false
RUN --mount=type=cache,target=/root/.cache/uv \
    if [ "$INSTALL_OCR" = "true" ]; then \
        uv sync --frozen --group ocr --no-install-project; \
    else \
        uv sync --frozen --no-install-project; \
    fi


# The unit suite: the cached dependencies, then the working tree (.dockerignore's allowlist, tests
# included) as the last layer, which is all a code change rebuilds.
FROM python:3.13.18-slim-trixie@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90 AS test
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    HOME=/tmp
COPY --from=test-venv /opt/venv /opt/venv
WORKDIR /app
COPY --chown=1000:1000 . .
USER 1000:1000
CMD ["pytest", "-n", "auto"]


# Production: the published image. Last, so it is what a plain `docker build` makes.
FROM base AS runtime

# Last, so a new version or date never invalidates the layers above.
ARG VERSION=dev
ARG REVISION=unknown
ARG CREATED=unknown
LABEL org.opencontainers.image.title="DayShift" \
      org.opencontainers.image.description="Discord bot that runs queue, captain draft, champion pick/ban and Elo for 6v6 Deadlock." \
      org.opencontainers.image.source="https://github.com/VARSITYLUNCHBUG/DayShift" \
      org.opencontainers.image.url="https://github.com/VARSITYLUNCHBUG/DayShift" \
      org.opencontainers.image.version="$VERSION" \
      org.opencontainers.image.revision="$REVISION" \
      org.opencontainers.image.created="$CREATED"
