"""
Tests for Unicode / UTF-8 encoding safety.

Covers:
- _serialize_json  (plan_judge_service)
- _safe_log        (plan_judge_service)
- GLMService._safe_json_loads  (glm_service)
- GLMService._ascii_safe       (glm_service)
"""
from __future__ import annotations

import json
import logging

import pytest

from backend.app.services.quality.plan_judge_service import _safe_log, _serialize_json
from backend.app.services.core.glm_service import GLMService


# ---------------------------------------------------------------------------
# _serialize_json
# ---------------------------------------------------------------------------

def test_serialize_with_emdash():
    data = {"message": "Score \u2014 87/100", "status": "ok"}
    result = _serialize_json(data)
    assert "\u2014" in result, "em-dash must be preserved (ensure_ascii=False)"
    assert json.loads(result) == data


def test_serialize_roundtrip_ascii():
    data = {"key": "plain ascii value", "n": 42}
    assert json.loads(_serialize_json(data)) == data


@pytest.mark.parametrize("char", ["\u2014", "\u2013", "\xe9", "\u20ac", "\U0001f510", "\u4e2d\u6587"])
def test_various_unicode_chars(char):
    data = {"char": char}
    result = _serialize_json(data)
    assert json.loads(result)["char"] == char


# ---------------------------------------------------------------------------
# _safe_log
# ---------------------------------------------------------------------------

def test_safe_log_with_unicode(caplog):
    with caplog.at_level(logging.INFO):
        _safe_log("Test avec em-dash \u2014 et accents \xe9\xe0\xf9")
    # No exception means the log call succeeded.


def test_safe_log_emoji(caplog):
    with caplog.at_level(logging.INFO):
        _safe_log("Emoji \U0001f510 et symboles \u20ac\xa3\xa5")


def test_safe_log_levels(caplog):
    for level in ("debug", "info", "warning", "error"):
        with caplog.at_level(logging.DEBUG):
            _safe_log(f"level={level} char=\u2014", level=level)


# ---------------------------------------------------------------------------
# GLMService._safe_json_loads
# ---------------------------------------------------------------------------

def test_safe_json_loads_plain():
    data = {"score": 75, "feedback": "Good work"}
    result = GLMService._safe_json_loads(json.dumps(data))
    assert result == data


def test_safe_json_loads_with_unicode():
    data = {"feedback": "Score \u2014 87/100, bien jou\xe9"}
    raw = json.dumps(data, ensure_ascii=False)
    result = GLMService._safe_json_loads(raw)
    assert result == data


def test_safe_json_loads_strips_markdown_fences():
    inner = '{"a": 1}'
    raw = f"```json\n{inner}\n```"
    assert GLMService._safe_json_loads(raw) == {"a": 1}


def test_safe_json_loads_invalid_raises_value_error():
    with pytest.raises(ValueError, match="GLM did not return valid JSON"):
        GLMService._safe_json_loads("this is not json at all \u2014")


def test_safe_json_loads_error_message_is_ascii():
    """The ValueError raised for bad JSON must not itself contain non-ASCII."""
    try:
        GLMService._safe_json_loads("bad output with em-dash \u2014 here")
    except ValueError as exc:
        msg = str(exc)
        msg.encode("ascii")  # raises if non-ASCII present


# ---------------------------------------------------------------------------
# GLMService._ascii_safe
# ---------------------------------------------------------------------------

def test_ascii_safe_emdash():
    assert GLMService._ascii_safe("hello \u2014 world") == "hello -- world"


def test_ascii_safe_endash():
    assert GLMService._ascii_safe("10\u20135") == "10-5"


def test_ascii_safe_curly_quotes():
    text = "\u201cquoted\u201d and \u2018single\u2019"
    result = GLMService._ascii_safe(text)
    assert result == '"quoted" and \'single\''


def test_ascii_safe_already_ascii():
    assert GLMService._ascii_safe("plain text 123") == "plain text 123"


def test_ascii_safe_unknown_non_ascii_replaced():
    # Characters not in _REPLACEMENTS dict are replaced with '?'
    result = GLMService._ascii_safe("caf\xe9")  # é
    assert result.encode("ascii")  # must be encodable
