"""Pruebas unitarias para las sugerencias opcionales del LLM."""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))


def load_module():
    path = SRC_DIR / "03_llm_suggestions.py"
    spec = importlib.util.spec_from_file_location("llm_suggestions_test", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"No se pudo cargar {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


LLM = load_module()


def suggestion_payload(*terms: str):
    return {
        "suggestions": [{"term": term} for term in terms],
        "groups": [],
        "domain_notes": [],
    }


def openai_result(model: str = "modelo"):
    return LLM.OpenAIResult(
        payload=suggestion_payload("bateria"),
        response_id="resp_1",
        model=model,
        usage={"input_tokens": 10, "output_tokens": 5},
        status="completed",
    )


class LlmSuggestionPureTests(unittest.TestCase):
    def test_clean_candidate_limits_context(self):
        cleaned = LLM.clean_candidate({
            "term": "Cámara frontal",
            "examples": ["x" * 300, "dos", "tres", "cuatro"],
        })
        self.assertEqual(cleaned["aspect_key_sugerido"], "camara_frontal")
        self.assertEqual(len(cleaned["examples"]), 3)
        self.assertEqual(len(cleaned["examples"][0]), 220)

    def test_response_validation_requires_exact_batch_coverage(self):
        valid = LLM.validate_suggestion_payload(
            suggestion_payload("bateria", "camara"),
            {"bateria", "camara"},
        )
        self.assertEqual(len(valid["suggestions"]), 2)
        with self.assertRaisesRegex(RuntimeError, "Faltantes"):
            LLM.validate_suggestion_payload(
                suggestion_payload("bateria"),
                {"bateria", "camara"},
            )

    def test_incomplete_and_refused_responses_are_explicit(self):
        with self.assertRaisesRegex(RuntimeError, "incompleta"):
            LLM.extract_response_text({
                "status": "incomplete",
                "incomplete_details": {"reason": "max_output_tokens"},
            })
        with self.assertRaisesRegex(RuntimeError, "rechazo"):
            LLM.extract_response_text({
                "output": [{"content": [{"type": "refusal", "refusal": "rechazo"}]}]
            })

    def test_run_signature_detects_incompatible_resume(self):
        report = {"dataset": {"dataset_key": "d"}, "candidates": []}
        context = {"curation_rules": {}, "profile": {}}
        signature = LLM.build_run_signature(
            report, "cafe", "m1", None, [], 3, 10, context
        )
        changed = LLM.build_run_signature(
            report, "cafe", "m2", None, [], 3, 10, context
        )
        LLM.validate_resume({"run_signature": signature}, signature)
        with self.assertRaisesRegex(RuntimeError, "otra ejecución"):
            LLM.validate_resume({"run_signature": signature}, changed)

    def test_numeric_arguments_are_validated(self):
        invalid = (
            ["--max-candidates", "0"],
            ["--batch-size", "0"],
            ["--min-review-mentions", "0"],
            ["--timeout", "0"],
            ["--retries", "-1"],
        )
        for arguments in invalid:
            with (
                self.subTest(arguments=arguments),
                mock.patch("sys.stderr", new=io.StringIO()),
                self.assertRaises(SystemExit),
            ):
                LLM.parse_args(list(arguments))


class LlmSuggestionIoTests(unittest.TestCase):
    def test_save_json_is_atomic_and_leaves_no_temporary(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "out.json"
            LLM.save_json(path, {"ok": True})
            self.assertEqual(LLM.load_json(path), {"ok": True})
            self.assertFalse(list(Path(temporary).glob("*.tmp")))

    def test_invalid_optional_profile_is_not_hidden(self):
        with tempfile.TemporaryDirectory() as temporary:
            domain_dir = Path(temporary)
            (domain_dir / "cafe.json").write_text("{invalido", encoding="utf-8")
            with mock.patch.object(LLM, "DOMAIN_DIR", domain_dir):
                with self.assertRaisesRegex(RuntimeError, "JSON válido"):
                    LLM.domain_profile_context("cafe")


class LlmSuggestionApiTests(unittest.TestCase):
    def test_call_openai_returns_payload_and_audit_metadata(self):
        api_response = {
            "id": "resp_123",
            "model": "gpt-test-snapshot",
            "status": "completed",
            "usage": {"input_tokens": 12, "output_tokens": 4},
            "output_text": json.dumps(suggestion_payload("bateria")),
        }
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(api_response).encode()
        with (
            mock.patch.object(LLM.urllib.request, "urlopen", return_value=response),
            mock.patch.object(LLM, "build_prompt", return_value="prompt") as build_prompt,
        ):
            result = LLM.call_openai(
                "key",
                "gpt-test",
                {},
                [{"term": "bateria"}],
                30,
                "cafe",
                [{"aspect_key": "sabor"}],
            )

        self.assertEqual(result.response_id, "resp_123")
        self.assertEqual(result.model, "gpt-test-snapshot")
        self.assertEqual(result.usage["input_tokens"], 12)
        build_prompt.assert_called_once_with(
            {},
            [{"term": "bateria"}],
            "cafe",
            [{"aspect_key": "sabor"}],
            None,
        )

    def test_transient_http_errors_are_retried(self):
        transient = LLM.OpenAIHTTPError(
            429,
            "rate limit",
            retry_after="0",
            request_id="req_1",
        )
        with (
            mock.patch.object(
                LLM,
                "call_openai",
                side_effect=[transient, openai_result()],
            ) as call,
            mock.patch.object(LLM.time, "sleep") as sleep,
        ):
            result = LLM.call_openai_with_retries(
                "key", "primary", {}, [{"term": "bateria"}], 30, 2, "cafe"
            )

        self.assertEqual(call.call_count, 2)
        sleep.assert_called_once_with(0.0)
        self.assertEqual(result.response_id, "resp_1")

    def test_non_transient_http_error_is_not_retried(self):
        error = LLM.OpenAIHTTPError(400, "bad request")
        with mock.patch.object(LLM, "call_openai", side_effect=error) as call:
            with self.assertRaises(LLM.OpenAIHTTPError):
                LLM.call_openai_with_retries(
                    "key", "primary", {}, [{"term": "bateria"}], 30, 3, "cafe"
                )
        call.assert_called_once()

    def test_fallback_model_is_the_one_recorded(self):
        forbidden = LLM.OpenAIHTTPError(403, "forbidden")
        fallback_result = openai_result("fallback-snapshot")
        with mock.patch.object(
            LLM,
            "call_openai",
            side_effect=[forbidden, fallback_result],
        ) as call:
            result = LLM.call_openai_with_retries(
                "key",
                "primary",
                {},
                [{"term": "bateria"}],
                30,
                0,
                "cafe",
                fallback_model="fallback",
            )

        self.assertEqual(call.call_args_list[1].args[1], "fallback")
        self.assertEqual(result.model, "fallback-snapshot")


if __name__ == "__main__":
    unittest.main()
