# Pin the base image to a specific digest for supply chain integrity
# Update this digest when intentionally upgrading the base image.
FROM python:3.14-slim@sha256:63a4c7f612a00f92042cbdcc7cdc6a306f38485af0a200b9c89de7d9b1607d15

WORKDIR /app

# Update OS packages to pick up security patches during build
# hadolint ignore=DL3008
RUN apt-get update && apt-get upgrade -y --no-install-recommends && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Copy and install Python package, then create non-root user in the same layer.
# User creation must follow pip install so the installed scripts are owned correctly.
COPY pyproject.toml README.md /app/
COPY src /app/src
RUN pip install --no-cache-dir . && \
    groupadd --gid 1000 appuser && \
    useradd --uid 1000 --gid 1000 --no-create-home --shell /bin/false appuser

USER appuser

# Note: config.yaml and OpenAPI specs must be provided via volume mounts
# See README.md for usage instructions

ENV MCP_TRANSPORT=stdio
# MCP servers over stdio need unbuffered output
ENV PYTHONUNBUFFERED=1

# Default component (can be overridden via -e AAS_COMPONENT=...)
ENV AAS_COMPONENT=aas-repo
# AAS_BASE_URL must be provided at runtime, e.g.:
#   docker run -e AAS_BASE_URL=http://your-backend:8080 ...
# There is no safe default — omitting it causes a clear startup error.

CMD ["sh", "-c", "aas-mcp-server --component ${AAS_COMPONENT} --base-url ${AAS_BASE_URL}"]
