## Purpose

Create a single markdown guide that explains the end-to-end authentication flow for an MCP server calling a Kyma-hosted backend protected by App Router and XSUAA, with SAP Cloud Identity Services (IAS) as the user identity provider.

The guide is intended to be practical first: a reader should understand the system roles, know what to configure in IAS, XSUAA, App Router, and Kyma, and be able to validate the proof of concept end-to-end using Bruno UI.

## Audience

- Engineers building or operating the MCP server integration
- Engineers unfamiliar with how IAS, XSUAA, App Router, and Kyma fit together
- Readers who need a PoC runbook more than a general SAP identity reference

## Scope

The guide will cover:

- The two-leg auth model:
  - `MCP Client -> IAS -> MCP Server`
  - `MCP Server -> XSUAA -> App Router -> Kyma Backend`
- The roles of IAS, XSUAA, App Router, Kyma backend, and the MCP server
- A high-level architecture diagram
- A detailed end-to-end sequence diagram including token issuance and token exchange
- The required configuration touchpoints in:
  - BTP subaccount trust configuration
  - XSUAA service instance and roles
  - IAS application configuration
  - App Router route/auth configuration
  - Kyma ingress/APIRule assumptions
- A Bruno-based PoC flow to verify the end-to-end exchange manually
- Expected outcomes and the most common failure modes
- A short production note explaining how the PoC differs from a production setup

The guide will not cover:

- A full production hardening playbook
- Non-XSUAA backend protection models
- A generic OAuth or OpenID Connect tutorial
- Automated implementation changes in code

## Recommended Output

Write one new markdown file under `docs/` as the primary operator-facing guide.

The guide should be optimized for GitHub readability and practical execution:

- Use a short introductory section that states the target scenario clearly
- Use an ASCII component diagram for fast scanning in plain markdown
- Use a Mermaid sequence diagram for the end-to-end flow
- Use tables sparingly for claims, configuration mapping, and troubleshooting
- Keep the Bruno section procedural and copyable

## Proposed File Structure

The guide should use the following sections:

1. Goal and target scenario
2. System actors and responsibilities
3. High-level architecture diagram
4. End-to-end sequence diagram
5. Token journey and claim expectations
6. Configuration checklist
7. IAS configuration
8. XSUAA configuration
9. App Router and Kyma configuration
10. Bruno proof of concept walkthrough
11. Success criteria
12. Common errors and what they mean
13. Short production notes

## Diagrams

The guide should include two diagrams.

### High-Level Architecture Diagram

An ASCII diagram should show:

- User / MCP client
- IAS
- MCP server
- XSUAA
- App Router
- Kyma backend

It should visually separate inbound auth from backend auth so that readers do not confuse the IAS login with the XSUAA-protected backend call.

### End-to-End Sequence Diagram

A Mermaid sequence diagram should show:

1. User starts login from the MCP client
2. MCP server redirects to IAS
3. IAS authenticates the user and returns the OIDC result to the MCP server
4. MCP server receives the upstream user token
5. MCP server calls XSUAA `/oauth/token`
6. XSUAA validates trust, user mapping, and audience
7. XSUAA issues an access token for the backend
8. MCP server calls the App Router with the XSUAA token
9. App Router validates the token and forwards to the backend
10. Backend responds

The sequence should explicitly label the tokens so the reader can distinguish:

- the IAS-issued user token
- the XSUAA-issued backend token

## Explanatory Content

The guide should explicitly explain the following points:

- IAS and XSUAA are complementary in this architecture, not alternatives
- IAS answers who the user is
- XSUAA answers whether that user is allowed to access the BTP-protected application
- App Router expects an XSUAA-accepted token, not the raw IAS token
- The most common reason direct token forwarding fails is audience mismatch
- Role collections in BTP are what ultimately drive the scopes present in the XSUAA token

## Configuration Guidance

The configuration sections should be presented as operator tasks, not abstract concepts.

### IAS section

Should explain:

- creating or identifying the IAS application for the local MCP flow
- configuring authorization code flow / PKCE assumptions if relevant to the PoC
- ensuring the IAS token has the correct audience for XSUAA exchange
- the trust relationship from IAS into the BTP subaccount

### XSUAA section

Should explain:

- creating the XSUAA service instance with scopes and role templates
- obtaining credentials via service key for the PoC
- assigning role collections to the user
- the trust expectations that allow XSUAA to accept IAS assertions

### App Router and Kyma section

Should explain:

- that App Router is the protected entrypoint in front of the backend
- that routes should use XSUAA-based auth
- that Kyma ingress/APIRule should not attempt conflicting JWT validation in front of App Router
- that the backend is reached through the App Router URL during the PoC

## Bruno PoC Design

The Bruno section should be the operational core of the guide.

It should walk through a minimal three-request validation flow:

1. Obtain IAS token in Bruno using the configured local app
2. Exchange the IAS token at XSUAA
3. Call the App Router with the XSUAA token

The Bruno section should include:

- collection variables
- which values the operator must obtain manually beforehand
- exact request purpose for each step
- what a successful response looks like
- what to inspect in the returned JWTs

It should be written so the reader can prove the architecture with Bruno before wiring the same flow into MCP server code.

## Success Criteria

The guide is successful if a reader can answer these questions after reading it:

- Why IAS alone is not sufficient for this backend
- Why XSUAA is needed in front of App Router / Kyma in this setup
- Which token is presented at each hop
- Which systems must trust each other
- How to test the exchange manually in Bruno

The PoC is successful if the reader can verify:

- IAS login works and returns a valid token
- XSUAA exchange succeeds
- the XSUAA token contains the expected audience/scopes
- App Router accepts the XSUAA token and forwards the request successfully

## Production Notes

The guide should end with a short note that the PoC uses convenient operator workflows and local/manual steps, while production typically replaces them with managed bindings, secrets, and deployment-managed configuration.

This section should stay short and mention only the most relevant differences, such as:

- service keys vs workload bindings/secrets
- manual Bruno validation vs application-driven exchange
- PoC role setup vs governed production role design

## Constraints

- Reuse and align with the existing repository guidance in `docs/jwt-bearer-token-exchange.md`
- Avoid contradicting the current documented App Router and Kyma assumptions
- Keep the tone instructional and practical, not academic
- Prefer one cohesive document over multiple scattered references
