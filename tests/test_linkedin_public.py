import io
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock
from urllib.error import URLError

from jobscout import linkedin_public
from jobscout.assistant import Assistant
from jobscout.events import Hub
from jobscout.profile import Profile
from jobscout.store import Store

# Trecho da página pública real (jobs-guest/jobs/api/jobPosting/<id>), reduzido.
PAGE = """
<section class="top-card-layout container-lined overflow-hidden babybear:rounded-[0px]">
  <h2 class="top-card-layout__title font-sans text-lg papabear:text-xl font-bold topcard__title">Data Engineer III</h2>
  <h4 class="top-card-layout__second-subline">
    <span class="topcard__flavor">
      <a class="topcard__org-name-link topcard__flavor--black-link" href="https://br.linkedin.com/company/stone">
        Stone
      </a>
    </span>
    <span class="topcard__flavor topcard__flavor--bullet">
      Brasil
    </span>
    <span class="num-applicants__caption topcard__flavor--metadata topcard__flavor--bullet">Mais de 100 candidaturas</span>
  </h4>
</section>
<div class="show-more-less-html__markup relative overflow-hidden">
  <p>Buscamos pessoa engenheira de dados.</p><ul><li>Python &amp; SQL</li><li>Spark</li></ul>
</div>
"""

URL = "https://www.linkedin.com/jobs/view/4476952226/"


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class ParseTest(unittest.TestCase):
    def test_reads_public_page(self) -> None:
        fields = linkedin_public.parse(PAGE)
        self.assertEqual(fields["title"], "Data Engineer III")
        self.assertEqual(fields["company"], "Stone")
        self.assertEqual(fields["location"], "Brasil")
        self.assertEqual(fields["description"], "Buscamos pessoa engenheira de dados.\n• Python & SQL\n• Spark")

    def test_job_id(self) -> None:
        self.assertEqual(linkedin_public.job_id(URL), "4476952226")
        self.assertEqual(linkedin_public.job_id("https://www.linkedin.com/jobs/view/data-engineer-at-stone-4476952226/"), "4476952226")
        self.assertIsNone(linkedin_public.job_id("https://www.linkedin.com/feed/"))

    def test_fetch_uses_public_address(self) -> None:
        seen = []

        def opener(request, timeout):
            seen.append(request.full_url)
            return Response(PAGE.encode())

        self.assertEqual(linkedin_public.fetch(URL, opener)["company"], "Stone")
        self.assertEqual(seen, ["https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/4476952226"])

    def test_fetch_errors(self) -> None:
        def offline(request, timeout):
            raise URLError("sem rede")

        with self.assertRaises(linkedin_public.PublicPageError):
            linkedin_public.fetch(URL, offline)
        with self.assertRaises(linkedin_public.PublicPageError):
            linkedin_public.fetch(URL, lambda request, timeout: Response(b"<html>login</html>"))


class FallbackTest(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = TemporaryDirectory()
        root = Path(self.folder.name)
        self.store = Store(root / "test.db")
        self.hub = Hub()
        self.calls = []
        self.assistant = Assistant(self.store, self.hub, Profile(root / "profile.json"), background=False, public_job=self.fake)
        self.result = linkedin_public.parse(PAGE)
        env = mock.patch.dict(os.environ, {"JOBSCOUT_LLM_PADRAO": "off"})
        env.start()
        self.addCleanup(env.stop)

    def tearDown(self) -> None:
        self.store.close()
        self.folder.cleanup()

    def fake(self, url):
        self.calls.append(url)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result

    def view(self, **vaga):
        return self.assistant.intake({"tipo": "job_viewed", "site": "linkedin", "pagina": "p", "vaga": {"url": URL, **vaga}})

    def test_link_only_becomes_full_draft(self) -> None:
        drafts = self.view()
        payload = drafts[0]["payload"]
        self.assertEqual((payload["title"], payload["company"], payload["location"]), ("Data Engineer III", "Stone", "Brasil"))
        self.assertIn("Spark", payload["description"])
        self.assertTrue(any("dados públicos" in item["texto"] for item in self.hub.recent()))

    def test_fetches_once_per_job(self) -> None:
        self.view()
        self.view()
        self.assistant.intake({"tipo": "application_submitted", "site": "linkedin", "vaga": {"url": URL}})
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.store.drafts("pendente")[0]["payload"]["status"], "candidatado")

    def test_page_data_wins_over_public(self) -> None:
        drafts = self.view(title="Engenheiro de Dados III")
        self.assertEqual(drafts[0]["payload"]["title"], "Engenheiro de Dados III")
        self.assertEqual(drafts[0]["payload"]["company"], "Stone")
        self.view(title="Engenheiro de Dados III", company="Stone")
        self.assertEqual(len(self.calls), 1)

    def test_submit_without_title_is_captured(self) -> None:
        drafts = self.assistant.intake({"tipo": "application_submitted", "site": "linkedin", "vaga": {"url": URL}})
        self.assertEqual(drafts[0]["payload"]["company"], "Stone")
        self.assertEqual(drafts[0]["payload"]["status"], "candidatado")

    def test_public_page_unavailable_is_logged_not_raised(self) -> None:
        self.result = linkedin_public.PublicPageError("LinkedIn não respondeu")
        self.assertEqual(self.view(), [])
        self.assertIn("página pública", self.store.failures()[0]["detail"])
        self.assertTrue(any(item["nivel"] == "erro" for item in self.hub.recent()))

    def test_no_fetch_for_discarded_job(self) -> None:
        self.assistant.discard(self.view()[0]["id"])
        self.calls.clear()
        self.assertEqual(self.view(), [])
        self.assertEqual(self.calls, [])
        self.assertIn("descartou", self.hub.recent()[0]["texto"])


if __name__ == "__main__":
    unittest.main()
