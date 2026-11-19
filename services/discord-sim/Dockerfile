# discord-sim: a fake Discord for local dev and tests. Never deploy it next to a real bot token.

# Build stage: uv installs the locked dependencies and the sim into /opt/venv. The same pinned
# Python and uv as the app's image (the root Dockerfile): bump them together.
FROM python:3.15.2-slim-trixie AS build

COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /usr/local/bin/uv

ENV UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /src
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-editable


# Runtime stage: just the virtualenv, run as an unprivileged user. No uv, pip caches or sources.
FROM python:3.15.2-slim-trixie

LABEL org.opencontainers.image.title="discord-sim" \
      org.opencontainers.image.description="Fake Discord REST v10 + gateway + control API for draft-bot dev and tests."

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    SIM_HOST=0.0.0.0 \
    SIM_PORT=8090

RUN useradd --uid 10001 --user-group --no-create-home --shell /usr/sbin/nologin sim
COPY --from=build /opt/venv /opt/venv

# Numeric, so a runtime that checks for a non-root user (runAsNonRoot) can tell.
USER 10001:10001
EXPOSE 8090
HEALTHCHECK --interval=5s --timeout=3s --start-period=5s --retries=5 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8090/_sim/health', timeout=2)"]
CMD ["discord-sim"]
