import json
import os
import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from jobscout import cv, llm, replies, suggest
from jobscout.linkedin_public import PublicPageError
from jobscout.server import App, serve_in_background

TEXT = """Engenheira de Dados
RESUMO
Engenheira de dados com foco em pipelines e BI.
EXPERIÊNCIA
Engenheira de Dados | Stone
jan 2021 – atual
- Construí pipelines em Python e Airflow que reduziram o custo em 30%
- Modelei o data warehouse em BigQuery e SQL
Analista de Dados | Itaú
03/2018 - 12/2020
- Dashboards em Power BI e SQL para a diretoria
FORMAÇÃO
Bacharelado em Sistemas de Informação | USP
2012 - 2016
IDIOMAS
Inglês: Avançado
HABILIDADES
Python, SQL, Git
"""

JOB = {"title": "Senior Data Engineer", "company": "Jobgether", "description": "BigQuery, SQL and dbt. Data warehouse modeling for analytics."}


def offline(url):
    raise PublicPageError("sem rede nos testes")


class StructureTest(unittest.TestCase):
    def test_reads_the_text_into_sections(self):
        data = cv.from_text(TEXT, date(2026, 10, 1))
        self.assertEqual(data["titulo"], "Engenheira de Dados")
        self.assertIn("pipelines", data["resumo"])
        roles = [(role["cargo"], role["empresa"], role["inicio"], role["fim"], role["atual"]) for role in data["experiencias"]]
        self.assertEqual(roles, [("Engenheira de Dados", "Stone", "2021-01", "", True), ("Analista de Dados", "Itaú", "2018-03", "2020-12", False)])
        self.assertEqual(data["formacao"][0]["instituicao"], "USP")
        self.assertEqual(data["idiomas"], [{"idioma": "Inglês", "nivel": "Avançado"}])
        self.assertIn("Git", [skill["nome"] for skill in data["habilidades"]])

    def test_text_round_trip_keeps_years_per_skill(self):
        data = cv.from_text(TEXT, date(2026, 10, 1))
        text = cv.to_text(data)
        self.assertEqual(suggest.experience(text, "SQL", date(2026, 10, 1))["meses"], 104)
        self.assertEqual(cv.from_text(text, date(2026, 10, 1))["experiencias"][0]["empresa"], "Stone")

    def test_clean_limits_and_drops_junk(self):
        data = cv.clean({"titulo": "x" * 500, "experiencias": [{"cargo": "", "empresa": "", "itens": []}, {"cargo": "Dev", "inicio": "2020-13"}],
                         "habilidades": ["SQL", {"nome": "sql"}, {"nome": "Python", "principal": True}]})
        self.assertEqual(len(data["titulo"]), 120)
        self.assertEqual(len(data["experiencias"]), 1)
        self.assertEqual(data["experiencias"][0]["inicio"], "")
        self.assertEqual([skill["nome"] for skill in data["habilidades"]], ["SQL", "Python"])

    def test_tailor_puts_what_matches_first_without_deleting(self):
        data = cv.from_text(TEXT, date(2026, 10, 1))
        version = cv.tailor(data, JOB)
        self.assertEqual(version["habilidades"][0]["vaga"], True)
        self.assertEqual(version["experiencias"][0]["itens"][0], "Modelei o data warehouse em BigQuery e SQL")
        self.assertEqual(version["alvo"]["faltam"], ["dbt"])
        self.assertEqual(len(version["experiencias"][0]["itens"]), 2)
        self.assertEqual(len(data["experiencias"][0]["itens"]), 2)  # o completo não muda

    def test_html_hides_what_the_version_hides_and_uses_job_language(self):
        data = cv.from_text(TEXT, date(2026, 10, 1))
        version = cv.tailor(data, JOB)
        version["experiencias"][1]["mostrar_itens"] = [False]
        page = cv.render_html(version, {"nome": "Ana <Souza>", "cidade": "São Paulo", "pais": "Brasil"}, "en")
        self.assertIn("Ana &lt;Souza&gt;", page)
        self.assertIn("Experience", page)
        self.assertIn("São Paulo, Brazil", page)
        self.assertNotIn("Dashboards em Power BI", page)
        english = {"title": "Data Engineer", "description": "We are looking for a data engineer to build and maintain our pipelines and work with the analytics team on reporting and data quality for the business. You will design models and improve them."}
        self.assertEqual(cv.language_for(english), "en")


class RepliesTest(unittest.TestCase):
    PROFILE = {"nome": "Ana Souza", "telefone": "+55 11 99999-0000", "pretensao_salarial": "R$ 15.000"}

    def draft(self, key, channel, lang, job, recruiter):
        intent = next(item for item in replies.library() if item["chave"] == key)
        return replies.template(intent, channel, lang, replies.values_for(lang, self.PROFILE, job, recruiter, ""))

    def test_short_channels_and_formal_email(self):
        whatsapp = self.draft("interesse", "whatsapp", "pt", {"title": "Dados", "company": "Acme"}, "Carla Mendes")
        self.assertEqual(whatsapp["assunto"], "")
        self.assertTrue(whatsapp["texto"].startswith("Olá Carla, tudo bem?\n\nObrigado pelo contato! Tenho interesse"))
        email = self.draft("salario", "email", "pt", {"title": "Dados", "company": "Acme"}, "Carla")
        self.assertEqual(email["assunto"], "Re: Dados — Acme")
        self.assertTrue(email["texto"].startswith("Olá Carla,\n\n"))
        self.assertIn("R$ 15.000", email["texto"])
        self.assertTrue(email["texto"].endswith("Atenciosamente,\nAna Souza\n+55 11 99999-0000"))
        english = self.draft("sem_interesse", "linkedin", "en", None, "John")
        self.assertIn("not interested", english["texto"])
        self.assertTrue(english["texto"].startswith("Hi John, how are you?"))

    def test_follow_up_praises_the_company_and_uses_the_application_date(self):
        job = {"title": "Dados", "company": "Acme", "applied_at": "2026-10-12T10:00:00-03:00"}
        text = self.draft("cobrar_retorno", "linkedin", "pt", job, "Carla")["texto"]
        self.assertIn("novidades sobre o processo da vaga de Dados na Acme, para a qual me candidatei em 12/10", text)
        self.assertIn("Gostei muito do que conheci da empresa", text)
        bare = self.draft("cobrar_retorno", "whatsapp", "pt", None, "")["texto"]
        self.assertTrue(bare.startswith("Olá, tudo bem?\n\nPassando para saber se há novidades sobre o processo."))
        email = self.draft("cobrar_retorno", "email", "pt", job, "Carla")["texto"]
        self.assertEqual(email.count("Olá"), 1)  # a saudação do corpo não repete a do e-mail

    def test_optional_segments_and_library_overrides(self):
        self.assertEqual(replies.fill("Oi[, {a}]! [Vaga {b}.]", {"a": "Ana", "b": ""}), "Oi, Ana!")
        library = replies.library({"interesse": {"pt": "Topo!", "ativo": False}, "meu_modelo": {"nome": "Meu modelo", "pt": "Oi {extra}"}})
        by_key = {item["chave"]: item for item in library}
        self.assertEqual((by_key["interesse"]["pt"], by_key["interesse"]["ativo"], by_key["interesse"]["editado"]), ("Topo!", False, True))
        self.assertIn("Gostei muito", by_key["cobrar_retorno"]["pt"])
        self.assertFalse(by_key["meu_modelo"]["padrao"])
        self.assertEqual(replies.custom_key("Meu modelo", {"meu_modelo"}), "meu_modelo_2")

    def test_conversation_sets_recruiter_language_and_job(self):
        turns = [{"autor": "John Smith", "texto": "Hi Ana! Are you open to a Data Engineer role at Acme?", "minha": False},
                 {"autor": "Ana", "texto": "Hi John!", "minha": True}]
        with mock.patch.dict(os.environ, {"JOBSCOUT_LLM_PADRAO": "off", "JOBSCOUT_LLM_MENSAGEM": ""}):
            llm.configure("")
            result = replies.write({"intencao": "mais_info", "canal": "linkedin", "conversa": turns}, self.PROFILE, "", {"title": "Data Engineer", "company": "Acme"})
        self.assertEqual((result["idioma"], result["recrutador"]), ("en", "John"))
        self.assertIn("tech stack", result["texto"])
        self.assertIn("Eu: Hi John!", replies.transcript(replies.conversation(turns), "John"))
        jobs = [{"company": "Acme", "status": "candidatado", "applied_at": "2026-10-01"}, {"company": "Nubank", "status": "candidatado"}]
        self.assertEqual(replies.match_job(["role at Acme"], jobs)["company"], "Acme")
        self.assertIsNone(replies.match_job(["nada a ver"], jobs))

    def test_short_channels_drop_formal_signature(self):
        self.assertEqual(replies.short_message("Olá Carla,\n\nTenho interesse.\n\nAtenciosamente,\nAna Souza"), "Olá Carla,\n\nTenho interesse.")
        self.assertEqual(replies.short_message("Oi! Tenho interesse."), "Oi! Tenho interesse.")

    def test_write_without_model_uses_template_and_validates(self):
        with mock.patch.dict(os.environ, {"JOBSCOUT_LLM_PADRAO": "off", "JOBSCOUT_LLM_MENSAGEM": ""}):
            llm.configure("")
            result = replies.write({"intencao": "agendar", "canal": "whatsapp", "mensagem": "Hi Ana, are you open to a chat?"}, self.PROFILE, "", None)
            self.assertEqual((result["origem"], result["idioma"]), ("modelo", "en"))
            with self.assertRaises(ValueError):
                replies.write({"intencao": "outro", "canal": "whatsapp"}, self.PROFILE, "", None)

    def test_write_with_model(self):
        self.addCleanup(llm.configure, "")
        with mock.patch.dict(os.environ, {"JOBSCOUT_LLM_MENSAGEM": "", "JOBSCOUT_LLM_PADRAO": "off"}):
            llm.configure("ollama:gemma3:4b")
            with mock.patch("jobscout.llm.ask_llm", return_value=json.dumps({"assunto": "Re: vaga", "texto": "Olá! Tenho interesse."})) as ask:
                result = replies.write({"intencao": "interesse", "canal": "email", "mensagem": "Olá Ana"}, self.PROFILE, "perfil", {"title": "Dados", "company": "Acme"})
        self.assertEqual((result["origem"], result["texto"], result["assunto"]), ("ia", "Olá! Tenho interesse.", "Re: vaga"))
        self.assertIn("Tenho interesse", ask.call_args.args[1])
        self.assertIn("E-MAILS A RECRUTADORES", ask.call_args.kwargs["system"])  # e-mail usa o estilo de e-mail
        self.assertIn("como se fosse eu, Ana,", ask.call_args.kwargs["system"])


    def test_opening_follows_the_conversation(self):
        intent = next(item for item in replies.library() if item["chave"] == "interesse")
        values = replies.values_for("pt", self.PROFILE, None, "Carla Mendes", "")
        def draft(turns):
            return replies.template(intent, "whatsapp", "pt", values, replies.history(replies.conversation(turns)))["texto"]
        # Primeira mensagem do dia: cumprimenta; se perguntaram como estou, responde.
        self.assertTrue(draft([{"autor": "Carla", "texto": "Tenho uma vaga para você.", "minha": False, "dia": "antes"}]).startswith("Olá Carla, tudo bem?\n\n"))
        self.assertTrue(draft([{"autor": "Carla", "texto": "Oi Ana, tudo bem? Tenho uma vaga.", "minha": False, "dia": "hoje"}]).startswith("Olá Carla, tudo bem e contigo?\n\n"))
        # Já conversamos hoje: sem cumprimento e sem repetir o agradecimento.
        today = [{"autor": "Carla", "texto": "Oi Ana!", "minha": False, "dia": "hoje"},
                 {"autor": "", "texto": "Olá Carla, tudo bem? Obrigado pelo contato.", "minha": True, "dia": "hoje"},
                 {"autor": "Carla", "texto": "A vaga é remota.", "minha": False, "dia": "hoje"}]
        self.assertTrue(draft(today).startswith("Tenho interesse em conhecer melhor a oportunidade."))
        # Sem datas na página: se eu já cumprimentei há pouco, não repete.
        undated = [{**turn, "dia": ""} for turn in today]
        self.assertFalse(draft(undated).startswith("Olá"))
        facts = replies.history(replies.conversation(today))
        self.assertEqual((facts["hoje"], facts["agradeci"], facts["perguntou"]), (True, True, False))
        self.assertIn("Abertura: sem cumprimento", replies.facts_text(facts, "", "whatsapp"))

    def test_model_greeting_is_replaced_by_the_decided_opening(self):
        self.addCleanup(llm.configure, "")
        turns = [{"autor": "Carla", "texto": "Oi! Podemos marcar?", "minha": False, "dia": "hoje"},
                 {"autor": "", "texto": "Olá Carla, tudo bem? Podemos sim.", "minha": True, "dia": "hoje"},
                 {"autor": "Carla", "texto": "Pode ser amanhã às 10h?", "minha": False, "dia": "hoje"}]
        with mock.patch.dict(os.environ, {"JOBSCOUT_LLM_MENSAGEM": "", "JOBSCOUT_LLM_PADRAO": "off"}):
            llm.configure("ollama:gemma3:4b")
            answer = json.dumps({"assunto": "", "texto": "Olá Carla, tudo bem? Amanhã às 10h funciona para mim."})
            with mock.patch("jobscout.llm.ask_llm", return_value=answer):
                result = replies.write({"intencao": "agendar", "canal": "whatsapp", "conversa": turns}, self.PROFILE, "", None, style="Escreva como {nome}.")
        self.assertEqual(result["texto"], "Amanhã às 10h funciona para mim.")
        self.assertEqual(replies.style_text("Escreva como {nome}.", self.PROFILE), "Escreva como Ana.")
        # Número que não está em lugar nenhum (salário inventado) derruba a resposta da IA.
        with mock.patch.dict(os.environ, {"JOBSCOUT_LLM_MENSAGEM": "", "JOBSCOUT_LLM_PADRAO": "off"}):
            llm.configure("ollama:gemma3:4b")
            invented = json.dumps({"texto": "Minha pretensão é 12.000 a 18.000."})
            with mock.patch("jobscout.llm.ask_llm", return_value=invented):
                result = replies.write({"intencao": "salario", "canal": "whatsapp", "mensagem": "Qual sua pretensão?"}, {"nome": "Ana"}, "", None)
        self.assertEqual(result["origem"], "modelo")
        self.assertIn("12.000", result["aviso"])
        self.assertEqual(replies.first_name("+55 31 9748-7304"), "")

class TaskModelsTest(unittest.TestCase):
    def tearDown(self):
        llm.configure("")

    def test_per_task_choice_and_privacy(self):
        with mock.patch.dict(os.environ, {"JOBSCOUT_LLM_PADRAO": "off", "JOBSCOUT_LLM_CURRICULO": "", "JOBSCOUT_LLM_MENSAGEM": "", "JOBSCOUT_LLM_NUVEM_PRIVADO": ""}):
            llm.configure("ollama:gemma3:4b", {"curriculo": "ollama:qwen2.5:7b", "mensagem": "gemini:gemini-flash-latest"}, "chave")
            self.assertEqual(llm.model_name("curriculo"), "ollama:qwen2.5:7b")
            self.assertEqual(llm.model_name("responder"), "ollama:gemma3:4b")
            self.assertEqual(llm.model_name("mensagem"), "")  # privada: nuvem bloqueada
            llm.configure("ollama:gemma3:4b", {"responder": "off"})
            self.assertEqual(llm.model_name("responder"), "")
            rows = {row["tarefa"]: row for row in llm.tasks()}
            self.assertTrue(rows["mensagem"]["privada"])


class ServerTest(unittest.TestCase):
    def setUp(self):
        env = mock.patch.dict(os.environ, {"JOBSCOUT_LLM_PADRAO": "off", "JOBSCOUT_LLM_RESPONDER": "", "JOBSCOUT_LLM_CURRICULO": "", "JOBSCOUT_GMAIL_CLIENT_ID": ""})
        env.start()
        self.addCleanup(env.stop)
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.app = App(Path(self.folder.name), background=False)
        self.app.assistant.public_job = offline
        self.app.assistant.public_company = offline
        self.app.preferences.save({"pasta": str(Path(self.folder.name) / "Pasta")})
        self.addCleanup(llm.configure, "")
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

    def test_full_resume_versions_and_preview(self):
        self.call("PUT", "/api/perfil", {"nome": "Ana Souza", "curriculo": TEXT})
        first = self.call("GET", "/api/curriculo/completo")
        self.assertIsNone(first["cv"])
        self.assertEqual(first["sugerido"]["experiencias"][0]["empresa"], "Stone")
        saved = self.call("PUT", "/api/curriculo/completo", {"cv": first["sugerido"]})
        self.assertEqual(saved["cv"]["experiencias"][0]["empresa"], "Stone")
        self.assertIn("01/2021 - atual", saved["texto"])
        job = self.call("POST", "/api/vagas", {"url": "https://example.com/vaga/9", "title": JOB["title"], "company": JOB["company"], "description": JOB["description"], "status": "candidatado"})
        version = self.call("POST", "/api/curriculo/versoes", {"vaga_id": job["id"], "ia": True})
        self.assertIn("IA indisponível", version["aviso"])
        self.assertEqual(version["data"]["alvo"]["faltam"], ["dbt"])
        version["data"]["experiencias"][0]["mostrar_itens"] = [True, False]
        edited = self.call("PUT", f"/api/curriculo/versoes/{version['id']}", {"dados": version["data"], "nome": "CV Jobgether", "idioma": "en"})
        self.assertEqual((edited["name"], edited["lang"], edited["data"]["experiencias"][0]["mostrar_itens"]), ("CV Jobgether", "en", [True, False]))
        page = self.call("GET", f"/api/curriculo/previa?versao={version['id']}")
        self.assertIn("Experience", page)
        self.assertEqual(len(self.call("GET", "/api/curriculo/completo")["versoes"]), 1)
        self.call("POST", f"/api/curriculo/versoes/{version['id']}/remover", {})
        self.assertEqual(self.call("GET", "/api/curriculo/completo")["versoes"], [])

    def test_pdf_goes_to_the_folder(self):
        self.call("PUT", "/api/perfil", {"nome": "Ana Souza", "curriculo": TEXT})
        with mock.patch("jobscout.cv.to_pdf", side_effect=lambda page, target: target) as to_pdf:
            result = self.call("POST", "/api/curriculo/pdf", {})
        self.assertEqual(result["nome"], "CV Ana Souza.pdf")
        self.assertIn("Currículos", result["arquivo"])
        self.assertIn("Ana Souza", to_pdf.call_args.args[0])

    def test_recruiters_link_to_many_jobs_and_drive_the_chat(self):
        ext = {"Origin": "chrome-extension://abc"}
        a = self.call("POST", "/api/vagas", {"url": "https://example.com/vaga/a", "title": "Dados Pleno", "company": "Acme", "status": "candidatado"})
        b = self.call("POST", "/api/vagas", {"url": "https://example.com/vaga/b", "title": "Dados Sênior", "company": "Acme", "status": "candidatado"})
        carla = self.call("POST", "/api/recrutadores", {"nome": "Carla Mendes", "linkedin": "https://www.linkedin.com/in/carla-m/", "vaga_id": a["id"]})
        self.call("POST", f"/api/vagas/{b['id']}/recrutadores", {"contato_id": carla["id"]})
        listed = {row["name"]: row for row in self.call("GET", "/api/recrutadores")}
        self.assertEqual(sorted(job["title"] for job in listed["Carla Mendes"]["vagas"]), ["Dados Pleno", "Dados Sênior"])
        self.assertEqual(listed["Carla Mendes"]["company"], "Acme")
        self.assertEqual([row["name"] for row in self.call("GET", f"/api/vagas/{a['id']}")["recrutadores"]], ["Carla Mendes"])
        context = self.call("POST", "/api/extensao/chat", {"nome": "carla mendes"}, headers=ext)
        self.assertEqual(context["recrutador"]["id"], carla["id"])
        self.assertEqual(len(context["recrutador"]["vagas"]), 2)
        self.assertTrue(any(intent["chave"] == "cobrar_retorno" for intent in context["intencoes"]))
        reply = self.call("POST", "/api/mensagens/responder", {"intencao": "cobrar_retorno", "canal": "linkedin", "contato_id": carla["id"],
                                                             "conversa": [{"autor": "Carla Mendes", "texto": "Oi Ana, tudo bem?", "minha": False}]}, headers=ext)
        self.assertIn("Acme", reply["texto"])
        self.assertEqual(reply["recrutador"], "Carla")
        linked = self.call("POST", "/api/extensao/chat/vincular", {"nome": "João Lima", "vaga_id": a["id"]}, headers=ext)
        self.assertEqual([job["titulo"] for job in linked["vagas"]], ["Dados Pleno"])
        self.call("POST", f"/api/vagas/{a['id']}/recrutadores/{carla['id']}/remover", {})
        self.assertEqual([row["name"] for row in self.call("GET", f"/api/vagas/{a['id']}")["recrutadores"]], ["João Lima"])
        with self.assertRaises(HTTPError) as caught:
            self.call("POST", "/api/recrutadores", {"email": "sem-arroba"})
        self.assertEqual(caught.exception.code, 422)

    def test_message_models_can_be_edited_created_and_restored(self):
        edited = self.call("PUT", "/api/mensagens/modelos/cobrar_retorno", {"pt": "Oi[, {recrutador}]! Novidades?", "ativo": True})
        self.assertTrue(edited["editado"])
        reply = self.call("POST", "/api/mensagens/responder", {"intencao": "cobrar_retorno", "canal": "whatsapp", "recrutador": "Carla"})
        self.assertEqual(reply["texto"], "Olá Carla, tudo bem?\n\nNovidades?")
        created = self.call("POST", "/api/mensagens/modelos", {"nome": "Confirmar horário", "instrucao": "Confirme o horário.", "pt": "Confirmado[, {recrutador}]!"})
        self.assertEqual(created["chave"], "confirmar_horario")
        self.call("POST", "/api/mensagens/modelos/cobrar_retorno/restaurar", {})
        models = {item["chave"]: item for item in self.call("GET", "/api/mensagens/modelos")}
        self.assertIn("Gostei muito", models["cobrar_retorno"]["pt"])
        self.call("POST", "/api/mensagens/modelos/confirmar_horario/restaurar", {})
        self.assertNotIn("confirmar_horario", {item["chave"] for item in self.call("GET", "/api/mensagens/modelos")})

    def test_message_style_can_be_edited_and_restored(self):
        style = self.call("GET", "/api/mensagens/estilo")
        self.assertTrue(style["padrao"])
        self.assertIn("CENÁRIO 1", style["texto"])
        edited = self.call("PUT", "/api/mensagens/estilo", {"texto": "Escreva curto, como {nome}."})
        self.assertEqual((edited["padrao"], edited["texto"]), (False, "Escreva curto, como {nome}."))
        with self.assertRaises(HTTPError) as caught:
            self.call("PUT", "/api/mensagens/estilo", {"texto": "x"}, headers={"Origin": "chrome-extension://abc"})
        self.assertEqual(caught.exception.code, 403)
        self.assertTrue(self.call("POST", "/api/mensagens/estilo/restaurar", {})["padrao"])

    def test_reply_and_task_models(self):
        result = self.call("POST", "/api/mensagens/responder", {"intencao": "mais_info", "canal": "linkedin", "recrutador": "Carla"})
        self.assertIn("Carla", result["texto"])
        self.call("PUT", "/api/preferencias", {"ia": "ollama:gemma3:4b", "ia_tarefas": {"curriculo": "off"}, "gemini_chave": "segredo"})
        state = self.call("GET", "/api/estado")
        self.assertIs(state["preferencias"]["gemini_chave"], True)  # a chave não volta para o painel
        rows = {row["tarefa"]: row for row in self.call("GET", "/api/ia")["tarefas"]}
        self.assertEqual(rows["curriculo"]["em_uso"], "")
        self.assertEqual(rows["responder"]["em_uso"], "ollama:gemma3:4b")
        with self.assertRaises(HTTPError) as caught:
            self.call("PUT", "/api/preferencias", {"ia_tarefas": {"inventada": "off"}})
        self.assertEqual(caught.exception.code, 422)
        with self.assertRaises(HTTPError) as caught:
            self.call("POST", "/api/ia/baixar", {"modelo": "rm -rf"})
        self.assertEqual(caught.exception.code, 422)


if __name__ == "__main__":
    unittest.main()
