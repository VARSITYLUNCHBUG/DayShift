# Browser end-to-end tests. Two targets on one pinned Playwright release and one locked set of
# Python packages (requirements.txt), so the client and the browser server always match:
#   chrome  a Playwright server; each test run connects and gets a fresh headless Chromium
#   e2e     pytest and the suite, driving that browser over PW_WS_ENDPOINT
# compose.test.yaml builds both; scripts/test.sh e2e runs them.

FROM mcr.microsoft.com/playwright/python:v1.64.1-noble AS base

# The image's own Python. It's a throwaway test image, so pip may install system-wide.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_BREAK_SYSTEM_PACKAGES=1 \
    PIP_ROOT_USER_ACTION=ignore

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --require-hashes -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt


FROM base AS chrome

USER pwuser
EXPOSE 3000
CMD ["playwright", "run-server", "--host", "0.0.0.0", "--port", "3000"]


FROM base AS e2e

RUN install -d -o pwuser -g pwuser /e2e /e2e/test-results
WORKDIR /e2e
COPY --chown=pwuser:pwuser . .
USER pwuser
# pytest.ini has the options. Artefacts of failed tests go to test-results/, which
# compose.test.yaml mounts on the host.
CMD ["pytest"]
