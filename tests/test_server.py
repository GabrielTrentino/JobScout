import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from docx import Document

from jobscout.linkedin_public import PublicPageError
from jobscout.server import App, serve_in_background

VAGA = {
    "url": "https://www.linkedin.com/jobs/view/4012345678/",
    "title": "Backend Python",
    "company": "Acme",
}



def offline(url):
    raise PublicPageError("sem rede nos testes")


class ServerTest(unittest.TestCase):
    def setUp(self) -> None:
        env = mock.patch.dict(os.environ, {"JOBSCOUT_LLM_PADRAO": "off", "JOBSCOUT_GMAIL_CLIENT_ID": ""})
        env.start()
        self.addCleanup(env.stop)
        self.folder = TemporaryDirectory()
        self.app = App(Path(self.folder.name), background=False)
        self.app.assistant.public_job = offline
        self.app.assistant.public_company = offline
        self.httpd = serve_in_background(app=self.app)
        host, port = self.httpd.server_address
        self.base = f"http://{host}:{port}"

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.app.close()
        self.folder.cleanup()

    def call(self, method: str, path: str, payload=None, headers=None):
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = Request(
            self.base + path,
            data=data,
            headers={"Content-Type": "application/json", **(headers or {})},
            method=method,
        )
        with urlopen(request) as response:
            return json.loads(response.read().decode("utf-8"))

    def test_home_is_the_panel(self) -> None:
        with urlopen(self.base + "/") as response:
            page = response.read().decode("utf-8")
        self.assertIn("Rascunhos", page)
        self.assertIn("/app.js", page)
        with urlopen(self.base + "/app.js") as response:
            self.assertIn("EventSource", response.read().decode("utf-8"))

    def test_extension_event_becomes_draft_and_approval_saves(self) -> None:
        result = self.call("POST", "/api/eventos", {"tipo": "job_viewed", "site": "linkedin", "vaga": VAGA},
                           headers={"Origin": "chrome-extension://abc"})
        self.assertEqual(result["pendentes"], 1)
        self.assertEqual(self.call("GET", "/api/vagas"), [])
        draft_id = result["rascunhos"][0]
        self.call("POST", f"/api/rascunhos/{draft_id}/aprovar", {"payload": {"title": "Backend Python Pleno"}})
        jobs = self.call("GET", "/api/vagas")
        self.assertEqual(jobs[0]["title"], "Backend Python Pleno")
        detail = self.call("GET", f"/api/vagas/{jobs[0]['id']}")
        self.assertTrue(detail["movimentos"])
        state = self.call("GET", "/api/estado")
        self.assertEqual(state["rascunhos"], [])

    def test_stream_pushes_new_draft(self) -> None:
        stream = urlopen(self.base + "/api/stream", timeout=5)
        self.addCleanup(stream.close)
        self.assertEqual(stream.readline(), b"retry: 1500\n")
        stream.readline()
        self.call("POST", "/api/eventos", {"tipo": "job_viewed", "site": "linkedin", "vaga": VAGA})
        kinds = []
        while "rascunhos" not in kinds:
            line = stream.readline().decode("utf-8")
            if line.startswith("data: "):
                kinds.append(json.loads(line[6:])["tipo"])
        self.assertEqual(kinds[0], "atividade")
        self.assertEqual(self.call("GET", "/api/atividade")[0]["nivel"], "aviso")

    def test_other_sites_cannot_post(self) -> None:
        with self.assertRaises(HTTPError) as caught:
            self.call("POST", "/api/eventos", {"tipo": "job_viewed", "vaga": VAGA}, headers={"Origin": "https://evil.example"})
        self.assertEqual(caught.exception.code, 403)
        caught.exception.close()

    def test_failed_approval_returns_reason(self) -> None:
        self.call("POST", "/api/eventos", {"tipo": "job_viewed", "site": "linkedin", "vaga": VAGA})
        result = self.call("POST", "/api/eventos", {
            "tipo": "form_detected", "site": "linkedin", "vaga": VAGA,
            "perguntas": [{"rotulo": "Por que você quer trabalhar aqui?", "campo": "js-1"}],
        })
        with self.assertRaises(HTTPError) as caught:
            self.call("POST", f"/api/rascunhos/{result['rascunhos'][0]}/aprovar", {})
        self.assertEqual(caught.exception.code, 422)
        self.assertIn("vaga", json.loads(caught.exception.read().decode("utf-8"))["erro"])
        caught.exception.close()

    def test_import_eml_creates_message_draft(self) -> None:
        job = self.call("POST", "/api/vagas", {**VAGA, "status": "candidatado"})
        eml = (
            "From: Carla <carla@acme.com>\r\nSubject: Convite para entrevista\r\n"
            "Content-Type: text/plain; charset=utf-8\r\n\r\nPodemos conversar dia 30/10 às 15h?"
        ).encode("utf-8")
        body, content_type = _multipart("convite.eml", eml)
        request = Request(self.base + "/api/emails/importar", data=body, headers={"Content-Type": content_type}, method="POST")
        with urlopen(request) as response:
            draft = json.loads(response.read().decode("utf-8"))
        self.assertEqual(draft["kind"], "mensagem")
        self.assertEqual(draft["payload"]["job_id"], job["id"])
        self.call("POST", f"/api/rascunhos/{draft['id']}/aprovar", {})
        self.assertEqual(self.call("GET", f"/api/vagas/{job['id']}")["vaga"]["status"], "entrevista")

    def test_profile_round_trip_and_standard_fields(self) -> None:
        self.call("PUT", "/api/perfil", {"nome": "Ana Souza", "email": "ana@email.com", "historias": [{"titulo": "X", "texto": "Y"}]})
        fields = {item["chave"]: item["valor"] for item in self.call("GET", "/api/perfil/campos")}
        self.assertEqual(fields["primeiro_nome"], "Ana")
        self.assertEqual(fields["sobrenome"], "Souza")
        self.assertNotIn("telefone", fields)

    def test_post_docx_lists_activities(self) -> None:
        with TemporaryDirectory() as folder:
            path = Path(folder) / "cv.docx"
            document = Document()
            document.add_paragraph("Experiência profissional")
            document.add_paragraph("Analista | Oficina")
            document.add_paragraph("• Modelei o fluxo de pedidos do comercial")
            document.save(path)
            payload = path.read_bytes()
        body, content_type = _multipart("cv.docx", payload)
        request = Request(self.base + "/api/analisar", data=body, headers={"Content-Type": content_type}, method="POST")
        with urlopen(request) as response:
            result = json.loads(response.read().decode("utf-8"))
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["grupos"][0]["atividades"][0], "Modelei o fluxo de pedidos do comercial")

    def test_rejects_other_resume_extensions(self) -> None:
        body, content_type = _multipart("notas.txt", b"texto")
        request = Request(self.base + "/api/analisar", data=body, headers={"Content-Type": content_type}, method="POST")
        with self.assertRaises(HTTPError) as caught:
            urlopen(request)
        self.assertEqual(caught.exception.code, 422)
        caught.exception.close()


def _multipart(filename: str, payload: bytes) -> tuple[bytes, str]:
    boundary = "----jobscouttest"
    head = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="arquivo"; filename="{filename}"\r\n'
        "Content-Type: application/octet-stream\r\n\r\n"
    ).encode("utf-8")
    tail = f"\r\n--{boundary}--\r\n".encode("utf-8")
    return head + payload + tail, f"multipart/form-data; boundary={boundary}"


if __name__ == "__main__":
    unittest.main()
