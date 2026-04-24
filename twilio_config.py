"""
Twilio Configuration Helper — verify, validate, automate, and test.

This script programmatically inspects the Twilio account setup,
revealing phone numbers, capabilities, webhooks, messaging services,
and RCS configuration. It validates the setup against what the
CES Twilio Adapter requires and flags any gaps.

Usage:
    python twilio_config.py              # Full inspection
    python twilio_config.py --json       # Machine-readable output
    python twilio_config.py --check      # Validation only (exit 0/1)
    python twilio_config.py --numbers    # Phone numbers only
    python twilio_config.py --webhooks   # Webhook audit only
"""

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

from dotenv import load_dotenv
from twilio.rest import Client

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ADAPTER_VOICE_ENDPOINT = "/incoming-call"
ADAPTER_MESSAGE_ENDPOINT = "/incoming-message"
ADAPTER_MEDIA_STREAM = "/media-stream"

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
class PhoneNumberInfo:
    sid: str
    phone_number: str
    friendly_name: str
    capabilities: dict[str, bool]
    voice_url: str
    voice_method: str
    voice_fallback_url: str
    sms_url: str
    sms_method: str
    sms_fallback_url: str
    status_callback: str
    address_requirements: str
    origin: str
    date_created: str
    date_updated: str
    bundle_sid: str | None = None
    status: str = ""


@dataclass
class MessagingServiceInfo:
    sid: str
    friendly_name: str
    inbound_request_url: str
    inbound_method: str
    phone_number_sids: list[str] = field(default_factory=list)
    date_created: str = ""


@dataclass
class ConversationsServiceInfo:
    sid: str
    friendly_name: str
    date_created: str = ""


@dataclass
class AccountInfo:
    sid: str
    name: str
    status: str
    type: str


@dataclass
class TwilioSetup:
    account: AccountInfo | None = None
    phone_numbers: list[PhoneNumberInfo] = field(default_factory=list)
    messaging_services: list[MessagingServiceInfo] = field(default_factory=list)
    conversations_services: list[ConversationsServiceInfo] = field(default_factory=list)
    validations: list[ValidationResult] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Fetch helpers
# ---------------------------------------------------------------------------


def _get_client() -> Client:
    """Build a Twilio client from environment or orchestrator-settings.json."""
    load_dotenv()

    sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth = os.getenv("TWILIO_AUTH_TOKEN")

    if not sid or not auth:
        # Try orchestrator-settings.json
        settings_path = os.path.join(
            os.path.dirname(__file__), "orchestrator-settings.json"
        )
        if os.path.exists(settings_path):
            with open(settings_path) as f:
                settings = json.load(f)
            sid = sid or settings.get("twilioSid")
            auth = auth or settings.get("twilioAuth")

    if not sid or not auth:
        print(
            "ERROR: TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN must be set "
            "via .env or orchestrator-settings.json",
            file=sys.stderr,
        )
        sys.exit(1)

    return Client(sid, auth)


def fetch_account(client: Client) -> AccountInfo:
    acct = client.api.account.fetch()
    return AccountInfo(
        sid=acct.sid,
        name=acct.friendly_name,
        status=acct.status,
        type=acct.type,
    )


def fetch_phone_numbers(client: Client) -> list[PhoneNumberInfo]:
    numbers = []
    for pn in client.incoming_phone_numbers.list(limit=100):
        numbers.append(
            PhoneNumberInfo(
                sid=pn.sid,
                phone_number=str(pn.phone_number),
                friendly_name=pn.friendly_name or "",
                capabilities={
                    "voice": pn.capabilities.get("voice", False),
                    "sms": pn.capabilities.get("sms", False),
                    "mms": pn.capabilities.get("mms", False),
                    "fax": pn.capabilities.get("fax", False),
                },
                voice_url=pn.voice_url or "",
                voice_method=pn.voice_method or "",
                voice_fallback_url=pn.voice_fallback_url or "",
                sms_url=pn.sms_url or "",
                sms_method=pn.sms_method or "",
                sms_fallback_url=pn.sms_fallback_url or "",
                status_callback=pn.status_callback or "",
                address_requirements=pn.address_requirements or "",
                origin=pn.origin or "",
                date_created=str(pn.date_created or ""),
                date_updated=str(pn.date_updated or ""),
                bundle_sid=pn.bundle_sid,
                status=getattr(pn, "status", ""),
            )
        )
    return numbers


def fetch_messaging_services(client: Client) -> list[MessagingServiceInfo]:
    services = []
    for ms in client.messaging.v1.services.list(limit=100):
        phone_sids = [pn.sid for pn in ms.phone_numbers.list()]
        services.append(
            MessagingServiceInfo(
                sid=ms.sid,
                friendly_name=ms.friendly_name or "",
                inbound_request_url=ms.inbound_request_url or "",
                inbound_method=ms.inbound_method or "",
                phone_number_sids=phone_sids,
                date_created=str(ms.date_created or ""),
            )
        )
    return services


def fetch_conversations_services(client: Client) -> list[ConversationsServiceInfo]:
    services = []
    try:
        for cs in client.conversations.v1.services.list(limit=100):
            services.append(
                ConversationsServiceInfo(
                    sid=cs.sid,
                    friendly_name=cs.friendly_name or "",
                    date_created=str(cs.date_created or ""),
                )
            )
    except Exception:
        pass
    return services


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _adapter_hostname() -> str:
    load_dotenv()
    return os.getenv("PUBLIC_SERVER_HOSTNAME", "")


def _expected_adapter_voice_url() -> str:
    hostname = _adapter_hostname()
    if not hostname:
        return ""
    scheme = "https://" if not hostname.startswith("http") else ""
    return f"{scheme}{hostname}{ADAPTER_VOICE_ENDPOINT}"


def _expected_adapter_message_url() -> str:
    hostname = _adapter_hostname()
    if not hostname:
        return ""
    scheme = "https://" if not hostname.startswith("http") else ""
    return f"{scheme}{hostname}{ADAPTER_MESSAGE_ENDPOINT}"


def validate_phone_numbers(setup: TwilioSetup) -> None:
    expected_voice = _expected_adapter_voice_url()
    expected_msg = _expected_adapter_message_url()

    for pn in setup.phone_numbers:
        # Voice webhook check
        if pn.capabilities["voice"]:
            if not pn.voice_url:
                setup.validations.append(
                    ValidationResult(
                        status=Status.WARN,
                        message=(
                            f"{pn.phone_number}: voice capability "
                            f"but no voice webhook configured"
                        ),
                        details={"phone_number": pn.phone_number, "sid": pn.sid},
                    )
                )
            elif expected_voice and pn.voice_url != expected_voice:
                setup.validations.append(
                    ValidationResult(
                        status=Status.WARN,
                        message=f"{pn.phone_number}: voice webhook points elsewhere",
                        details={
                            "phone_number": pn.phone_number,
                            "current": pn.voice_url,
                            "expected": expected_voice,
                        },
                    )
                )
            else:
                setup.validations.append(
                    ValidationResult(
                        status=Status.OK,
                        message=(
                            f"{pn.phone_number}: voice webhook " f"correctly configured"
                        ),
                        details={"voice_url": pn.voice_url},
                    )
                )
        else:
            setup.validations.append(
                ValidationResult(
                    status=Status.INFO,
                    message=f"{pn.phone_number}: no voice capability",
                    details={"phone_number": pn.phone_number},
                )
            )

        # SMS webhook check
        if pn.capabilities["sms"]:
            if not pn.sms_url:
                setup.validations.append(
                    ValidationResult(
                        status=Status.WARN,
                        message=(
                            f"{pn.phone_number}: SMS capability "
                            f"but no SMS webhook configured"
                        ),
                        details={"phone_number": pn.phone_number, "sid": pn.sid},
                    )
                )
            elif expected_msg and pn.sms_url != expected_msg:
                setup.validations.append(
                    ValidationResult(
                        status=Status.WARN,
                        message=f"{pn.phone_number}: SMS webhook points elsewhere",
                        details={
                            "phone_number": pn.phone_number,
                            "current": pn.sms_url,
                            "expected": expected_msg,
                        },
                    )
                )
            else:
                setup.validations.append(
                    ValidationResult(
                        status=Status.OK,
                        message=f"{pn.phone_number}: SMS webhook correctly configured",
                        details={"sms_url": pn.sms_url},
                    )
                )
        else:
            setup.validations.append(
                ValidationResult(
                    status=Status.INFO,
                    message=f"{pn.phone_number}: no SMS capability",
                    details={"phone_number": pn.phone_number},
                )
            )

    # Number mapping coverage
    mapping_file = os.getenv("NUMBERS_CONFIG_FILE", "number_mappings.json")
    mapping_path = os.path.join(os.path.dirname(__file__), mapping_file)
    if os.path.exists(mapping_path):
        with open(mapping_path) as f:
            mappings = json.load(f)
        mapped_numbers = set(mappings.keys())
        twilio_numbers = {pn.phone_number for pn in setup.phone_numbers}
        unmapped = twilio_numbers - mapped_numbers
        if unmapped:
            setup.validations.append(
                ValidationResult(
                    status=Status.WARN,
                    message=f"Twilio numbers not in {mapping_file}: {sorted(unmapped)}",
                    details={"unmapped": sorted(unmapped)},
                )
            )
        else:
            setup.validations.append(
                ValidationResult(
                    status=Status.OK,
                    message=f"All Twilio numbers have mappings in {mapping_file}",
                    details={"mapped": sorted(mapped_numbers)},
                )
            )
        extra_mapped = mapped_numbers - twilio_numbers
        if extra_mapped:
            setup.validations.append(
                ValidationResult(
                    status=Status.WARN,
                    message=(
                        f"Numbers in {mapping_file} not on "
                        f"Twilio: {sorted(extra_mapped)}"
                    ),
                    details={"extra": sorted(extra_mapped)},
                )
            )
    else:
        # Check Firestore mapping
        collection_id = os.getenv("NUMBERS_COLLECTION_ID")
        if collection_id:
            setup.validations.append(
                ValidationResult(
                    status=Status.INFO,
                    message=(
                        f"Using Firestore collection '{collection_id}' "
                        f"for mappings (cannot verify remotely)"
                    ),
                    details={"collection_id": collection_id},
                )
            )
        else:
            setup.validations.append(
                ValidationResult(
                    status=Status.FAIL,
                    message=(
                        "No number mapping configured — "
                        "set NUMBERS_CONFIG_FILE or NUMBERS_COLLECTION_ID"
                    ),
                )
            )


def validate_messaging(setup: TwilioSetup) -> None:
    if not setup.messaging_services:
        setup.validations.append(
            ValidationResult(
                status=Status.INFO,
                message="No messaging services configured",
            )
        )
    else:
        for ms in setup.messaging_services:
            if not ms.inbound_request_url:
                setup.validations.append(
                    ValidationResult(
                        status=Status.WARN,
                        message=(
                            f"Messaging service '{ms.friendly_name}' "
                            f"({ms.sid}) has no inbound URL"
                        ),
                        details={"sid": ms.sid},
                    )
                )
            else:
                setup.validations.append(
                    ValidationResult(
                        status=Status.OK,
                        message=(
                            f"Messaging service '{ms.friendly_name}' "
                            f"({ms.sid}) inbound URL: "
                            f"{ms.inbound_request_url}"
                        ),
                        details={"sid": ms.sid, "url": ms.inbound_request_url},
                    )
                )

    if not setup.conversations_services:
        setup.validations.append(
            ValidationResult(
                status=Status.INFO,
                message="No conversations services configured (RCS requires one)",
            )
        )
    else:
        setup.validations.append(
            ValidationResult(
                status=Status.OK,
                message=(
                    f"{len(setup.conversations_services)} "
                    f"conversations service(s) found"
                ),
                details={
                    "services": [
                        {"sid": cs.sid, "name": cs.friendly_name}
                        for cs in setup.conversations_services
                    ]
                },
            )
        )


def run_validations(setup: TwilioSetup) -> None:
    validate_phone_numbers(setup)
    validate_messaging(setup)


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

_STATUS_ICONS = {
    Status.OK: "✅",
    Status.WARN: "⚠️ ",
    Status.FAIL: "❌",
    Status.INFO: "ℹ️ ",
}


def _cap_str(caps: dict[str, bool]) -> str:
    parts = []
    for cap, enabled in caps.items():
        parts.append(f"{cap.upper()}" if enabled else f"  {cap}  ")
    return " | ".join(parts)


def print_account(setup: TwilioSetup) -> None:
    if not setup.account:
        return
    a = setup.account
    print("\n" + "=" * 60)
    print("  TWILIO ACCOUNT")
    print("=" * 60)
    print(f"  SID    : {a.sid}")
    print(f"  Name   : {a.name}")
    print(f"  Status : {a.status}")
    print(f"  Type   : {a.type}")


def print_phone_numbers(setup: TwilioSetup) -> None:
    if not setup.phone_numbers:
        print("\n  (no phone numbers found)")
        return
    print(f"\n{'='*60}")
    print(f"  PHONE NUMBERS ({len(setup.phone_numbers)})")
    print(f"{'='*60}")
    for pn in setup.phone_numbers:
        print(f"\n  📞 {pn.phone_number}  ({pn.friendly_name})")
        print(f"     SID       : {pn.sid}")
        print(f"     Capabilities: {_cap_str(pn.capabilities)}")
        print(f"     Origin    : {pn.origin}")
        print(f"     Status    : {pn.status}")
        print(f"     Created   : {pn.date_created}")
        print(f"     Updated   : {pn.date_updated}")
        print("\n  --- Webhooks ---")
        print(f"     Voice URL : {pn.voice_url or '(not set)'}")
        print(f"     Voice Method: {pn.voice_method or '(not set)'}")
        print(f"     Voice Fallback: {pn.voice_fallback_url or '(not set)'}")
        print(f"     SMS URL   : {pn.sms_url or '(not set)'}")
        print(f"     SMS Method: {pn.sms_method or '(not set)'}")
        print(f"     SMS Fallback: {pn.sms_fallback_url or '(not set)'}")
        print(f"     Status CB : {pn.status_callback or '(not set)'}")
        if pn.bundle_sid:
            print(f"     Bundle SID: {pn.bundle_sid}")


def print_messaging(setup: TwilioSetup) -> None:
    print(f"\n{'='*60}")
    print(f"  MESSAGING SERVICES ({len(setup.messaging_services)})")
    print(f"{'='*60}")
    if not setup.messaging_services:
        print("  (none)")
    for ms in setup.messaging_services:
        print(f"\n  📨 {ms.friendly_name} ({ms.sid})")
        print(f"     Inbound URL   : {ms.inbound_request_url or '(not set)'}")
        print(f"     Inbound Method: {ms.inbound_method or '(not set)'}")
        print(f"     Phone Numbers : {len(ms.phone_number_sids)}")
        print(f"     Created       : {ms.date_created}")

    print(f"\n{'='*60}")
    print(f"  CONVERSATIONS SERVICES ({len(setup.conversations_services)})")
    print(f"{'='*60}")
    if not setup.conversations_services:
        print("  (none — RCS requires a conversations service)")
    for cs in setup.conversations_services:
        print(f"\n  💬 {cs.friendly_name} ({cs.sid})")
        print(f"     Created: {cs.date_created}")


def print_validations(setup: TwilioSetup) -> None:
    print(f"\n{'='*60}")
    print(f"  VALIDATION RESULTS ({len(setup.validations)})")
    print(f"{'='*60}")
    for v in setup.validations:
        icon = _STATUS_ICONS.get(v.status, "  ")
        print(f"  {icon} [{v.status.value}] {v.message}")
        for key, val in v.details.items():
            print(f"       └─ {key}: {val}")


def print_adapter_config(setup: TwilioSetup) -> None:
    """Show what this adapter expects based on current .env / settings."""
    load_dotenv()
    print("\n" + "=" * 60)
    print("  ADAPTER CONFIGURATION")
    print("=" * 60)
    hostname = os.getenv("PUBLIC_SERVER_HOSTNAME", "(not set)")
    mapping_file = os.getenv("NUMBERS_CONFIG_FILE", "")
    collection_id = os.getenv("NUMBERS_COLLECTION_ID", "")
    auth_secret = os.getenv("AUTH_TOKEN_SECRET_PATH", "")
    print(f"  PUBLIC_SERVER_HOSTNAME : {hostname}")
    if hostname and not hostname.startswith("http"):
        print(
            "  Expected Voice URL     : " f"https://{hostname}{ADAPTER_VOICE_ENDPOINT}"
        )
        print(
            "  Expected Message URL   : "
            f"https://{hostname}{ADAPTER_MESSAGE_ENDPOINT}"
        )
        print("  Expected Media Stream  : " f"wss://{hostname}{ADAPTER_MEDIA_STREAM}")
    print(f"  NUMBERS_CONFIG_FILE    : {mapping_file or '(not set)'}")
    print(f"  NUMBERS_COLLECTION_ID  : {collection_id or '(not set)'}")
    print(f"  AUTH_TOKEN_SECRET_PATH : {auth_secret or '(not set — using ADC)'}")
    print(
        "  GOOGLE_APPLICATION_CREDENTIALS: "
        f"{os.getenv('GOOGLE_APPLICATION_CREDENTIALS', '(not set)')}"
    )


# ---------------------------------------------------------------------------
# Full inspection
# ---------------------------------------------------------------------------


def inspect() -> TwilioSetup:
    """Run a full inspection and return structured results."""
    client = _get_client()
    setup = TwilioSetup()

    # Fetch
    setup.account = fetch_account(client)
    setup.phone_numbers = fetch_phone_numbers(client)
    setup.messaging_services = fetch_messaging_services(client)
    setup.conversations_services = fetch_conversations_services(client)

    # Validate
    run_validations(setup)

    return setup


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Twilio Configuration Helper — verify, validate, automate, test"
    )
    parser.add_argument(
        "--json", action="store_true", help="Output as JSON (machine-readable)"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help=("Validation-only mode: " "exit 0 if all OK, 1 if any FAIL/WARN"),
    )
    parser.add_argument(
        "--numbers",
        action="store_true",
        help="Show phone numbers only",
    )
    parser.add_argument(
        "--webhooks",
        action="store_true",
        help="Show webhook audit only",
    )
    args = parser.parse_args()

    setup = inspect()

    if args.json:
        output = {
            "account": asdict(setup.account) if setup.account else None,
            "phone_numbers": [asdict(pn) for pn in setup.phone_numbers],
            "messaging_services": [asdict(ms) for ms in setup.messaging_services],
            "conversations_services": [
                asdict(cs) for cs in setup.conversations_services
            ],
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
    print_adapter_config(setup)
    print_account(setup)

    if args.numbers:
        print_phone_numbers(setup)
        return

    if args.webhooks:
        print_phone_numbers(setup)
        print_messaging(setup)
        print_validations(setup)
        return

    # Default: full report
    print_phone_numbers(setup)
    print_messaging(setup)
    print_validations(setup)

    # Summary
    ok = sum(1 for v in setup.validations if v.status == Status.OK)
    warn = sum(1 for v in setup.validations if v.status == Status.WARN)
    fail = sum(1 for v in setup.validations if v.status == Status.FAIL)
    info = sum(1 for v in setup.validations if v.status == Status.INFO)
    print(f"\n{'='*60}")
    print(f"  SUMMARY: {ok} OK | {warn} WARN | {fail} FAIL | {info} INFO")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
