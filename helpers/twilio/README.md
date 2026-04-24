# helpers/twilio — Twilio Configuration Helper

Programmatic Twilio account inspection, validation, and automation tool for the CES Twilio Adapter. Do not guess — verify, validate, automate, and test.

## Quick Start

```bash
# From the project root with venv activated:
source .venv/bin/activate

# Full inspection
python -m helpers.twilio

# Short-hand (same result)
python -m helpers.twilio.config
```

## CLI Modes

| Command | Description |
|---|---|
| `python -m helpers.twilio` | Full inspection report |
| `python -m helpers.twilio --json` | Machine-readable JSON output |
| `python -m helpers.twilio --check` | Validation-only; exit 0 if OK, 1 if issues |
| `python -m helpers.twilio --numbers` | Phone numbers only |
| `python -m helpers.twilio --webhooks` | Webhook audit only |
| `python -m helpers.twilio --wire` | Wire webhooks per mapping file config |
| `python -m helpers.twilio --dry-run` | Preview what --wire would do (no changes) |
| `python -m helpers.twilio --wire --voice-only` | Wire voice webhooks only (skip SMS) |

## Programmatic Usage (for agents and scripts)

### Inspection and Validation

```python
from helpers.twilio import inspect, TwilioSetup, Status

# Run a full inspection
setup: TwilioSetup = inspect()

# Access account info
print(setup.account.name)      # "OSL-OPS"
print(setup.account.sid)       # "AC8b7306bbc..."

# Access phone numbers
for pn in setup.phone_numbers:
    print(pn.phone_number, pn.capabilities, pn.voice_url)

# Access messaging services
for ms in setup.messaging_services:
    print(ms.sid, ms.inbound_request_url)

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

### Webhook Automation

```python
from helpers.twilio import configure_webhooks, WireResult

# Preview what would be done (no changes)
results: list[WireResult] = configure_webhooks(dry_run=True)
for r in results:
    if r.skipped:
        print(f"{r.phone_number}: {r.skipped}")
    else:
        print(f"{r.phone_number}: voice={r.voice_url_set}, sms={r.sms_url_set}")

# Wire webhooks for real
results = configure_webhooks()

# Wire voice only (skip SMS)
results = configure_webhooks(voice_only=True)

# Pass an existing client
from twilio.rest import Client
client = Client(sid, auth_token)
results = configure_webhooks(client=client)
```

### Per-Number Webhook Routing

Each phone number can point to a different adapter (Cloud Run instance).
Webhook targets are resolved from `number_mappings.json`:

1. **Per-number override**: `webhook_base_url` field on the number's entry
2. **Global default**: `PUBLIC_SERVER_HOSTNAME` env var

```json
{
  "+441527388966": {
    "label": "osl-national",
    "deployment_id": "projects/...",
    "environment": "prod"
  },
  "+447878757844": {
    "label": "osl-mobile",
    "deployment_id": "projects/...",
    "environment": "prod",
    "webhook_base_url": "different-adapter-xxx.uc.a.run.app"
  }
}
```

In this example:
- `+441527388966` uses the default adapter (`PUBLIC_SERVER_HOSTNAME`)
- `+447878757844` overrides to a different Cloud Run instance

The `--wire` command and `configure_webhooks()` respect this resolution order
automatically — no extra flags needed.

## What It Inspects

### Account
- Account SID, friendly name, status, type

### Phone Numbers
- All incoming phone numbers on the account
- Capabilities per number: Voice, SMS, MMS, Fax
- Webhook URLs: Voice, Voice Fallback, SMS, SMS Fallback, Status Callback
- Webhook HTTP methods
- Bundle SID, origin, address requirements
- Created/updated timestamps

### Messaging Services
- All messaging services (SID, friendly name)
- Inbound request URL and method
- Associated phone number SIDs

### Conversations Services
- All conversations services (required for RCS)
- SID, friendly name, creation date

## What It Validates

| Check | Severity | Description |
|---|---|---|
| Voice webhook missing | WARN | Number has voice capability but no voice URL set |
| Voice webhook mismatch | WARN | Voice URL does not point to this adapter |
| SMS webhook missing | WARN | Number has SMS capability but no SMS URL set |
| SMS webhook mismatch | WARN | SMS URL does not point to this adapter |
| Number mapping gap | WARN | A Twilio number is not in `number_mappings.json` |
| Stale mapping | WARN | A number in `number_mappings.json` is not on Twilio |
| No mapping configured | FAIL | Neither `NUMBERS_CONFIG_FILE` nor `NUMBERS_COLLECTION_ID` is set |
| Messaging service no URL | WARN | Messaging service has phone numbers but no inbound URL |
| Messaging service empty | INFO | Messaging service exists but has no phone numbers assigned |
| No conversations service | INFO | No conversations service (required for RCS) |
| Voice/SMS not capable | INFO | Number does not support the capability (informational) |

## Credential Resolution

The helper resolves Twilio credentials in this order:

1. **`.env` file** — `TWILIO_ACCOUNT_SID` and `TWILIO_AUTH_TOKEN`
2. **`orchestrator-settings.json`** — `twilioSid` and `twilioAuth` fields (project root)
3. **Error exit** — if neither source provides credentials

The `PUBLIC_SERVER_HOSTNAME` env var is used to compute expected webhook URLs for validation.

## Validation Exit Codes (`--check`)

| Exit Code | Meaning |
|---|---|
| 0 | All validations passed (no WARN or FAIL) |
| 1 | Issues found (at least one WARN or FAIL) |

Use `--check` in CI/CD pipelines or deployment scripts to gate deployments on a valid Twilio configuration.

## File Structure

```
helpers/
├── __init__.py              # Package root
└── twilio/
    ├── __init__.py           # Re-exports public API
    ├── __main__.py           # python -m helpers.twilio entry
    ├── config.py             # Core logic: fetch, validate, display
    └── README.md             # This file
```

## Extending

This helper is designed to grow with the project. Planned enhancements include:

- RCS sender discovery and configuration
- `number_mappings.json` sync from live Twilio numbers
- Deployment readiness pre-flight checks
- Integration with `script/deploy.sh` for automated pre-deploy validation

## Cross-Helper Integration

The Twilio helper complements the GCP helper — they work independently
but are more powerful together. Neither depends on the other.

### Case Study: Deploying and Wiring the CES Twilio Adapter

The full workflow for this project uses both helpers in sequence:

```python
# Step 1: Inspect Twilio account (Twilio helper only)
from helpers.twilio import inspect as twilio_inspect

twilio = twilio_inspect()
# -> Reveals phone numbers, capabilities, webhook gaps
# -> WARN: All 3 voice webhooks point to other services
# -> WARN: +447878757844 has SMS but no SMS webhook

# Step 2: Inspect GCP infrastructure (GCP helper only)
from helpers.gcp import inspect as gcp_inspect

gcp = gcp_inspect()
# -> Reveals Cloud Run services, enabled APIs, secrets
# -> WARN: No adapter service deployed yet
# -> FAIL: Secret Manager API not enabled (now fixed)

# Step 3: Deploy the adapter to Cloud Run (GCP helper)
# After deployment, the GCP helper can discover the new service URI:
for svc in gcp.cloud_run_services:
    if "twilio-adapter" in svc.name:
        adapter_uri = svc.uri
        print(f"Adapter deployed at: {adapter_uri}")

# Step 4: Configure Twilio webhooks to point to the adapter
from helpers.twilio import configure_webhooks

# Preview first
results = configure_webhooks(dry_run=True)
# Then wire for real
results = configure_webhooks()
# Per-number routing is automatic via number_mappings.json

# Step 5: Verify everything is wired correctly
# Re-run both inspections to confirm all validations pass
twilio = twilio_inspect()
gcp = gcp_inspect()
# Now: voice webhooks point to adapter, adapter is deployed,
# APIs enabled, secrets configured
```

### Using Individually

Each helper works standalone — you only need the Twilio helper to
inspect Twilio, and only the GCP helper to inspect GCP:

```python
# Twilio-only: Check webhook configuration
from helpers.twilio import inspect
setup = inspect()
for pn in setup.phone_numbers:
    print(f"{pn.phone_number}: voice={pn.voice_url}")

# GCP-only: Find deployed Cloud Run services
from helpers.gcp import inspect
setup = inspect()
for svc in setup.cloud_run_services:
    print(f"{svc.name} ({svc.region}): {svc.uri}")
```
