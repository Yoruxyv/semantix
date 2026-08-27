FROM ghcr.io/astral-sh/uv:0.11.32@sha256:df4cae8f3a96d175e2e5f992e597550000edbe78fdc2594d5cd8de1a217f504c AS uv

FROM python:3.14-slim@sha256:83ff1d245a3d57d04152252d3ef9cb361494d0b3395abd65a5ebe91c401c8e83 AS builder

COPY --from=uv /uv /uvx /bin/

ENV UV_NO_CACHE=1 \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

COPY app ./app
RUN uv sync --locked --no-dev --no-editable

FROM python:3.14-slim@sha256:83ff1d245a3d57d04152252d3ef9cb361494d0b3395abd65a5ebe91c401c8e83 AS runtime

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN addgroup --system app \
    && adduser --system --ingroup app app \
    && SYSTEM_SITE_PACKAGES="$(python -c 'import site; print(site.getsitepackages()[0])')" \
    && rm -rf "$SYSTEM_SITE_PACKAGES"/pip* \
        "$SYSTEM_SITE_PACKAGES"/setuptools* \
        "$SYSTEM_SITE_PACKAGES"/wheel* \
    && rm -f /usr/local/bin/pip* /usr/bin/openssl

COPY --from=builder --chown=app:app /app/.venv /app/.venv

USER app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
