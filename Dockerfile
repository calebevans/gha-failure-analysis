FROM python:3.12-slim

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml README.md LICENSE ./
COPY src ./src

RUN uv pip install --system --no-cache . && \
    chgrp -R 0 /app && \
    chmod -R g=u /app && \
    useradd -u 1001 -m -d /home/gha-user gha-user && \
    mkdir -p /home/gha-user/.cache && \
    chown -R 1001:0 /home/gha-user && \
    chmod -R g=u /home/gha-user

USER 1001

ENTRYPOINT ["gha-failure-analysis"]
