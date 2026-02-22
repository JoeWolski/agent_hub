# syntax=docker/dockerfile:1.7

ARG PYTHON_IMAGE=python:3.11-slim-bookworm
ARG NODE_IMAGE=node:20-bookworm-slim

FROM ${NODE_IMAGE} AS frontend-builder
WORKDIR /opt/agent_hub/web
COPY web/package.json web/yarn.lock web/index.html web/vite.config.js ./
COPY web/src ./src
RUN corepack enable \
 && corepack yarn install --frozen-lockfile \
 && corepack yarn build

FROM ${PYTHON_IMAGE} AS base
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/agent_hub/.venv \
    PATH=/opt/agent_hub/.venv/bin:/root/.local/bin:${PATH}

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
    bash \
    ca-certificates \
    curl \
    docker.io \
    git \
    openssh-client \
    tini \
 && rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://astral.sh/uv/install.sh | sh

WORKDIR /opt/agent_hub

FROM base AS production
COPY pyproject.toml uv.lock README.md ./
COPY bin ./bin
COPY config ./config
COPY docker ./docker
COPY src ./src
COPY --from=frontend-builder /opt/agent_hub/web/dist ./web/dist

RUN install -m 0755 /opt/agent_hub/docker/agent_hub/run-agent-hub.sh /usr/local/bin/run-agent-hub.sh \
 && chmod +x /opt/agent_hub/bin/agent_hub /opt/agent_hub/docker/hub_artifact \
 && uv sync --frozen --no-dev

EXPOSE 8765
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/run-agent-hub.sh"]
CMD []

FROM production AS development
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
    ffmpeg \
    jq \
    nodejs \
    npm \
    xauth \
    xdotool \
    xvfb \
 && rm -rf /var/lib/apt/lists/*

RUN if ! command -v corepack >/dev/null 2>&1; then npm install -g corepack@0.31.0; fi \
 && corepack enable

COPY tests ./tests
COPY tools/demo ./tools/demo
COPY web ./web

RUN uv sync --frozen --no-dev \
 && cd /opt/agent_hub/web \
 && corepack yarn install --frozen-lockfile \
 && cd /opt/agent_hub/tools/demo \
 && npm ci \
 && npx playwright install --with-deps firefox

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["bash"]
