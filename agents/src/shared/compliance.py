"""SOC2/GDPR compliance controls — data classification, PII redaction, retention,
right-to-erasure (NFR-2).

Data classes
------------
- PUBLIC:       no restriction. Eg. open-source repo names.
- INTERNAL:     non-sensitive operational data. Eg. workflow run IDs, agent decisions.
- CONFIDENTIAL: secrets/tokens/keys — MUST NOT appear in audit logs or LLM prompts.
- PII:          identifies a natural person (email, phone, SSN, IP). GDPR subject data.

Retention (days) per class is consulted by the housekeeper. The audit chain itself
is immutable (NFR-2 hash-chain) so erasure here appends a `subject.erased`
tombstone instead of deleting prior entries — entries are redacted-on-read.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

import boto3
from boto3.dynamodb.conditions import Key

from shared.config import settings

logger = logging.getLogger(__name__)


class DataClass(str, Enum):
    PUBLIC = "PUBLIC"
    INTERNAL = "INTERNAL"
    CONFIDENTIAL = "CONFIDENTIAL"
    PII = "PII"


# SOC2: retention per data class (days). 0 = keep forever (audit immutability).
RETENTION_DAYS: dict[DataClass, int] = {
    DataClass.PUBLIC: 365,
    DataClass.INTERNAL: 180,
    DataClass.CONFIDENTIAL: 30,
    DataClass.PII: 30,  # GDPR: minimize PII retention
}


# --- detection patterns -----------------------------------------------------
# Order matters: more specific patterns first so credential matches don't get
# swallowed by generic ones.
_PATTERNS: list[tuple[str, DataClass, re.Pattern[str]]] = [
    # CONFIDENTIAL — secrets
    ("aws_access_key", DataClass.CONFIDENTIAL, re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("aws_secret_key", DataClass.CONFIDENTIAL,
     re.compile(r"(?i)aws(.{0,20})?(secret|access).{0,20}?[=:]\s*[\"']?([A-Za-z0-9/+=]{40})[\"']?")),
    ("github_token", DataClass.CONFIDENTIAL, re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,255}\b")),
    ("private_key_block", DataClass.CONFIDENTIAL,
     re.compile(r"-----BEGIN ([A-Z ]+)?PRIVATE KEY-----[\s\S]+?-----END [A-Z ]+?PRIVATE KEY-----")),
    ("jwt", DataClass.CONFIDENTIAL,
     re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
    ("bearer_token", DataClass.CONFIDENTIAL,
     re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{20,}")),
    ("password_assignment", DataClass.CONFIDENTIAL,
     re.compile(r"(?i)(password|passwd|secret|api[_-]?key)\s*[=:]\s*[\"']?[^\s\"',;]{6,}")),
    # PII
    ("email", DataClass.PII,
     re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")),
    ("ssn_us", DataClass.PII, re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("phone_intl", DataClass.PII,
     re.compile(r"(?<!\d)\+?\d{1,3}[-.\s]?\(?\d{2,4}\)?[-.\s]?\d{3,4}[-.\s]?\d{3,4}(?!\d)")),
    ("credit_card", DataClass.PII,
     re.compile(r"\b(?:\d[ -]*?){13,16}\b")),
    ("ipv4", DataClass.PII,
     re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b")),
]


@dataclass
class Finding:
    kind: str
    data_class: DataClass
    start: int
    end: int
    sample: str  # already truncated; never the full secret


@dataclass
class RedactionResult:
    redacted: str
    findings: list[Finding] = field(default_factory=list)
    highest_class: DataClass = DataClass.PUBLIC


def _rank(c: DataClass) -> int:
    return {DataClass.PUBLIC: 0, DataClass.INTERNAL: 1,
            DataClass.CONFIDENTIAL: 2, DataClass.PII: 2}[c]


def classify(text: str) -> DataClass:
    """Return the highest data class that any pattern matches in `text`."""
    if not text:
        return DataClass.PUBLIC
    highest = DataClass.INTERNAL  # anything we process is at least INTERNAL
    for _kind, cls, pat in _PATTERNS:
        if pat.search(text):
            if _rank(cls) > _rank(highest):
                highest = cls
    return highest


def redact(text: str, *, mask: str = "[REDACTED:{kind}]") -> RedactionResult:
    """Redact secrets + PII. Returns the sanitized string + findings audit trail.

    The sample stored in findings is masked (`<6chars>...`) so the result itself
    is safe to log.
    """
    if not text:
        return RedactionResult(redacted=text or "")

    findings: list[Finding] = []
    out = text
    highest = DataClass.PUBLIC

    # Apply in order; track offsets against the ORIGINAL string for findings.
    for kind, cls, pat in _PATTERNS:
        for m in pat.finditer(text):
            raw = m.group(0)
            sample = (raw[:4] + "…") if len(raw) > 6 else "…"
            findings.append(Finding(kind=kind, data_class=cls,
                                    start=m.start(), end=m.end(), sample=sample))
            if _rank(cls) > _rank(highest):
                highest = cls
        out = pat.sub(mask.format(kind=kind), out)

    if findings and _rank(DataClass.INTERNAL) > _rank(highest):
        highest = DataClass.INTERNAL
    return RedactionResult(redacted=out, findings=findings, highest_class=highest)


# --- right-to-erasure (GDPR Art. 17) ----------------------------------------

class ComplianceManager:
    """SOC2/GDPR controls bolted onto the existing DynamoDB tables."""

    def __init__(self) -> None:
        self._dynamodb = boto3.resource("dynamodb", region_name=settings.aws_region)
        self._state = self._dynamodb.Table(settings.dynamodb_state_table)
        self._audit = self._dynamodb.Table(settings.dynamodb_audit_table)

    async def erase_subject(self, subject_id: str, *, requested_by: str = "system") -> dict[str, Any]:
        """GDPR Art. 17 right-to-erasure.

        - Scans the state table for any task that mentions `subject_id` in its
          input_data, output_data, or context, and overwrites those fields with
          `{"_erased": true, "_erased_at": ts}`.
        - Appends a `subject.erased` audit entry naming the subject + requester
          (the audit chain itself is immutable; prior entries with the subject
          remain hash-chained but their PII payloads were already redacted at
          write time by `redact()`).
        """
        if not subject_id or len(subject_id) < 3:
            return {"erased": 0, "error": "subject_id too short"}

        ts = datetime.now(timezone.utc).isoformat()
        # Scan is fine for compliance ops — infrequent and rate-bound.
        scan_kwargs = {
            "FilterExpression": "contains(#io, :s) OR contains(#oo, :s) OR contains(#co, :s)",
            "ExpressionAttributeNames": {"#io": "input_data", "#oo": "output_data", "#co": "context"},
            "ExpressionAttributeValues": {":s": subject_id},
        }
        erased = 0
        try:
            resp = self._state.scan(**scan_kwargs)
            for item in resp.get("Items", []):
                self._state.update_item(
                    Key={"PK": item["PK"], "SK": item["SK"]},
                    UpdateExpression="SET input_data = :e, output_data = :e, context = :e",
                    ExpressionAttributeValues={":e": {"_erased": True, "_erased_at": ts}},
                )
                erased += 1
        except Exception as exc:  # pragma: no cover — surfaced to caller
            logger.error("erase scan failed: %s", exc)
            return {"erased": erased, "error": str(exc)}

        # Append a tombstone to the immutable audit chain. We import lazily to
        # avoid a circular import between shared.state and shared.compliance.
        try:
            from shared.state import AgentTask, TaskStatus, state_manager  # type: ignore

            tombstone = AgentTask(
                agent_type="compliance",
                task_type="subject.erased",
                context={"subject_id_hash": _hash_subject(subject_id),
                         "requested_by": requested_by,
                         "records_erased": erased,
                         "erased_at": ts},
                status=TaskStatus.COMPLETED,
            )
            await state_manager._audit_log("subject.erased", tombstone)
        except Exception as exc:
            logger.warning("erasure audit append failed: %s", exc)

        return {"subject_id_hash": _hash_subject(subject_id),
                "erased": erased, "erased_at": ts, "requested_by": requested_by}

    async def retention_sweep(self, *, dry_run: bool = True) -> dict[str, Any]:
        """SOC2: identify state-table records past their retention window.

        Defaults to dry-run because deletion is irreversible. Audit chain is
        never touched (immutability requirement).
        """
        from datetime import timedelta

        now = datetime.now(timezone.utc)
        thresholds = {cls: now - timedelta(days=days)
                      for cls, days in RETENTION_DAYS.items() if days > 0}

        scan = self._state.scan(ProjectionExpression="PK, SK, created_at, #s",
                                ExpressionAttributeNames={"#s": "status"})
        candidates: list[dict[str, Any]] = []
        for item in scan.get("Items", []):
            created = item.get("created_at")
            if not created:
                continue
            try:
                ts = datetime.fromisoformat(str(created).replace("Z", "+00:00"))
            except ValueError:
                continue
            # Default to INTERNAL bucket — caller can tag tasks with data_class later.
            if ts < thresholds[DataClass.INTERNAL]:
                candidates.append({"PK": item["PK"], "SK": item["SK"],
                                   "created_at": str(created)})

        deleted = 0
        if not dry_run:
            for c in candidates:
                self._state.delete_item(Key={"PK": c["PK"], "SK": c["SK"]})
                deleted += 1

        return {"scanned": len(scan.get("Items", [])),
                "candidates": len(candidates),
                "deleted": deleted,
                "dry_run": dry_run,
                "policy_days": {k.value: v for k, v in RETENTION_DAYS.items()}}


def _hash_subject(subject_id: str) -> str:
    import hashlib
    return hashlib.sha256(subject_id.encode("utf-8")).hexdigest()[:16]


compliance_manager = ComplianceManager()
