# helpers — Configuration Helpers for the CES Twilio Adapter

Programmatic inspection, validation, and automation tools for Twilio and GCP. Each helper works independently but complements the other when used together. Do not guess — verify, validate, automate, and test.

## Package Structure

```
helpers/
├── __init__.py              # Package root
├── README.md                # This file — cross-helper guide
├── gcp/
│   ├── __init__.py           # Re-exports public API
│   ├── __main__.py           # python -m helpers.gcp entry
│   ├── config.py             # Core logic: fetch, validate, display
│   └── README.md             # GCP-specific documentation
└── twilio/
    ├── __init__.py           # Re-exports public API
    ├── __main__.py           # python -m helpers.twilio entry
    ├── config.py             # Core logic: fetch, validate, display
    └── README.md             # Twilio-specific documentation
```

## Design Principles

1. **Independent** — Each helper works standalone. The Twilio helper does not import the GCP helper and vice versa.
2. **Complementary** — When used together, the helpers provide a complete picture of the adapter's infrastructure and can automate cross-platform configuration.
3. **Structured** — Both helpers return typed dataclasses (`TwilioSetup`, `GcpSetup`) with consistent validation patterns.
4. **Consistent** — Same CLI modes (`--json`, `--check`, `--services`/`--numbers`, `--webhooks`/`--apis`), same `Status` enum, same `ValidationResult` pattern.
5. **Safe** — All helpers are read-only by default. Writes (webhook updates, deployments) will be added as explicit opt-in operations.

## Quick Start

```bash
source .venv/bin/activate

# Inspect everything
python -m helpers.twilio
python -m helpers.gcp

# Validate for CI/CD (exit 0/1)
python -m helpers.twilio --check
python -m helpers.gcp --check

# Machine-readable output
python -m helpers.twilio --json
python -m helpers.gcp --json
```

## Case Study: CES Twilio Adapter Deployment Workflow

This project is the case study. The adapter runs on Google Cloud Run and receives webhooks from Twilio phone numbers. Here is the complete workflow using both helpers.

### Phase 1: Inspect Current State

```python
from helpers.twilio import inspect as twilio_inspect
from helpers.gcp import inspect as gcp_inspect

# What do we have on Twilio?
twilio = twilio_inspect()
print(f"Account: {twilio.account.name}")
for pn in twilio.phone_numbers:
    print(
        f"  {pn.phone_number}: "
        f"voice={pn.capabilities['voice']}, "
        f"sms={pn.capabilities['sms']}"
    )
    print(f"    voice_url: {pn.voice_url or '(not set)'}")
    print(f"    sms_url:   {pn.sms_url or '(not set)'}")

# What do we have on GCP?
gcp = gcp_inspect()
print(f"\nProject: {gcp.project.project_id}")
print(f"Cloud Run services: {len(gcp.cloud_run_services)}")
api_names = {a.name for a in gcp.enabled_apis}
print(f"Required APIs: "
      f"run={'✅' if 'run.googleapis.com' in api_names else '❌'}, "
      f"ces={'✅' if 'ces.googleapis.com' in api_names else '❌'}, "
      f"datastore={'✅' if 'datastore.googleapis.com' in api_names else '❌'}")
```

### Phase 2: Validate Readiness

```python
from helpers.twilio import Status as TwilioStatus
from helpers.gcp import Status as GcpStatus

twilio = twilio_inspect()
gcp = gcp_inspect()

# Check for blocking issues
twilio_fails = [v for v in twilio.validations if v.status == TwilioStatus.FAIL]
gcp_fails = [v for v in gcp.validations if v.status == GcpStatus.FAIL]

if twilio_fails or gcp_fails:
    print("BLOCKING ISSUES:")
    for v in twilio_fails + gcp_fails:
        print(f"  {v.status.value}: {v.message}")
else:
    print("No blockers — safe to proceed with deployment")
```

### Phase 3: Deploy and Wire

After deploying the adapter to Cloud Run (e.g., via `bash script/deploy.sh`), use both helpers to wire the webhooks:

```python
from helpers.twilio import inspect as twilio_inspect
from helpers.gcp import inspect as gcp_inspect

# Find the deployed adapter's URI
gcp = gcp_inspect()
adapter_uri = None
for svc in gcp.cloud_run_services:
    if "twilio-adapter" in svc.name:
        adapter_uri = svc.uri
        break

if not adapter_uri:
    print("ERROR: Adapter not found in Cloud Run")
else:
    # Compare with Twilio webhooks
    twilio = twilio_inspect()
    for pn in twilio.phone_numbers:
        if pn.capabilities["voice"]:
            expected = f"{adapter_uri}/incoming-call"
            if pn.voice_url != expected:
                print(
                    f"ACTION NEEDED: Update {pn.phone_number} "
                    f"voice webhook\n"
                    f"  current: {pn.voice_url or '(not set)'}\n"
                    f"  target:  {expected}"
                )

        if pn.capabilities["sms"]:
            expected = f"{adapter_uri}/incoming-message"
            if pn.sms_url != expected:
                print(
                    f"ACTION NEEDED: Update {pn.phone_number} "
                    f"SMS webhook\n"
                    f"  current: {pn.sms_url or '(not set)'}\n"
                    f"  target:  {expected}"
                )
```

### Phase 4: Verify End-to-End

```bash
# Both should exit 0 when everything is configured correctly
python -m helpers.twilio --check && python -m helpers.gcp --check
echo "All checks passed!"
```

## Current Project State (Live)

| Component | Status | Detail |
|---|---|---|
| **Twilio Account** | ✅ | OSL-OPS (AC8b7306bbc...), active |
| **Phone Numbers** | ✅ | 3 numbers: +441527388966, +443330389929, +447878757844 |
| **Number Mappings** | ✅ | All 3 mapped in `number_mappings.json` with CES deployment ID |
| **Voice Webhooks** | ⚠️ | All 3 point to other services (not this adapter) |
| **SMS Webhooks** | ⚠️ | +447878757844 has SMS capability but no webhook |
| **GCP Project** | ✅ | `oslai-492217` |
| **Cloud Run API** | ✅ | Enabled |
| **CES API** | ✅ | Enabled |
| **Datastore API** | ✅ | Enabled |
| **Secret Manager API** | ✅ | Enabled |
| **Secret Manager Access** | ⚠️ | SA needs `roles/secretmanager.viewer` |
| **Adapter Service** | ⚠️ | Not deployed yet |

## CLI Reference

Both helpers share the same CLI pattern:

| Flag | Twilio Helper | GCP Helper |
|---|---|---|
| *(default)* | Full inspection report | Full inspection report |
| `--json` | Machine-readable JSON | Machine-readable JSON |
| `--check` | Validation-only (exit 0/1) | Validation-only (exit 0/1) |
| `--numbers` / `--services` | Phone numbers only | Cloud Run services only |
| `--webhooks` / `--apis` | Webhook audit | Enabled APIs only |

## Programmatic API

Both helpers expose the same core pattern:

```python
from helpers.twilio import inspect as twilio_inspect, TwilioSetup
from helpers.gcp import inspect as gcp_inspect, GcpSetup

# Both return a Setup dataclass with:
#   .account / .project    — account/project info
#   .phone_numbers / .cloud_run_services  — resource lists
#   .validations           — list of ValidationResult
#   .validations[i].status — Status.OK / WARN / FAIL / INFO
#   .validations[i].message — human-readable description
#   .validations[i].details — machine-readable dict

twilio: TwilioSetup = twilio_inspect()
gcp: GcpSetup = gcp_inspect()
```

## Roadmap

The helpers are designed to grow with the project. Next phases:

- **Webhook automation** — Programmatically update Twilio webhooks to point to Cloud Run services
- **Deployment automation** — Deploy the adapter to Cloud Run from the helper
- **Secret management** — Create and manage secrets in GCP Secret Manager
- **IAM management** — Grant required roles to service accounts
- **Pre-flight checks** — Validate everything before `script/deploy.sh`
- **End-to-end pipeline** — Single command to deploy, configure, and verify
