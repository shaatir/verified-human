# Security policy

## Prototype scope

Verified-Human is a demonstration of explainable participant-risk triage. It is not an identity
verification service, an anti-fraud guarantee, or a production-ready security control.

The web UI runs entirely in the browser. Its telemetry checksum uses a client-held demo challenge,
so it demonstrates event binding but does not provide server-validated tamper resistance. Footprint
data and threat profiles are mock data; no live OSINT lookup happens in this repository.

## Reporting a vulnerability

Please do not post a suspected vulnerability in a public issue. Use GitHub private vulnerability
reporting for this repository when available, or contact the maintainer through the `shaatir`
GitHub profile with a concise description, reproduction steps, impact, and a safe contact method.

Never include credentials, personal data, participant responses, or third-party account data in a
report. Keep any validation non-destructive and within systems you control.

## Supported versions

Only the current `main` branch is maintained. There is no production deployment or security SLA.
