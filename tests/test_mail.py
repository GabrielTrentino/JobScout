import os
import unittest
from datetime import datetime, timezone
from unittest import mock

from jobscout import mail

CONVITE = b"""From: Carla Lima <carla@acme.com.br>
To: ana@email.com
Subject: Processo seletivo Backend Python - convite para entrevista
Date: Tue, 27 Oct 2026 09:30:00 -0300
Message-ID: <abc123@acme.com.br>
Content-Type: text/plain; charset=utf-8

Ola Ana,

Gostariamos de agendar uma entrevista com o time no dia 30/10 as 14h30 pelo Google Meet.

Abracos,
Carla
"""

JOBS = [
    {"id": 1, "title": "Backend Python", "company": "Acme", "status": "candidatado", "status_at": "2026-10-20"},
    {"id": 2, "title": "Dados", "company": "Beta", "status": "candidatado", "status_at": "2026-10-21"},
]


class MailTest(unittest.TestCase):
    def setUp(self) -> None:
        env = mock.patch.dict(os.environ, {"JOBSCOUT_LLM_PADRAO": "off"})
        env.start()
        self.addCleanup(env.stop)

    def test_parse_eml(self) -> None:
        parsed = mail.parse_eml(CONVITE)
        self.assertEqual(parsed["remetente_email"], "carla@acme.com.br")
        self.assertEqual(parsed["remetente_nome"], "Carla Lima")
        self.assertIn("entrevista", parsed["assunto"])
        self.assertIn("30/10", parsed["corpo"])

    def test_invite_is_classified_linked_and_dated(self) -> None:
        draft = mail.build_draft(mail.parse_eml(CONVITE), JOBS)
        self.assertEqual(draft["classificacao"], "entrevista")
        self.assertEqual(draft["job_id"], 1)
        self.assertEqual(draft["status_proposto"], "entrevista")
        self.assertIn("-10-30T14:30", draft["data_evento"])

    def test_rejection_beats_interview_words(self) -> None:
        message = {"assunto": "Retorno sobre a entrevista", "corpo": "Infelizmente seguiremos com outros candidatos."}
        self.assertEqual(mail.classify(message), ("rejeicao", "regras"))

    def test_prefilter(self) -> None:
        self.assertTrue(mail.looks_relevant({"remetente_email": "rh@beta.io", "assunto": "Oi", "corpo": ""}, JOBS))
        self.assertTrue(mail.looks_relevant({"remetente_email": "x@gmail.com", "assunto": "Processo seletivo", "corpo": ""}, JOBS))
        self.assertFalse(mail.looks_relevant({"remetente_email": "loja@ofertas.com", "assunto": "Black Friday", "corpo": "50% off"}, JOBS))

    def test_platform_sender_does_not_link_by_domain(self) -> None:
        message = {"remetente_email": "jobs-noreply@linkedin.com", "assunto": "Atualização", "corpo": "Sua candidatura"}
        self.assertIsNone(mail.link_job(message, [{"id": 9, "title": "X", "company": "LinkedIn"}]))

    def test_extract_written_date(self) -> None:
        reference = datetime(2026, 10, 27, tzinfo=timezone.utc)
        self.assertEqual(mail.extract_when("Pode ser 5 de novembro às 10h?", reference), "2026-11-05T10:00+00:00")
        self.assertIsNone(mail.extract_when("Sem data aqui", reference))


if __name__ == "__main__":
    unittest.main()
