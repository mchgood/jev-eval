"""Official SDK adapter; dry-run never fabricates inference results."""

import os
import re

from typesafe_sdk import Choice, Noul, RetryPolicy, Score, TypeSafeClient

from .schema import Case


def request_for(case: Case) -> dict:
    return {"state": case.state, "questions": {"decision": case.question}}


class JevBackend:
    def __init__(self, model: str, timeout: float):
        self.model = model
        self.client = TypeSafeClient(model=model, timeout=timeout, retry=RetryPolicy(max_retries=0))

    def evaluate(self, case: Case) -> dict:
        cls = {"choice": Choice, "noul": Noul, "score": Score}[case.question["type"]]
        response = self.client.system_one(
            state=case.state,
            questions={"decision": cls.model_validate(case.question)},
            model=self.model,
        )
        return response.model_dump(mode="json")

    def close(self):
        self.client.close()


def error_details(exc: Exception) -> dict:
    """Record selected service error fields, never headers or a full exception dump."""
    result = {"error_type": type(exc).__name__}
    status = getattr(exc, "status", None)
    if isinstance(status, int):
        result["http_status"] = status
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        detail = body.get("detail", body.get("error", body))
        if isinstance(detail, dict) and isinstance(detail.get("message"), str):
            message = detail["message"]
            key = os.getenv("TYPESAFE_API_KEY")
            if key:
                message = message.replace(key, "[REDACTED]")
            message = re.sub(r"apikey_[A-Za-z0-9_]+", "[REDACTED]", message)
            message = re.sub(r"(?i)bearer\s+[^\s]+", "Bearer [REDACTED]", message)
            result["error_message"] = message[:500]
    return result
