"""
Utilities for interacting with Twilio.
"""

import logging
from typing import Mapping

from twilio.request_validator import RequestValidator

logger = logging.getLogger(__name__)


def validate_twilio_signature(
    url: str, params: Mapping, signature: str | None, validator: RequestValidator
) -> bool:
    """Validates a Twilio request signature."""
    # force url to appear as https or wss because Cloud Run sees http / ws
    url = url.replace("http:", "https:").replace("ws:", "wss:")
    is_valid = validator.validate(url, params, signature)
    if not is_valid:
        logger.warning(f"Twilio signature validation failed for url: {url}")
    logger.info(f"Twilio signature validation result: {is_valid}")
    return is_valid
