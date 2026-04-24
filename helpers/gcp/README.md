# helpers/gcp — GCP Configuration Helper

Programmatic Google Cloud Platform inspection, validation, and automation tool for the CES Twilio Adapter. Provides direct programmatic access to the associated GCP project to verify infrastructure, manage Cloud Run services, and automate webhook configuration. Do not guess — verify, validate, automate, and test.

## Quick Start

```bash
# From the project root with venv activated:
source .venv/bin/activate

# Full inspection
python -m helpers.gcp

# Short-hand (same result)
python -m helpers.gcp.config
```

## CLI Modes

| Command | Description |
|---|---|
| `python -m helpers.gcp` | Full inspection report |
| `python -m helpers.gcp --json` | Machine-readable JSON output |
| `python -m helpers.gcp --check` | Validation-only; exit 0 if OK, 1 if issues |
| `python -m helpers.gcp --services` | Cloud Run services only |
| `python -m helpers.gcp --apis` | Enabled APIs only |

## Programmatic Usage (for agents and scripts)

```python
from helpers.gcp import inspect, GcpSetup, Status

# Run a full inspection
setup: GcpSetup = inspect()

# Access project info
print(setup.project.project_id)           # "oslai-492217"
print(setup.project.service_account.email) # "qoder-osl@..."

# Access Cloud Run services
for svc in setup.cloud_run_services:
    print(svc.name, svc.region, svc.uri)

# Access enabled APIs
api_names = {api.name for api in setup.enabled_apis}
if "run.googleapis.com" in api_names:
    print("Cloud Run API is enabled")

# Access Secret Manager secrets
for s in setup.secrets:
    print(s.name, s.replication)

# Check validation results
for v in setup.validations:
    if v.status == Status.FAIL:
        print(f"BLOCKER: {v.message}")
    elif v.status == Status.WARN:
        print(f"Warning: {v.message}")

# Quick pass/fail check
has_issues = any(
    v.status in (Status.FAIL, Status.WARN)
    for v in setup.validations
)
```

### Advanced: Direct API Access

```python
from helpers.gcp.config import _get_token, _api_request, _get_project_id

# Get a fresh OAuth2 token for custom API calls
token = _get_token()
project_id = _get_project_id()

# Make authenticated requests to any GCP REST API
url = f"https://run.googleapis.com/v2/projects/{project_id}/locations/us-central1/services"
data = _api_request(url, token)
```

## What It Inspects

### Project
- Project ID
- Service account email, display name, disabled status

### Cloud Run Services
- All Cloud Run services across multiple regions
- Service name, region, URI
- Service account used by each service
- Creation and update timestamps
- Ingress/public access status

### Enabled APIs
- Full list of enabled GCP APIs (with titles)
- Marked with `*` if required for the adapter

### Secret Manager
- All accessible secrets (name, replication policy, creation date)
- Detects permission issues (service account may lack access)

## What It Validates

| Check | Severity | Description |
|---|---|---|
| Required API enabled | OK/FAIL | Cloud Run, Datastore, Secret Manager, CES APIs |
| Optional API enabled | OK/INFO | Cloud Build, Artifact Registry, IAM, Firestore |
| Adapter service found | OK/WARN | Cloud Run service matching PUBLIC_SERVER_HOSTNAME |
| No services found | WARN | No Cloud Run services in any scanned region |
| Secret Manager accessible | WARN | Service account may lack `roles/secretmanager.viewer` |

### Required APIs

| API | Name | Purpose |
|---|---|---|
| `run.googleapis.com` | Cloud Run Admin API | Deploy and manage the adapter |
| `datastore.googleapis.com` | Cloud Datastore API | Firestore phone number mappings |
| `secretmanager.googleapis.com` | Secret Manager API | Store Twilio auth tokens |
| `ces.googleapis.com` | CES API | Conversational AI agent access |
| `cloudapis.googleapis.com` | Google Cloud APIs | Core GCP access |

## Credential Resolution

The helper resolves GCP credentials in this order:

1. **`GOOGLE_APPLICATION_CREDENTIALS`** env var — path to a service account JSON file (relative paths resolved from project root)
2. **`orchestrator-settings.json`** — `gcpJson` field containing inline service account JSON
3. **Error exit** — if neither source provides credentials

## Regions Scanned for Cloud Run

The helper scans these regions for Cloud Run services:

```
us-central1, us-east1, us-east4, us-west1,
europe-west1, europe-west2, europe-west4, europe-west9,
asia-east1, asia-northeast1, asia-southeast1
```

Additional regions can be added via the `CLOUD_RUN_REGIONS` constant in `config.py`.

## Validation Exit Codes (`--check`)

| Exit Code | Meaning |
|---|---|
| 0 | All validations passed (no WARN or FAIL) |
| 1 | Issues found (at least one WARN or FAIL) |

Use `--check` in CI/CD pipelines or deployment scripts to gate deployments on valid GCP infrastructure.

## File Structure

```
helpers/
├── __init__.py              # Package root (shared)
├── gcp/
│   ├── __init__.py           # Re-exports public API
│   ├── __main__.py           # python -m helpers.gcp entry
│   ├── config.py             # Core logic: fetch, validate, display
│   └── README.md             # This file
└── twilio/
    ├── ...
```

## Extending

This helper is the foundation for GCP automation. Planned enhancements:

- **Deploy Cloud Run services** programmatically
- **Update webhooks** on Twilio numbers to point to deployed Cloud Run URIs
- **Create/manage secrets** in Secret Manager
- **Grant IAM permissions** to service accounts
- **Firestore collection management** for phone number mappings
- **End-to-end deployment pipeline** combining Twilio + GCP helpers
- **Pre-flight deployment validation** before `script/deploy.sh`

## Cross-Helper Integration

The GCP helper complements the Twilio helper — they work independently
but are more powerful together. Neither depends on the other.

### Case Study: Deploying and Wiring the CES Twilio Adapter

This project (CES Twilio Adapter) is deployed on Cloud Run and receives
webhooks from Twilio. The full workflow uses both helpers:

```python
# Step 1: Inspect GCP infrastructure (GCP helper only)
from helpers.gcp import inspect as gcp_inspect

gcp = gcp_inspect()
# -> Reveals Cloud Run services, enabled APIs, secrets
# -> Project: oslai-492217
# -> 1 Cloud Run service: osl-webhooks (europe-west1)
# -> 65 enabled APIs including Cloud Run, CES, Datastore
# -> WARN: No adapter service deployed yet
# -> WARN: Secret Manager not accessible (needs IAM grant)

# Step 2: Fix GCP issues before deploying
# Enable APIs, grant IAM roles, create secrets
# Then deploy: bash script/deploy.sh

# Step 3: Verify deployment (GCP helper)
gcp = gcp_inspect()
for svc in gcp.cloud_run_services:
    if "twilio-adapter" in svc.name:
        adapter_uri = svc.uri
        print(f"Deployed at: {adapter_uri}")
        # e.g. https://ces-twilio-adapter-xxxxx-uc.a.run.app

# Step 4: Wire Twilio webhooks to the new service
# (combines data from both helpers)
from helpers.twilio import inspect as twilio_inspect

twilio = twilio_inspect()
for pn in twilio.phone_numbers:
    if pn.capabilities["voice"] and pn.voice_url != f"{adapter_uri}/incoming-call":
        print(
            f"ACTION: Update {pn.phone_number} "
            f"voice webhook\n"
            f"  from: {pn.voice_url or '(not set)'}\n"
            f"  to:   {adapter_uri}/incoming-call"
        )
    if pn.capabilities["sms"] and pn.sms_url != f"{adapter_uri}/incoming-message":
        print(
            f"ACTION: Update {pn.phone_number} "
            f"SMS webhook\n"
            f"  from: {pn.sms_url or '(not set)'}\n"
            f"  to:   {adapter_uri}/incoming-message"
        )

# Step 5: Validate end-to-end
# Re-run both helpers and check --check exits 0
# python -m helpers.gcp --check
# python -m helpers.twilio --check
```

### Current Project State

Based on the live inspection of this project:

| Component | Status | Detail |
|---|---|---|
| GCP Project | ✅ | `oslai-492217`, SA `qoder-osl@oslai-492217` |
| Cloud Run | ✅ | `osl-webhooks` in `europe-west1` (existing service) |
| Adapter Service | ⚠️ | Not deployed yet — no service matching adapter hostname |
| Cloud Run API | ✅ | Enabled |
| CES API | ✅ | Enabled |
| Datastore API | ✅ | Enabled |
| Secret Manager API | ✅ | Enabled (newly enabled) |
| Secret Manager Access | ⚠️ | SA lacks `roles/secretmanager.viewer` |
| Twilio Numbers | ✅ | 3 numbers discovered |
| Voice Webhooks | ⚠️ | All point to other services, not this adapter |
| SMS Webhooks | ⚠️ | +447878757844 has SMS capability but no webhook |
| Number Mappings | ✅ | All 3 numbers mapped in `number_mappings.json` |

### Using Individually

Each helper works standalone — you only need the GCP helper to inspect
GCP, and only the Twilio helper to inspect Twilio:

```python
# GCP-only: Check if required APIs are enabled
from helpers.gcp import inspect, Status
setup = inspect()
api_names = {a.name for a in setup.enabled_apis}
required = ["run.googleapis.com", "datastore.googleapis.com", "ces.googleapis.com"]
for api in required:
    print(f"{api}: {'enabled' if api in api_names else 'MISSING'}")

# Twilio-only: List phone number capabilities
from helpers.twilio import inspect
setup = inspect()
for pn in setup.phone_numbers:
    print(f"{pn.phone_number}: voice={pn.capabilities['voice']}, sms={pn.capabilities['sms']}")
```
