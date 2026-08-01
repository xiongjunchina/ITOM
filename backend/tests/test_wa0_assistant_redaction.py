"""WA0 redaction contracts for model, message persistence, and ordinary logs."""

import json

from app.assistant.redaction import redact_for_log, redact_for_message, redact_for_model


def test_redaction_recursively_removes_case_insensitive_secrets_without_mutating_input():
    """Removing recursive key handling would leak nested credentials to a model or persisted message."""
    raw = {
        "Password": "p@ss-raw",
        "items": [{"TOKEN": "token-raw"}, {"nested": {"api_key": "key-raw"}}],
        "Cookie": "session=raw-cookie",
    }

    model = redact_for_model(raw)
    message = redact_for_message(raw)
    log = redact_for_log(raw)

    assert raw["Password"] == "p@ss-raw"
    for output in (model, message, log):
        rendered = json.dumps(output, ensure_ascii=False)
        assert "p@ss-raw" not in rendered
        assert "token-raw" not in rendered
        assert "key-raw" not in rendered
        assert "raw-cookie" not in rendered
        assert output["Password"] == "[REDACTED]"


def test_redaction_scrubs_bearer_jwt_and_explicit_dynamic_sensitive_fields():
    """Removing string-pattern or dynamic-field protection would retain secrets under harmless keys."""
    bearer = "Bearer bearer-raw-value"
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1c2VyIn0.signature-raw"
    raw = {
        "note": f"authorization is {bearer}; token is {jwt}",
        "fields": [
            {"code": "vpn_password", "sensitive": True, "value": "dynamic-password-raw"},
            {"code": "display_name", "sensitive": False, "value": "safe value"},
        ],
    }

    output = redact_for_model(raw)
    rendered = json.dumps(output, ensure_ascii=False)

    assert bearer not in rendered
    assert jwt not in rendered
    assert "dynamic-password-raw" not in rendered
    assert output["fields"][0]["value"] == "[REDACTED]"
    assert output["fields"][1]["value"] == "safe value"


def test_redaction_supports_declared_sensitive_field_names_for_all_output_boundaries():
    """Ignoring server-declared form sensitivity would leak a field that has no sensitive-looking name."""
    raw = {"form": {"private_answer": "custom-secret-raw", "title": "printer"}}

    outputs = [
        redact_for_model(raw, sensitive_fields={"private_answer"}),
        redact_for_message(raw, sensitive_fields={"PRIVATE_ANSWER"}),
        redact_for_log(raw, sensitive_fields={"private_answer"}),
    ]

    for output in outputs:
        rendered = json.dumps(output, ensure_ascii=False)
        assert "custom-secret-raw" not in rendered
        assert output["form"]["private_answer"] == "[REDACTED]"
        assert output["form"]["title"] == "printer"
