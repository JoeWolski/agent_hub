ARG BASE_IMAGE=nvidia/cuda:12.2.2-cudnn8-devel-ubuntu22.04
FROM ${BASE_IMAGE}

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
    bash \
    ca-certificates \
    curl \
    gosu \
    git \
    less \
    openssh-client \
    passwd \
    sudo \
 && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
 && apt-get update \
 && apt-get install -y --no-install-recommends nodejs \
 && npm install -g @openai/codex \
 && npm cache clean --force \
 && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /home/codex/projects

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

WORKDIR /home/codex/projects
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["codex"]
