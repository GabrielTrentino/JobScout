import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from jobscout import ai_suggest, llm
from jobscout.assistant import similarity
from jobscout.preferences import Preferences
from jobscout.server import App

FIELDS = [
    {"campo": "js-1", "rotulo": "Você já trabalhou em startups?", "tipo": "radio", "opcoes": ["Sim", "Não"]},
    {"campo": "js-2", "rotulo": "Quantas pessoas você já liderou?", "tipo": "number", "opcoes": []},
    {"campo": "js-3", "rotulo": "Qual ferramenta de BI prefere?", "tipo": "select", "opcoes": ["Power BI", "Tableau"]},
]


class ParseTest(unittest.TestCase):
    def test_keeps_only_answers_that_fit_the_field(self):
        raw = json.dumps({"respostas": [
            {"campo": "js-1", "resposta": "sim", "base": "Stone era startup"},
            {"campo": "js-2", "resposta": "cerca de 4 pessoas", "base": "currículo"},
            {"campo": "js-3", "resposta": "Looker", "base": ""},
            {"campo": "js-9", "resposta": "x"},
        ]})
        found = {item["campo"]: item for item in ai_suggest.parse(raw, FIELDS, "ollama:gemma3:4b")}
        self.assertEqual(found["js-1"]["valor"], "Sim")
        self.assertEqual(found["js-1"]["origem"], "ia")
        self.assertIn("Stone era startup", found["js-1"]["base"])
        self.assertEqual(found["js-2"]["valor"], "4")
        self.assertNotIn("js-3", found)  # opção que não existe no campo
        self.assertNotIn("js-9", found)

    def test_empty_missing_or_broken_answers_disappear(self):
        self.assertEqual(ai_suggest.parse("não é json", FIELDS, "m"), [])
        raw = json.dumps({"respostas": [{"campo": "js-1", "resposta": ""}, {"campo": "js-2", "resposta": "[falta: dado]"}]})
        self.assertEqual(ai_suggest.parse(raw, FIELDS, "m"), [])
        wrapped = 'Claro! {"respostas": [{"campo": "js-1", "resposta": "Não", "base": "histórico"}]}'
        self.assertEqual(ai_suggest.parse(wrapped, FIELDS, "m")[0]["valor"], "Não")
        no_source = json.dumps({"respostas": [{"campo": "js-1", "resposta": "Não", "base": ""}]})
        self.assertEqual(ai_suggest.parse(no_source, FIELDS, "m"), [])

    def test_number_fields_get_numbers_and_text_limits_hold(self):
        fields = [
            {"campo": "n", "rotulo": "How many years with AWS?", "tipo": "number", "opcoes": []},
            {"campo": "m", "rotulo": "How many years with Go?", "tipo": "number", "opcoes": []},
            {"campo": "t", "rotulo": "Current employer", "tipo": "text", "opcoes": [], "max": 10},
            {"campo": "d", "rotulo": "Years with Spark?", "tipo": "number", "opcoes": []},
        ]
        raw = json.dumps({"respostas": [
            {"campo": "n", "resposta": "Não consta no currículo.", "base": "currículo"},
            {"campo": "m", "resposta": "talvez", "base": "x"},
            {"campo": "t", "resposta": "Stone Pagamentos S.A.", "base": "currículo"},
            {"campo": "d", "resposta": "2.5 anos", "base": "currículo"},
        ]})
        found = {item["campo"]: item for item in ai_suggest.parse(raw, fields, "m")}
        self.assertEqual(found["n"]["valor"], "0")
        self.assertIn("Não consta no currículo", found["n"]["base"])
        self.assertNotIn("m", found)
        self.assertNotIn("t", found)
        self.assertEqual(found["d"]["valor"], "2")

    def test_sensitive_questions_never_pass(self):
        fields = [{"campo": "g", "rotulo": "Qual seu gênero?", "tipo": "select", "opcoes": ["A", "B"]}]
        self.assertEqual(ai_suggest.parse(json.dumps({"respostas": [{"campo": "g", "resposta": "A"}]}), fields, "m"), [])


class ExamplesTest(unittest.TestCase):
    def test_similar_past_answers_come_first(self):
        answers = [
            {"question": "Qual sua cor favorita?", "answer": "azul", "title": "A", "company": "X"},
            {"question": "Já trabalhou em startup?", "answer": "Sim, na Stone", "title": "Dados", "company": "Y"},
            {"question": "Qual seu gênero?", "answer": "—", "title": "", "company": ""},
        ]
        past = ai_suggest.examples(["Você já trabalhou em startups?"], answers, similarity)
        self.assertEqual(past[0]["resposta"], "Sim, na Stone")
        self.assertNotIn("—", [item["resposta"] for item in past])
        text = ai_suggest.prompt(FIELDS, "Ana", past, {"title": "Dev", "company": "Acme", "description": "Python"})
        self.assertIn("Como a pessoa respondeu antes", text)
        self.assertIn('campo "js-3" (select)', text)
        self.assertIn("Power BI", text)


class ChoiceTest(unittest.TestCase):
    def tearDown(self):
        llm.configure("")

    def test_panel_choice_turns_the_model_on_unless_env_fixes_it(self):
        with mock.patch.dict(os.environ, {"JOBSCOUT_LLM_PADRAO": "off", "JOBSCOUT_LLM_RESPONDER": ""}):
            self.assertEqual(llm.model_name("responder"), "")
            llm.configure("ollama:gemma3:4b")
            self.assertEqual(llm.model_name("responder"), "ollama:gemma3:4b")
        with mock.patch.dict(os.environ, {"JOBSCOUT_LLM_RESPONDER": "gemini:flash"}):
            self.assertEqual(llm.model_name("responder"), "gemini:flash")

    def test_preferences_validate_the_model(self):
        with TemporaryDirectory() as folder:
            prefs = Preferences(Path(folder) / "p.json")
            self.assertEqual(prefs.save({"ia": "ollama:gemma3:4b"})["ia"], "ollama:gemma3:4b")
            self.assertEqual(prefs.save({"ia": "off"})["ia"], "")
            with self.assertRaises(ValueError):
                prefs.save({"ia": "chatgpt"})


class AssistantAITest(unittest.TestCase):
    def setUp(self):
        env = mock.patch.dict(os.environ, {"JOBSCOUT_LLM_PADRAO": "off", "JOBSCOUT_LLM_RESPONDER": "", "JOBSCOUT_GMAIL_CLIENT_ID": ""})
        env.start()
        self.addCleanup(env.stop)
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.app = App(Path(self.folder.name), background=False)
        self.addCleanup(self.app.close)
        self.addCleanup(llm.configure, "")

    def test_without_model_it_says_so_and_skips(self):
        self.assertEqual(self.app.assistant.ai_suggestions(FIELDS), {"ia": False, "sugestoes": []})

    def test_with_model_it_filters_and_retries_what_was_skipped(self):
        llm.configure("ollama:gemma3:4b")
        reply = json.dumps({"respostas": [{"campo": "js-1", "resposta": "Sim", "base": "perfil"}]})
        with mock.patch("jobscout.llm.ask_llm", return_value=reply) as ask:
            result = self.app.assistant.ai_suggestions(FIELDS + [{"campo": "g", "rotulo": "Qual seu gênero?", "tipo": "text"}],
                                                       {"url": "https://example.com/vaga", "title": "Dev", "company": "Acme"})
        self.assertTrue(result["ia"])
        self.assertEqual([item["valor"] for item in result["sugestoes"]], ["Sim"])
        prompt = ask.call_args_list[0].args[1]
        self.assertNotIn("gênero", prompt)
        self.assertTrue(ask.call_args.kwargs["as_json"])

    def test_questions_only_the_profile_answers_never_go_to_the_model(self):
        llm.configure("ollama:gemma3:4b")
        only_profile = [
            {"campo": "x1", "rotulo": "Are you legally authorized to work in Brazil?", "tipo": "radio", "opcoes": ["Yes", "No"]},
            {"campo": "x2", "rotulo": "Will you require visa sponsorship?", "tipo": "radio", "opcoes": ["Yes", "No"]},
            {"campo": "x3", "rotulo": "What is your salary expectation?", "tipo": "text"},
            {"campo": "x4", "rotulo": "What is your English level?", "tipo": "select", "opcoes": ["Basic", "Fluent"]},
        ]
        with mock.patch("jobscout.llm.ask_llm") as ask:
            result = self.app.assistant.ai_suggestions(only_profile)
        ask.assert_not_called()
        self.assertEqual(result, {"ia": True, "sugestoes": []})

    def test_model_offline_is_reported_not_raised(self):
        llm.configure("ollama:gemma3:4b")
        with mock.patch("jobscout.llm.ask_llm", side_effect=llm.LLMUnavailable("sem Ollama")):
            result = self.app.assistant.ai_suggestions(FIELDS)
        self.assertEqual(result["sugestoes"], [])
        self.assertIn("sem Ollama", result["erro"])



class FormLanguageTest(unittest.TestCase):
    def test_each_open_field_asks_for_its_language_and_long_answers_fit(self):
        fields = [
            {"campo": "a", "rotulo": "Why do you want to work here?", "tipo": "textarea"},
            {"campo": "b", "rotulo": "Por que você quer trabalhar aqui?", "tipo": "textarea"},
        ]
        text = ai_suggest.prompt(fields, "perfil", [], None)
        self.assertIn("Responda em inglês", text)
        self.assertIn("Responda em português", text)
        raw = json.dumps({"respostas": [{"campo": "a", "resposta": "x" * 900, "base": "currículo"}]})
        self.assertEqual(len(ai_suggest.parse(raw, fields, "m")[0]["valor"]), 900)

    def test_open_answers_cannot_invent_tools_or_numbers(self):
        fields = [{"campo": "a", "rotulo": "Tell me about a project", "tipo": "textarea"}]
        facts = "Construí pipelines em Python e reduzi 30% do custo"
        good = json.dumps({"respostas": [{"campo": "a", "resposta": "Construí pipelines em Python e reduzi 30% do custo.", "base": "currículo"}]})
        self.assertEqual(len(ai_suggest.parse(good, fields, "m", facts)), 1)
        for bad in ("Usei Kafka nos pipelines.", "Reduzi 75% do custo com Python."):
            raw = json.dumps({"respostas": [{"campo": "a", "resposta": bad, "base": "currículo"}]})
            self.assertEqual(ai_suggest.parse(raw, fields, "m", facts), [])

    def test_checkbox_group_accepts_several_options(self):
        fields = [{"campo": "a", "rotulo": "Which tools?", "tipo": "checkbox", "opcoes": ["Python", "SQL", "Excel"]}]
        raw = json.dumps({"respostas": [{"campo": "a", "resposta": "Python; SQL", "base": "currículo"}]})
        self.assertEqual(ai_suggest.parse(raw, fields, "m")[0]["valor"], "Python; SQL")


if __name__ == "__main__":
    unittest.main()
