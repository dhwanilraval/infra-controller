# Infra Controller

Bare-metal lifecycle management platform built on Redfish. Vendor-agnostic server discovery, provisioning, monitoring, and orchestration through a single REST API.

Manages the full server lifecycle — from discovering a BMC on the network, through hardware configuration and OS installation, to firmware compliance and decommissioning.

## Features

- **Vendor-agnostic BMC communication** — Redfish (DMTF standard) as the primary interface with IPMI fallback for legacy hardware
- **Multi-OS provisioning** — RHEL/Ubuntu via Red Hat Satellite, Windows via MECM, VMware ESXi via vCenter, CoreOS/Flatcar via Ignition
- **Hardware inventory** — CPU, memory, storage, NIC, GPU, and TPM discovery across any Redfish-compliant server
- **Workflow engine** — Multi-step orchestration with checkpoint-based retry/resume and user-defined custom workflows
- **Firmware compliance** — Define version baselines per vendor/model, run fleet-wide drift detection
- **Multi-tenant isolation** — Organization → Project hierarchy with role-based access (owner/admin/operator/viewer)
- **Prometheus metrics** — Unauthenticated `/metrics` endpoint for fleet monitoring integration
- **Real-time events** — WebSocket streaming + event history API
- **Entra ID (Azure AD) auth** — Group-to-role RBAC mapping, plus local JWT and open modes
- **85 REST endpoints** across 16 API modules

## Supported Hardware

Infra Controller works with any server that exposes a Redfish-compliant BMC. Tested and supported vendors:

| Vendor | Platforms | BMC |
|---|---|---|
| **Dell** | PowerEdge (R750, R7525, R650, R640, etc.) | iDRAC 9 / iDRAC 8 |
| **HPE** | ProLiant (DL360, DL380, DL560, etc.) | iLO 5 / iLO 6 |
| **Lenovo** | ThinkSystem (SR630, SR650, SR670, etc.) | XClarity Controller (XCC) |
| **Supermicro** | X11, X12, X13 series | SMC BMC / Redfish |
| **Cisco** | UCS C-Series (C220, C240, C480, etc.) | Cisco IMC |
| **Inspur** | NF5280, NF5468, SA5248, etc. | Inspur BMC |
| **Huawei** | FusionServer (2288H, 2488H, etc.) | iBMC |
| **Fujitsu** | PRIMERGY (RX2530, RX2540, etc.) | iRMC S5 / S6 |

IPMI fallback is available for older servers without Redfish support (any IPMI 2.0 compliant BMC).

## Architecture

```mermaid
graph TB
    Zephyr["Zephyr"]

    Zephyr -->|REST API| API

    subgraph API["FastAPI — REST + WebSocket"]
        direction TB
        subgraph Modules["API Modules (85 endpoints)"]
            direction LR
            M1["Machines\nPower · BIOS · Boot\nStorage · Firmware"]
            M2["GPU · TPM\nIPMI · PCIe"]
            M3["Provisioning\nProfiles · Jobs\nCallback"]
            M4["Firmware\nCompliance\nBaselines · Reports"]
            M5["Tenants\nOrg · Project\nMembers · RBAC"]
            M6["Dashboard\nMetrics · Events\nAuth"]
        end
        WF["Workflow Engine — checkpoint-based retry/resume, custom steps"]
    end

    subgraph Integrations["Integration Clients"]
        direction LR
        RF["Redfish Client\n(DMTF standard)"]
        IP["IPMI Client\n(pyghmi)"]
        SAT["Satellite Client\n(Foreman API)"]
        MECM["MECM Client\n(AdminService)"]
        VC["vCenter Client\n(vSphere API)"]
        IGN["Ignition\nGenerator"]
    end

    subgraph External["External Systems"]
        direction LR
        BMC1["BMC\nRedfish"]
        BMC2["BMC\nIPMI"]
        SAT_S["Red Hat\nSatellite"]
        MECM_S["Microsoft\nMECM"]
        VC_S["VMware\nvCenter"]
    end

    DB[("PostgreSQL 16\nasync via asyncpg")]

    Modules --> WF
    WF --> Integrations
    RF --> BMC1
    IP --> BMC2
    SAT --> SAT_S
    MECM --> MECM_S
    VC --> VC_S
    API --> DB
```

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.12 |
| Framework | FastAPI + Uvicorn (ASGI) |
| Database | PostgreSQL 16 |
| ORM | SQLAlchemy 2.0 async + asyncpg |
| Migrations | Alembic |
| Auth | JWT — none / local / Entra ID (Azure AD) |
| BMC | Redfish (httpx) + IPMI fallback (pyghmi) |
| Containers | Docker + docker-compose |

## Quick Start

```bash
# Clone
git clone https://github.com/dhwanilraval/infra-controller.git
cd infra-controller

# Start with Docker
docker compose up -d

# API docs
open http://localhost:8000/docs

# Health check
curl http://localhost:8000/health
```

The API documentation is auto-generated at `/docs` (Swagger UI) and `/redoc` (ReDoc).

## API Overview — 85 Endpoints

### Machines (27 endpoints)

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/v1/machines` | List all machines (filter by state, vendor) |
| `POST` | `/api/v1/machines` | Register machine + auto-enroll via Redfish |
| `GET` | `/api/v1/machines/{id}` | Get machine details |
| `PATCH` | `/api/v1/machines/{id}` | Update machine metadata |
| `DELETE` | `/api/v1/machines/{id}` | Decommission machine |
| `POST` | `/api/v1/machines/{id}/power` | Power action (on/off/restart/force_off) |
| `GET` | `/api/v1/machines/{id}/power` | Get power state |
| `GET` | `/api/v1/machines/{id}/bios` | Read BIOS attributes |
| `PATCH` | `/api/v1/machines/{id}/bios` | Write BIOS attributes |
| `GET` | `/api/v1/machines/{id}/boot` | Get boot order/mode |
| `PATCH` | `/api/v1/machines/{id}/boot` | Set boot override (PXE/disk/CD) |
| `GET` | `/api/v1/machines/{id}/storage` | Storage controllers + drives |
| `GET` | `/api/v1/machines/{id}/firmware` | Firmware inventory |
| `POST` | `/api/v1/machines/{id}/firmware/update` | Trigger firmware update (SimpleUpdate) |
| `GET` | `/api/v1/machines/{id}/health` | Full health check (sensors + power + thermal) |
| `GET` | `/api/v1/machines/{id}/logs` | BMC system logs |
| `GET` | `/api/v1/machines/{id}/secure-boot` | Secure Boot status |
| `PATCH` | `/api/v1/machines/{id}/secure-boot` | Enable/disable Secure Boot |
| `GET` | `/api/v1/machines/{id}/virtual-media` | List mounted virtual media |
| `GET` | `/api/v1/machines/{id}/redfish/{path}` | Raw Redfish proxy |
| `POST` | `/api/v1/machines/{id}/workflows` | Start workflow (enroll/health/custom) |
| `GET` | `/api/v1/machines/{id}/workflows` | List workflows for machine |
| `GET` | `/api/v1/machines/{id}/workflows/{wf_id}` | Get workflow status |
| `POST` | `/api/v1/machines/{id}/workflows/{wf_id}/resume` | Resume failed workflow from checkpoint |

### GPU (4 endpoints)

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/v1/machines/{id}/gpus` | List GPUs (PCIe + Processor detection) |
| `GET` | `/api/v1/machines/{id}/gpus/health` | GPU thermal + health data |
| `GET` | `/api/v1/machines/{id}/pcie` | All PCIe devices |
| `GET` | `/api/v1/gpu-summary` | Fleet GPU summary |

### IPMI Fallback (7 endpoints)

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/v1/machines/{id}/ipmi/power` | IPMI power state |
| `POST` | `/api/v1/machines/{id}/ipmi/power` | IPMI power action |
| `GET` | `/api/v1/machines/{id}/ipmi/sensors` | IPMI sensor data |
| `GET` | `/api/v1/machines/{id}/ipmi/inventory` | IPMI hardware inventory |
| `GET` | `/api/v1/machines/{id}/ipmi/boot` | IPMI boot device |
| `GET` | `/api/v1/machines/{id}/ipmi/events` | IPMI system event log |
| `GET` | `/api/v1/machines/{id}/ipmi/check` | Check IPMI availability |

### TPM (2 endpoints)

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/v1/machines/{id}/tpm` | TPM modules + BIOS policy + Secure Boot |
| `GET` | `/api/v1/tpm-summary` | Fleet TPM coverage summary |

### OS Provisioning (11 endpoints)

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/v1/provisioning-profiles` | List provisioning profiles |
| `POST` | `/api/v1/provisioning-profiles` | Create profile (OS + config template) |
| `GET` | `/api/v1/provisioning-profiles/{id}` | Get profile |
| `PATCH` | `/api/v1/provisioning-profiles/{id}` | Update profile |
| `DELETE` | `/api/v1/provisioning-profiles/{id}` | Delete profile |
| `POST` | `/api/v1/machines/{id}/provision` | Provision machine (hardware prep → OS install) |
| `GET` | `/api/v1/machines/{id}/provision-jobs` | List provisioning jobs |
| `GET` | `/api/v1/machines/{id}/provision-jobs/{jid}/status` | Poll provisioning status |
| `POST` | `/api/v1/provision-callback` | Webhook — installer reports completion |
| `GET` | `/api/v1/provision-files/{id}/{filename}` | Serve Ignition/config files |
| `GET` | `/api/v1/provisioning-integrations` | Show enabled integrations |

Supported OS families and their provisioning tools:

| OS Family | Tool | Method |
|---|---|---|
| RHEL / Ubuntu | Red Hat Satellite | Foreman API → hostgroup + activation key + build mode |
| Windows Server | Microsoft MECM | AdminService API → device import + task sequence |
| VMware ESXi | vCenter | vSphere API → add host + license + cluster join |
| CoreOS / Flatcar | Ignition | Generate v3.4.0 config → serve via HTTP |

### Firmware Compliance (9 endpoints)

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/v1/firmware-baselines` | List compliance baselines |
| `POST` | `/api/v1/firmware-baselines` | Create baseline (expected versions + vendor/model filter) |
| `GET` | `/api/v1/firmware-baselines/{id}` | Get baseline |
| `PATCH` | `/api/v1/firmware-baselines/{id}` | Update baseline |
| `DELETE` | `/api/v1/firmware-baselines/{id}` | Delete baseline |
| `POST` | `/api/v1/machines/{id}/compliance-check` | Check machine against matching baselines |
| `GET` | `/api/v1/machines/{id}/compliance-reports` | List compliance reports |
| `GET` | `/api/v1/compliance-summary` | Fleet compliance rate + breakdown |
| `POST` | `/api/v1/compliance-check-all` | Check all machines (background) |

### Multi-Tenant (14 endpoints)

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/v1/orgs` | List organizations |
| `POST` | `/api/v1/orgs` | Create organization (creator → owner) |
| `GET` | `/api/v1/orgs/{slug}` | Get organization |
| `PATCH` | `/api/v1/orgs/{slug}` | Update organization |
| `DELETE` | `/api/v1/orgs/{slug}` | Deactivate organization |
| `GET` | `/api/v1/orgs/{slug}/projects` | List projects |
| `POST` | `/api/v1/orgs/{slug}/projects` | Create project |
| `GET` | `/api/v1/orgs/{slug}/projects/{slug}` | Get project |
| `PATCH` | `/api/v1/orgs/{slug}/projects/{slug}` | Update project |
| `DELETE` | `/api/v1/orgs/{slug}/projects/{slug}` | Deactivate project |
| `GET` | `/api/v1/orgs/{slug}/members` | List members |
| `POST` | `/api/v1/orgs/{slug}/members` | Add member |
| `PATCH` | `/api/v1/orgs/{slug}/members/{id}` | Change member role |
| `DELETE` | `/api/v1/orgs/{slug}/members/{id}` | Remove member |

### Dashboard (3 endpoints)

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/v1/dashboard/summary` | Fleet health (by state/health/power/vendor) |
| `GET` | `/api/v1/dashboard/events` | Recent events |
| `GET` | `/api/v1/dashboard/workflows` | Active workflows |

### Auth (3 endpoints)

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/v1/auth/config` | Auth mode + provider info |
| `POST` | `/api/v1/auth/login` | Local login (returns JWT) |
| `GET` | `/api/v1/auth/me` | Current user info |

### Other

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/metrics` | Prometheus metrics (unauthenticated) |
| `GET` | `/api/v1/credentials` | List BMC credentials |
| `POST` | `/api/v1/credentials` | Store BMC credential |
| `DELETE` | `/api/v1/credentials/{id}` | Delete credential |
| `POST` | `/api/v1/discovery` | Discover BMCs on a subnet |
| `GET` | `/api/v1/events/history` | Event history |
| `WS` | `/ws/events` | Real-time event stream |
| `POST` | `/api/v1/machines/{id}/run` | Run Ansible playbook |
| `GET` | `/api/v1/ansible/playbooks` | List available playbooks |

## Configuration

All settings use the `IC_` environment variable prefix.

### Core

| Variable | Default | Description |
|---|---|---|
| `IC_DATABASE_URL` | `postgresql+asyncpg://infra:infra@localhost:5432/infra_controller` | PostgreSQL connection |
| `IC_SECRET_KEY` | `change-me-in-production` | JWT signing key |
| `IC_AUTH_MODE` | `none` | Auth mode: `none`, `local`, `entra_id` |
| `IC_REDFISH_DEFAULT_TIMEOUT` | `30` | Redfish request timeout (seconds) |
| `IC_REDFISH_VERIFY_SSL` | `false` | Verify BMC TLS certificates |
| `IC_MAX_CONCURRENT_WORKFLOWS` | `10` | Parallel workflow limit |

### Entra ID (Azure AD)

| Variable | Description |
|---|---|
| `IC_ENTRA_TENANT_ID` | Azure AD tenant ID |
| `IC_ENTRA_CLIENT_ID` | App registration client ID |
| `IC_ENTRA_AUDIENCE` | Token audience (defaults to client ID) |
| `IC_ENTRA_ROLE_ADMIN` | Entra group Object ID → admin role |
| `IC_ENTRA_ROLE_OPERATOR` | Entra group Object ID → operator role |
| `IC_ENTRA_ROLE_VIEWER` | Entra group Object ID → viewer role |

### Provisioning Integrations

| Variable | Description |
|---|---|
| `IC_SATELLITE_ENABLED` | Enable Red Hat Satellite (`true`/`false`) |
| `IC_SATELLITE_URL` | Satellite server URL |
| `IC_SATELLITE_USERNAME` | Satellite API username |
| `IC_SATELLITE_PASSWORD` | Satellite API password |
| `IC_MECM_ENABLED` | Enable Microsoft MECM |
| `IC_MECM_URL` | MECM AdminService URL |
| `IC_MECM_CLIENT_ID` | Entra app client ID for MECM |
| `IC_MECM_CLIENT_SECRET` | Entra app client secret |
| `IC_MECM_TENANT_ID` | Azure tenant ID |
| `IC_MECM_SITE_CODE` | MECM site code |
| `IC_VCENTER_ENABLED` | Enable VMware vCenter |
| `IC_VCENTER_URL` | vCenter URL |
| `IC_VCENTER_USERNAME` | vCenter username |
| `IC_VCENTER_PASSWORD` | vCenter password |
| `IC_VCENTER_DATACENTER` | Target datacenter name |
| `IC_VCENTER_CLUSTER` | Target cluster name |
| `IC_CALLBACK_BASE_URL` | Base URL for provision callbacks |

## Machine Lifecycle

```
DISCOVERED → ENROLLING → ENROLLED → PROVISIONING → READY → IN_USE
                                                       ↓
                                    MAINTENANCE ← ← ← ←
                                        ↓
                                  DECOMMISSIONING → DECOMMISSIONED

                        (any state) → ERROR
```

## Workflow Engine

Workflows orchestrate multi-step BMC operations with automatic checkpointing:

- **Enrollment** — Connect → inventory hardware → detect GPUs → detect TPM → set state
- **Health check** — Power state → sensors → thermal → BIOS → storage → TPM → GPU
- **Provisioning** — BIOS config → RAID setup → boot order → OS deploy
- **Custom** — User-defined step sequences via JSON

Features:
- **Retry/resume** — Configurable `max_retries`, resume from last successful checkpoint
- **Checkpoints** — Each completed step is persisted; failed workflows restart from the failure point
- **Background execution** — Workflows run asynchronously, poll via API or watch via WebSocket

## Ansible Customization

Post-provisioning configuration is handled through Ansible playbooks. Enable with `IC_ANSIBLE_ENABLED=true` and place playbooks in the configured directory (`IC_ANSIBLE_PLAYBOOK_DIR`, default `./playbooks`).

### Running Playbooks

```bash
# List available playbooks
curl http://localhost:8000/api/v1/ansible/playbooks

# Run a playbook against a machine
curl -X POST http://localhost:8000/api/v1/ansible/42/run \
  -H "Content-Type: application/json" \
  -d '{"playbook": "harden-os", "extra_vars": {"ntp_server": "10.0.0.1"}}'
```

The machine's BMC credentials (`bmc_ip`, `bmc_user`, `bmc_pass`) are automatically injected as extra vars — playbooks don't need to hardcode connection details.

### Example Playbooks

| Playbook | Purpose |
|---|---|
| `harden-os.yml` | CIS benchmarks, SSH hardening, firewall rules |
| `install-gpu-drivers.yml` | NVIDIA CUDA toolkit + driver install |
| `join-k8s.yml` | kubeadm/k3s/RKE2 cluster join |
| `configure-monitoring.yml` | Deploy node_exporter, promtail, etc. |
| `setup-storage.yml` | LVM, mount points, NFS/iSCSI clients |
| `network-config.yml` | Bond interfaces, VLAN tagging, MTU settings |
| `security-baseline.yml` | TPM enrollment, certificate provisioning, SELinux |
| `decommission.yml` | Wipe disks, remove from AD/DNS, revoke certs |

### Playbook Structure

```yaml
# playbooks/join-k8s.yml
---
- name: Join Kubernetes cluster
  hosts: all
  become: true
  vars:
    k8s_version: "1.30"
    cluster_api: "{{ k8s_api_server }}"
    join_token: "{{ k8s_join_token }}"
  tasks:
    - name: Install kubeadm
      apt:
        name: "kubeadm={{ k8s_version }}.*"
        state: present

    - name: Join cluster
      command: >
        kubeadm join {{ cluster_api }}
        --token {{ join_token }}
        --discovery-token-ca-cert-hash {{ ca_hash }}
      args:
        creates: /etc/kubernetes/kubelet.conf
```

Pass cluster-specific values via `extra_vars` at runtime — the same playbook works across different clusters and environments.

### Workflow Integration

Ansible playbooks can be chained as steps in custom workflows. A typical post-provision flow:

```
OS Provisioned → harden-os → configure-monitoring → join-k8s → Machine READY
```

Each step runs as part of the workflow engine with checkpoint/retry support — if `join-k8s` fails, the workflow resumes from that step without re-running the earlier playbooks.

## Prometheus Metrics

Scrape `/metrics` (unauthenticated) for fleet monitoring:

```
# Machine fleet
ic_machines_total{state="enrolled",vendor="Dell",health_status="OK",power_state="On"} 12

# Workflows
ic_workflows_total{status="completed",workflow_type="enroll"} 45

# Provisioning
ic_provisioning_jobs_total{status="completed"} 30

# Hardware features
ic_machines_gpu_total 8
ic_machines_tpm_present 15

# Events
ic_events_total 1247
```

## Firmware Compliance

Define baselines with expected firmware versions, optionally filtered by vendor/model:

```json
{
  "name": "Dell R750 Q1 2026",
  "vendor_filter": "Dell Inc.",
  "model_filter": "PowerEdge R750",
  "rules": {
    "bios": "2.19.1",
    "bmc": "6.10.80.00",
    "components": {
      "NIC": "22.5.9",
      "RAID": "52.28.0-4565"
    }
  }
}
```

Run `POST /api/v1/machines/{id}/compliance-check` to compare actual firmware against baselines, or `POST /api/v1/compliance-check-all` for the entire fleet.

## Multi-Tenancy

Organization → Project hierarchy with role-based access:

```
Organization (acme-corp)
├── Project (gpu-cluster)
│   └── Machines scoped to this project
├── Project (dev-lab)
│   └── Machines scoped to this project
└── Members
    ├── alice@acme.com (owner)
    ├── bob@acme.com (operator)
    └── charlie@acme.com (viewer)
```

Role hierarchy: **owner** > **admin** > **operator** > **viewer**. System-level admins (from JWT) bypass org-level checks.

## Project Structure

```
app/
├── api/                    # FastAPI routers (16 modules)
│   ├── machines.py         # Core machine CRUD + BMC operations
│   ├── gpu.py              # GPU inventory + health
│   ├── ipmi.py             # IPMI fallback endpoints
│   ├── tpm.py              # TPM inventory + fleet summary
│   ├── provisioning.py     # OS provisioning + profiles + callback
│   ├── firmware.py         # Firmware compliance baselines + checks
│   ├── tenants.py          # Org/project/member management
│   ├── metrics.py          # Prometheus /metrics endpoint
│   ├── dashboard.py        # Fleet summary + events + workflows
│   ├── credentials.py      # BMC credential store
│   ├── discovery.py        # Network BMC discovery
│   ├── auth_routes.py      # Auth config + login + /me
│   ├── events_ws.py        # WebSocket events + history
│   └── ansible.py          # Ansible playbook runner
├── models/                 # SQLAlchemy models
│   ├── machine.py          # Machine, Workflow, MachineEvent, BMCCredential
│   ├── provisioning.py     # ProvisioningProfile, ProvisioningJob
│   ├── firmware.py         # FirmwareBaseline, ComplianceReport
│   └── tenant.py           # Organization, Project, OrgMember
├── schemas/                # Pydantic request/response schemas
├── redfish/                # Redfish BMC client + discovery
├── ipmi/                   # IPMI client (pyghmi wrapper)
├── provisioning/           # OS provisioning integrations
│   ├── satellite.py        # Red Hat Satellite (Foreman API)
│   ├── mecm.py             # Microsoft MECM (AdminService API)
│   ├── vcenter.py          # VMware vCenter (vSphere API)
│   ├── ignition.py         # CoreOS/Flatcar Ignition generator
│   └── orchestrator.py     # Provisioning dispatcher
├── engine/                 # Workflow engine + state machine
├── events/                 # Event broadcasting (WebSocket)
├── auth.py                 # JWT auth (none/local/Entra ID)
├── config.py               # Settings (IC_ env prefix)
├── database.py             # Async SQLAlchemy setup
└── main.py                 # FastAPI app entrypoint
```

## Development

```bash
# Local development (without Docker)
pip install -r requirements.txt
export IC_DATABASE_URL="postgresql+asyncpg://infra:infra@localhost:5432/infra_controller"
uvicorn app.main:app --reload --port 8000

# Run with Docker
docker compose up -d

# CLI
python scripts/cli.py list
python scripts/cli.py register --name server-01 --bmc-ip 10.0.0.100 --user admin --pass admin
python scripts/cli.py power server-01 --action restart
```

## License

Proprietary — internal use only.
