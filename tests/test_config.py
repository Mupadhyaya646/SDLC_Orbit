"""LLM settings: latest-generation defaults, overrides, opt-in temperature (stdlib only)."""
import os
import pathlib
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from sdlc_orbit import config  # noqa: E402

_LLM_VARS = ("ANTHROPIC_API_KEY", "LLM_API_KEY", "LLM_MODEL", "LLM_MODEL_OPUS", "LLM_MODEL_SONNET",
             "LLM_TEMPERATURE", "ANTHROPIC_BASE_URL", "LLM_BASE_URL", "LLM_EXTRA_HEADERS")


class LlmSettings(unittest.TestCase):
    def setUp(self):
        self._env = {k: v for k, v in os.environ.items() if k not in _LLM_VARS}
        patcher = mock.patch.dict(os.environ, self._env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_api_key_is_required(self):
        with self.assertRaises(RuntimeError):
            config.llm_settings()

    def test_defaults_are_latest_generation(self):
        os.environ["ANTHROPIC_API_KEY"] = "k"
        s = config.llm_settings()
        self.assertEqual((s.model_opus, s.model_sonnet), ("claude-opus-5-5", "claude-sonnet-5-5"))

    def test_temperature_not_sent_by_default(self):
        os.environ["ANTHROPIC_API_KEY"] = "k"
        self.assertIsNone(config.llm_settings().temperature)
        os.environ["LLM_TEMPERATURE"] = "0.3"
        self.assertEqual(config.llm_settings().temperature, 0.3)

    def test_overrides(self):
        os.environ.update(ANTHROPIC_API_KEY="k", LLM_MODEL="claude-fable-5-1", LLM_MODEL_SONNET="claude-haiku-5-5")
        s = config.llm_settings()
        self.assertEqual((s.model_opus, s.model_sonnet), ("claude-fable-5-1", "claude-haiku-5-5"))

    def test_gateway_headers(self):
        os.environ.update(ANTHROPIC_API_KEY="k", LLM_EXTRA_HEADERS="x-application-id=abc, x-foo=bar")
        self.assertEqual(config.llm_settings().extra_headers, {"x-application-id": "abc", "x-foo": "bar"})


if __name__ == "__main__":
    unittest.main()
