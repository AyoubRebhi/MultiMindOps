import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from backend.app.core.config import Settings
from backend.app.services.core.groq_key_manager import (
    GroqKeyManager,
    extract_retry_after_seconds,
    is_groq_auth_error,
    is_groq_rate_limit_error,
)


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


class GroqKeyManagerTests(unittest.TestCase):
    def test_settings_load_multiple_groq_keys(self):
        env_path = Path("tests") / ".tmp_groq_keys.env"
        env_path.write_text(
            "GROQ_API_KEY=key-a\nGROQ_API_KEY_2=key-b\n",
            encoding="utf-8",
        )
        settings_obj = Settings(
            _env_file=None,
            GROQ_API_KEY="key-a",
            GROQ_API_KEY_2="key-b",
            GROQ_API_KEY_3="",
        )
        original_env_file = settings_obj.model_config.get("env_file")
        settings_obj.model_config["env_file"] = str(env_path)
        try:
            entries = settings_obj.get_groq_key_entries()
        finally:
            settings_obj.model_config["env_file"] = original_env_file
            if env_path.exists():
                env_path.unlink()

        self.assertEqual(
            entries,
            [
                {"name": "GROQ_API_KEY", "value": "key-a"},
                {"name": "GROQ_API_KEY_2", "value": "key-b"},
            ],
        )

    def test_get_active_key_returns_first_available_key(self):
        manager = GroqKeyManager(
            [
                {"name": "GROQ_API_KEY", "value": "key-a"},
                {"name": "GROQ_API_KEY_2", "value": "key-b"},
            ]
        )

        active = manager.get_active_key()

        self.assertEqual(active.name, "GROQ_API_KEY")
        self.assertEqual(active.label, "key 1")

    def test_rate_limited_key_switches_to_next_available_key(self):
        manager = GroqKeyManager(
            [
                {"name": "GROQ_API_KEY", "value": "key-a"},
                {"name": "GROQ_API_KEY_2", "value": "key-b"},
            ]
        )
        now = datetime(2026, 4, 2, 12, 0, tzinfo=timezone.utc)

        manager.mark_key_rate_limited("GROQ_API_KEY", retry_after_seconds=120, now=now)
        next_key = manager.get_next_available_key(now=now + timedelta(seconds=1))

        self.assertIsNotNone(next_key)
        self.assertEqual(next_key.name, "GROQ_API_KEY_2")

    def test_rate_limited_key_is_not_reused_before_cooldown_ends(self):
        manager = GroqKeyManager(
            [
                {"name": "GROQ_API_KEY", "value": "key-a"},
                {"name": "GROQ_API_KEY_2", "value": "key-b"},
            ]
        )
        now = datetime(2026, 4, 2, 12, 0, tzinfo=timezone.utc)

        manager.mark_key_rate_limited("GROQ_API_KEY", retry_after_seconds=30, now=now)

        first_available = manager.get_next_available_key(now=now + timedelta(seconds=5))
        second_available = manager.get_next_available_key(
            exclude_names={"GROQ_API_KEY_2"},
            now=now + timedelta(seconds=31),
        )

        self.assertEqual(first_available.name, "GROQ_API_KEY_2")
        self.assertEqual(second_available.name, "GROQ_API_KEY")

    def test_all_keys_exhausted_returns_clear_message(self):
        manager = GroqKeyManager(
            [
                {"name": "GROQ_API_KEY", "value": "key-a"},
                {"name": "GROQ_API_KEY_2", "value": "key-b"},
                {"name": "GROQ_API_KEY_3", "value": "key-c"},
            ]
        )
        now = datetime(2026, 4, 2, 12, 0, tzinfo=timezone.utc)

        manager.mark_key_rate_limited("GROQ_API_KEY", retry_after_seconds=60, now=now)
        manager.mark_key_rate_limited("GROQ_API_KEY_2", retry_after_seconds=120, now=now)
        manager.mark_key_rate_limited("GROQ_API_KEY_3", retry_after_seconds=180, now=now)

        self.assertIsNone(manager.get_next_available_key(now=now + timedelta(seconds=1)))
        self.assertIn(
            "No Groq API keys are currently available",
            manager.describe_unavailable_state(now=now + timedelta(seconds=1)),
        )

    def test_extract_retry_after_seconds_from_realistic_rate_limit_message(self):
        error = FakeGroqError(
            "Rate limit reached. Please try again in 2h19m48.575999999s.",
            status_code=429,
        )

        retry_after = extract_retry_after_seconds(error)

        self.assertEqual(retry_after, 8389)
        self.assertTrue(is_groq_rate_limit_error(error))

    def test_detects_auth_error_without_treating_it_as_rate_limit(self):
        error = FakeGroqError("Invalid API key provided", status_code=401)

        self.assertTrue(is_groq_auth_error(error))
        self.assertFalse(is_groq_rate_limit_error(error))


if __name__ == "__main__":
    unittest.main()
