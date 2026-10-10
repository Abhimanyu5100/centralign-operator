# One image for both services in docker-compose.yml: Acme (`make acme`) and the bench runner (`make bench`).
# The Playwright base image brings Python 3.12 and the Chromium build that matches the locked playwright (1.63.0),
# so the GUI oracle and the browser adversarial script run inside the container (N.158: keep the tag equal to
# uv.lock; tests/test_packaging.py checks it).
FROM mcr.microsoft.com/playwright/python:v1.63.0-noble

COPY --from=ghcr.io/astral-sh/uv:0.12.23 /uv /uvx /bin/
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends make tzdata \
    && rm -rf /var/lib/apt/lists/*

# Timestamps in IST like the frozen task clocks (the base image is UTC); the bench prints GIT_COMMIT, as the image
# has no .git (`GIT_COMMIT=$(git rev-parse --short HEAD) docker compose build`; empty prints "unknown").
ARG GIT_COMMIT=
ENV TZ=Asia/Kolkata GIT_COMMIT=${GIT_COMMIT} \
    PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_LINK_MODE=copy UV_FROZEN=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv PATH=/opt/venv/bin:$PATH
WORKDIR /app

# Dependencies first (a cached layer), then the code. .dockerignore keeps out .env, .venv, runs/ and .git.
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-install-project
COPY . .
RUN uv sync --frozen

EXPOSE 8000
CMD ["make", "acme", "HOST=0.0.0.0"]
