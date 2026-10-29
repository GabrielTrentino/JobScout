import base64
import io
import json
import os
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock
from urllib.parse import parse_qs, urlparse

from jobscout.gmail import Gmail, GmailError


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class GmailTest(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = TemporaryDirectory()
        self.token = Path(self.folder.name) / "token.json"
        env = mock.patch.dict(os.environ, {
            "JOBSCOUT_GMAIL_CLIENT_ID": "client",
            "JOBSCOUT_GMAIL_CLIENT_SECRET": "secret",
        })
        env.start()
        self.addCleanup(env.stop)
        self.requests = []

    def tearDown(self) -> None:
        self.folder.cleanup()

    def opener(self, request, timeout=30):
        self.requests.append(request)
        url = request.full_url
        if url.startswith("https://oauth2.googleapis.com/token"):
            return FakeResponse(json.dumps({"access_token": "tok", "refresh_token": "ref", "expires_in": 3600}).encode())
        if "/messages?" in url:
            return FakeResponse(json.dumps({"messages": [{"id": "m1"}, {"id": "m2"}]}).encode())
        raw = base64.urlsafe_b64encode(b"Subject: Oi\r\n\r\ncorpo").decode().rstrip("=")
        return FakeResponse(json.dumps({"raw": raw}).encode())

    def test_oauth_flow_uses_readonly_scope_and_pkce(self) -> None:
        gmail = Gmail(self.token, self.opener)
        url = gmail.auth_url("http://127.0.0.1:8765/api/gmail/retorno")
        query = parse_qs(urlparse(url).query)
        self.assertEqual(query["scope"], ["https://www.googleapis.com/auth/gmail.readonly"])
        self.assertEqual(query["code_challenge_method"], ["S256"])
        gmail.finish("code", query["state"][0], "http://127.0.0.1:8765/api/gmail/retorno")
        self.assertTrue(gmail.connected())
        self.assertIn(b"code_verifier=", self.requests[0].data)
        with self.assertRaises(GmailError):
            gmail.finish("code", query["state"][0], "http://127.0.0.1:8765/api/gmail/retorno")

    def test_fetch_skips_seen_messages(self) -> None:
        self.token.write_text(json.dumps({"access_token": "tok", "refresh_token": "ref", "expires_at": time.time() + 600}))
        gmail = Gmail(self.token, self.opener)
        found = gmail.fetch_new(lambda message_id: message_id == "m1")
        self.assertEqual([message_id for message_id, _ in found], ["m2"])
        self.assertEqual(found[0][1], b"Subject: Oi\r\n\r\ncorpo")
        self.assertEqual(self.requests[0].get_header("Authorization"), "Bearer tok")

    def test_expired_token_is_refreshed(self) -> None:
        self.token.write_text(json.dumps({"access_token": "old", "refresh_token": "ref", "expires_at": 0}))
        gmail = Gmail(self.token, self.opener)
        gmail.fetch_new(lambda message_id: True)
        self.assertIn(b"grant_type=refresh_token", self.requests[0].data)
        self.assertEqual(json.loads(self.token.read_text())["refresh_token"], "ref")


if __name__ == "__main__":
    unittest.main()
