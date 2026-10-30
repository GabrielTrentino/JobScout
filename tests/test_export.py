import json
import os
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from jobscout import preferences, xlsx
from jobscout.linkedin_public import PublicPageError
from jobscout.server import App, serve_in_background

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def offline(url):
    raise PublicPageError("sem rede nos testes")


def sheet_rows(path_or_bytes, index=1):
    source = path_or_bytes if isinstance(path_or_bytes, (str, Path)) else __import__("io").BytesIO(path_or_bytes)
    with zipfile.ZipFile(source) as archive:
        for name in archive.namelist():
            if name.endswith(".xml") or name.endswith(".rels"):
                ElementTree.fromstring(archive.read(name))  # todo XML precisa ser válido
        root = ElementTree.fromstring(archive.read(f"xl/worksheets/sheet{index}.xml"))
        workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
    names = [sheet.get("name") for sheet in workbook.find("m:sheets", NS)]
    rows = []
    for row in root.find("m:sheetData", NS):
        cells = []
        for cell in row:
            text = cell.find("m:is/m:t", NS)
            value = cell.find("m:v", NS)
            cells.append(text.text if text is not None else value.text if value is not None else "")
        rows.append(cells)
    return names, rows


class XlsxTest(unittest.TestCase):
    def test_builds_a_valid_workbook(self):
        content = xlsx.build([
            ("Vagas", ["ID", "Título"], [[1, "Dados & BI <sênior>"], [2, "Com \x0bcontrole"]]),
            ("Vagas", ["A"], [["x"]]),
            ("Nome: com/inválidos?", ["A"], []),
        ])
        names, rows = sheet_rows(content)
        self.assertEqual(names, ["Vagas", "Vagas (2)", "Nome  com inválidos"])
        self.assertEqual(rows[0], ["ID", "Título"])
        self.assertEqual(rows[1], ["1", "Dados & BI <sênior>"])
        self.assertEqual(rows[2], ["2", "Com controle"])

    def test_columns(self):
        self.assertEqual([xlsx.column(i) for i in (0, 25, 26, 27, 701, 702)], ["A", "Z", "AA", "AB", "ZZ", "AAA"])

    def test_needs_a_sheet(self):
        with self.assertRaises(ValueError):
            xlsx.build([])


class PreferencesTest(unittest.TestCase):
    def test_defaults_and_validation(self):
        with TemporaryDirectory() as folder:
            prefs = preferences.Preferences(Path(folder) / "p.json")
            self.assertEqual(prefs.load()["nome"], "JobScout")
            self.assertEqual(prefs.save({"nome": "  Minha   Busca "})["nome"], "Minha Busca")
            self.assertEqual(prefs.save({"nome": ""})["nome"], "JobScout")
            with self.assertRaises(ValueError):
                prefs.save({"pasta": "relativa"})
            with self.assertRaises(ValueError):
                prefs.save({"nome": "x" * 41})

    def test_prepare_copies_the_extension_without_tests(self):
        with TemporaryDirectory() as folder:
            target = Path(folder) / "JobScout"
            paths = preferences.prepare(target, "Minha Busca", "http://127.0.0.1:8765/")
            extension = Path(paths["extensao"])
            self.assertTrue((extension / "manifest.json").is_file())
            self.assertTrue((extension / "content" / "page.js").is_file())
            self.assertFalse((extension / "tests").exists())
            self.assertTrue(Path(paths["exportacoes"]).is_dir())
            guide = Path(paths["guia"]).read_text(encoding="utf-8")
            self.assertIn("Minha Busca", guide)
            self.assertIn(str(extension), guide)
            preferences.prepare(target, "Minha Busca", "http://127.0.0.1:8765/")  # de novo, sem erro

    def test_inside(self):
        with TemporaryDirectory() as folder:
            base = Path(folder)
            self.assertTrue(preferences.inside(base, base / "a" / "b.xlsx"))
            self.assertFalse(preferences.inside(base, base.parent))


class ExportServerTest(unittest.TestCase):
    def setUp(self):
        env = mock.patch.dict(os.environ, {"JOBSCOUT_LLM_PADRAO": "off", "JOBSCOUT_GMAIL_CLIENT_ID": ""})
        env.start()
        self.addCleanup(env.stop)
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.app = App(Path(self.folder.name), background=False)
        self.app.assistant.public_job = offline
        self.app.assistant.public_company = offline
        self.home = Path(self.folder.name) / "Pasta do JobScout"
        self.app.preferences.save({"pasta": str(self.home)})
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

    def add_job(self, url, title, status):
        job = self.call("POST", "/api/vagas", {"url": url, "title": title, "company": "Acme", "status": status})
        return job

    def test_name_and_folder(self):
        state = self.call("GET", "/api/estado")
        self.assertEqual(state["preferencias"]["nome"], "JobScout")
        self.assertFalse(state["preferencias"]["pronta"])
        saved = self.call("PUT", "/api/preferencias", {"nome": "Caça Vagas"})
        self.assertEqual(saved["nome"], "Caça Vagas")
        self.assertTrue(saved["pronta"])
        self.assertTrue((self.home / preferences.EXTENSION_FOLDER / "manifest.json").is_file())
        with self.assertRaises(HTTPError) as caught:
            self.call("PUT", "/api/preferencias", {"nome": "x"}, headers={"Origin": "chrome-extension://abc"})
        self.assertEqual(caught.exception.code, 403)

    def test_export_chosen_sheets_and_statuses(self):
        self.add_job("https://example.com/vaga/1", "Dados Pleno", "candidatado")
        self.add_job("https://example.com/vaga/2", "Dados Sênior", "visualizada")
        result = self.call("POST", "/api/exportar", {"abas": ["vagas", "linha"], "status": ["candidatado"]})
        path = Path(result["arquivo"])
        self.assertTrue(path.is_file())
        self.assertEqual(path.parent, self.home / preferences.EXPORT_FOLDER)
        names, rows = sheet_rows(path)
        self.assertEqual(names, ["Vagas", "Linha do tempo"])
        self.assertEqual([row[2] for row in rows[1:]], ["Dados Pleno"])
        with self.assertRaises(HTTPError) as caught:
            self.call("POST", "/api/exportar", {"abas": []})
        self.assertEqual(caught.exception.code, 422)

    def test_open_only_inside_the_folder(self):
        self.call("POST", "/api/pasta/preparar", {})
        with mock.patch("jobscout.preferences.reveal") as reveal:
            self.call("POST", "/api/pasta/abrir", {"alvo": "extensao"})
            reveal.assert_called_once()
            with self.assertRaises(HTTPError) as caught:
                self.call("POST", "/api/pasta/abrir", {"arquivo": str(Path(self.folder.name) / "jobscout.db")})
            self.assertEqual(caught.exception.code, 404)
            self.assertEqual(reveal.call_count, 1)

    def test_suggestions_for_the_extension(self):
        self.call("PUT", "/api/perfil", {"nivel_ingles": "Fluente", "autorizacao_trabalho": "Sim"})
        result = self.call("POST", "/api/extensao/sugestoes", {"campos": [
            {"campo": "js-1", "rotulo": "Qual seu nível de inglês?", "tipo": "select", "opcoes": ["Básico", "Avançado", "Fluente"]},
            {"campo": "js-2", "rotulo": "Are you authorized to work in Brazil?", "tipo": "radio", "opcoes": ["Yes", "No"]},
            {"campo": "js-3", "rotulo": "Qual seu gênero?", "tipo": "select", "opcoes": ["A", "B"]},
            {"campo": "js-4", "rotulo": "Cor favorita", "tipo": "text", "opcoes": []},
        ]}, headers={"Origin": "chrome-extension://abc"})
        by_field = {item["campo"]: item["valor"] for item in result["sugestoes"]}
        self.assertEqual(by_field, {"js-1": "Fluente", "js-2": "Yes"})


if __name__ == "__main__":
    unittest.main()
