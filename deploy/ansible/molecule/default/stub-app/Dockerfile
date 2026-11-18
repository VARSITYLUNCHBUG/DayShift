# Stand-in for ghcr.io/varsitylunchbug/dl-mm-discord in the Molecule scenario. It answers the
# same commands, probes and metrics scrapes the compose files and Prometheus use, without Django
# or Discord. Same base image as the real one, and the same database driver (uv.lock's psycopg),
# so the migrate job runs the app's own database role commands: prepare.yml copies
# league/observability/monitoring_role.py and config/app_role.py in beside django/, a psycopg
# stand-in for the little of Django they use.
FROM python:3.13.18-slim-trixie@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90

RUN pip install --no-cache-dir "psycopg[binary]==3.3.8"

# The static files migrate copies to the volume the edge serves, and that volume's mount point,
# owned by the app so a new volume is too.
RUN useradd --uid 1000 --user-group --no-create-home --shell /usr/sbin/nologin app \
    && install -d -o app -g app /srv/static \
    && install -d /app/staticfiles \
    && echo "molecule static file" > /app/staticfiles/molecule.txt
WORKDIR /app
COPY stub.py manage.py /app/
COPY league /app/league
COPY config /app/config
COPY django /app/django
COPY uvicorn.py /usr/local/bin/uvicorn
RUN chmod 0755 /usr/local/bin/uvicorn

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app
USER app
EXPOSE 8000
CMD ["uvicorn", "config.asgi:application", "--host", "0.0.0.0", "--port", "8000"]
