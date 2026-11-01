import io
import json
import os
import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from jobscout import llm, resume_tools
from jobscout.linkedin_public import PublicPageError
from jobscout.server import App, serve_in_background

RESUME = """EXPERIÊNCIA
Analista de Dados | Itaú
03/2018 - 12/2020
- Consultas em SQL e dashboards em Power BI
Engenheira de Dados | Stone
jan 2021 – atual
- Construí os pipelines de dados do time de crédito
HABILIDADES
Python, Docker
"""


def offline(url):
    raise PublicPageError("sem rede nos testes")


class FakeResponse(io.BytesIO):
    def __init__(self, body, status=200):
        super().__init__(body.encode("utf-8"))
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def fake_web(pages):
    def opener(request, timeout=10):
        url = request.full_url
        for prefix, (status, body) in pages.items():
            if url.startswith(prefix):
                if status != 200:
                    raise HTTPError(url, status, "erro", {}, None)
                return FakeResponse(body, status)
        raise HTTPError(url, 404, "não achei", {}, None)

    return opener


class UnderstoodTest(unittest.TestCase):
    def test_years_per_skill_and_declared_time(self):
        profile = {"curriculo": RESUME, "skills_extras": [{"skill": "SQL", "anos": 9, "nota": "desde 2016"}]}
        data = resume_tools.understood(profile, date(2026, 10, 1))
        skills = {item["skill"]: item for item in data["skills"]}
        self.assertEqual(skills["SQL"]["anos_curriculo"], 2.8)
        self.assertEqual(skills["SQL"]["anos_informados"], 9)
        self.assertEqual(skills["SQL"]["vale"], 9)
        self.assertEqual(skills["Python"]["meses"], 0)  # só na lista de habilidades
        self.assertEqual(data["skills"][0]["skill"], "SQL")

    def test_checks_point_out_what_hurts_forms(self):
        points = " | ".join(point["texto"] for point in resume_tools.checks({"curriculo": RESUME}, date(2026, 10, 1)))
        self.assertIn("não cita ferramentas", points)  # Stone: atividade sem ferramenta
        self.assertIn("Python aparece no currículo, mas fora de um cargo", points)
        self.assertIn("LinkedIn", points)
        self.assertIn("vazio", resume_tools.checks({"curriculo": ""})[0]["texto"])


class OnlineTest(unittest.TestCase):
    def test_github_languages_by_year(self):
        repos = [
            {"name": "etl", "language": "Python", "created_at": "2017-03-01", "pushed_at": "2025-01-01", "stargazers_count": 3, "fork": False},
            {"name": "nb", "language": "Jupyter Notebook", "created_at": "2019-01-01", "pushed_at": "2020-01-01", "stargazers_count": 0, "fork": False},
            {"name": "infra", "language": "HCL", "created_at": "2023-01-01", "pushed_at": "2024-06-01", "stargazers_count": 0, "fork": False},
            {"name": "copia", "language": "Go", "created_at": "2020-01-01", "pushed_at": "2020-01-01", "stargazers_count": 0, "fork": True},
        ]
        opener = fake_web({
            "https://api.github.com/users/ana/repos": (200, json.dumps(repos)),
            "https://api.github.com/users/ana": (200, json.dumps({"name": "Ana", "public_repos": 4, "created_at": "2016-05-01T00:00:00Z", "html_url": "https://github.com/ana"})),
        })
        result = resume_tools.github("ana", opener)
        langs = {item["skill"]: item for item in result["linguagens"]}
        self.assertEqual(langs["Python"]["repos"], 2)
        self.assertEqual((langs["Python"]["de"], langs["Python"]["ate"], langs["Python"]["anos"]), (2017, 2025, 9))
        self.assertIn("Terraform", langs)
        self.assertNotIn("Go", langs)  # fork não conta
        self.assertFalse(resume_tools.github("ninguem", opener)["ok"])

    def test_github_user_from_profile_or_resume(self):
        self.assertEqual(resume_tools.github_user({"github": "https://github.com/ana-souza"}), "ana-souza")
        self.assertEqual(resume_tools.github_user({"github": "@ana"}), "ana")
        self.assertEqual(resume_tools.github_user({"curriculo": "Portfólio: github.com/anadev/projetos"}), "anadev")
        self.assertEqual(resume_tools.github_user({}), "")

    def test_linkedin_login_wall_explains_the_pdf_route(self):
        wall = fake_web({"https://www.linkedin.com/in/ana/": (999, "")})
        result = resume_tools.linkedin("https://www.linkedin.com/in/ana", wall)
        self.assertFalse(result["ok"])
        self.assertIn("Salvar em PDF", result["erro"])
        page = '<meta property="og:title" content="Ana Souza - Engenheira de Dados"><meta property="og:description" content="Stone · USP">'
        open_page = fake_web({"https://www.linkedin.com/in/ana/": (200, page)})
        self.assertEqual(resume_tools.linkedin("ana", open_page)["titulo"], "Ana Souza - Engenheira de Dados")


class BacklogServerTest(unittest.TestCase):
    def setUp(self):
        env = mock.patch.dict(os.environ, {"JOBSCOUT_LLM_PADRAO": "off", "JOBSCOUT_LLM_RESPONDER": "", "JOBSCOUT_GMAIL_CLIENT_ID": ""})
        env.start()
        self.addCleanup(env.stop)
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.app = App(Path(self.folder.name), background=False)
        self.app.assistant.public_job = offline
        self.app.assistant.public_company = offline
        self.addCleanup(llm.configure, "")
        self.httpd = serve_in_background(app=self.app)
        host, port = self.httpd.server_address
        self.base = f"http://{host}:{port}"

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.app.close()

    def call(self, method, path, payload=None, headers=None):
        request = Request(
            self.base + path,
            data=json.dumps(payload).encode("utf-8") if payload is not None else None,
            headers={"Content-Type": "application/json", **(headers or {})},
            method=method,
        )
        with urlopen(request) as response:
            return json.loads(response.read().decode("utf-8"))

    def test_improvement_flow_reflects_the_updated_resume(self):
        self.call("PUT", "/api/perfil", {"curriculo": RESUME})
        question = "How many years of work experience do you have with SQL?"
        created = self.call("POST", "/api/melhorias", {
            "pergunta": question, "tipo": "number", "sugestao": "2", "base": "Currículo: SQL em 1 cargo",
            "vaga": {"url": "https://www.linkedin.com/jobs/view/1/", "title": "Data Engineer", "company": "Jobgether"},
        }, headers={"Origin": "chrome-extension://abc"})
        self.assertEqual(created["state"], "aberto")
        self.assertEqual(created["job"], "Data Engineer — Jobgether")
        again = self.call("POST", "/api/melhorias", {"pergunta": question, "sugestao": "2"}, headers={"Origin": "chrome-extension://abc"})
        self.assertEqual(again["id"], created["id"])  # mesma pergunta não duplica
        self.assertEqual(self.call("GET", "/api/estado")["melhorias_abertas"], 1)

        same = self.call("POST", f"/api/melhorias/{created['id']}/reprocessar", {})
        self.assertEqual(same["latest"]["valor"], "2")
        self.assertFalse(same["latest"]["mudou"])

        # A pessoa informa o tempo real de SQL na tela Currículo e reprocessa.
        self.call("PUT", "/api/perfil", {"skills_extras": [{"skill": "SQL", "anos": "8", "nota": "desde a faculdade"}]})
        self.assertEqual(self.call("GET", "/api/perfil")["curriculo"], RESUME.strip())  # salvar uma parte não apaga a outra
        changed = self.call("POST", f"/api/melhorias/{created['id']}/reprocessar", {})
        self.assertEqual(changed["latest"]["valor"], "8")
        self.assertTrue(changed["latest"]["mudou"])
        self.assertIn("Informado por você", changed["latest"]["base"])

        done = self.call("PATCH", f"/api/melhorias/{created['id']}", {"estado": "resolvido"})
        self.assertEqual(done["state"], "resolvido")
        self.assertEqual(self.call("GET", "/api/estado")["melhorias_abertas"], 0)
        with self.assertRaises(HTTPError) as caught:
            self.call("POST", f"/api/melhorias/{created['id']}/reprocessar", {}, headers={"Origin": "chrome-extension://abc"})
        self.assertEqual(caught.exception.code, 403)

    def test_analysis_and_review_without_model(self):
        self.call("PUT", "/api/perfil", {"curriculo": RESUME})
        analysis = self.call("GET", "/api/curriculo/analise")
        self.assertTrue(analysis["skills"])
        self.assertTrue(analysis["pontos"])
        with self.assertRaises(HTTPError) as caught:
            self.call("POST", "/api/curriculo/revisar-ia", {})
        self.assertEqual(caught.exception.code, 502)

    def test_review_with_model(self):
        llm.configure("ollama:gemma3:4b")
        reply = json.dumps({"resumo": "Bom.", "pontos": [{"tipo": "lacuna", "texto": "Stone sem ferramentas", "pergunta": "Quais ferramentas?"}]})
        with mock.patch("jobscout.llm.ask_llm", return_value=reply):
            result = self.call("POST", "/api/curriculo/revisar-ia", {})
        self.assertEqual(result["pontos"][0]["pergunta"], "Quais ferramentas?")

    def test_review_drops_false_missing_dates(self):
        llm.configure("ollama:gemma3:4b")
        self.call("PUT", "/api/perfil", {"curriculo": RESUME})
        reply = json.dumps({"pontos": [
            {"tipo": "lacuna", "texto": "Cargos sem data de início ou fim.", "pergunta": "Quais as datas?"},
            {"tipo": "melhoria", "texto": "Resultados sem números.", "pergunta": "Quanto?"},
        ]})
        with mock.patch("jobscout.llm.ask_llm", return_value=reply):
            result = self.call("POST", "/api/curriculo/revisar-ia", {})
        self.assertEqual([point["texto"] for point in result["pontos"]], ["Resultados sem números."])

    def test_health_and_results(self):
        health = self.call("GET", "/api/saude")
        names = {item["nome"]: item["estado"] for item in health["itens"]}
        self.assertEqual(names["IA"], "desligado")
        self.assertEqual(names["Extensão do Chrome"], "aviso")  # ainda não falou com o app
        self.assertEqual(health["geral"], "aviso")
        self.call("GET", "/api/extensao/resumo", headers={"Origin": "chrome-extension://abc"})
        names = {item["nome"]: item["estado"] for item in self.call("GET", "/api/saude")["itens"]}
        self.assertEqual(names["Extensão do Chrome"], "ok")
        drafts = self.call("POST", "/api/eventos", {
            "tipo": "application_submitted", "site": "linkedin", "vaga": {"url": "https://www.linkedin.com/jobs/view/77/", "title": "Dev", "company": "Acme"},
            "respostas": [{"rotulo": "Qual sua pretensão salarial?", "valor": "R$ 14.000"}], "documentos": ["CV Ana.pdf"],
        }, headers={"Origin": "chrome-extension://abc"})
        self.call("POST", f"/api/rascunhos/{drafts['rascunhos'][0]}/aprovar", {})
        rows = self.call("GET", "/api/resultados")
        self.assertEqual((rows[0]["documentos"], rows[0]["salario_informado"]), ("CV Ana.pdf", "R$ 14.000"))

    def test_online_uses_the_profile(self):
        with mock.patch.object(self.app, "resume_online", return_value={"github": {"ok": False, "erro": "x"}}) as online:
            result = self.call("POST", "/api/curriculo/online", {})
        online.assert_called_once()
        self.assertFalse(result["github"]["ok"])


if __name__ == "__main__":
    unittest.main()
