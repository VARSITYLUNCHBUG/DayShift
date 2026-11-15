# Build stage: uv resolves the locked dependencies into /opt/venv.
FROM python:3.13-slim AS build

ENV UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never

RUN pip install --no-cache-dir "uv>=0.5,<1"

WORKDIR /app
COPY pyproject.toml uv.lock ./
# Score OCR is optional and large (onnxruntime, numpy, pillow). Build with
# `--build-arg INSTALL_OCR=true` to read report screenshots, then run `/ocr mode`.
ARG INSTALL_OCR=false
RUN if [ "$INSTALL_OCR" = "true" ]; then \
        uv sync --frozen --no-dev --group ocr --no-install-project; \
    else \
        uv sync --frozen --no-dev --no-install-project; \
    fi


# Runtime stage: the app and its virtualenv, without uv or pip caches.
FROM python:3.13-slim

ARG VERSION=dev
ARG REVISION=unknown
ARG CREATED=unknown
LABEL org.opencontainers.image.title="dl-mm-discord" \
      org.opencontainers.image.description="Discord bot that runs queue, captain draft, champion pick/ban and Elo for 6v6 Deadlock." \
      org.opencontainers.image.source="https://github.com/VARSITYLUNCHBUG/dl-mm-discord" \
      org.opencontainers.image.url="https://github.com/VARSITYLUNCHBUG/dl-mm-discord" \
      org.opencontainers.image.version="$VERSION" \
      org.opencontainers.image.revision="$REVISION" \
      org.opencontainers.image.created="$CREATED"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

RUN useradd --create-home --uid 1000 app

COPY --from=build /opt/venv /opt/venv
WORKDIR /app
COPY --chown=app:app . .
RUN DEBUG=true python manage.py collectstatic --noinput && chown -R app:app /app/staticfiles

USER app

EXPOSE 8000
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2", "--access-logfile", "-"]
