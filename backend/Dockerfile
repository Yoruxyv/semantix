FROM ghcr.io/astral-sh/uv:0.12.22@sha256:f513a91fc62fe7c17567eee97230dd198e43edb8a9fbecca843714a4358fe1bc AS uv

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

RUN apt-get update \
    && apt-get install --only-upgrade --yes --no-install-recommends \
        libc-bin \
        libc6 \
        perl-base \
        gzip \
        libpcre2-8-0 \
        libsqlite3-0 \
        libssl3t64 \
        openssl \
        openssl-provider-legacy \
    && rm -rf /var/lib/apt/lists/* \
    && addgroup --system app \
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
