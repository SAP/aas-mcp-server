# Backend Authentication Configuration

This document explains how the AAS MCP Server authenticates to the AAS backend, the available strategies, and how to configure them.

---

## Overview

Every outbound request from the MCP server to the AAS backend carries an `Authorization: Bearer <token>` header (or none, depending on the strategy). The server resolves which token to use at request time via a pluggable **backend auth strategy**.

```
MCP Client → AAS MCP Server → AAS Backend (REST API)
                    ↑
             backend auth strategy
             decides what token
             goes here
```

The strategy is selected automatically from the environment variables you set. You rarely need to name the strategy explicitly — just set the credentials you have and the server picks the right one.

---

## Strategy selection: how it works

The server probes the environment at startup using an ordered rule chain (similar to AWS SDK credential chain):

```
1. BACKEND_AUTH_STRATEGY set explicitly?  → use it, skip probing
2. BACKEND_AUTH_CLIENT_ID + BACKEND_AUTH_CLIENT_SECRET + BACKEND_AUTH_AUDIENCE set?  → token_exchange
3. BACKEND_AUTH_CLIENT_ID + BACKEND_AUTH_CLIENT_SECRET set (no audience)?  → client_credentials
4. Nothing set?  → forward (default)
```

`none` is never auto-selected — it must always be set explicitly.

> **Migration note (breaking change):** Earlier versions of the server triggered `token_exchange` automatically
> when only `BACKEND_AUTH_AUDIENCE` was set (relying on `OAUTH_CLIENT_ID` / `OAUTH_CLIENT_SECRET` for the
> credentials). This behaviour has been removed. Auto-detection now requires all three variables —
> `BACKEND_AUTH_CLIENT_ID`, `BACKEND_AUTH_CLIENT_SECRET`, and `BACKEND_AUTH_AUDIENCE` — to be set together.
>
> If you are upgrading from a configuration that relied on `BACKEND_AUTH_AUDIENCE` alone triggering
> `token_exchange`, you must add `BACKEND_AUTH_CLIENT_ID` and `BACKEND_AUTH_CLIENT_SECRET` explicitly
> (or set `BACKEND_AUTH_STRATEGY=token_exchange` to skip probing and configure the strategy directly).
> Without this change, the server will silently fall back to the `forward` strategy.

The server logs what it selected and why at startup:

```
INFO  Backend auth: auto-selected token_exchange
      (BACKEND_AUTH_CLIENT_ID + BACKEND_AUTH_CLIENT_SECRET + BACKEND_AUTH_AUDIENCE set).
      To override, set BACKEND_AUTH_STRATEGY explicitly.
```

---

## Strategies

### `forward` (default)

Forwards the inbound MCP client token to the AAS backend unchanged.

**When to use:** MCP clients and the AAS backend share the same identity provider — the same JWT is accepted by both.

**What to set:** Nothing. This is the default when no credentials are configured.

```bash
# No variables needed — forward is the default
AAS_BASE_URL=https://aas.example.com
```

**How it works:**
- FastMCP validates the inbound Bearer token against the upstream IdP
- The validated token is forwarded as-is to every AAS request
- No token exchange or new token is fetched

---

### `token_exchange` (auto-selected when audience is set)

Exchanges the inbound user token for a new token scoped to the AAS backend audience, via RFC 8693.

**When to use:** MCP clients and the AAS backend use the same IdP but different OAuth audiences. The user authenticates to the MCP server, and the server exchanges that token for one the AAS backend accepts.

**What to set:**

| Variable | Required | Description |
|---|---|---|
| `BACKEND_AUTH_CLIENT_ID` | Yes | Client ID of the MCP server application at the IdP |
| `BACKEND_AUTH_CLIENT_SECRET` | Yes | Client secret of the MCP server application |
| `BACKEND_AUTH_AUDIENCE` | Yes | OAuth client ID of the AAS backend application |
| `BACKEND_AUTH_TOKEN_ENDPOINT` | Yes* | Token endpoint URL of the IdP |
| `BACKEND_AUTH_SCOPE` | No | Space-separated scopes to request in the exchanged token |

*`BACKEND_AUTH_TOKEN_ENDPOINT` can be omitted if `OAUTH_ISSUER_URL` is set — the endpoint is then discovered automatically from the IdP's OIDC metadata document.

**Example:**

```bash
BACKEND_AUTH_CLIENT_ID=mcp-server
BACKEND_AUTH_CLIENT_SECRET=mcp-secret
BACKEND_AUTH_AUDIENCE=aas-backend-client-id
BACKEND_AUTH_TOKEN_ENDPOINT=https://idp.example.com/realms/my-realm/protocol/openid-connect/token
```

**How it works:**
1. MCP client authenticates to the IdP, receives a user JWT
2. User JWT arrives at the MCP server as an inbound Bearer token
3. For each AAS request, the server calls the IdP token endpoint with the user JWT as `subject_token`
4. IdP returns a new token scoped to `BACKEND_AUTH_AUDIENCE`
5. New token is used as the AAS request Authorization header
6. Exchanged tokens are cached per user and refreshed before expiry

---

### `client_credentials` (auto-selected when client ID/secret set, no audience)

Fetches a machine-to-machine token from the IdP using a client ID and secret. No user context is involved.

**When to use:** The MCP server authenticates as itself (a service account) to the AAS backend. User identity is not propagated.

**What to set:**

| Variable | Required | Description |
|---|---|---|
| `BACKEND_AUTH_CLIENT_ID` | Yes | Service account client ID |
| `BACKEND_AUTH_CLIENT_SECRET` | Yes | Service account client secret |
| `BACKEND_AUTH_TOKEN_ENDPOINT` | Yes* | Token endpoint URL of the IdP |
| `BACKEND_AUTH_SCOPE` | No | Space-separated scopes to request |
| `BACKEND_AUTH_AUDIENCE` | No | Audience claim to include in the token request |

*Can be omitted if `OAUTH_ISSUER_URL` is set.

**Example:**

```bash
BACKEND_AUTH_CLIENT_ID=aas-mcp-service
BACKEND_AUTH_CLIENT_SECRET=service-secret
BACKEND_AUTH_TOKEN_ENDPOINT=https://idp.example.com/realms/my-realm/protocol/openid-connect/token
BACKEND_AUTH_SCOPE=aas:read
```

**How it works:**
1. At startup the server fetches a token using the OAuth 2.0 client credentials grant (RFC 6749 §4.4)
2. Token is cached and refreshed before expiry
3. Every AAS request uses this single service-account token regardless of which MCP user made the request

---

### `none`

No `Authorization` header is sent to the AAS backend.

**When to use:** The AAS backend has no authentication, uses mTLS at the network layer, or handles auth via a sidecar proxy.

**What to set:**

```bash
BACKEND_AUTH_STRATEGY=none
```

This strategy must be set explicitly — it is never auto-selected.

---

## All environment variables

| Variable | Description |
|---|---|
| `BACKEND_AUTH_STRATEGY` | Explicit strategy override: `forward`, `token_exchange`, `client_credentials`, `none`. When not set, strategy is auto-detected from other vars. |
| `BACKEND_AUTH_CLIENT_ID` | Client ID for token exchange or client credentials. Takes precedence over `OAUTH_CLIENT_ID`. |
| `BACKEND_AUTH_CLIENT_SECRET` | Client secret for token exchange or client credentials. Takes precedence over `OAUTH_CLIENT_SECRET`. |
| `BACKEND_AUTH_AUDIENCE` | Required for `token_exchange` (the AAS backend's OAuth client ID). Optional for `client_credentials`. |
| `BACKEND_AUTH_TOKEN_ENDPOINT` | Token endpoint URL. When not set, discovered from `OAUTH_ISSUER_URL` via OIDC metadata. |
| `BACKEND_AUTH_SCOPE` | Space-separated scopes to include in the token request. Optional for both `token_exchange` and `client_credentials`. |

---

## Decision table: what do I set?

| My setup | Variables to set |
|---|---|
| MCP and AAS share the same IdP, same JWT works for both | Nothing — `forward` is the default |
| MCP and AAS share the same IdP, but AAS needs a specific audience | `BACKEND_AUTH_CLIENT_ID` + `BACKEND_AUTH_CLIENT_SECRET` + `BACKEND_AUTH_AUDIENCE` + `BACKEND_AUTH_TOKEN_ENDPOINT` |
| MCP server authenticates as a service account (no user context) | `BACKEND_AUTH_CLIENT_ID` + `BACKEND_AUTH_CLIENT_SECRET` + `BACKEND_AUTH_TOKEN_ENDPOINT` |
| AAS backend has no authentication | `BACKEND_AUTH_STRATEGY=none` |
| Any of the above, but I want to be explicit | Set `BACKEND_AUTH_STRATEGY` to the strategy name + the required vars |

---

## Token endpoint discovery

For strategies that require a token endpoint (`token_exchange`, `client_credentials`), the endpoint can be resolved two ways:

**Explicit:**
```bash
BACKEND_AUTH_TOKEN_ENDPOINT=https://idp.example.com/realms/my-realm/protocol/openid-connect/token
```

**Auto-discovered from OIDC metadata** (when `BACKEND_AUTH_TOKEN_ENDPOINT` is not set):
```bash
OAUTH_ISSUER_URL=https://idp.example.com/realms/my-realm
# Server fetches https://idp.example.com/realms/my-realm/.well-known/openid-configuration
# and reads token_endpoint from the response
```

Explicit takes precedence over discovery.

---

## Kubernetes example

**Shared IdP (`forward`, default):**
```yaml
# No BACKEND_AUTH_* vars needed
env:
  - name: AAS_BASE_URL
    value: "https://aas-backend.internal"
  - name: OAUTH_ISSUER_URL
    value: "https://idp.example.com/realms/my-realm"
  - name: OAUTH_CLIENT_ID
    value: "aas-mcp-server"
```

**Token exchange:**
```yaml
env:
  - name: AAS_BASE_URL
    value: "https://aas-backend.internal"
  - name: OAUTH_ISSUER_URL
    value: "https://idp.example.com/realms/my-realm"
  - name: OAUTH_CLIENT_ID
    value: "aas-mcp-server"
  - name: BACKEND_AUTH_CLIENT_ID
    valueFrom:
      secretKeyRef:
        name: aas-mcp-backend-auth
        key: client-id
  - name: BACKEND_AUTH_CLIENT_SECRET
    valueFrom:
      secretKeyRef:
        name: aas-mcp-backend-auth
        key: client-secret
  - name: BACKEND_AUTH_AUDIENCE
    value: "aas-backend-client-id"
  # BACKEND_AUTH_TOKEN_ENDPOINT not set — discovered from OAUTH_ISSUER_URL
```

**Client credentials:**
```yaml
env:
  - name: AAS_BASE_URL
    value: "https://aas-backend.internal"
  - name: BACKEND_AUTH_CLIENT_ID
    valueFrom:
      secretKeyRef:
        name: aas-mcp-backend-auth
        key: client-id
  - name: BACKEND_AUTH_CLIENT_SECRET
    valueFrom:
      secretKeyRef:
        name: aas-mcp-backend-auth
        key: client-secret
  - name: BACKEND_AUTH_TOKEN_ENDPOINT
    value: "https://idp.example.com/realms/my-realm/protocol/openid-connect/token"
```

---

## Troubleshooting

### Server starts but AAS requests return 401

Check the startup log for which strategy was selected:
```
INFO  Backend auth: forward — inbound MCP token forwarded as-is to AAS
```

If `forward` was selected but you expected `token_exchange`, confirm `BACKEND_AUTH_CLIENT_ID`, `BACKEND_AUTH_CLIENT_SECRET`, and `BACKEND_AUTH_AUDIENCE` are all set. If only `OAUTH_CLIENT_ID`/`OAUTH_CLIENT_SECRET` are set, those are for inbound MCP auth — not for backend auth.

### Server refuses to start with a ValueError

The selected strategy is misconfigured. The error message names the exact variable to fix:
```
BACKEND_AUTH_AUDIENCE is required when BACKEND_AUTH_STRATEGY=token_exchange.
Set it to the OAuth client ID of the AAS backend application.
```

### Wrong strategy auto-selected

Set `BACKEND_AUTH_STRATEGY` explicitly to override auto-detection:
```bash
BACKEND_AUTH_STRATEGY=client_credentials
```

### Token endpoint discovery fails at startup

Set `BACKEND_AUTH_TOKEN_ENDPOINT` explicitly instead of relying on OIDC discovery:
```bash
BACKEND_AUTH_TOKEN_ENDPOINT=https://idp.example.com/realms/my-realm/protocol/openid-connect/token
```
