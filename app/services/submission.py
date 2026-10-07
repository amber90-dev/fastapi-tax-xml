"""Submission gateway.

The API talks to a `SubmissionGateway` interface, so the real government channel (for example
a SOAP data-box client) can be plugged in later without touching the endpoints. The default
`SandboxGateway` never contacts any outside system: it validates the XML again and returns a
deterministic receipt, which keeps local runs and tests safe.
"""

import hashlib
from dataclasses import dataclass
from typing import Protocol

from app.services.xml_builder import validate_xml


@dataclass(frozen=True)
class Receipt:
    receipt_id: str
    accepted: bool
    message: str


class SubmissionGateway(Protocol):
    def submit(self, *, declaration_id: str, xml: str) -> Receipt: ...


class SandboxGateway:
    def submit(self, *, declaration_id: str, xml: str) -> Receipt:
        validate_xml(xml)
        digest = hashlib.sha256(f"{declaration_id}:{xml}".encode()).hexdigest()[:16]
        return Receipt(receipt_id=f"SBX-{digest}", accepted=True, message="Accepted by sandbox gateway")


def get_gateway() -> SubmissionGateway:
    return SandboxGateway()
