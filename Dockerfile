FROM python:3.12-slim

WORKDIR /app

# Copy and install Python package
COPY pyproject.toml README.md /app/
COPY src /app/src
RUN pip install --no-cache-dir .

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
