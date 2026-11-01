import json
import os
import unittest
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest import mock

from jobscout.assistant import Assistant, DraftError, normalize_url
from jobscout.events import Hub
from jobscout.linkedin_public import PublicPageError
from jobscout.profile import Profile
from jobscout.store import Store

VAGA = {
    "url": "https://www.linkedin.com/jobs/view/4012345678/?refId=abc&trk=x",
    "title": "Backend Python",
    "company": "Acme",
    "location": "São Paulo",
    "description": "APIs com Python e Docker.",
}
CANONICAL = "https://www.linkedin.com/jobs/view/4012345678/"



def offline(url):
    raise PublicPageError("sem rede nos testes")


class AssistantTest(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = TemporaryDirectory()
        root = Path(self.folder.name)
        self.store = Store(root / "test.db")
        self.hub = Hub()
        self.events = self.hub.subscribe()
        self.assistant = Assistant(self.store, self.hub, Profile(root / "profile.json"), background=False,
                                   public_job=offline, public_company=offline)
        env = mock.patch.dict(os.environ, {"JOBSCOUT_LLM_PADRAO": "off"})
        env.start()
        self.addCleanup(env.stop)

    def tearDown(self) -> None:
        self.store.close()
        self.folder.cleanup()

    def view(self, **changes):
        return self.assistant.intake({"tipo": "job_viewed", "site": "linkedin", "vaga": {**VAGA, **changes}})

    def test_viewing_a_job_creates_a_draft_and_nothing_else(self) -> None:
        drafts = self.view()
        self.assertEqual(len(drafts), 1)
        self.assertEqual(drafts[0]["kind"], "vaga")
        self.assertEqual(drafts[0]["payload"]["url"], CANONICAL)
        self.assertEqual(self.store.jobs(), [])
        kinds = [json.loads(self.events.get_nowait())["tipo"] for _ in range(self.events.qsize())]
        self.assertIn("rascunhos", kinds)
        texts = [item["texto"] for item in self.hub.recent()]
        self.assertTrue(texts[0].startswith("Novo rascunho"))
        self.assertTrue(texts[1].startswith("LinkedIn: lendo a vaga"))

    def test_activity_explains_why_nothing_happened(self) -> None:
        self.assistant.discard(self.view()[0]["id"])
        self.view()
        self.assertIn("descartou", self.hub.recent()[0]["texto"])
        self.assistant.approve(self.view(url="https://www.linkedin.com/jobs/view/5/")[0]["id"])
        self.view(url="https://www.linkedin.com/jobs/view/5/")
        self.assertIn("já está salva e nada mudou", self.hub.recent()[0]["texto"])

    def test_viewing_again_does_not_duplicate_the_draft(self) -> None:
        self.view()
        self.assertEqual(self.view(), [])
        self.assertEqual(self.store.pending_count(), 1)

    def test_approval_saves_job_and_logs_movement(self) -> None:
        draft = self.view()[0]
        self.assistant.approve(draft["id"])
        job = self.store.job_by_url(CANONICAL)
        self.assertEqual(job["title"], "Backend Python")
        self.assertEqual(job["status"], "visualizada")
        kinds = [move["kind"] for move in self.store.movements()]
        self.assertIn("vaga_criada", kinds)
        self.assertIn("rascunho_aprovado", kinds)

    def test_user_edit_wins_over_new_capture(self) -> None:
        draft = self.view()[0]
        self.assistant.edit(draft["id"], {"title": "Pessoa Backend"})
        self.view(title="Backend Python II", location="Remoto")
        payload = self.store.draft(draft["id"])["payload"]
        self.assertEqual(payload["title"], "Pessoa Backend")
        self.assertEqual(payload["location"], "São Paulo")

    def test_discarded_job_is_not_proposed_again_by_viewing(self) -> None:
        draft = self.view()[0]
        self.assistant.discard(draft["id"])
        self.assertEqual(self.view(), [])
        self.assertEqual(self.store.jobs(), [])

    def test_submit_before_approval_marks_the_pending_draft(self) -> None:
        draft = self.view()[0]
        self.assistant.intake({"tipo": "application_submitted", "site": "linkedin", "vaga": VAGA, "quando": "2026-10-27T10:00:00"})
        self.assertEqual(self.store.pending_count(), 1)
        self.assistant.approve(draft["id"])
        job = self.store.job_by_url(CANONICAL)
        self.assertEqual(job["status"], "candidatado")
        self.assertEqual(job["applied_at"], "2026-10-27T10:00:00")

    def test_submit_after_approval_proposes_status_change(self) -> None:
        self.assistant.approve(self.view()[0]["id"])
        drafts = self.assistant.intake({"tipo": "application_submitted", "site": "linkedin", "vaga": VAGA})
        self.assertEqual(drafts[0]["kind"], "status")
        self.assertEqual(self.store.job_by_url(CANONICAL)["status"], "visualizada")
        self.assistant.approve(drafts[0]["id"])
        self.assertEqual(self.store.job_by_url(CANONICAL)["status"], "candidatado")

    def test_changed_job_page_proposes_only_the_changed_fields(self) -> None:
        self.assistant.approve(self.view()[0]["id"])
        drafts = self.view(title="Backend Python Sênior")
        self.assertEqual(drafts[0]["kind"], "vaga_alteracao")
        self.assertEqual(list(drafts[0]["payload"]["mudancas"]), ["title"])
        self.assistant.approve(drafts[0]["id"], {"mudancas": {"title": {"para": "Backend Sênior"}}})
        self.assertEqual(self.store.job_by_url(CANONICAL)["title"], "Backend Sênior")

    def test_answer_needs_job_approval_then_is_saved_and_queued_for_insertion(self) -> None:
        drafts = self.assistant.intake({
            "tipo": "form_detected",
            "site": "linkedin",
            "pagina": "https://www.linkedin.com/jobs/view/4012345678/",
            "vaga": VAGA,
            "perguntas": [{"rotulo": "Qual sua pretensão salarial?", "campo": "js-3"}],
        })
        answer = next(draft for draft in drafts if draft["kind"] == "resposta")
        with self.assertRaises(DraftError):
            self.assistant.approve(answer["id"], {"resposta": "R$ 12 mil"})
        job_draft = self.store.pending_draft("vaga:" + CANONICAL)
        self.assistant.approve(job_draft["id"])
        self.assistant.approve(answer["id"])
        job = self.store.job_by_url(CANONICAL)
        saved = self.store.answers(job["id"])
        self.assertEqual(saved[0]["answer"], "R$ 12 mil")
        insertion = self.store.pending_insertions("https://www.linkedin.com/jobs/view/4012345678/")
        self.assertEqual(insertion[0]["field"], "js-3")
        self.assertEqual(insertion[0]["text"], "R$ 12 mil")

    def test_empty_answer_cannot_be_approved(self) -> None:
        self.assistant.approve(self.view()[0]["id"])
        drafts = self.assistant.intake({
            "tipo": "form_detected", "site": "linkedin", "vaga": VAGA,
            "perguntas": [{"rotulo": "Por que você quer trabalhar na Acme?", "campo": "js-1"}],
        })
        with self.assertRaises(DraftError):
            self.assistant.approve(drafts[0]["id"])

    def test_similar_question_reuses_an_approved_answer(self) -> None:
        self.assistant.approve(self.view()[0]["id"])
        first = self.assistant.intake({
            "tipo": "form_detected", "site": "linkedin", "vaga": VAGA,
            "perguntas": [{"rotulo": "Qual é a sua pretensão salarial?", "campo": "js-1"}],
        })[0]
        self.assistant.approve(first["id"], {"resposta": "R$ 12 mil CLT"})
        other = {**VAGA, "url": "https://www.linkedin.com/jobs/view/999/", "company": "Beta"}
        drafts = self.assistant.intake({
            "tipo": "form_detected", "site": "linkedin", "vaga": other,
            "perguntas": [{"rotulo": "Pretensão salarial", "campo": "js-9"}],
        })
        answer = next(draft for draft in drafts if draft["kind"] == "resposta")
        self.assertEqual(answer["payload"]["resposta"], "R$ 12 mil CLT")
        self.assertEqual(answer["payload"]["sugerida_por"], "historico")

    def test_approved_draft_cannot_be_decided_twice(self) -> None:
        draft = self.view()[0]
        self.assistant.approve(draft["id"])
        with self.assertRaises(DraftError):
            self.assistant.discard(draft["id"])

    def test_manual_status_change_is_direct_and_logged(self) -> None:
        self.assistant.approve(self.view()[0]["id"])
        job = self.store.job_by_url(CANONICAL)
        self.assistant.set_status(job["id"], "entrevista")
        self.assertEqual(self.store.job(job["id"])["status"], "entrevista")
        self.assertEqual(self.store.movements(1, job["id"])[0]["detail"], {"de": "visualizada", "para": "entrevista"})

    def test_search_finds_answer_by_company(self) -> None:
        self.assistant.approve(self.view()[0]["id"])
        draft = self.assistant.intake({
            "tipo": "form_detected", "site": "linkedin", "vaga": VAGA,
            "perguntas": [{"rotulo": "Qual sua pretensão salarial?", "campo": "js-1"}],
        })[0]
        self.assistant.approve(draft["id"], {"resposta": "R$ 12 mil"})
        results = self.assistant.search("o que respondi sobre pretensão salarial na Acme?")
        self.assertEqual(results[0]["tipo"], "resposta")
        self.assertIn("12 mil", results[0]["texto"])

    def test_normalize_url_drops_tracking(self) -> None:
        self.assertEqual(
            normalize_url("https://acme.inhire.app/vagas/123/backend?utm_source=x&id=7#top"),
            "https://acme.inhire.app/vagas/123/backend?id=7",
        )


if __name__ == "__main__":
    unittest.main()
