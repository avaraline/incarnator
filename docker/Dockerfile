ARG IMAGE_HOST=python
ARG IMAGE_LABEL=3.13-slim

# Build stage: install dependencies with uv

FROM ${IMAGE_HOST}:${IMAGE_LABEL} AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

RUN apt-get update && apt-get install -y --no-install-recommends gcc libc6-dev && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock /app/
WORKDIR /app

RUN uv sync --frozen --no-dev --no-install-project


# Runtime image

FROM ${IMAGE_HOST}:${IMAGE_LABEL}

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    GUNICORN_CMD_ARGS="--workers 8" \
    PATH="/takahe/.venv/bin:$PATH"

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpq5 \
        libxslt1.1 \
        nginx \
        busybox \
        postgresql-client \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /cache

# Python mimetypes package is missing some common mappings
COPY docker/mime.types /etc/mime.types

# Configure nginx
COPY docker/nginx.conf /etc/nginx/
COPY docker/nginx.conf.d/* /etc/nginx/conf.d/

COPY . /takahe
COPY --from=builder /app/.venv /takahe/.venv

# Sanity-test the nginx config
RUN nginx -t

WORKDIR /takahe

RUN TAKAHE_DEBUG="true" python manage.py collectstatic --noinput

EXPOSE 8000

CMD ["bash", "docker/run.sh"]
