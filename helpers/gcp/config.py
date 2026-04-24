"""
GCP Configuration Helper — verify, validate, automate, and test.

This module programmatically inspects the Google Cloud project setup
associated with the CES Twilio Adapter. It reveals Cloud Run services,
enabled APIs, service accounts, Secret Manager secrets, and validates
the infrastructure against what the adapter requires.

Usage:
    python -m helpers.gcp                    # Full inspection
    python -m helpers.gcp --json             # Machine-readable output
    python -m helpers.gcp --check            # Validation only (exit 0/1)
    python -m helpers.gcp --services         # Cloud Run services only
    python -m helpers.gcp --apis             # Enabled APIs only

As a library:
    from helpers.gcp import inspect, GcpSetup
    setup: GcpSetup = inspect()
    for v in setup.validations:
        print(v.status, v.message)
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

from dotenv import load_dotenv
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import service_account

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

CLOUD_RUN_REGIONS = [
    "us-central1",
    "us-east1",
    "us-east4",
    "us-west1",
    "europe-west1",
    "europe-west2",
    "europe-west4",
    "europe-west9",
    "asia-east1",
    "asia-northeast1",
    "asia-southeast1",
]

# APIs the CES Twilio Adapter depends on
REQUIRED_APIS = [
    ("run.googleapis.com", "Cloud Run Admin API"),
    ("datastore.googleapis.com", "Cloud Datastore API"),
    ("secretmanager.googleapis.com", "Secret Manager API"),
    ("ces.googleapis.com", "CES API"),
    ("cloudapis.googleapis.com", "Google Cloud APIs"),
]

# APIs that are optional but commonly used
OPTIONAL_APIS = [
    ("cloudbuild.googleapis.com", "Cloud Build API"),
    ("artifactregistry.googleapis.com", "Artifact Registry API"),
    ("iam.googleapis.com", "IAM API"),
    ("iamcredentials.googleapis.com", "IAM Credentials API"),
    ("firestore.googleapis.com", "Cloud Firestore API"),
]

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class Status(str, Enum):
    OK = "OK"
    WARN = "WARN"
    FAIL = "FAIL"
    INFO = "INFO"


@dataclass
class ValidationResult:
    status: Status
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class ServiceAccountInfo:
    email: str
    display_name: str
    disabled: bool
    project_id: str


@dataclass
class GcpProjectInfo:
    project_id: str
    project_number: str = ""
    service_account: ServiceAccountInfo | None = None


@dataclass
class CloudRunServiceInfo:
    name: str
    region: str
    uri: str
    created: str
    updated: str = ""
    service_account: str = ""
    is_public: bool = False


@dataclass
class EnabledApiInfo:
    name: str
    title: str


@dataclass
class SecretInfo:
    name: str
    replication: str = ""
    created: str = ""


@dataclass
class GcpSetup:
    project: GcpProjectInfo | None = None
    cloud_run_services: list[CloudRunServiceInfo] = field(default_factory=list)
    enabled_apis: list[EnabledApiInfo] = field(default_factory=list)
    secrets: list[SecretInfo] = field(default_factory=list)
    validations: list[ValidationResult] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Credential resolution
# ---------------------------------------------------------------------------


def _get_credentials() -> service_account.Credentials:
    """Resolve GCP credentials from .env or orchestrator-settings.json."""
    load_dotenv()

    # Method 1: GOOGLE_APPLICATION_CREDENTIALS file
    creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if creds_path:
        # Resolve relative to project root
        if not os.path.isabs(creds_path):
            creds_path = os.path.join(_PROJECT_ROOT, creds_path)
        if os.path.exists(creds_path):
            creds = service_account.Credentials.from_service_account_file(
                creds_path,
                scopes=["https://www.googleapis.com/auth/cloud-platform"],
            )
            return creds

    # Method 2: orchestrator-settings.json gcpJson field
    settings_path = os.path.join(_PROJECT_ROOT, "orchestrator-settings.json")
    if os.path.exists(settings_path):
        with open(settings_path) as f:
            settings = json.load(f)
        gcp_json_str = settings.get("gcpJson")
        if gcp_json_str:
            gcp_json = json.loads(gcp_json_str)
            creds = service_account.Credentials.from_service_account_info(
                gcp_json,
                scopes=["https://www.googleapis.com/auth/cloud-platform"],
            )
            return creds

    print(
        "ERROR: No GCP credentials found. Set GOOGLE_APPLICATION_CREDENTIALS "
        "or add gcpJson to orchestrator-settings.json",
        file=sys.stderr,
    )
    sys.exit(1)


def _get_token() -> str:
    """Get a fresh OAuth2 access token."""
    creds = _get_credentials()
    creds.refresh(GoogleRequest())
    return creds.token


def _get_project_id() -> str:
    """Get the GCP project ID from credentials."""
    creds = _get_credentials()
    return creds.project_id


def _api_request(url: str, token: str) -> dict | None:
    """Make an authenticated API request, returning JSON or None."""
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 403:
            return {"_error": "PERMISSION_DENIED", "_code": 403}
        if e.code == 404:
            return {"_error": "NOT_FOUND", "_code": 404}
        return {
            "_error": f"HTTP_{e.code}",
            "_code": e.code,
            "_body": e.read().decode()[:200],
        }
    except Exception as e:
        return {"_error": str(e)}


# ---------------------------------------------------------------------------
# Fetch helpers
# ---------------------------------------------------------------------------


def fetch_project_info(token: str) -> GcpProjectInfo:
    """Fetch project info and service account details."""
    creds = _get_credentials()
    project_id = creds.project_id

    # Fetch service account info
    sa_info = None
    sa_url = (
        f"https://iam.googleapis.com/v1/projects/{project_id}"
        f"/serviceAccounts/{creds.service_account_email}"
    )
    sa_data = _api_request(sa_url, token)
    if sa_data and "_error" not in sa_data:
        sa_info = ServiceAccountInfo(
            email=sa_data.get("email", creds.service_account_email),
            display_name=sa_data.get("displayName", ""),
            disabled=sa_data.get("disabled", False),
            project_id=project_id,
        )

    return GcpProjectInfo(
        project_id=project_id,
        service_account=sa_info,
    )


def fetch_cloud_run_services(token: str, project_id: str) -> list[CloudRunServiceInfo]:
    """Discover Cloud Run services across known regions."""
    services = []
    for region in CLOUD_RUN_REGIONS:
        url = (
            f"https://run.googleapis.com/v2/projects/{project_id}"
            f"/locations/{region}/services"
        )
        data = _api_request(url, token)
        if not data or "_error" in data:
            continue
        for svc in data.get("services", []):
            full_name = svc.get("name", "")
            short_name = full_name.split("/")[-1]
            # Determine ingress setting
            ingress = (
                svc.get("template", {})
                .get("annotations", {})
                .get(
                    "run.googleapis.com/ingress",
                    "",
                )
            )
            uri = svc.get("uri", "")
            services.append(
                CloudRunServiceInfo(
                    name=short_name,
                    region=region,
                    uri=uri,
                    created=svc.get("createTime", "")[:19],
                    updated=svc.get("updateTime", "")[:19],
                    service_account=(svc.get("template", {}).get("serviceAccount", "")),
                    is_public=bool(uri and ingress != "internal"),
                )
            )
    return services


def fetch_enabled_apis(token: str, project_id: str) -> list[EnabledApiInfo]:
    """List enabled GCP APIs for the project."""
    url = (
        f"https://serviceusage.googleapis.com/v1/projects/{project_id}"
        f"/services?filter=state:ENABLED&pageSize=200"
    )
    data = _api_request(url, token)
    if not data or "_error" in data:
        return []
    apis = []
    for svc in data.get("services", []):
        config = svc.get("config", {})
        apis.append(
            EnabledApiInfo(
                name=config.get("name", svc.get("name", "")),
                title=config.get("title", ""),
            )
        )
    return apis


def fetch_secret_manager_secrets(token: str, project_id: str) -> list[SecretInfo]:
    """List secrets in Secret Manager."""
    url = f"https://secretmanager.googleapis.com/v1" f"/projects/{project_id}/secrets"
    data = _api_request(url, token)
    if not data or "_error" in data:
        return []
    secrets = []
    for s in data.get("secrets", []):
        name = s.get("name", "").split("/")[-1]
        replication = s.get("replication", {}).get("automatic", {})
        rep_type = "automatic" if replication else "customer-managed"
        secrets.append(
            SecretInfo(
                name=name,
                replication=rep_type,
                created=s.get("createTime", "")[:19],
            )
        )
    return secrets


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_apis(setup: GcpSetup) -> None:
    """Validate that required APIs are enabled."""
    enabled_names = {api.name for api in setup.enabled_apis}

    for api_name, api_title in REQUIRED_APIS:
        if api_name in enabled_names:
            setup.validations.append(
                ValidationResult(
                    status=Status.OK,
                    message=f"Required API enabled: {api_title}",
                    details={"api": api_name},
                )
            )
        else:
            setup.validations.append(
                ValidationResult(
                    status=Status.FAIL,
                    message=f"Required API NOT enabled: {api_title}",
                    details={"api": api_name},
                )
            )

    for api_name, api_title in OPTIONAL_APIS:
        if api_name in enabled_names:
            setup.validations.append(
                ValidationResult(
                    status=Status.OK,
                    message=f"Optional API enabled: {api_title}",
                    details={"api": api_name},
                )
            )
        else:
            setup.validations.append(
                ValidationResult(
                    status=Status.INFO,
                    message=f"Optional API not enabled: {api_title}",
                    details={"api": api_name},
                )
            )


def validate_cloud_run(setup: GcpSetup) -> None:
    """Validate Cloud Run services for the adapter."""
    load_dotenv()
    adapter_hostname = os.getenv("PUBLIC_SERVER_HOSTNAME", "")

    if not setup.cloud_run_services:
        setup.validations.append(
            ValidationResult(
                status=Status.WARN,
                message="No Cloud Run services found in scanned regions",
                details={"regions_scanned": CLOUD_RUN_REGIONS},
            )
        )
        return

    # Check if any service matches the adapter hostname
    if adapter_hostname:
        adapter_found = False
        for svc in setup.cloud_run_services:
            if svc.uri and adapter_hostname in svc.uri:
                adapter_found = True
                setup.validations.append(
                    ValidationResult(
                        status=Status.OK,
                        message=(
                            f"Adapter service found: {svc.name} " f"in {svc.region}"
                        ),
                        details={
                            "service": svc.name,
                            "region": svc.region,
                            "uri": svc.uri,
                        },
                    )
                )
                break
        if not adapter_found:
            setup.validations.append(
                ValidationResult(
                    status=Status.WARN,
                    message=(
                        f"No Cloud Run service matches "
                        f"PUBLIC_SERVER_HOSTNAME "
                        f"'{adapter_hostname}'"
                    ),
                    details={
                        "expected_hostname": adapter_hostname,
                        "available_uris": [s.uri for s in setup.cloud_run_services],
                    },
                )
            )

    # Report all services found
    for svc in setup.cloud_run_services:
        setup.validations.append(
            ValidationResult(
                status=Status.INFO,
                message=(
                    f"Cloud Run service: {svc.name} " f"({svc.region}) -> {svc.uri}"
                ),
                details={
                    "name": svc.name,
                    "region": svc.region,
                    "uri": svc.uri,
                    "service_account": svc.service_account,
                },
            )
        )


def validate_secret_manager(setup: GcpSetup) -> None:
    """Validate Secret Manager configuration."""
    if not setup.secrets:
        # Check if we got a permission error
        setup.validations.append(
            ValidationResult(
                status=Status.WARN,
                message=(
                    "No secrets accessible — service account may lack "
                    "Secret Manager access (roles/secretmanager.viewer)"
                ),
            )
        )
        return

    # Check for expected secret names
    expected_secrets = ["ces-twilio-auth-token", "ces-twilio-adapter-token"]
    secret_names = {s.name for s in setup.secrets}

    for expected in expected_secrets:
        if expected in secret_names:
            setup.validations.append(
                ValidationResult(
                    status=Status.OK,
                    message=f"Expected secret found: {expected}",
                    details={"secret": expected},
                )
            )
        else:
            setup.validations.append(
                ValidationResult(
                    status=Status.INFO,
                    message=f"Expected secret not found: {expected}",
                    details={"secret": expected},
                )
            )


def run_validations(setup: GcpSetup) -> None:
    validate_apis(setup)
    validate_cloud_run(setup)
    validate_secret_manager(setup)


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

_STATUS_ICONS = {
    Status.OK: "✅",
    Status.WARN: "⚠️ ",
    Status.FAIL: "❌",
    Status.INFO: "ℹ️ ",
}


def print_project(setup: GcpSetup) -> None:
    if not setup.project:
        return
    p = setup.project
    print("\n" + "=" * 60)
    print("  GCP PROJECT")
    print("=" * 60)
    print(f"  Project ID  : {p.project_id}")
    if p.service_account:
        sa = p.service_account
        print(f"  SA Email    : {sa.email}")
        print(f"  SA Name     : {sa.display_name or '(not set)'}")
        print(f"  SA Disabled : {sa.disabled}")


def print_cloud_run_services(setup: GcpSetup) -> None:
    print("\n" + "=" * 60)
    print(f"  CLOUD RUN SERVICES ({len(setup.cloud_run_services)})")
    print("=" * 60)
    if not setup.cloud_run_services:
        print("  (none found in scanned regions)")
    for svc in setup.cloud_run_services:
        print(f"\n  ☁️  {svc.name} ({svc.region})")
        print(f"     URI          : {svc.uri or '(no URI)'}")
        print(f"     Created      : {svc.created}")
        print(f"     Updated      : {svc.updated}")
        print(f"     SA           : {svc.service_account or '(default)'}")
        print(f"     Public       : {svc.is_public}")


def print_apis(setup: GcpSetup) -> None:
    print("\n" + "=" * 60)
    print(f"  ENABLED APIs ({len(setup.enabled_apis)})")
    print("=" * 60)
    if not setup.enabled_apis:
        print("  (could not retrieve)")
    required_names = {a[0] for a in REQUIRED_APIS}
    for api in sorted(setup.enabled_apis, key=lambda a: a.name):
        marker = " *" if api.name in required_names else ""
        print(f"  - {api.name}{marker}: {api.title}")
    print("\n  * = required for CES Twilio Adapter")


def print_secrets(setup: GcpSetup) -> None:
    print("\n" + "=" * 60)
    print(f"  SECRET MANAGER ({len(setup.secrets)})")
    print("=" * 60)
    if not setup.secrets:
        print("  (none accessible — may lack permissions)")
    for s in setup.secrets:
        print(f"  🔑 {s.name} (replication: {s.replication})")


def print_validations(setup: GcpSetup) -> None:
    print("\n" + "=" * 60)
    print(f"  VALIDATION RESULTS ({len(setup.validations)})")
    print("=" * 60)
    for v in setup.validations:
        icon = _STATUS_ICONS.get(v.status, "  ")
        print(f"  {icon} [{v.status.value}] {v.message}")
        for key, val in v.details.items():
            print(f"       └─ {key}: {val}")


def print_adapter_config() -> None:
    """Show what this adapter expects from GCP."""
    load_dotenv()
    print("\n" + "=" * 60)
    print("  ADAPTER GCP CONFIGURATION")
    print("=" * 60)
    hostname = os.getenv("PUBLIC_SERVER_HOSTNAME", "(not set)")
    region = os.getenv("GCP_REGION", "(not set)")
    creds = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "(not set)")
    mapping = os.getenv("NUMBERS_CONFIG_FILE", "")
    collection = os.getenv("NUMBERS_COLLECTION_ID", "")
    auth_secret = os.getenv("AUTH_TOKEN_SECRET_PATH", "")
    print(f"  PUBLIC_SERVER_HOSTNAME      : {hostname}")
    print(f"  GCP_REGION                  : {region}")
    print(f"  GOOGLE_APPLICATION_CREDENTIALS: {creds}")
    print(f"  NUMBERS_CONFIG_FILE         : {mapping or '(not set)'}")
    print(f"  NUMBERS_COLLECTION_ID       : {collection or '(not set)'}")
    print(f"  AUTH_TOKEN_SECRET_PATH      : {auth_secret or '(not set)'}")


# ---------------------------------------------------------------------------
# Full inspection
# ---------------------------------------------------------------------------


def inspect() -> GcpSetup:
    """Run a full GCP inspection and return structured results."""
    setup = GcpSetup()

    # Get credentials and token
    creds = _get_credentials()
    creds.refresh(GoogleRequest())
    token = creds.token
    project_id = creds.project_id

    # Fetch
    setup.project = fetch_project_info(token)
    setup.cloud_run_services = fetch_cloud_run_services(token, project_id)
    setup.enabled_apis = fetch_enabled_apis(token, project_id)
    setup.secrets = fetch_secret_manager_secrets(token, project_id)

    # Validate
    run_validations(setup)

    return setup


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description=("GCP Configuration Helper — " "verify, validate, automate, test")
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON (machine-readable)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help=("Validation-only mode: " "exit 0 if all OK, 1 if any FAIL/WARN"),
    )
    parser.add_argument(
        "--services",
        action="store_true",
        help="Show Cloud Run services only",
    )
    parser.add_argument(
        "--apis",
        action="store_true",
        help="Show enabled APIs only",
    )
    args = parser.parse_args()

    setup = inspect()

    if args.json:
        output = {
            "project": asdict(setup.project) if setup.project else None,
            "cloud_run_services": [asdict(s) for s in setup.cloud_run_services],
            "enabled_apis": [asdict(a) for a in setup.enabled_apis],
            "secrets": [asdict(s) for s in setup.secrets],
            "validations": [asdict(v) for v in setup.validations],
        }
        print(json.dumps(output, indent=2, default=str))
        return

    if args.check:
        has_issues = any(
            v.status in (Status.FAIL, Status.WARN) for v in setup.validations
        )
        if has_issues:
            print("FAIL — issues found:")
            for v in setup.validations:
                if v.status in (Status.FAIL, Status.WARN):
                    icon = _STATUS_ICONS.get(v.status, "  ")
                    print(f"  {icon} {v.message}")
            sys.exit(1)
        else:
            print("OK — no issues found")
            sys.exit(0)

    # Full display
    print_adapter_config()
    print_project(setup)

    if args.services:
        print_cloud_run_services(setup)
        return

    if args.apis:
        print_apis(setup)
        return

    # Default: full report
    print_cloud_run_services(setup)
    print_apis(setup)
    print_secrets(setup)
    print_validations(setup)

    # Summary
    ok = sum(1 for v in setup.validations if v.status == Status.OK)
    warn = sum(1 for v in setup.validations if v.status == Status.WARN)
    fail = sum(1 for v in setup.validations if v.status == Status.FAIL)
    info = sum(1 for v in setup.validations if v.status == Status.INFO)
    print("\n" + "=" * 60)
    print(f"  SUMMARY: {ok} OK | {warn} WARN | " f"{fail} FAIL | {info} INFO")
    print("=" * 60)


if __name__ == "__main__":
    main()
