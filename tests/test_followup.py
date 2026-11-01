"""Acompanhamento: etapas por empresa, lembretes com agenda, busca automática, e-mails e abordagens no chat."""

import imaplib
import json
import os
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from jobscout import appearance, approach, cv, imap_mail, jobsearch, llm, mail, pipeline, reminders, replies
from jobscout.gmail import GmailError
from jobscout.preferences import Preferences
from jobscout.linkedin_public import PublicPageError
from jobscout.server import App, serve_in_background

EXT = {"Origin": "chrome-extension://abc"}

GUPY_PAGE = """<html><script id="__NEXT_DATA__" type="application/json" nonce="x">""" + json.dumps({
    "props": {"pageProps": {"initialJobList": {"data": [
        {"id": 1, "name": "Engenheiro de Dados Sênior", "careerPageName": "Cadastra", "workplaceType": "remote",
         "city": "", "state": "", "description": "<p>Python, Airflow e <b>dbt</b></p>",
         "jobUrl": "https://cadastra.gupy.io/job/abc=?jobBoardSource=gupy_portal", "publishedDate": "2026-10-29T18:32:06.745Z"},
        {"id": 2, "name": "Vendedor de Loja", "careerPageName": "Varejo", "workplaceType": "on-site",
         "city": "Recife", "state": "PE", "description": "Vendas", "jobUrl": "https://varejo.gupy.io/job/xyz"},
        {"id": 3, "name": "Engenheira de Dados Pleno", "careerPageName": "Banco X", "workplaceType": "on-site",
         "city": "São Paulo", "state": "SP", "description": "Spark e Python", "jobUrl": "https://bancox.gupy.io/job/qq"},
    ]}}},
}) + "</script></html>"

ALERT_HTML = """<html><body><table>
<tr><td><a href="https://www.linkedin.com/comm/jobs/view/4012345678/?trackingId=x"><img src="logo.png"></a></td>
<td><a href="https://www.linkedin.com/comm/jobs/view/4012345678/?trackingId=x">Data Engineer</a><br>
Acme Corp<br>São Paulo, Brasil (Remoto)</td></tr>
<tr><td><a href="https://www.linkedin.com/comm/jobs/view/4099999999/?trk=y">Analytics Engineer</a></td></tr>
<tr><td>Nubank · São Paulo (Híbrido)</td></tr>
<tr><td><a href="https://www.linkedin.com/comm/jobs/view/4099999999/">Ver vaga</a></td></tr>
<tr><td><a href="https://www.linkedin.com/comm/jobs/search/">Ver todas as vagas</a></td></tr>
</table></body></html>"""

ALERT_TEXT = """Suas vagas recomendadas

Data Engineer
Acme Corp
São Paulo, Brasil
View job: https://www.linkedin.com/comm/jobs/view/4012345678/?trackingId=x

---------
Analytics Engineer
Nubank
São Paulo
View job: https://www.linkedin.com/comm/jobs/view/4099999999/
"""


def offline(url):
    raise PublicPageError("sem rede nos testes")


class PipelineTest(unittest.TestCase):
    def test_initial_stages_follow_the_status(self):
        stages = pipeline.initial_stages([dict(stage) for stage in pipeline.DEFAULT_PIPELINE], "candidatado")
        self.assertEqual([stage["state"] for stage in stages[:3]], ["feita", "atual", "pendente"])
        interview = pipeline.initial_stages([dict(stage) for stage in pipeline.DEFAULT_PIPELINE], "entrevista")
        self.assertEqual(pipeline.current(interview)["name"], "Triagem com RH")
        custom = pipeline.initial_stages([{"name": "Aplicada", "kind": "candidatado"}, {"name": "Case", "kind": "em_analise"}], "entrevista")
        self.assertEqual(pipeline.current(custom)["name"], "Case")  # sem etapa de entrevista: a mais avançada que existe

    def test_advance_and_validation(self):
        stages = pipeline.initial_stages([dict(stage) for stage in pipeline.DEFAULT_PIPELINE], "visualizada")
        stages[2]["state"] = "pulada"
        moved = pipeline.advance(stages, 4, "2026-10-30T10:00:00-03:00")
        self.assertEqual([stage["state"] for stage in moved[:6]], ["feita", "feita", "pulada", "feita", "atual", "pendente"])
        with self.assertRaises(ValueError):
            pipeline.clean_stages([{"nome": "A", "estado": "atual"}, {"nome": "B", "estado": "atual"}])
        self.assertEqual(len(pipeline.clean_pipeline([{"nome": "X"}, {"nome": "x"}, {"nome": ""}])), 1)


class SearchTest(unittest.TestCase):
    CONFIG = jobsearch.clean_config({"titulos": ["Engenheiro de Dados"], "palavras": ["Python", "dbt"], "excluir": ["vendas"], "modelos": ["remoto"]})

    def test_gupy_and_score(self):
        items = jobsearch.parse_gupy(GUPY_PAGE)
        self.assertEqual(items[0]["url"], "https://cadastra.gupy.io/job/abc=")
        self.assertEqual((items[0]["company"], items[0]["work_mode"]), ("Cadastra", "remoto"))
        self.assertEqual(items[0]["description"], "Python, Airflow e dbt")
        points, reasons = jobsearch.score(items[0], self.CONFIG)
        self.assertGreaterEqual(points, 80)
        self.assertIn("título: Engenheiro de Dados", reasons)
        self.assertEqual(jobsearch.score(items[1], self.CONFIG)[0], 0)  # "vendas" é excluída
        hybrid, why = jobsearch.score(items[2], self.CONFIG)
        self.assertLess(hybrid, points)
        self.assertIn("título similar: Engenheira de Dados", why)
        with self.assertRaises(jobsearch.SearchError):
            jobsearch.parse_gupy("<html>mudou</html>")

    def test_inhire_and_linkedin_alerts(self):
        data = {"tenantName": "Olist", "jobsPage": [
            {"displayName": "Analista de Dados Sênior", "jobId": "2e22", "status": "published", "workplaceType": "Hybrid", "location": "São Paulo, SP, BR"},
            {"displayName": "Rascunho", "jobId": "x", "status": "draft"},
        ]}
        items = jobsearch.parse_inhire(data, "olist")
        self.assertEqual([item["url"] for item in items], ["https://olist.inhire.app/vagas/2e22"])
        self.assertEqual(items[0]["work_mode"], "hibrido")
        from_html = {item["url"]: item for item in jobsearch.parse_linkedin_alert({"html": ALERT_HTML, "corpo": ""})}
        self.assertEqual(set(from_html), {"https://www.linkedin.com/jobs/view/4012345678/", "https://www.linkedin.com/jobs/view/4099999999/"})
        acme = from_html["https://www.linkedin.com/jobs/view/4012345678/"]
        self.assertEqual((acme["title"], acme["company"], acme["work_mode"]), ("Data Engineer", "Acme Corp", "remoto"))
        from_text = {item["title"]: item for item in jobsearch.parse_linkedin_alert({"html": "", "corpo": ALERT_TEXT})}
        self.assertEqual(from_text["Analytics Engineer"]["company"], "Nubank")

    def test_config_limits(self):
        with self.assertRaises(ValueError):
            jobsearch.clean_config({"intervalo_horas": 1})
        config = jobsearch.clean_config({"inhire_empresas": "https://olist.inhire.app/vagas, Dock", "titulos": "Dados; Data Engineer"})
        self.assertEqual(config["inhire_empresas"], ["olist", "dock"])
        self.assertEqual(config["titulos"], ["Dados", "Data Engineer"])


class MailRelevanceTest(unittest.TestCase):
    def setUp(self):
        env = mock.patch.dict(os.environ, {"JOBSCOUT_LLM_PADRAO": "off", "JOBSCOUT_LLM_CLASSIFICAR": ""})
        env.start()
        self.addCleanup(env.stop)
        llm.configure("")

    def message(self, subject, body, sender="ana@acme.com", bulk=False):
        return {"assunto": subject, "corpo": body, "remetente_email": sender, "remetente_nome": "Ana", "em_massa": bulk}

    def test_rules_decide_the_clear_cases(self):
        self.assertTrue(mail.relevance(self.message("Entrevista", "Gostaríamos de agendar sua entrevista para a vaga."), [])["recrutamento"])
        self.assertFalse(mail.relevance(self.message("Webinar", "Inscreva-se no webinar sobre vagas em dados", bulk=True), [])["recrutamento"])
        self.assertFalse(mail.relevance(self.message("Oi", "Vamos almoçar amanhã?"), [])["recrutamento"])
        alert = mail.relevance(self.message("Vagas", "Data Engineer", sender="jobalerts-noreply@linkedin.com"), [])
        self.assertTrue(alert["alerta"])
        ats = mail.relevance(self.message("Atualização", "Sua candidatura para a vaga foi atualizada.", sender="no-reply@gupy.io"), [])
        self.assertTrue(ats["recrutamento"])

    def test_ai_decides_the_doubtful_ones(self):
        self.addCleanup(llm.configure, "")
        llm.configure("ollama:gemma3:4b")
        doubtful = self.message("Oportunidade", "Temos uma oportunidade que pode te interessar.", bulk=True)
        answer = json.dumps({"recrutamento": False, "motivo": "newsletter de vagas"})
        with mock.patch("jobscout.llm.ask_llm", return_value=answer):
            verdict = mail.relevance(doubtful, [])
        self.assertEqual((verdict["recrutamento"], verdict["origem"], verdict["motivo"]), (False, "llm", "newsletter de vagas"))


class ApproachTest(unittest.TestCase):
    def test_rules_find_company_and_title(self):
        def found(text):
            return approach.detect([{"texto": text, "minha": False}], use_ai=False)
        hit = found("Oi Ana! Temos uma vaga de Engenheira de Dados aqui na Acme, 100% remota.")
        self.assertEqual((hit["titulo"], hit["empresa"], hit["modelo"]), ("Engenheira de Dados", "Acme", "remoto"))
        self.assertEqual(found("Hi! Reaching out about a Senior Data Engineer role at Stripe.")["empresa"], "Stripe")
        self.assertIsNone(found("Bom dia! Podemos marcar amanhã?"))
        mine = approach.detect([{"texto": "Tenho interesse na vaga de Dados na Acme", "minha": True}], use_ai=False)
        self.assertIsNone(mine)  # só o que o recrutador escreveu conta


class FakeCalendar:
    def __init__(self):
        self.events, self.deleted = [], []

    def calendar_ready(self):
        return True

    def create_event(self, event):
        self.events.append(event)
        return {"id": f"ev{len(self.events)}"}

    def delete_event(self, event_id):
        self.deleted.append(event_id)


class ServerTest(unittest.TestCase):
    def setUp(self):
        env = mock.patch.dict(os.environ, {"JOBSCOUT_LLM_PADRAO": "off", "JOBSCOUT_LLM_RESPONDER": "", "JOBSCOUT_LLM_CLASSIFICAR": "",
                                           "JOBSCOUT_LLM_MENSAGEM": "", "JOBSCOUT_GMAIL_CLIENT_ID": ""})
        env.start()
        self.addCleanup(env.stop)
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.app = App(Path(self.folder.name), background=False)
        self.app.assistant.public_job = offline
        self.app.assistant.public_company = offline
        self.app.preferences.save({"pasta": str(Path(self.folder.name) / "Pasta")})
        self.addCleanup(llm.configure, "")
        llm.configure("")
        self.httpd = serve_in_background(app=self.app)
        host, port = self.httpd.server_address
        self.base = f"http://{host}:{port}"

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.app.close()

    def call(self, method, path, payload=None, headers=None):
        request = Request(self.base + path, data=json.dumps(payload).encode("utf-8") if payload is not None else None,
                          headers={"Content-Type": "application/json", **(headers or {})}, method=method)
        with urlopen(request) as response:
            body = response.read().decode("utf-8")
            return json.loads(body) if response.headers.get_content_type() == "application/json" else body

    def job(self, title="Data Engineer", company="Acme", status="candidatado", url="https://example.com/vaga/1"):
        return self.call("POST", "/api/vagas", {"url": url, "title": title, "company": company, "status": status})

    def test_company_board_drives_stages_and_status(self):
        job = self.job()
        view = self.call("GET", f"/api/vagas/{job['id']}/etapas")
        self.assertEqual(view["etapas"][1]["state"], "atual")  # candidatado → "Currículo enviado"
        company = view["empresa"]["id"]
        board = [{"nome": "Aplicada", "tipo": "candidatado"}, {"nome": "Teste técnico", "tipo": "em_analise"},
                 {"nome": "Painel com o time", "tipo": "entrevista"}, {"nome": "Visita ao escritório", "tipo": "entrevista"},
                 {"nome": "Proposta", "tipo": "proposta"}]
        saved = self.call("PUT", f"/api/empresas/{company}/quadro", {"quadro": board, "aplicar": True})
        self.assertEqual((saved["vagas_atualizadas"], saved["personalizado"]), (1, True))
        self.assertEqual(saved["vagas"][0]["etapa"], "Aplicada")
        moved = self.call("POST", f"/api/vagas/{job['id']}/etapas/mover", {"etapa": "Visita ao escritório"})
        self.assertEqual(pipeline.current(moved["etapas"])["name"], "Visita ao escritório")
        self.assertEqual(self.call("GET", f"/api/vagas/{job['id']}")["vaga"]["status"], "entrevista")
        # Pelo quadro geral: proposta leva a etapa para "Proposta".
        self.call("PATCH", f"/api/vagas/{job['id']}/status", {"status": "proposta"})
        self.assertEqual(pipeline.current(self.call("GET", f"/api/vagas/{job['id']}/etapas")["etapas"])["name"], "Proposta")
        boards = self.call("GET", "/api/quadros")
        self.assertEqual((boards[0]["nome"], boards[0]["personalizado"]), ("Acme", True))
        with self.assertRaises(HTTPError) as caught:
            self.call("PUT", f"/api/empresas/{company}/quadro", {"quadro": board}, headers=EXT)
        self.assertEqual(caught.exception.code, 403)

    def test_reminders_repeat_go_to_calendar_and_stop_with_the_job(self):
        calendar = FakeCalendar()
        self.app.reminders.calendar = calendar
        job = self.job()
        listed = self.call("GET", "/api/lembretes")
        preset = next(item for item in listed["modelos"] if item["chave"] == "cobrar_retorno")
        past = (datetime.now().astimezone() - timedelta(hours=1)).isoformat(timespec="minutes")
        created = self.call("POST", "/api/lembretes", {"vaga_id": job["id"], "titulo": preset["titulo"], "intencao": "cobrar_retorno",
                                                      "quando": past, "cada_dias": 7, "vezes": 3})
        self.assertEqual(created["title"], "Cobrar retorno: Data Engineer — Acme")
        self.assertEqual(calendar.events[0]["recurrence"], ["RRULE:FREQ=DAILY;INTERVAL=7;COUNT=3"])
        self.assertEqual(created["calendar_id"], "ev1")
        self.assertEqual([row["id"] for row in self.app.reminders.check()], [created["id"]])
        self.assertEqual(self.app.reminders.check(), [])  # avisa uma vez só
        done = self.call("POST", f"/api/lembretes/{created['id']}/feito", {})
        self.assertEqual((done["remaining"], done["state"]), (2, "ativo"))
        self.assertGreater(datetime.fromisoformat(done["next_at"]), datetime.now().astimezone())
        self.call("PATCH", f"/api/vagas/{job['id']}/status", {"status": "recusada"})
        self.call("POST", f"/api/lembretes/{created['id']}/adiar", {})
        self.app.store.update_reminder(created["id"], next_at=past)
        self.app.reminders.check()
        self.assertEqual(self.app.store.reminder(created["id"])["state"], "parado")
        self.assertEqual(calendar.deleted, ["ev1", "ev2"])  # adiar refaz o evento; parar apaga o novo
        with self.assertRaises(HTTPError) as caught:
            self.call("POST", "/api/lembretes", {"titulo": "x", "quando": "amanhã"})
        self.assertEqual(caught.exception.code, 422)

    def test_search_runs_sources_and_saves_the_choice(self):
        self.job(title="Engenheira de Dados Pleno", company="Banco X", url="https://bancox.gupy.io/job/qq")
        pages = {"portal.gupy.io": GUPY_PAGE}

        class Response:
            def __init__(self, body):
                self.body = body.encode("utf-8")

            def read(self):
                return self.body

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def opener(request, timeout=0):
            if "himalayas" in request.full_url:
                return Response(json.dumps({"jobs": [{"applicationLink": "https://himalayas.app/companies/acme/jobs/1", "title": "Senior Data Engineer", "companyName": "Acme Remote",
                                                      "locationRestrictions": ["Brazil"], "description": "<p>Python</p>"}]}))
            if "boards-api.greenhouse" in request.full_url:
                return Response(json.dumps({"jobs": [{"absolute_url": "https://job-boards.greenhouse.io/gitlab/jobs/1", "title": "Data Engineer", "company_name": "GitLab",
                                                      "location": {"name": "Remote, LATAM"}, "content": "&lt;p&gt;Python&lt;/p&gt;"}]}))
            if "inhire" in request.full_url:
                return Response(json.dumps({"tenantName": "Olist", "jobsPage": [
                    {"displayName": "Engenheiro de Dados", "jobId": "77", "status": "published", "workplaceType": "Remote"}]}))
            return Response(next(body for host, body in pages.items() if host in request.full_url))

        self.app.search.opener = opener
        self.app.search.pause = 0
        self.app.search.alerts = lambda: [{"html": ALERT_HTML, "corpo": "", "recebido_em": None}]
        with self.assertRaises(HTTPError) as caught:
            self.call("POST", "/api/busca/rodar", {})
        self.assertEqual(caught.exception.code, 409)  # nada para procurar ainda
        state = self.call("PUT", "/api/busca/config", {"titulos": ["Engenheiro de Dados", "Data Engineer"], "palavras": ["Python"],
                                                      "excluir": ["vendas"], "inhire_empresas": ["olist"], "ativo": True,
                                                      "ats_empresas": ["https://job-boards.greenhouse.io/gitlab"]})
        self.assertEqual(state["config"]["ats_empresas"], ["greenhouse:gitlab"])
        self.assertIn("Analytics Engineer", state["similares"])
        self.assertTrue(state["config"]["ativo"])
        summary = self.call("POST", "/api/busca/rodar", {})
        results = self.call("GET", "/api/busca/resultados")
        urls = [row["url"] for row in results]
        self.assertIn("https://cadastra.gupy.io/job/abc=", urls)
        self.assertIn("https://olist.inhire.app/vagas/77", urls)
        self.assertIn("https://www.linkedin.com/jobs/view/4012345678/", urls)
        self.assertIn("https://himalayas.app/companies/acme/jobs/1", urls)
        self.assertIn("https://job-boards.greenhouse.io/gitlab/jobs/1", urls)
        self.assertNotIn("https://bancox.gupy.io/job/qq", urls)  # já salva
        self.assertNotIn("https://varejo.gupy.io/job/xyz", urls)  # excluída
        self.assertEqual(summary["novas"], len(results))
        again = self.call("POST", "/api/busca/rodar", {})
        self.assertEqual(again["novas"], 0)  # o que já apareceu não volta
        chosen = next(row for row in results if "cadastra" in row["url"])
        job = self.call("POST", f"/api/busca/resultados/{chosen['id']}/salvar", {})
        self.assertEqual((job["title"], job["company"], job["status"]), ("Engenheiro de Dados Sênior", "Cadastra", "visualizada"))
        self.assertNotIn(chosen["id"], [row["id"] for row in self.call("GET", "/api/busca/resultados")])
        with self.assertRaises(HTTPError) as caught:
            self.call("PUT", "/api/busca/config", {"intervalo_horas": 1})
        self.assertEqual(caught.exception.code, 422)

    def test_chat_approach_becomes_an_opportunity_draft(self):
        turns = [{"autor": "Carla Mendes", "texto": "Oi Ana! Temos uma vaga de Engenheira de Dados aqui na Acme, remota.", "minha": False, "dia": "hoje"}]
        payload = {"canal": "whatsapp", "nome": "Carla Mendes", "telefone": "+55 11 98888-7777", "conversa": turns}
        first = self.call("POST", "/api/extensao/chat/abordagem", payload, headers=EXT)
        self.assertEqual((first["estado"], first["vaga"]["empresa"]), ("novo", "Acme"))
        self.assertEqual(self.call("POST", "/api/extensao/chat/abordagem", payload, headers=EXT)["estado"], "rascunho")
        draft = self.call("GET", "/api/rascunhos")[0]
        self.assertEqual((draft["kind"], draft["payload"]["work_mode"]), ("vaga", "Remoto"))
        approved = self.call("POST", f"/api/rascunhos/{draft['id']}/aprovar", {})
        job_id = approved["job_id"] if "job_id" in approved else approved["vaga"]["id"] if "vaga" in approved else None
        jobs = self.call("GET", "/api/vagas")
        self.assertEqual((jobs[0]["title"], jobs[0]["company"], jobs[0]["source"]), ("Engenheira de Dados", "Acme", "whatsapp"))
        recruiters = self.call("GET", f"/api/vagas/{jobs[0]['id']}")["recrutadores"]
        self.assertEqual(recruiters[0]["name"], "Carla Mendes")
        self.assertEqual(self.call("POST", "/api/extensao/chat/abordagem", payload, headers=EXT)["estado"], "salva")
        self.assertIsNotNone(job_id or jobs[0]["id"])
        quiet = self.call("POST", "/api/extensao/chat/abordagem", {"canal": "linkedin", "nome": "João", "conversa": [
            {"autor": "João", "texto": "Bom dia, tudo bem?", "minha": False}]}, headers=EXT)
        self.assertEqual(quiet["estado"], "nada")

    def test_chat_keeps_history_and_answers_from_the_records(self):
        self.job(title="Data Engineer", company="Acme")
        first = self.call("POST", "/api/chat", {"texto": "O que tenho na Acme?"})
        self.assertEqual([row["role"] for row in first["mensagens"]], ["pessoa", "jobscout"])
        self.assertIn("Acme", first["mensagens"][1]["text"])
        self.assertTrue(first["mensagens"][1]["sources"])
        second = self.call("POST", "/api/chat", {"conversa": first["id"], "texto": "E sobre a Zeta?"})
        self.assertEqual(len(second["mensagens"]), 4)
        self.assertEqual([row["title"] for row in self.call("GET", "/api/chat")], ["O que tenho na Acme?"])
        self.call("POST", f"/api/chat/{first['id']}/remover", {})
        self.assertEqual(self.call("GET", "/api/chat"), [])

    def test_appearance_presets_fit_and_sent_resume(self):
        saved = self.call("PUT", "/api/aparencia/tema", {"tema": {"nome": "T", "escuro": {"bg": "#000000"}}})
        self.assertEqual(saved["tema"]["escuro"]["bg"], "#000000")
        self.assertIsNone(self.call("POST", "/api/aparencia/tema/restaurar", {})["tema"])
        avatar = self.call("PUT", "/api/aparencia/boneco", {"idle": "data:image/png;base64,AAAA"})
        self.assertIn("idle", avatar["boneco"])
        self.assertIsNone(self.call("POST", "/api/aparencia/boneco/restaurar", {})["boneco"])
        state = self.call("PUT", "/api/busca/presets", {"presets": [{"nome": "Dados remoto", "config": {"titulos": ["Data Engineer"], "modelos": ["remoto"]}}]})
        self.assertEqual(state["presets"][0]["config"]["titulos"], ["Data Engineer"])
        self.call("PUT", "/api/perfil", {"curriculo": "Engenheira de Dados | Stone\n01/2021 - atual\n- Pipelines em Python"})
        job = self.call("POST", "/api/vagas", {"url": "https://example.com/vaga/9", "title": "Dev", "company": "Acme", "description": "Python e Kafka", "status": "candidatado"})
        detail = self.call("GET", f"/api/vagas/{job['id']}")
        self.assertEqual(detail["encaixe"], 50)
        marked = self.call("POST", f"/api/vagas/{job['id']}/curriculo", {"documento": "Currículo padrão"})
        self.assertEqual(marked["curriculo"]["tipo"], "Padrão")
        self.assertEqual(self.call("GET", "/api/resultados")[0]["curriculo"]["tipo"], "Padrão")
        self.call("PUT", "/api/preferencias", {"google_cliente": "id", "google_chave": "segredo"})
        self.assertTrue(self.app.gmail.configured())
        self.assertIs(self.call("GET", "/api/preferencias")["google_chave"], True)  # a chave não volta para o painel

    def test_presets_models_stage_dates_and_chat_record(self):
        job = self.job()
        self.call("PUT", f"/api/vagas/{job['id']}/etapas", {"etapas": [
            {"nome": "Currículo enviado", "tipo": "candidatado", "estado": "atual"},
            {"nome": "Teste técnico", "tipo": "em_analise", "quando": "2030-01-10T14:00"}]})
        titles = [row["title"] for row in self.call("GET", f"/api/lembretes?vaga={job['id']}")["lembretes"]]
        self.assertEqual(titles, ["Teste técnico: Data Engineer — Acme"])
        self.call("PUT", f"/api/vagas/{job['id']}/etapas", {"etapas": [
            {"nome": "Currículo enviado", "tipo": "candidatado", "estado": "atual"},
            {"nome": "Teste técnico", "tipo": "em_analise", "quando": "2030-01-11T14:00"}]})
        rows = self.call("GET", f"/api/lembretes?vaga={job['id']}")["lembretes"]
        self.assertEqual(len(rows), 1)  # data nova troca o lembrete, não duplica
        self.assertTrue(rows[0]["next_at"].startswith("2030-01-11"))
        self.assertIn("calendar.google.com", rows[0]["agenda_link"])
        self.assertIn("BEGIN:VCALENDAR", self.call("GET", f"/api/lembretes/{rows[0]['id']}/agenda.ics"))

        self.call("PUT", "/api/curriculo/completo", {"cv": {"titulo": "Eng", "experiencias": [{"cargo": "Dados", "itens": ["x"]}]}})
        model = self.call("POST", "/api/curriculo/versoes", {"modelo": "Dados"})
        self.assertIsNone(model["job_id"])
        with self.assertRaises(HTTPError):
            self.call("POST", "/api/curriculo/versoes", {"modelo": "Dados"})
        options = self.call("POST", "/api/extensao/curriculos", {"url": job["url"]}, headers=EXT)["curriculos"]
        self.assertEqual([item["nome"] for item in options], ["Padrão: Dados", "Currículo completo"])
        marked = self.call("POST", f"/api/vagas/{job['id']}/curriculo", {"documento": "Dados"})
        self.assertEqual(marked["curriculo"], {"tipo": "Padrão", "nome": "Dados"})

        self.assertFalse(self.call("GET", "/api/resultados")[0]["retorno"])
        recorded = self.call("POST", "/api/extensao/chat/registrar", {"vaga_id": job["id"], "canal": "linkedin", "texto": "Obrigado!", "intencao": "interesse", "recebeu": True}, headers=EXT)
        self.assertTrue(recorded["registrado"])
        self.assertEqual(self.call("GET", f"/api/vagas/{job['id']}")["mensagens"][0]["body"], "Obrigado!")
        self.assertTrue(self.call("GET", "/api/resultados")[0]["retorno"])

        calls = []
        self.app.search._gupy = lambda config, notes: calls.append(config["titulos"]) or []
        self.app.search.pause = 0
        self.call("PUT", "/api/busca/config", {"titulos": ["Data Engineer"], "fontes": {"himalayas": False}})
        self.call("PUT", "/api/busca/presets", {"presets": [
            {"nome": "A", "auto": True, "config": {"titulos": ["BI Analyst"], "fontes": {"himalayas": False}}},
            {"nome": "B", "config": {"titulos": ["Nunca"], "fontes": {"himalayas": False}}}]})
        self.app.search.run()
        self.assertEqual(calls, [["Data Engineer"], ["BI Analyst"]])  # só o preset marcado entra sozinho
        calls.clear()
        self.app.search.run(manual=True)
        self.assertEqual(calls, [["Data Engineer"]])

    def test_email_style_is_separate(self):
        chat = self.call("GET", "/api/mensagens/estilo")
        email = self.call("GET", "/api/mensagens/estilo?canal=email")
        self.assertIn("LinkedIn ou WhatsApp", chat["texto"])
        self.assertIn("E-MAILS A RECRUTADORES", email["texto"])
        self.call("PUT", "/api/mensagens/estilo?canal=email", {"texto": "Escreva e-mails curtos como {nome}."})
        self.assertFalse(self.call("GET", "/api/mensagens/estilo?canal=email")["padrao"])
        self.assertTrue(self.call("GET", "/api/mensagens/estilo")["padrao"])  # o do chat não mudou
        self.assertIn("e-mails curtos como Ana", replies.system_prompt("Escreva e-mails curtos como {nome}.", {"nome": "Ana Souza"}, None, "email"))
        intent = next(item for item in replies.library() if item["chave"] == "interesse")
        chat_prompt = replies.system_prompt("", {"nome": "Ana"}, intent, "whatsapp")
        self.assertIn("CENÁRIO 1", chat_prompt)
        self.assertNotIn("CENÁRIO 6", chat_prompt)


class ImprovementsTest(unittest.TestCase):
    def test_similar_titles_and_work_modes(self):
        self.assertIn("Data Engineer", jobsearch.similar_titles("Engenheiro de Dados Sênior"))
        self.assertIn("Engenheiro de Dados", jobsearch.similar_titles("Data Engineer"))
        self.assertEqual(jobsearch.similar_titles("Analista de Suporte"), ["Support Analyst"])
        self.assertEqual(jobsearch.profile_modes("Remoto, Presencial (mudando de cidade)"), ["remoto", "presencial_mudanca"])
        config = jobsearch.clean_config({"titulos": ["Data Engineer"], "modelos": ["presencial_cidade"]})
        config["cidade"] = "Goiânia"
        here, why = jobsearch.score({"title": "Data Engineer", "location": "Goiânia", "work_mode": "presencial"}, config)
        away, _ = jobsearch.score({"title": "Data Engineer", "location": "Recife", "work_mode": "presencial"}, config)
        self.assertGreater(here, away)
        self.assertIn("Presencial (na sua cidade)", why)
        moving = {**config, "modelos": ["presencial_mudanca"]}
        self.assertGreater(jobsearch.score({"title": "Data Engineer", "location": "Recife", "work_mode": "presencial"}, moving)[0], away)

    def test_resume_structure_clients_education_and_check(self):
        data = cv.clean({
            "habilidades": [{"nome": "Python"}, {"nome": "Excel"}],
            "experiencias": [{"cargo": "Consultor de Dados", "empresa": "Accenture", "itens": ["Pipelines em Python e Airflow"],
                              "habilidades": ["dbt", "dbt"], "clientes": [{"nome": "Itaú", "inicio": "2022-01", "fim": "2023-02", "descricao": "Modelagem"}, {"descricao": "sem nome"}]}],
            "formacao": [{"curso": "Bacharelado em Sistemas"}, {"curso": "MBA em Dados"}, {"curso": "Pós-graduação em IA"}],
        })
        role = data["experiencias"][0]
        self.assertEqual((role["habilidades"], [client["nome"] for client in role["clientes"]]), (["dbt"], ["Itaú"]))
        self.assertEqual([item["tipo"] for item in data["formacao"]], ["graduacao", "pos", "pos"])
        page = cv.render_html(data, {"nome": "Ana"}, "pt")
        for text in ("Pós-graduação", "Graduação", "Empresas atendidas", "Itaú", "dbt"):
            self.assertIn(text, page)
        self.assertIn("- Cliente Itaú", cv.to_text(data))
        check = cv.skill_check(data)
        self.assertEqual(check["fora_das_experiencias"], ["Excel"])
        self.assertIn("Airflow", [entry["nome"] for entry in check["fora_do_perfil"]])
        self.assertIn("dbt", [entry["nome"] for entry in check["fora_do_perfil"]])

    def test_ai_item_drops_invented_numbers(self):
        with mock.patch("jobscout.llm.ask_llm", return_value=json.dumps({"texto": "Reduzi 30% do custo com Airflow", "motivo": "x"})):
            self.assertEqual(cv.ai_item("Fiz pipelines em Airflow", {"cargo": "Dados"})["texto"], "")
        with mock.patch("jobscout.llm.ask_llm", return_value=json.dumps({"texto": "Liderei o time usando Python", "motivo": "x"})):
            self.assertEqual(cv.ai_item("Liderei 3 pessoas", {"cargo": "Dados"})["texto"], "")  # ferramenta que o item não cita
        with mock.patch("jobscout.llm.ask_llm", return_value=json.dumps({"texto": "Construí pipelines em Airflow", "motivo": "verbo"})):
            self.assertEqual(cv.ai_item("Fiz pipelines em Airflow", {"cargo": "Dados"})["texto"], "Construí pipelines em Airflow")

    def test_resume_kind(self):
        versions = [{"name": "Data_Engineer_Acme", "label": "Data_Engineer_Acme", "pdf": "CV Ana - Data_Engineer_Acme.pdf", "job_id": 3},
                    {"name": "Dados", "label": "Dados", "pdf": "CV Ana - Dados.pdf", "job_id": None}]
        self.assertEqual(cv.custom_label({"title": "Data Engineer Sr", "company": "Acme Inc."}), "Data_Engineer_Sr_Acme_Inc")
        self.assertEqual(cv.resume_kind("CV Ana - Data_Engineer_Acme.pdf", versions), {"tipo": "Customizado", "nome": "Data_Engineer_Acme"})
        self.assertEqual(cv.resume_kind("Curriculo_modelo_x.pdf", versions), {"tipo": "Padrão", "nome": "Curriculo_modelo_x"})
        self.assertEqual(cv.resume_kind("CV Ana - Dados.pdf", versions), {"tipo": "Padrão", "nome": "Dados"})
        self.assertEqual(cv.resume_kind("", versions)["tipo"], "")

    def test_theme_and_avatar_validation(self):
        theme = appearance.clean_theme({"nome": "Azul", "claro": {"bg": "#fff", "accent": "rgb(1, 2, 3)"}})
        self.assertEqual(theme["claro"]["bg"], "#fff")
        with self.assertRaises(ValueError):
            appearance.clean_theme({"claro": {"bg": "red; } body { display: none"}})
        with self.assertRaises(ValueError):
            appearance.clean_theme({"claro": {"inventada": "#fff"}})
        with self.assertRaises(ValueError):
            appearance.clean_avatar({"think": "data:image/png;base64,AAAA"})
        with self.assertRaises(ValueError):
            appearance.clean_avatar({"idle": "data:text/html;base64,AAAA"})
        self.assertEqual(appearance.clean_avatar({"idle": "data:image/gif;base64,AAAA"}), {"idle": "data:image/gif;base64,AAAA"})


class FakeImap:
    instances = []

    def __init__(self, host):
        self.host, self.calls = host, []
        FakeImap.instances.append(self)

    def login(self, email, password):
        if password != "abcdefghijklmnop":
            raise imaplib.IMAP4.error("AUTHENTICATIONFAILED")

    def select(self, box, readonly=False):
        self.readonly = readonly

    def uid(self, command, *args):
        self.calls.append((command, args))
        if command == "SEARCH":
            return "OK", [b"7 9"]
        return "OK", [(b"9 (BODY[] {5}", b"Subject: Oi\r\n\r\ncorpo"), b")"]

    def logout(self):
        pass


class ImapTest(unittest.TestCase):
    def setUp(self):
        FakeImap.instances = []
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.prefs = Preferences(Path(self.folder.name) / "p.json")
        self.mail = imap_mail.ImapMail(self.prefs.load, self.prefs.save, connector=FakeImap)

    def test_app_password_login_read_only_and_cipher(self):
        with self.assertRaises(GmailError):
            self.mail.connect("ana@gmail.com", "errada")
        self.assertFalse(self.mail.connected())
        self.mail.connect("ana@gmail.com", "abcd efgh ijkl mnop")
        stored = self.prefs.load()
        self.assertEqual(stored["imap_servidor"], "imap.gmail.com")
        self.assertNotIn("abcdefghijklmnop", stored["imap_senha"])
        self.assertEqual(imap_mail.reveal(stored["imap_senha"]), "abcdefghijklmnop")
        found = self.mail.fetch_new(lambda key: key == "imap-9" and False, limit=1)
        client = FakeImap.instances[-1]
        self.assertTrue(client.readonly)
        self.assertEqual(client.calls[0][1][1], "X-GM-RAW")
        self.assertIn("newer_than:3d", client.calls[0][1][2])
        self.assertEqual(client.calls[1][1][1], "(BODY.PEEK[])")  # não marca como lido
        self.assertEqual(found[0][0], "imap-9")
        self.assertEqual(self.mail.fetch_new(lambda key: True), [])
        self.mail.disconnect()
        self.assertFalse(self.mail.connected())

    def test_other_servers_use_plain_criteria(self):
        self.assertEqual(imap_mail._criteria("newer_than:7d", False)[0], "SINCE")
        self.assertEqual(imap_mail.server_for("ana@yahoo.com.br"), "imap.mail.yahoo.com")


class ReminderUnitTest(unittest.TestCase):
    def test_calendar_link_and_ics_without_any_api(self):
        reminder = {"id": 7, "title": "Cobrar retorno: Dados, Acme", "next_at": "2026-11-06T09:00-03:00", "every_days": 7, "remaining": 3, "notes": ""}
        link = reminders.calendar_link(reminder)
        self.assertIn("action=TEMPLATE", link)
        self.assertIn("20261106T120000Z", link)
        self.assertIn("recur=RRULE", link)
        text = reminders.ics(reminder)
        self.assertIn("RRULE:FREQ=DAILY;INTERVAL=7;COUNT=3", text)
        self.assertIn("SUMMARY:Cobrar retorno: Dados\\, Acme", text)

    def test_clean_and_event(self):
        with self.assertRaises(ValueError):
            reminders.clean({"titulo": "x", "quando": "2026-11-01", "cada_dias": 200}, None)
        data = reminders.clean({"titulo": "Pedir feedback: {vaga}", "quando": "2026-11-01", "cada_dias": 0, "vezes": 5}, {"id": 1, "title": "Dados", "company": "Acme"})
        self.assertEqual((data["title"], data["remaining"]), ("Pedir feedback: Dados — Acme", 1))
        self.assertTrue(data["next_at"].startswith("2026-11-01T09:00"))
        event = reminders.calendar_event({**data, "job_title": "Dados", "job_company": "Acme"}, "http://127.0.0.1:8765/")
        self.assertNotIn("recurrence", event)
        self.assertEqual(event["start"]["timeZone"], "America/Sao_Paulo")


if __name__ == "__main__":
    unittest.main()
