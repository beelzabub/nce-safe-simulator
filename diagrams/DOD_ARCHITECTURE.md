# NCE Safe Simulator — DoD Architecture View Set

A standard set of architecture views organized along DoDAF viewpoints, suitable
for program reviews and as the starting skeleton of an assessment package. Each
graphical view is generated from a script in this directory using the Python
[`diagrams`](https://diagrams.mingrammer.com/) library (same convention as the
existing ECS/EKS deployment diagrams); tables and sequence views live in this
document and render natively in GitLab.

## AV-1 — Overview and Summary

| | |
|---|---|
| **System** | NCE Safe Simulator (`nce-safe-simulator`) |
| **Purpose** | Simulate, measure, and report Lean-Agile (SAFe 6.0) portfolio execution against a GitLab system of record — realistic seeded data, portfolio reports, and dashboards for program stakeholders |
| **Sponsor context** | PMW 120-styled demonstration environment (SAIC study group) |
| **Architecture** | Vue 3 SPA + FastAPI/uvicorn backend + Python mixin core; GitLab REST/GraphQL as the only system of record; no database — state is JSON snapshots and generated sites on disk/EFS |
| **Deployments** | AWS EKS (recommended), AWS ECS Fargate, single-box EC2 + Caddy — one shared container image (ECR `nce-safe-simulator:latest`, ARM64) |
| **Data sensitivity** | Synthetic SAFe portfolio data (no PII/CUI). The one real secret is the GitLab Personal Access Token, held in SSM SecureString `/nce/config` (cloud) or the `GITLAB_TOKEN` env var (local) |
| **Hosting** | AWS commercial, account `881490118830`, `us-east-1` (not GovCloud; no Impact Level accreditation claimed) |

## View Index

| View | DoDAF viewpoint | Script | Output |
|---|---|---|---|
| Operational concept | OV-1 | `ov1_operational_concept.py` | `ov1-architecture.png` |
| System interfaces | SV-1 | `sv1_system_interfaces.py` | `sv1-architecture.png` |
| Deployment topology (EKS) | SV-2 | `sv2_deployment_eks.py` | `sv2-architecture.png` |
| Data flow | SV-4 | `dataflow_architecture.py` | `dataflow-architecture.png` |
| DevSecOps pipeline | — (DevSecOps ref design) | `devsecops_pipeline.py` | `devsecops-architecture.png` |
| Simple deployment (EKS / ECS) | SV-2 (summary) | `eks_architecture.py` / `ecs_architecture.py` | `eks-architecture.png` / `ecs-architecture.png` |
| Ports, protocols & services | PPSM (SV-6 style) | this document | table below |
| Logon & consent flow | OV-6c | this document | sequence below |

All PNGs are rendered at container build time (Dockerfile stage 2) into
`public/architecture/` and viewable in the web UI via the **AWS** architecture
dialog. To regenerate locally:

```bash
cd cdk
make dod-diagrams   # OV-1, SV-1, SV-2, data flow, DevSecOps
make eks-diagram    # simple EKS view (labels from live CloudFormation outputs)
make ecs-diagram    # simple ECS view
```

## PPSM — Ports, Protocols, and Services

| # | Source | Destination | Port | Protocol | Service / Purpose | Boundary control |
|---|---|---|---|---|---|---|
| 1 | User browser | CloudFront | 443 | HTTPS/TLS | Web UI, API, report sites (EKS/ECS deployments) | CloudFront-managed cert; viewer HTTPS |
| 2 | CloudFront | ALB | 80 | HTTP | Origin fetch, WebSocket upgrade forwarded | ALB SG allows only the CloudFront origin-facing prefix list |
| 3 | ALB | App pod / task | 80 | HTTP | FastAPI/uvicorn (target-type `ip`) | VPC-internal; health check `/` |
| 4 | User browser | Caddy | 443 | HTTPS/TLS | Single-box deployment (`nce-safe-sim.com`) | Let's Encrypt cert (ACME) |
| 5 | User browser | Caddy | 80 | HTTP | ACME HTTP-01 challenge + redirect to 443 | Redirect-only |
| 6 | Caddy | App container | 80 | HTTP | Reverse proxy on Docker network `nce-net` | No host port published by the app |
| 7 | Browser ↔ app | (via 1–3) | 443/80 | WebSocket `/ws/run` | Job log streaming | Same session auth as HTTP; closes 1008 unauthenticated |
| 8 | App | GitLab | 443 | HTTPS | REST v4 + GraphQL (system of record) | PAT with `api` scope; TLS verify on by default |
| 9 | App pod/task | EFS | 2049 | NFS (TLS in transit) | `/config /reports /interactive /quarto-site` | EFS SG ingress tcp/2049 from cluster SG only |
| 10 | App | AWS SSM / S3 / CloudWatch | 443 | HTTPS | Config pull, background staging, log delivery | IRSA / task role, least-privilege (`ssm:GetParameter` on `/nce/config`) |
| 11 | Amazon Managed Grafana | CloudFront `/data/*.json` | 443 | HTTPS | Dashboard datasource (Infinity plugin) | Read-only report JSON; AMG auth via IAM Identity Center |

Local development listens on `127.0.0.1:4645` (configurable) and is out of
scope for the boundary.

## OV-6c — Logon and Consent Sequence

Standard DoD Notice and Consent banner (DTM 08-060) fronts the sign-in card and
requires explicit acknowledgment once per browser session; authentication is
enforced per `auth.method` (`none` = cosmetic front door, `basic` = server-side
enforcement on every endpoint and the jobs WebSocket).

```mermaid
sequenceDiagram
    autonumber
    actor U as User
    participant B as Browser (Vue SPA)
    participant S as FastAPI Auth Gate
    U->>B: Navigate to any app route
    B->>B: No session → redirect /login
    B->>U: DoD Notice & Consent banner (DTM 08-060)
    U->>B: Acknowledge (stored per browser session)
    U->>B: Credentials in sign-in card
    B->>S: POST /api/auth/login
    alt method: basic — valid credentials
        S->>S: Constant-time compare, mint token (secrets.token_urlsafe)
        S-->>B: Set-Cookie nce_session (12 h TTL)
        B->>U: Enter application
    else method: basic — invalid
        S-->>B: 401 → inline rejection
    else method: none
        S-->>B: Accepted (cosmetic gate, client-side flag only)
    end
    Note over B,S: Every /api/*, /reports, /quarto, /data request and the<br/>jobs WebSocket carries the cookie (or Authorization: Basic)
    U->>B: Sign out
    B->>S: POST /api/auth/logout (session invalidated)
    Note over B: Banner acknowledgment survives sign-out;<br/>authentication does not
```

## Security Posture Summary

| Area | Current state |
|---|---|
| Transport | TLS at CloudFront (cloud) / Caddy-Let's Encrypt (single-box); HTTP only inside the VPC/Docker network |
| Consent banner | DTM 08-060 verbatim, on by default (`auth.dod_banner_enabled`), re-acknowledged each browser session |
| Authentication | `none` (default, cosmetic) or `basic` (dev credential); CAC/PKI, OIDC, SAML, LDAP, and local accounts are planned plug-ins in `server/auth_gate.py` (issues #152–#156) |
| Sessions | In-memory, `secrets.token_urlsafe(32)`, 12-hour TTL, cookie `nce_session`; lost on restart by design |
| Secrets | GitLab PAT never committed — SSM SecureString in cloud, env var locally; Grafana API key in SSM with 30-day rotation |
| Data at rest | EFS encrypted, transit encryption enabled; content is synthetic portfolio data |
| Logging | Job/stdout logs to CloudWatch (`/eks/nce-eks`, `/ecs/nce-safe-simulator`), 1-month retention |
| Network | No inbound admin ports — `make eks-exec`/`ecs-exec` uses SSM exec; ALB reachable only from CloudFront |

### Known gaps (candidate roadmap items)

- **AuthN**: no CAC/PIV or federated identity yet — `basic` is dev-only (#152–#156 track the AAA methods).
- **AuthZ**: no RBAC; access is authenticated-vs-not. Job conflicts are handled by writer/read-only constraint groups, not permissions.
- **Pipeline security**: CI runs tests only — no SAST/dependency scanning/container scanning/SBOM stages; image deploys are operator-driven `make` targets tagged `:latest`.
- **Audit**: job logs exist, but there is no per-user structured audit trail.
- **Hosting**: commercial `us-east-1`; a GovCloud/IL-targeted deployment would need its own accreditation work.
