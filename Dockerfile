# syntax=docker/dockerfile:1.7

ARG PYTHON_IMAGE=python:3.14.6-slim-bookworm
FROM ${PYTHON_IMAGE}

ARG APP_UID=10001
ARG APP_GID=10001

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN groupadd --gid "${APP_GID}" app \
    && useradd --uid "${APP_UID}" --gid "${APP_GID}" \
        --no-create-home --home-dir /nonexistent \
        --shell /usr/sbin/nologin app

WORKDIR /app

COPY backend/requirements.txt /tmp/requirements.txt
RUN python -m pip install --no-cache-dir --requirement /tmp/requirements.txt \
    && rm /tmp/requirements.txt

COPY --chown=${APP_UID}:${APP_GID} alembic.ini ./alembic.ini
COPY --chown=${APP_UID}:${APP_GID} backend/app ./backend/app
COPY --chown=${APP_UID}:${APP_GID} backend/migrations ./backend/migrations
COPY --chown=${APP_UID}:${APP_GID} backend/tools ./backend/tools

RUN install -d --owner="${APP_UID}" --group="${APP_GID}" /data

USER ${APP_UID}:${APP_GID}

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health/ready', timeout=3).read()"]

CMD ["python", "-m", "uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
