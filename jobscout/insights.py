"""O que dá para tirar da vaga só com regras: skills, inglês, modalidade, salário, região e senioridade.

Nada aqui usa IA. O resultado vai para o rascunho da vaga e passa pela aprovação como o resto.
"""

from __future__ import annotations

import re
from typing import Any

from jobscout.activities import clean_space, fold

# Nome exibido e padrões já sem acento e em minúsculas (o texto passa por fold antes).
SKILLS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Python", (r"\bpython\b",)),
    ("SQL", (r"\bsql\b",)),
    ("PySpark", (r"\bpyspark\b",)),
    ("Spark", (r"\bspark\b",)),
    ("Scala", (r"\bscala\b",)),
    ("Java", (r"\bjava\b(?!\s*script)",)),
    ("JavaScript", (r"\bjavascript\b", r"\bjs\b")),
    ("TypeScript", (r"\btypescript\b",)),
    ("Node.js", (r"\bnode(\.?js)?\b",)),
    ("React", (r"\breact\b",)),
    ("Go", (r"\bgolang\b", r"\bgo\s+lang")),
    ("C#", (r"c#", r"\.net\b")),
    ("Airflow", (r"\bairflow\b",)),
    ("dbt", (r"\bdbt\b",)),
    ("Kafka", (r"\bkafka\b",)),
    ("Databricks", (r"\bdatabricks\b",)),
    ("Snowflake", (r"\bsnowflake\b",)),
    ("BigQuery", (r"\bbig\s?query\b",)),
    ("Redshift", (r"\bredshift\b",)),
    ("Synapse", (r"\bsynapse\b",)),
    ("Data Factory", (r"\bdata factory\b", r"\badf\b")),
    ("Glue", (r"\baws glue\b", r"\bglue\b")),
    ("EMR", (r"\bemr\b",)),
    ("Lambda", (r"\blambda\b",)),
    ("S3", (r"\bs3\b",)),
    ("AWS", (r"\baws\b", r"amazon web services")),
    ("Azure", (r"\bazure\b",)),
    ("GCP", (r"\bgcp\b", r"google cloud")),
    ("Docker", (r"\bdocker\b",)),
    ("Kubernetes", (r"\bkubernetes\b", r"\bk8s\b")),
    ("Terraform", (r"\bterraform\b",)),
    ("CI/CD", (r"\bci\s*/\s*cd\b", r"\bpipelines? de ci\b")),
    ("Git", (r"\bgit\b", r"\bgithub\b", r"\bgitlab\b")),
    ("Linux", (r"\blinux\b",)),
    ("PostgreSQL", (r"\bpostgres(ql)?\b",)),
    ("MySQL", (r"\bmysql\b",)),
    ("SQL Server", (r"\bsql server\b",)),
    ("Oracle", (r"\boracle\b",)),
    ("MongoDB", (r"\bmongo(db)?\b",)),
    ("Redis", (r"\bredis\b",)),
    ("Elasticsearch", (r"\belastic(search)?\b",)),
    ("Power BI", (r"\bpower\s?bi\b",)),
    ("Tableau", (r"\btableau\b",)),
    ("Looker", (r"\blooker\b",)),
    ("Excel", (r"\bexcel\b",)),
    ("Pandas", (r"\bpandas\b",)),
    ("NumPy", (r"\bnumpy\b",)),
    ("Machine Learning", (r"machine learning", r"aprendizado de maquina", r"\bml\b")),
    ("LLM / IA generativa", (r"\bllms?\b", r"ia generativa", r"generative ai", r"\bgenai\b", r"\brag\b")),
    ("ETL / ELT", (r"\betl\b", r"\belt\b")),
    ("Data Lake", (r"data\s?lake(house)?",)),
    ("Data Warehouse", (r"data\s?warehouse", r"\bdw\b")),
    ("Modelagem de dados", (r"modelagem de dados", r"data model(l)?ing", r"modelagem dimensional")),
    ("Streaming", (r"\bstreaming\b", r"tempo real", r"real[- ]time")),
    ("APIs REST", (r"\brest(ful)?\b", r"\bapis?\b")),
    ("Scrum / Ágil", (r"\bscrum\b", r"\bagil\b", r"\bagile\b", r"\bkanban\b")),
    ("Jira", (r"\bjira\b",)),
)

ENGLISH_REQUIRED = (
    r"ingles (fluente|avancado|intermediario|tecnico|conversacional|proficiente)",
    r"(fluente|avancado|proficiencia) em ingles",
    r"(fluent|advanced|proficient|strong|excellent|good|professional)\s+(level of\s+)?english",
    r"english (fluency|proficiency|is (a )?(must|required))",
    r"\b(b2|c1|c2)\b.{0,30}(ingles|english)",
    r"(ingles|english).{0,30}\b(b2|c1|c2)\b",
)
ENGLISH_PLUS = (
    r"(ingles|english).{0,50}(diferencial|desejavel|plus|nice to have|sera um diferencial)",
    r"(diferencial|desejavel|nice to have|plus).{0,50}(ingles|english)",
)
EN_WORDS = re.compile(r"\b(the|and|with|you|your|we|our|experience|team|will|of|to|in|for|skills)\b")
PT_WORDS = re.compile(r"\b(de|e|com|voce|para|nos|nossa|experiencia|equipe|time|sera|em|do|da)\b")

INTERNATIONAL = (
    r"\busd\b", r"us\$", r"u\$", r"\bdolar(es)?\b", r"\beur\b", r"€", r"\bcontractor\b",
    r"\b(est|pst|cst|edt|pdt)\b", r"\bus[- ]based\b",
)
# Sinais fracos: só contam se nada indicar contratação no Brasil.
INTERNATIONAL_WEAK = (r"\bworldwide\b", r"\banywhere\b", r"\binternational\b", r"\bglobal team\b")
LATAM = (r"\blatam\b", r"latin america", r"america latina")
BRAZIL = (r"\bclt\b", r"\bpj\b", r"r\$", r"vale[- ](refeicao|alimentacao)", r"plano de saude", r"\bbrasil\b", r"\bbrazil\b")

MODES = (
    ("Híbrido", (r"\bhibrid[oa]\b", r"\bhybrid\b")),
    ("Remoto", (r"\bremot[oa]\b", r"\bremote\b", r"home[- ]office", r"\bwork from home\b", r"anywhere")),
    ("Presencial", (r"\bpresencial\b", r"\bon[- ]?site\b", r"\bin[- ]office\b")),
)

SENIORITY = (
    ("Estágio", (r"\bestagi(o|ario|aria)\b", r"\bintern(ship)?\b")),
    ("Júnior", (r"\bjunior\b", r"\bjr\.?\b", r"\bentry[- ]level\b", r"\bassistente\b")),
    ("Pleno", (r"\bpleno\b", r"\bmid([- ]level)?\b", r"\bii\b")),
    ("Sênior", (r"\bsenior\b", r"\bsr\.?\b", r"\biii\b")),
    ("Especialista / Lead", (r"\bespecialista\b", r"\blead\b", r"\bstaff\b", r"\bprincipal\b", r"\btech lead\b", r"\blider\b")),
)

MONEY = re.compile(
    r"(?:R\$|US\$|U\$|USD|EUR|€|\$)\s?\d[\d.,]*\s?(?:k|mil)?"
    r"(?:\s?(?:-|–|a|até|to)\s?(?:R\$|US\$|U\$|USD|EUR|€|\$)?\s?\d[\d.,]*\s?(?:k|mil)?)?"
    r"(?:\s?(?:/|por|per)\s?(?:m[eê]s|month|ano|year|hora|hour|h))?",
    re.IGNORECASE,
)
MONEY_CONTEXT = re.compile(r"sal[aá]rio|salary|remunera|compensation|pagamento|faixa|range|bolsa|pretens", re.IGNORECASE)


def _any(patterns: tuple[str, ...], text: str) -> bool:
    return any(re.search(pattern, text) for pattern in patterns)


def skills(text: str) -> list[str]:
    folded = fold(text or "")
    found: list[tuple[int, str]] = []
    for name, patterns in SKILLS:
        spots = [match.start() for pattern in patterns if (match := re.search(pattern, folded))]
        if spots:
            found.append((min(spots), name))
    names = [name for _, name in sorted(found)]
    if "PySpark" in names and "Spark" in names:
        names.remove("Spark")
    return names


def english(title: str, description: str) -> str:
    folded = fold(description or "")
    if _any(ENGLISH_PLUS, folded):
        return "diferencial"
    if _any(ENGLISH_REQUIRED, folded):
        return "obrigatório"
    en = len(EN_WORDS.findall(folded))
    pt = len(PT_WORDS.findall(folded))
    if en >= 20 and en > pt * 2:
        return "vaga em inglês"
    if re.search(r"\b(ingles|english)\b", folded):
        return "citado"
    return ""


def work_mode(title: str, location: str, description: str) -> str:
    for text in (fold(f"{title} {location}"), fold(description or "")):
        hits = [(match.start(), name) for name, patterns in MODES for p in patterns if (match := re.search(p, text))]
        if hits:
            return min(hits)[1]
    return ""


def salary(description: str) -> str:
    text = description or ""
    best = ""
    for match in MONEY.finditer(text):
        value = clean_space(match.group(0))
        if not re.search(r"\d{3,}|\d\s?(k|mil)\b", value, re.IGNORECASE):
            continue
        context = text[max(0, match.start() - 80):match.start()]
        if MONEY_CONTEXT.search(context):
            return value
        best = best or value
    return best


def region(location: str, description: str) -> str:
    folded = fold(f"{location} {description or ''}")
    if _any(LATAM, folded):
        return "LATAM"
    if _any(INTERNATIONAL, folded):
        return "internacional"
    if _any(BRAZIL, folded):
        return "Brasil"
    if _any(INTERNATIONAL_WEAK, folded):
        return "internacional"
    return ""


def seniority(title: str, from_site: str = "") -> str:
    folded = fold(title or "")
    for name, patterns in reversed(SENIORITY):
        if _any(patterns, folded):
            return name
    site = clean_space(from_site or "")
    if site and fold(site) not in {"nao aplicavel", "not applicable"}:
        return site
    return ""


def enrich(job: dict[str, Any]) -> dict[str, Any]:
    """Completa os campos extras vazios. O que já veio da página tem prioridade."""
    title, location, description = job.get("title", ""), job.get("location", ""), job.get("description", "")
    guesses = {
        "seniority": seniority(title, job.get("seniority", "")),
        "work_mode": work_mode(title, location, description),
        "english": english(title, description),
        "salary": salary(description),
        "region": region(location, description),
        "skills": ", ".join(skills(f"{title}\n{description}")),
    }
    filled = dict(job)
    for name, value in guesses.items():
        if value and (not filled.get(name) or name == "seniority"):
            filled[name] = value
    return filled


def fit(job_skills: str, mine: list[str]) -> dict[str, list[str]]:
    wanted = [item.strip() for item in (job_skills or "").split(",") if item.strip()]
    have = {fold(item) for item in mine}
    return {
        "tem": [item for item in wanted if fold(item) in have],
        "falta": [item for item in wanted if fold(item) not in have],
    }
