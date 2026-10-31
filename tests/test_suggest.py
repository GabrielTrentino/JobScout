import unittest
from datetime import date

from jobscout import suggest

RESUME = """EXPERIÊNCIA
Engenheiro de Dados | Stone
jan 2021 – atual
- Construí pipelines em Python e Airflow
- Modelei dados em SQL
Analista de Dados | Itaú
03/2018 - 12/2020
- Dashboards em Power BI e SQL
- Automação em Python
FORMAÇÃO
Bacharelado em Sistemas | USP
2012 - 2016
- TCC sobre Python e Java
"""

PROFILE = {
    "curriculo": RESUME,
    "nivel_ingles": "Avançado",
    "autorizacao_trabalho": "Sim",
    "precisa_visto": "Não",
    "aceita_mudanca": "Não",
    "modelos_trabalho": "Remoto, Híbrido",
    "pretensao_salarial": "R$ 12.000",
    "disponibilidade": "30 dias",
}


def ask(question, options=None, kind="text"):
    found = suggest.suggest(question, PROFILE, options=options, kind=kind)
    return found["valor"] if found else None


class PeriodTest(unittest.TestCase):
    def test_reads_common_formats(self):
        today = date(2026, 10, 1)
        self.assertEqual(suggest.period_months("jan 2021 – atual", today), (2021 * 12, 2026 * 12 + 9))
        self.assertEqual(suggest.period_months("03/2018 - 12/2020", today), (2018 * 12 + 2, 2020 * 12 + 11))
        self.assertEqual(suggest.period_months("2019 - 2021", today), (2019 * 12, 2021 * 12 + 11))
        self.assertIsNone(suggest.period_months("sem data", today))

    def test_overlapping_roles_count_once_and_education_is_ignored(self):
        info = suggest.experience(RESUME, "Python", date(2026, 10, 1))
        self.assertEqual(info["cargos"], 2)
        self.assertEqual(info["de"], 2018)
        self.assertEqual(info["meses"], 34 + 70)
        self.assertIsNone(suggest.experience(RESUME, "Java", date(2026, 10, 1)))


class SuggestTest(unittest.TestCase):
    def test_tool_checkboxes_follow_the_resume(self):
        profile = {"curriculo": "Pipelines em Python e Airflow"}
        found = suggest.suggest("Which tools have you used?", profile, options=["Python", "Airflow", "COBOL", "Excel"], kind="checkbox")
        self.assertEqual(found["valor"], "Python; Airflow")

    def test_salary_in_real_and_dollar(self):
        both = {"pretensao_salarial": "R$ 15.000 CLT", "pretensao_usd": "US$ 4,000/mês"}
        self.assertEqual(suggest.suggest("Qual sua pretensão salarial?", both)["valor"], "R$ 15.000 CLT")
        english = suggest.suggest("What is your salary expectation?", both)
        self.assertEqual(english["valor"], "US$ 4,000/mês")
        self.assertIn("R$ 15.000", english["base"])  # a outra moeda aparece para conferir
        self.assertEqual(suggest.suggest("Pretensão salarial em dólar?", both)["valor"], "US$ 4,000/mês")
        self.assertEqual(suggest.suggest("Salary expectation (BRL)", both)["valor"], "R$ 15.000 CLT")
        self.assertEqual(suggest.suggest("Salary expectation in USD", both, kind="number")["valor"], "4000")
        self.assertEqual(suggest.suggest("Pretensão salarial (R$)", both, kind="number")["valor"], "15000")
        # Sem valor na moeda pedida: não converte nem chuta.
        only_real = {"pretensao_salarial": "R$ 15.000"}
        self.assertIsNone(suggest.suggest("Salary expectation in USD", only_real))
        self.assertIsNone(suggest.suggest("What is your salary expectation?", only_real, kind="number"))
        fallback = suggest.suggest("What is your salary expectation?", only_real)
        self.assertEqual(fallback["valor"], "R$ 15.000")
        self.assertIn("sem valor em dólar", fallback["base"])
        self.assertEqual([suggest.salary_number(text) for text in ("R$ 15.000,00", "US$ 4,000/mês", "4k", "R$ 8.500")], ["15000", "4000", "4000", "8500"])

    def test_based_in_a_region_comes_from_the_profile_country(self):
        profile = {"pais": "Brasil", "cidade": "Goiânia"}
        latam = suggest.suggest("Are you currently based in Latin America?", profile, options=["Yes", "No"], kind="radio")
        self.assertEqual((latam["valor"], latam["origem"]), ("Yes", "perfil"))
        self.assertEqual(suggest.suggest("Are you located in Europe?", profile, options=["Yes", "No"], kind="radio")["valor"], "No")
        self.assertEqual(suggest.suggest("Você mora no Brasil?", profile, options=["Sim", "Não"], kind="radio")["valor"], "Sim")
        # Sem país no Perfil, ninguém chuta (nem a IA: é pergunta só do Perfil).
        self.assertIsNone(suggest.suggest("Are you based in LATAM?", {}, options=["Yes", "No"], kind="radio"))
        self.assertTrue(suggest.profile_only("Are you currently based in Latin America?"))

    def test_years_with_a_skill_come_from_the_resume(self):
        self.assertTrue(ask("Quantos anos de experiência você tem com Python?", kind="number").isdigit())
        self.assertEqual(ask("How many years of experience do you have with SQL?", ["Less than 1 year", "1-2 years", "3-5 years", "6+ years"], "select"), "6+ years")
        self.assertEqual(ask("Quantos anos de experiência com Kafka?"), "0")
        aws = suggest.suggest("How many years of work experience do you have with Amazon Web Services (AWS)?", PROFILE, kind="number")
        self.assertEqual(aws["valor"], "0")
        self.assertIn("Não consta no currículo", aws["base"])
        self.assertEqual(ask("How many years of experience do you have with Kafka?", ["0", "1-2", "3+"], "select"), "0")
        self.assertIsNone(suggest.suggest("Quantos anos com Kafka?", {"curriculo": ""}))  # sem currículo, não sabe

    def test_fields_that_only_take_numbers(self):
        self.assertTrue(suggest.numeric_question("How many years of work experience do you have with SQL?"))
        self.assertTrue(suggest.numeric_question("Quantas pessoas você liderou?"))
        self.assertFalse(suggest.numeric_question("Qual sua pretensão salarial?"))
        self.assertTrue(suggest.fits("3", "number"))
        self.assertFalse(suggest.fits("Não consta no currículo.", "number"))
        self.assertFalse(suggest.fits("x" * 24, "text", 20))
        self.assertTrue(suggest.fits("x" * 20, "text", 20))

    def test_year_ranges(self):
        options = ["Menos de 1 ano", "1 a 2 anos", "3 a 5 anos", "Mais de 5 anos"]
        self.assertEqual(suggest.fit_years(0.5, options), 0)
        self.assertEqual(suggest.fit_years(2.4, options), 1)
        self.assertEqual(suggest.fit_years(4, options), 2)
        self.assertEqual(suggest.fit_years(8, options), 3)

    def test_profile_quick_answers(self):
        self.assertEqual(ask("Qual o seu nível de inglês?", ["Básico", "Intermediário", "Avançado", "Fluente"], "select"), "Avançado")
        self.assertEqual(ask("Do you speak English?", ["Yes", "No"], "radio"), "Yes")
        self.assertEqual(ask("Are you legally authorized to work in Brazil?", ["Yes", "No"], "radio"), "Yes")
        self.assertEqual(ask("Will you require visa sponsorship?", ["Yes", "No"], "radio"), "No")
        self.assertEqual(ask("Você aceita trabalhar no modelo presencial?", ["Sim", "Não"], "radio"), "Não")
        self.assertEqual(ask("Are you comfortable working in a hybrid setting?", ["Yes", "No"], "radio"), "Yes")
        self.assertEqual(ask("Qual sua pretensão salarial?", kind="number"), "12000")
        self.assertEqual(ask("Qual sua pretensão salarial?"), "R$ 12.000")

    def test_location_comes_from_the_profile_city(self):
        profile = {**PROFILE, "cidade": "São Paulo, SP"}
        for question in ("What is your current location?", "Where are you based?", "Em que cidade você mora?"):
            found = suggest.suggest(question, profile)
            self.assertEqual(found["valor"], "São Paulo, SP", question)
        self.assertIsNone(suggest.suggest("What is your current location?", {**PROFILE, "cidade": ""}))
        self.assertIsNone(suggest.suggest("Preferred work location?", profile))

    def test_location_country_follows_the_question_language(self):
        profile = {**PROFILE, "cidade": "São Paulo", "estado": "SP", "pais": "Brasil"}
        self.assertEqual(suggest.suggest("What is your current location?", profile)["valor"], "São Paulo, SP, Brazil")
        self.assertEqual(suggest.suggest("Qual sua localização atual?", profile)["valor"], "São Paulo, SP, Brasil")
        self.assertEqual(suggest.suggest("Country", profile, options=["Argentina", "Brazil", "Chile"], kind="select")["valor"], "Brazil")
        self.assertEqual(suggest.suggest("País", profile, options=["Argentina", "Brasil"], kind="select")["valor"], "Brasil")
        self.assertEqual(suggest.suggest("Which country do you live in?", profile)["valor"], "Brazil")

    def test_has_experience_only_says_yes_when_the_resume_shows_it(self):
        self.assertEqual(ask("Você tem experiência com Airflow?", ["Sim", "Não"], "radio"), "Sim")
        self.assertIsNone(ask("Você tem experiência com Kafka?", ["Sim", "Não"], "radio"))
        self.assertIsNone(ask("Descreva sua experiência com Python", kind="textarea"))

    def test_sensitive_questions_never_get_a_suggestion(self):
        for question in ("Qual é o seu gênero?", "Do you identify as a person with a disability?", "Qual sua raça/cor?", "Data de nascimento"):
            self.assertIsNone(ask(question, ["Sim", "Não"], "select"), question)

    def test_missing_profile_answer_means_no_suggestion(self):
        self.assertIsNone(suggest.suggest("Are you authorized to work in Brazil?", {"curriculo": ""}, options=["Yes", "No"], kind="radio"))
        self.assertIsNone(ask("Qual sua cor favorita?"))

    def test_option_must_exist(self):
        self.assertIsNone(ask("Qual o seu nível de inglês?", ["A", "B"], "select"))


if __name__ == "__main__":
    unittest.main()
