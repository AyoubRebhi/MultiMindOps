import unittest
from types import SimpleNamespace

from backend.app.services.core.groq_key_manager import GroqKeyManager, NoGroqAPIKeysAvailableError
from backend.app.services.core.llm_service import LLMService


class FakeGroqError(Exception):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response = SimpleNamespace(status_code=status_code, headers=headers or {})


class FakeClient:
    def __init__(self, behavior):
        self._behavior = behavior
        self.chat = SimpleNamespace(completions=self)

    def create(self, **_: object):
        return self._behavior()


class LLMServiceTests(unittest.TestCase):
    def test_safe_json_loads_accepts_fenced_json(self):
        payload = """```json
{
  "agent": "PlannerAgent",
  "steps": ["one"]
}
```"""

        parsed = LLMService._safe_json_loads(payload)

        self.assertEqual(parsed["agent"], "PlannerAgent")
        self.assertEqual(parsed["steps"], ["one"])

    def test_safe_json_loads_repairs_multiline_artifact_strings(self):
        payload = """
{
  "agent": "InfrastructureAgent",
  "artifacts": {
    "dockerfile": "FROM python:3.11-slim
WORKDIR /app
COPY . ."
  }
}
""".strip()

        parsed = LLMService._safe_json_loads(payload)

        self.assertEqual(parsed["agent"], "InfrastructureAgent")
        self.assertIn("WORKDIR /app", parsed["artifacts"]["dockerfile"])

    def test_keeps_first_key_when_request_succeeds(self):
        manager = GroqKeyManager(
            [
                {"name": "GROQ_API_KEY", "value": "key-a"},
                {"name": "GROQ_API_KEY_2", "value": "key-b"},
            ]
        )
        calls: list[str] = []

        def client_factory(api_key: str):
            calls.append(api_key)
            return FakeClient(
                lambda: SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))]
                )
            )

        llm = LLMService(key_manager=manager, client_factory=client_factory)

        result = llm.chat("sys", "user")

        self.assertEqual(result, "ok")
        self.assertEqual(calls, ["key-a"])

    def test_switches_to_next_key_when_first_key_is_rate_limited(self):
        manager = GroqKeyManager(
            [
                {"name": "GROQ_API_KEY", "value": "key-a"},
                {"name": "GROQ_API_KEY_2", "value": "key-b"},
            ]
        )
        calls: list[str] = []

        def client_factory(api_key: str):
            calls.append(api_key)
            if api_key == "key-a":
                return FakeClient(
                    lambda: (_ for _ in ()).throw(
                        FakeGroqError(
                            "Error code: 429 - rate_limit_exceeded. "
                            "Please try again in 90s.",
                            status_code=429,
                        )
                    )
                )
            return FakeClient(
                lambda: SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content="fallback-ok"))]
                )
            )

        llm = LLMService(key_manager=manager, client_factory=client_factory)

        result = llm.chat("sys", "user")

        self.assertEqual(result, "fallback-ok")
        self.assertEqual(calls, ["key-a", "key-b"])

    def test_raises_clear_error_when_all_keys_are_rate_limited(self):
        manager = GroqKeyManager(
            [
                {"name": "GROQ_API_KEY", "value": "key-a"},
                {"name": "GROQ_API_KEY_2", "value": "key-b"},
                {"name": "GROQ_API_KEY_3", "value": "key-c"},
                {"name": "GROQ_API_KEY_4", "value": "key-d"},
                {"name": "GROQ_API_KEY_5", "value": "key-e"},
                {"name": "GROQ_API_KEY_6", "value": "key-f"},
            ]
        )

        def client_factory(api_key: str):
            return FakeClient(
                lambda: (_ for _ in ()).throw(
                    FakeGroqError(
                        f"{api_key} hit rate_limit_exceeded and tokens per day. "
                        "Please try again in 120s.",
                        status_code=429,
                    )
                )
            )

        llm = LLMService(key_manager=manager, client_factory=client_factory)

        with self.assertRaises(NoGroqAPIKeysAvailableError) as raised:
            llm.chat("sys", "user")

        self.assertIn("No Groq API keys are currently available", str(raised.exception))

    def test_auth_error_disables_first_key_and_uses_next_one(self):
        manager = GroqKeyManager(
            [
                {"name": "GROQ_API_KEY", "value": "key-a"},
                {"name": "GROQ_API_KEY_2", "value": "key-b"},
            ]
        )
        calls: list[str] = []

        def client_factory(api_key: str):
            calls.append(api_key)
            if api_key == "key-a":
                return FakeClient(
                    lambda: (_ for _ in ()).throw(
                        FakeGroqError("Invalid API key provided", status_code=401)
                    )
                )
            return FakeClient(
                lambda: SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content="auth-fallback"))]
                )
            )

        llm = LLMService(key_manager=manager, client_factory=client_factory)

        result = llm.chat("sys", "user")

        self.assertEqual(result, "auth-fallback")
        self.assertEqual(calls, ["key-a", "key-b"])


if __name__ == "__main__":
    unittest.main()
