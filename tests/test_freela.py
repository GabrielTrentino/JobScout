import unittest
from datetime import date

from jobscout import freela


def payment(amount, currency="BRL", due=None, paid=None):
    return {"amount": amount, "currency": currency, "due_date": due, "paid_at": paid}


def project(status="andamento", renewal=None, end=None):
    return {"id": 1, "title": "Site", "client": "Acme", "status": status, "renewal_date": renewal, "end_date": end}


class CleanTest(unittest.TestCase):
    def test_needs_project_or_client(self):
        with self.assertRaises(ValueError):
            freela.clean({"title": " ", "client": ""})
        self.assertEqual(freela.clean({"client": "Acme"})["client"], "Acme")

    def test_partial_accepts_status_only(self):
        self.assertEqual(freela.clean({"status": "contrato"}, partial=True), {"status": "contrato"})

    def test_rejects_invalid_values(self):
        for data in ({"status": "x"}, {"kind": "x"}, {"currency": "XPT"}, {"start_date": "31/12/2026"}, {"amount": "-3"}, {"payment_day": "40"}):
            with self.assertRaises(ValueError, msg=data):
                freela.clean(data, partial=True)

    def test_brazilian_number(self):
        self.assertEqual(freela.clean({"amount": "1.500,50"}, partial=True)["amount"], 1500.5)
        self.assertEqual(freela.clean({"amount": "1500.50"}, partial=True)["amount"], 1500.5)


class EstimateTest(unittest.TestCase):
    def test_total_comes_from_the_lines(self):
        data = freela.clean_estimate({"itens": [{"descricao": "API", "horas": "10"}, {"descricao": "Testes", "horas": 2.5}], "valor_hora": "100", "total": 1})
        self.assertEqual((data["hours"], data["total"]), (12.5, 1250))

    def test_needs_a_line(self):
        with self.assertRaises(ValueError):
            freela.clean_estimate({"itens": [{"descricao": " ", "horas": 3}]})

    def test_text_for_the_client(self):
        data = freela.clean_estimate({"itens": [{"descricao": "API", "horas": 10}], "valor_hora": 100, "validade": "2026-12-01"})
        text = freela.estimate_text({"title": "Site"}, data)
        self.assertIn("API: 10h", text)
        self.assertIn("R$ 1.000,00", text)
        self.assertIn("01/12/2026", text)


class SummaryTest(unittest.TestCase):
    TODAY = date(2026, 11, 2)

    def test_money_keeps_currencies_apart(self):
        payments = [payment(100), payment(50, "USD"), payment(30, paid="2026-11-01T10:00:00"), payment(70, paid="2026-10-01T10:00:00")]
        result = freela.summary([], payments, [], self.TODAY)
        self.assertEqual(result["a_receber"], {"BRL": 100, "USD": 50})
        self.assertEqual(result["recebido_mes"], {"BRL": 30})

    def test_late_payment(self):
        result = freela.summary([], [payment(10, due="2026-11-01"), payment(10, due="2026-11-02"), payment(10, due="2026-10-01", paid="2026-10-02")], [], self.TODAY)
        self.assertEqual(result["atrasados"], 1)

    def test_renewals_inside_the_window(self):
        projects = [project(renewal="2026-11-20"), project(renewal="2027-02-01"), project(end="2026-10-01"), project(status="concluido", end="2026-11-10")]
        self.assertEqual([row["date"] for row in freela.summary(projects, [], [], self.TODAY)["a_renovar"]], ["2026-11-20"])

    def test_estimates_waiting(self):
        self.assertEqual(freela.summary([], [], [{"state": "enviada"}, {"state": "aprovada"}], self.TODAY)["estimativas_sem_retorno"], 1)


class PageTest(unittest.TestCase):
    def test_platform_wins(self):
        self.assertEqual(freela.page_kind("https://www.workana.com/job/app", "Criar app"), "freela")
        self.assertEqual(freela.platform_of("https://www.99freelas.com.br/project/x"), "99Freelas")

    def test_similar_host_is_not_a_platform(self):
        self.assertEqual(freela.platform_of("https://workana.com.evil.io/x"), "")

    def test_job_page_mentioning_budget_stays_a_job(self):
        text = "Requirements and responsibilities. You will manage the budget. Qualifications below. Apply now."
        self.assertEqual(freela.page_kind("https://acme.com/careers/gerente", "Gerente de projetos", text), "vaga")

    def test_one_word_decides_nothing(self):
        self.assertEqual(freela.page_kind("https://blog.com/a", "Viagem", "Dicas de orçamento para a viagem."), "outra")

    def test_title_decides(self):
        self.assertEqual(freela.page_kind("https://acme.com/a", "Freela de design", ""), "freela")

    def test_facts_cross_with_profile(self):
        facts = freela.page_facts("https://www.workana.com/job/x", "Dashboard", "Precisamos de Python e SQL. Orçamento de R$ 2.000", ["python"])
        self.assertEqual(facts["tipo"], "freela")
        self.assertEqual(facts["encaixe"], 50)
        self.assertEqual([name.lower() for name in facts["tem"]], ["python"])
        self.assertEqual(facts["valores"], ["R$ 2.000"])

    def test_value_without_the_final_period(self):
        self.assertEqual(freela.page_facts("https://a.com", "x", "Pago R$ 3.000. Ou US$ 500, ou R$ 5 mil.", [])["valores"], ["R$ 3.000", "US$ 500", "R$ 5 mil"])

    def test_no_skills_means_no_fit(self):
        self.assertIsNone(freela.page_facts("https://a.com", "Receita", "Bolo de cenoura", [])["encaixe"])


if __name__ == "__main__":
    unittest.main()
