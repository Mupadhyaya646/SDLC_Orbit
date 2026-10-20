import asyncio
import json
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

try:
    import httpx
    from sdlc_orbit.config import CortexSettings
    from sdlc_orbit.cortex import CortexClient, CortexError

    HAVE = True
except ImportError:
    HAVE = False

SETTINGS = dict(base_url="https://gw.example/cortex", user="u@lilly.com", groups="g1,g2", org="orgx", bearer="tok")


@unittest.skipUnless(HAVE, "httpx not installed")
class CortexClientTest(unittest.TestCase):
    def _client(self, handler):
        return CortexClient(CortexSettings(**SETTINGS), transport=httpx.MockTransport(handler))

    def test_streaming_request_shape_and_reply(self):
        seen = {}

        def handler(request):
            seen["url"] = str(request.url)
            seen["headers"] = request.headers
            seen["body"] = request.read().decode()
            lines = (
                '{"type":"step","name":"Model","status":"running"}\n'
                '{"type":"message","message_fragment":"Hel"}\n'
                '{"type":"message","message_fragment":"lo"}\n'
            )
            return httpx.Response(200, content=lines.encode())

        acts = []

        async def on_activity(t):
            acts.append(t)

        out = asyncio.run(self._client(handler).ask("salesforce-design-agent-d", "do it", "s1:design", on_activity))
        self.assertEqual(out, "Hello")
        self.assertEqual(seen["url"], "https://gw.example/cortex/model/ask/salesforce-design-agent-d")
        self.assertEqual(seen["headers"]["x-user"], "u@lilly.com")
        self.assertEqual(seen["headers"]["x-groups"], "g1,g2")
        self.assertEqual(seen["headers"]["x-org"], '{"name": "orgx"}')
        self.assertEqual(seen["headers"]["authorization"], "Bearer tok")
        self.assertIn("multipart/form-data", seen["headers"]["content-type"])
        for needle in ('name="q"', "do it", 'name="model_session_id_param"', "s1:design", 'name="stream"'):
            self.assertIn(needle, seen["body"])
        self.assertEqual(acts, ["⚙️ Model"])

    def test_non_streaming_json_document(self):
        out = asyncio.run(self._client(lambda r: httpx.Response(200, json={"message": "plain"})).ask("a", "q", "s"))
        self.assertEqual(out, "plain")

    def test_http_error_and_empty_reply_raise(self):
        with self.assertRaises(CortexError):
            asyncio.run(self._client(lambda r: httpx.Response(403, json={"message": "token expired or invalid"})).ask("a", "q", "s"))
        with self.assertRaises(CortexError):
            asyncio.run(self._client(lambda r: httpx.Response(200, content=b"")).ask("a", "q", "s"))

    def test_azure_ad_client_credentials_token_is_fetched_once_and_sent_as_bearer(self):
        calls = {"token": 0, "ask_auth": []}

        def handler(request):
            if "login.microsoftonline.com" in str(request.url):
                calls["token"] += 1
                body = request.read().decode()
                self.assertIn("grant_type=client_credentials", body)
                self.assertIn("scope=api%3A%2F%2FCortex.lilly.com%2F.default", body)
                self.assertIn("/tenant-1/oauth2/v2.0/token", str(request.url))
                return httpx.Response(200, json={"access_token": "aad-tok", "expires_in": 3600})
            calls["ask_auth"].append(request.headers["authorization"])
            return httpx.Response(200, json={"message": "ok"})

        cfg = CortexSettings(
            base_url="https://gw.example/cortex",
            user="u@lilly.com",
            groups="",
            org="",
            bearer=None,
            tenant_id="tenant-1",
            client_id="cid",
            client_secret="sec",
        )
        client = CortexClient(cfg, transport=httpx.MockTransport(handler))
        asyncio.run(client.ask("a", "q", "s"))
        asyncio.run(client.ask("a", "q", "s"))
        self.assertEqual(calls["token"], 1)
        self.assertEqual(calls["ask_auth"], ["Bearer aad-tok", "Bearer aad-tok"])

    def test_react_final_response_envelope_is_unwrapped(self):
        envelope = '{"action": "final_response", "message": "## VERDICT: APPROVED\\nline 2"}'
        lines = "".join(json.dumps({"type": "message", "message_fragment": envelope[i : i + 7]}) + "\n" for i in range(0, len(envelope), 7))
        out = asyncio.run(self._client(lambda r: httpx.Response(200, content=lines.encode())).ask("a", "q", "s"))
        self.assertEqual(out, "## VERDICT: APPROVED\nline 2")

    def test_optional_headers_omitted_when_unset(self):
        seen = {}

        def handler(request):
            seen["headers"] = request.headers
            return httpx.Response(200, json={"message": "ok"})

        cfg = CortexSettings(base_url="https://gw.example/cortex", user="u@lilly.com", groups="", org="", bearer=None)
        asyncio.run(CortexClient(cfg, transport=httpx.MockTransport(handler)).ask("a", "q", "s"))
        self.assertNotIn("x-groups", seen["headers"])
        self.assertNotIn("x-org", seen["headers"])
        self.assertNotIn("authorization", seen["headers"])


if __name__ == "__main__":
    unittest.main()
