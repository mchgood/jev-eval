"""Official SDK adapter; dry-run never fabricates inference results."""

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
