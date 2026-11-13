"""Guardrails and governance: prompt-injection, PII, secret and policy checks."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

from src.core.events import utcnow


INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions",
    r"disregard\s+(the\s+)?(system|developer)\s+(prompt|message)",
    r"reveal\s+(your\s+)?(system\s+prompt|instructions|api\s*key)",
    r"you\s+are\s+now\s+(dan|jailbroken|unrestricted)",
    r"act\s+as\s+(an?\s+)?unfiltered",
    r"<\s*\|?\s*im_start\s*\|?\s*>",
    r"###\s*OVERRIDE",
]

SECRET_PATTERNS = [
    (r"sk-[A-Za-z0-9]{20,}", "openai_api_key"),
    (r"sk-ant-[A-Za-z0-9\-_]{20,}", "anthropic_api_key"),
    (r"ghp_[A-Za-z0-9]{30,}", "github_token"),
    (r"AKIA[0-9A-Z]{16}", "aws_access_key"),
    (r"-----BEGIN (RSA|OPENSSH|EC) PRIVATE KEY-----", "private_key"),
]

PII_PATTERNS = [
    (r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", "email"),
    (r"\b(?:\+?\d{1,3}[\s-]?)?(?:\(?\d{3}\)?[\s-]?)\d{3}[\s-]?\d{4}\b", "phone"),
    (r"\b\d{3}-\d{2}-\d{4}\b", "ssn"),
    (r"\b(?:\d[ -]*?){13,16}\b", "credit_card"),
]

DISALLOWED = [
    (r"\b(how\s+to\s+(make|build|synthesize)\s+(a\s+)?(bomb|nerve\s+agent|bioweapon))", "dangerous_instructions"),
    (r"\b(child\s+sexual|csam|minor\s+sexual)", "sexual_minors"),
    (r"\b(kill\s+yourself|suicide\s+instructions)", "self_harm"),
]


@dataclass
class GuardrailResult:
    allowed: bool = True
    score: float = 1.0
    issues: list[dict] = field(default_factory=list)
    redacted_text: str = ""
    checked_at: str = field(default_factory=utcnow)

    def to_dict(self) -> dict:
        return {
            "allowed": self.allowed,
            "score": round(self.score, 3),
            "issues": self.issues,
            "redacted_text": self.redacted_text,
            "checked_at": self.checked_at,
        }


class GuardrailEngine:
    """Deterministic safety layer applied to inputs, outputs and tool calls.

    Creative screenwriting violence is *flagged* rather than blocked; the
    guardrail is designed to stop prompt injection, secret leakage and
    genuinely disallowed instructions.
    """

    def __init__(self, strict: bool = True, max_chars: int = 2_000_000):
        self.strict = strict
        self.max_chars = max_chars

    def check_input(self, text: str, kind: str = "text") -> GuardrailResult:
        return self._check(text, kind=kind, output=False)

    def check_output(self, text: str, kind: str = "output") -> GuardrailResult:
        return self._check(text, kind=kind, output=True)

    def check_script(self, text: str) -> GuardrailResult:
        result = self.check_input(text, kind="screenplay")
        # Screenplay violence is allowed for a certified production pipeline.
        result.allowed = True
        # Never echo the whole screenplay back through API payloads or run
        # records — a short excerpt is enough for the dashboard/audit trail.
        result.redacted_text = text[:280] + ("…" if len(text) > 280 else "")
        return result

    def _check(self, text: str, kind: str, output: bool) -> GuardrailResult:
        text = text or ""
        issues: list[dict] = []
        redacted = text
        score = 1.0

        if len(text) > self.max_chars:
            issues.append({
                "type": "size_limit",
                "severity": "high",
                "detail": f"payload {len(text)} chars exceeds {self.max_chars}",
            })
            score -= 0.5

        lower = text.lower()
        for pattern in INJECTION_PATTERNS:
            if re.search(pattern, lower, re.IGNORECASE):
                issues.append({
                    "type": "prompt_injection",
                    "severity": "high",
                    "detail": f"matched pattern: {pattern}",
                })
                score -= 0.4

        for pattern, label in SECRET_PATTERNS:
            if re.search(pattern, text):
                issues.append({"type": "secret_leak", "severity": "critical", "detail": label})
                redacted = re.sub(pattern, f"[REDACTED:{label}]", redacted)
                score -= 0.6

        for pattern, label in PII_PATTERNS:
            matches = re.findall(pattern, text)
            if matches:
                issues.append({
                    "type": "pii",
                    "severity": "medium",
                    "detail": f"{len(matches)} possible {label} value(s)",
                })
                redacted = re.sub(pattern, f"[REDACTED:{label}]", redacted)
                score -= 0.1 * min(3, len(matches))

        if output:
            for pattern, label in DISALLOWED:
                if re.search(pattern, lower, re.IGNORECASE):
                    issues.append({
                        "type": "policy_violation",
                        "severity": "critical",
                        "detail": label,
                    })
                    score -= 0.8

        critical = any(i["severity"] == "critical" for i in issues)
        high = sum(1 for i in issues if i["severity"] == "high")
        allowed = not critical
        if self.strict and high >= 2:
            allowed = False
        if kind == "screenplay":
            allowed = True

        return GuardrailResult(
            allowed=allowed,
            score=max(0.0, min(1.0, round(score, 3))),
            issues=issues,
            redacted_text=redacted,
        )

    def check_tool_call(self, tool: str, arguments: dict[str, Any]) -> GuardrailResult:
        payload = f"{tool} {arguments}"
        return self.check_input(payload, kind="tool_call")


class AuditLog:
    """In-memory governance audit trail (also persisted with each run)."""

    def __init__(self):
        self._entries: list[dict] = []

    def record(self, action: str, actor: str, resource: str, detail: str = "", outcome: str = "ok") -> dict:
        entry = {
            "id": f"audit_{len(self._entries) + 1:05d}",
            "timestamp": utcnow(),
            "action": action,
            "actor": actor,
            "resource": resource,
            "detail": detail,
            "outcome": outcome,
        }
        self._entries.append(entry)
        return entry

    def list(self, limit: int = 100) -> list[dict]:
        return list(reversed(self._entries))[:limit]


class ApprovalGate:
    """Human-in-the-loop approvals used by the LangGraph-style interrupt."""

    def __init__(self):
        self._requests: dict[str, dict] = {}

    def request(self, run_id: str, stage: str, summary: str, payload: Optional[dict] = None) -> dict:
        request = {
            "id": f"approval_{run_id}_{stage}",
            "run_id": run_id,
            "stage": stage,
            "summary": summary,
            "payload": payload or {},
            "status": "pending",
            "requested_at": utcnow(),
            "decided_at": None,
            "decided_by": None,
            "comment": "",
        }
        self._requests[request["id"]] = request
        return request

    def decide(self, approval_id: str, approved: bool, by: str = "operator", comment: str = "") -> dict:
        request = self._requests.get(approval_id)
        if not request:
            raise KeyError(f"approval not found: {approval_id}")
        request.update({
            "status": "approved" if approved else "rejected",
            "decided_at": utcnow(),
            "decided_by": by,
            "comment": comment,
        })
        return request

    def get(self, approval_id: str) -> Optional[dict]:
        return self._requests.get(approval_id)

    def list(self, run_id: Optional[str] = None) -> list[dict]:
        values = list(self._requests.values())
        if run_id:
            values = [v for v in values if v["run_id"] == run_id]
        return sorted(values, key=lambda v: v["requested_at"], reverse=True)
