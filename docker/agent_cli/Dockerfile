ARG BASE_IMAGE=nvidia/cuda:12.2.2-cudnn8-devel-ubuntu22.04
FROM ${BASE_IMAGE}
ARG AGENT_PROVIDER=codex
ARG LOCAL_USER
ARG LOCAL_HOME

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
    bash \
    ca-certificates \
    curl \
    gh \
    gosu \
    git \
    less \
    openssh-client \
    python3 \
    passwd \
    sudo \
 && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
 && apt-get update \
 && apt-get install -y --no-install-recommends nodejs \
 && case "${AGENT_PROVIDER}" in \
      codex) npm install -g @openai/codex ;; \
      claude) : "${LOCAL_USER:?LOCAL_USER build arg is required for claude provider}" \
              && : "${LOCAL_HOME:?LOCAL_HOME build arg is required for claude provider}" \
              && if ! getent group "${LOCAL_USER}" >/dev/null 2>&1; then \
                   groupadd "${LOCAL_USER}"; \
                 fi \
              && if ! id -u "${LOCAL_USER}" >/dev/null 2>&1; then \
                   useradd --home-dir "${LOCAL_HOME}" --create-home --shell /bin/bash --gid "${LOCAL_USER}" "${LOCAL_USER}"; \
                 else \
                   usermod --home "${LOCAL_HOME}" "${LOCAL_USER}" || true; \
                 fi \
              && mkdir -p "${LOCAL_HOME}" \
              && (chown "$(id -u "${LOCAL_USER}")":"$(id -g "${LOCAL_USER}")" "${LOCAL_HOME}" || true) \
              && sudo -u "${LOCAL_USER}" -H bash -lc 'set -euo pipefail; export PATH="$HOME/.local/bin:$PATH"; curl -fsSL https://claude.ai/install.sh | bash -; test -x "$HOME/.local/bin/claude"; claude --version >/dev/null' ;; \
      gemini) npm install -g @google/gemini-cli ;; \
      none) echo "Skipping agent CLI install for setup image." ;; \
      *) echo "Unsupported AGENT_PROVIDER='${AGENT_PROVIDER}'" >&2; exit 1 ;; \
    esac \
 && npm cache clean --force \
 && rm -rf /var/lib/apt/lists/*

COPY docker/agent_cli/docker-entrypoint.py /usr/local/bin/docker-entrypoint.py
COPY docker/agent_cli/hub_artifact /usr/local/bin/hub_artifact
RUN chmod +x /usr/local/bin/docker-entrypoint.py /usr/local/bin/hub_artifact

WORKDIR /projects
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.py"]
CMD ["codex"]
