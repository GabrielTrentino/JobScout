import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from jobscout import insights
from jobscout.assistant import Assistant
from jobscout.events import Hub
from jobscout.linkedin_public import PublicPageError
from jobscout.profile import Profile
from jobscout.store import Store

URL = "https://www.linkedin.com/jobs/view/4476952226/"
PUBLIC = {
    "title": "Data Engineer III",
    "company": "Stone",
    "location": "Brasil",
    "description": "Python, SQL e Airflow. Trabalho remoto. Inglês avançado. Salário: R$ 15.000 a R$ 18.000 por mês. CLT.",
    "seniority": "Não aplicável",
    "employment_type": "Tempo integral",
    "industry": "Serviços de TI",
    "company_url": "https://www.linkedin.com/company/stone-co/",
}
COMPANY = {"industry": "Serviços de TI", "size": "5.001-10.000 funcionários", "headquarters": "São Paulo, SP"}


class InsightsTest(unittest.TestCase):
    def test_rules(self) -> None:
        job = insights.enrich(PUBLIC)
        self.assertEqual(job["seniority"], "Sênior")
        self.assertEqual(job["work_mode"], "Remoto")
        self.assertEqual(job["english"], "obrigatório")
        self.assertEqual(job["salary"], "R$ 15.000 a R$ 18.000 por mês")
        self.assertEqual(job["region"], "Brasil")
        self.assertEqual(job["skills"], "Python, SQL, Airflow")

    def test_english_and_region_variants(self) -> None:
        self.assertEqual(insights.english("", "English is a plus, nice to have."), "diferencial")
        text = "We are looking for a data engineer with experience in Python and SQL. You will work with our team " * 3
        self.assertEqual(insights.english("", text), "vaga em inglês")
        self.assertEqual(insights.region("", "Payment in USD as contractor"), "internacional")
        self.assertEqual(insights.region("", "Remote for LATAM candidates"), "LATAM")
        self.assertEqual(insights.work_mode("Engenheiro (Híbrido)", "São Paulo", "remoto às sextas"), "Híbrido")

    def test_seniority_from_site_when_title_is_silent(self) -> None:
        self.assertEqual(insights.seniority("Data Engineer", "Pleno-sênior"), "Pleno-sênior")
        self.assertEqual(insights.seniority("Data Engineer", "Não aplicável"), "")

    def test_fit(self) -> None:
        self.assertEqual(insights.fit("Python, SQL, Airflow", ["python", "Airflow"]), {"tem": ["Python", "Airflow"], "falta": ["SQL"]})


class CompanyFlowTest(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = TemporaryDirectory()
        root = Path(self.folder.name)
        self.store = Store(root / "test.db")
        self.hub = Hub()
        self.company_calls = []
        self.assistant = Assistant(
            self.store, self.hub, Profile(root / "profile.json"), background=False,
            public_job=lambda url: dict(PUBLIC), public_company=self.fake_company,
        )
        env = mock.patch.dict(os.environ, {"JOBSCOUT_LLM_PADRAO": "off"})
        env.start()
        self.addCleanup(env.stop)

    def tearDown(self) -> None:
        self.store.close()
        self.folder.cleanup()

    def fake_company(self, url):
        self.company_calls.append(url)
        return dict(COMPANY)

    def approve_job(self, **event):
        drafts = self.assistant.intake({"tipo": "job_viewed", "site": "linkedin", "vaga": {"url": URL}, **event})
        self.assistant.approve(drafts[0]["id"])
        return self.store.job_by_url(URL)

    def test_draft_carries_extracted_fields(self) -> None:
        draft = self.assistant.intake({"tipo": "job_viewed", "site": "linkedin", "vaga": {"url": URL}})[0]
        payload = draft["payload"]
        self.assertEqual(payload["seniority"], "Sênior")
        self.assertEqual(payload["english"], "obrigatório")
        self.assertIn("Airflow", payload["skills"])

    def test_approving_job_registers_company_with_public_data(self) -> None:
        job = self.approve_job()
        self.assertEqual(job["seniority"], "Sênior")
        companies = self.assistant.companies()
        self.assertEqual(len(companies), 1)
        self.assertEqual(companies[0]["name"], "Stone")
        self.assertEqual(companies[0]["size"], "5.001-10.000 funcionários")
        self.assertEqual(companies[0]["vagas"], 1)
        self.assertEqual(self.company_calls, ["https://www.linkedin.com/company/stone-co/"])
        detail = self.assistant.company_detail(companies[0]["id"])
        self.assertEqual(detail["vagas"][0]["url"], URL)
        self.assertTrue(any(move["kind"] == "empresa_cadastrada" for move in detail["movimentos"]))

    def test_company_page_unavailable_keeps_company(self) -> None:
        def offline(url):
            raise PublicPageError("pediu login")

        self.assistant.public_company = offline
        self.approve_job()
        company = self.assistant.companies()[0]
        self.assertEqual(company["name"], "Stone")
        self.assertIsNone(company["fetched_at"])
        with self.assertRaises(PublicPageError):
            self.assistant.refresh_company(company["id"])

    def test_form_answers_saved_on_approval_and_reused(self) -> None:
        answers = [{"rotulo": "Quantos anos de experiência com Python?", "valor": "5"}, {"rotulo": "Vazio", "valor": ""}]
        drafts = self.assistant.intake({
            "tipo": "application_submitted", "site": "linkedin", "vaga": {"url": URL}, "respostas": answers,
        })
        self.assertEqual(drafts[0]["payload"]["respostas"], answers[:1])
        self.assistant.approve(drafts[0]["id"])
        job = self.store.job_by_url(URL)
        saved = self.store.answers(job["id"])
        self.assertEqual([(a["question"], a["answer"], a["origin"]) for a in saved], [("Quantos anos de experiência com Python?", "5", "formulario")])
        self.assertEqual(self.assistant.answer_history()[0]["valor"], "5")

    def test_user_can_skip_saving_form_answers(self) -> None:
        drafts = self.assistant.intake({
            "tipo": "application_submitted", "site": "linkedin", "vaga": {"url": URL},
            "respostas": [{"rotulo": "Pretensão", "valor": "10000"}],
        })
        self.assistant.approve(drafts[0]["id"], {"guardar_respostas": False})
        self.assertEqual(self.store.answers(self.store.job_by_url(URL)["id"]), [])

    def test_cold_job_becomes_draft_once(self) -> None:
        job = self.approve_job()
        self.assistant.set_status(job["id"], "candidatado")
        self.assertEqual(self.assistant.check_cold(14), [])
        self.store._run("UPDATE movements SET at = '2026-01-01T10:00:00-03:00'")
        self.store._run("UPDATE applications SET updated_at = '2026-01-01T10:00:00-03:00'")
        drafts = self.assistant.check_cold(14)
        self.assertEqual(len(drafts), 1)
        self.assertEqual(drafts[0]["payload"]["para"], "fria")
        self.assertEqual(self.assistant.check_cold(14), [])
        self.assistant.discard(drafts[0]["id"])
        self.assertEqual(self.assistant.check_cold(14), [])

    def test_approving_cold_draft_moves_job(self) -> None:
        job = self.approve_job()
        self.assistant.set_status(job["id"], "entrevista")
        self.store._run("UPDATE movements SET at = '2026-01-01T10:00:00-03:00'")
        draft = self.assistant.check_cold(7)[0]
        self.assistant.approve(draft["id"])
        self.assertEqual(self.store.job(job["id"])["status"], "fria")

    def test_add_by_link_only(self) -> None:
        job = self.assistant.add_job({"url": URL, "status": "candidatado"})
        self.assertEqual((job["title"], job["company"], job["status"]), ("Data Engineer III", "Stone", "candidatado"))
        self.assertEqual(self.assistant.companies()[0]["candidaturas"], 1)


if __name__ == "__main__":
    unittest.main()
