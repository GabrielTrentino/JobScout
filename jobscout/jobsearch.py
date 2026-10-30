"""Busca automática de vagas a cada X horas, pelo que a pessoa procura (títulos, empresas, palavras).

Fontes, todas públicas e sem login:
- Gupy: a página de busca do portal (portal.gupy.io/job-search) traz as vagas no próprio HTML.
- Himalayas: API pública de vagas remotas, com busca por termo e país (só as abertas ao país do Perfil).
- InHire: a lista pública de cada empresa ({empresa}.inhire.app), pela mesma API que a página usa.
- Greenhouse, Lever e Ashby: API pública do quadro de vagas de cada empresa listada.
- LinkedIn: os alertas de vaga que o LinkedIn manda por e-mail, lidos pelo Gmail. O LinkedIn não tem
  API de busca para uso pessoal e a busca sem login vai contra os termos de uso, então não é usada.

Limites: poucas requisições por rodada (uma por título na Gupy, uma por empresa na InHire), com pausa
entre elas, e intervalo mínimo de MIN_HOURS entre rodadas. Nada é salvo como vaga sem a pessoa pedir.
"""

from __future__ import annotations

import html
import json
import re
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from jobscout import places
from jobscout.activities import clean_space, fold

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Safari/537.36"
GUPY_SEARCH = "https://portal.gupy.io/job-search/term={term}"
INHIRE_API = "https://api.inhire.app/job-posts/public/pages"
INHIRE_JOB = "https://{tenant}.inhire.app/vagas/{job_id}"
HIMALAYAS_API = "https://himalayas.app/jobs/api/search?q={term}&limit=20"
ATS_API = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true",
    "lever": "https://api.lever.co/v0/postings/{slug}?mode=json",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{slug}",
}
ATS_HOSTS = (
    ("greenhouse", re.compile(r"greenhouse\.io/(?:embed/job_board\?for=)?([a-z0-9-]+)")),
    ("lever", re.compile(r"lever\.co/([a-z0-9-]+)")),
    ("ashby", re.compile(r"ashbyhq\.com/([a-z0-9-]+)")),
)
MAX_COMPANIES = 20
MAX_HIMALAYAS = 3
MIN_HOURS = 2
MAX_HOURS = 168
PAUSE_SECONDS = 2.0
MAX_TERMS = 8
MAX_TENANTS = 20
MIN_SCORE = 30
WORK_MODES = {"remoto": "Remoto", "hibrido": "Híbrido", "presencial": "Presencial"}
# O que a pessoa aceita: presencial se divide entre a cidade atual e mudando de cidade.
ACCEPTED_MODES = {
    "remoto": "Remoto", "hibrido": "Híbrido",
    "presencial_cidade": "Presencial (na cidade atual)", "presencial_mudanca": "Presencial (mudando de cidade)",
}

# Títulos equivalentes, em qualquer idioma. Procurar um procura os outros.
SYNONYMS: tuple[tuple[str, ...], ...] = (
    ("Engenheiro de Dados", "Engenheira de Dados", "Data Engineer", "Analytics Engineer", "Engenheiro de Analytics", "ETL Developer"),
    ("Analista de Dados", "Data Analyst", "Analista de BI", "BI Analyst", "Business Intelligence Analyst"),
    ("Cientista de Dados", "Data Scientist", "Machine Learning Scientist"),
    ("Engenheiro de Machine Learning", "Machine Learning Engineer", "ML Engineer", "MLOps Engineer", "AI Engineer"),
    ("Arquiteto de Dados", "Data Architect"),
    ("Engenheiro de Software", "Software Engineer", "Desenvolvedor de Software", "Software Developer"),
    ("Desenvolvedor Backend", "Desenvolvedor Back-end", "Backend Developer", "Back-end Engineer", "Backend Engineer"),
    ("Desenvolvedor Frontend", "Desenvolvedor Front-end", "Frontend Developer", "Front-end Engineer", "Frontend Engineer"),
    ("Desenvolvedor Full Stack", "Full Stack Developer", "Fullstack Engineer", "Full Stack Engineer"),
    ("Engenheiro DevOps", "DevOps Engineer", "Site Reliability Engineer", "SRE", "Platform Engineer"),
    ("Arquiteto de Software", "Software Architect", "Solutions Architect", "Arquiteto de Soluções"),
    ("Analista de Sistemas", "Systems Analyst"),
    ("Analista de Testes", "QA Engineer", "Test Engineer", "Analista de QA", "QA Analyst"),
    ("Gerente de Produto", "Product Manager", "PM"),
    ("Designer de Produto", "Product Designer", "UX Designer", "Designer UX"),
    ("Gerente de Projetos", "Project Manager"),
    ("Analista de Marketing", "Marketing Analyst"),
    ("Recrutador", "Recrutadora", "Recruiter", "Talent Acquisition"),
)
SENIORITY_WORDS = re.compile(r"\b(junior|jr|pleno|pl|senior|sr|especialista|lead|staff|principal|i{1,3})\b\.?", re.I)
# Palavra a palavra, para o que não está na tabela: "Analista de Suporte" -> "Support Analyst".
ROLE_WORDS = {
    "engenheiro": "Engineer", "engenheira": "Engineer", "analista": "Analyst", "desenvolvedor": "Developer", "desenvolvedora": "Developer",
    "gerente": "Manager", "coordenador": "Coordinator", "coordenadora": "Coordinator", "arquiteto": "Architect", "arquiteta": "Architect",
    "consultor": "Consultant", "consultora": "Consultant", "especialista": "Specialist", "cientista": "Scientist", "designer": "Designer",
}
AREA_WORDS = {
    "dados": "Data", "software": "Software", "suporte": "Support", "seguranca": "Security", "infraestrutura": "Infrastructure", "redes": "Network",
    "produto": "Product", "projetos": "Project", "vendas": "Sales", "financeiro": "Finance", "negocios": "Business", "sistemas": "Systems",
    "qualidade": "Quality", "marketing": "Marketing", "operacoes": "Operations", "recursos": "Resources", "automacao": "Automation",
}

DEFAULTS: dict[str, Any] = {
    "ativo": False,
    "intervalo_horas": 6,
    "titulos": [],
    "empresas": [],
    "palavras": [],
    "excluir": [],
    "modelos": [],
    "local": "",
    "fontes": {"gupy": True, "himalayas": True, "inhire": True, "ats": True, "linkedin_email": True},
    "inhire_empresas": [],
    "ats_empresas": [],
    "expandir": True,
    "ultima": None,
}


class SearchError(RuntimeError):
    pass


def _words(raw: Any, limit: int = 20) -> list[str]:
    items = raw if isinstance(raw, list) else re.split(r"[,\n;]", str(raw or ""))
    result, seen = [], set()
    for item in items:
        value = clean_space(str(item))[:60]
        if value and fold(value) not in seen:
            seen.add(fold(value))
            result.append(value)
    return result[:limit]


def _tenant(value: str) -> str:
    """"olist", "olist.inhire.app" ou "https://olist.inhire.app/vagas" → "olist"."""
    value = fold(value).strip()
    match = re.search(r"([a-z0-9-]+)\.inhire\.app", value)
    return match.group(1) if match else re.sub(r"[^a-z0-9-]", "", value)


def _ats_company(value: str) -> str:
    """"greenhouse:gitlab" ou o link do quadro de vagas -> "greenhouse:gitlab"; sem sistema reconhecido, vazio."""
    text = fold(value).strip()
    prefix = re.match(r"^(greenhouse|lever|ashby)\s*:\s*([a-z0-9-]+)$", text)
    if prefix:
        return f"{prefix.group(1)}:{prefix.group(2)}"
    for name, pattern in ATS_HOSTS:
        match = pattern.search(text)
        if match:
            return f"{name}:{match.group(1)}"
    return ""


def similar_titles(title: str) -> list[str]:
    """Títulos equivalentes em outros idiomas: "Engenheiro de Dados Sr" -> Data Engineer, Analytics Engineer..."""
    plain = clean_space(SENIORITY_WORDS.sub(" ", fold(title).replace("(a)", "")))
    for group in SYNONYMS:
        if plain in {fold(name) for name in group}:
            return [name for name in group if fold(name) != fold(title)]
    match = re.match(r"^(\w+)(?: (?:de|do|da|em))? (\w+)$", plain)
    if match and match.group(1) in ROLE_WORDS and match.group(2) in AREA_WORDS:
        return [f"{AREA_WORDS[match.group(2)]} {ROLE_WORDS[match.group(1)]}"]
    return []


def search_terms(config: dict[str, Any]) -> list[str]:
    """Os títulos pedidos e os similares, sem repetir: os pedidos vêm primeiro."""
    terms = list(config["titulos"])
    if config.get("expandir", True):
        for title in config["titulos"]:
            terms += similar_titles(title)
    unique, seen = [], set()
    for term in terms:
        if fold(term) not in seen:
            seen.add(fold(term))
            unique.append(term)
    return unique


def profile_modes(accepted: str) -> list[str]:
    """Modelos aceitos no Perfil -> chaves da busca."""
    folded = fold(accepted)
    keys = []
    if "remoto" in folded:
        keys.append("remoto")
    if "hibrido" in folded:
        keys.append("hibrido")
    if "cidade atual" in folded or re.search(r"presencial(?! \()", folded):
        keys.append("presencial_cidade")
    if "mudando" in folded:
        keys.append("presencial_mudanca")
    return keys


def clean_config(raw: Any, current: dict[str, Any] | None = None) -> dict[str, Any]:
    base = {**DEFAULTS, **(current or {})}
    data = raw if isinstance(raw, dict) else {}
    merged = {**base, **{key: value for key, value in data.items() if key in DEFAULTS}}
    try:
        hours = int(merged["intervalo_horas"])
    except (TypeError, ValueError) as exc:
        raise ValueError("Intervalo inválido.") from exc
    if not MIN_HOURS <= hours <= MAX_HOURS:
        raise ValueError(f"Busque a cada {MIN_HOURS} a {MAX_HOURS} horas (limite para não ser bloqueado pelos sites).")
    sources = merged.get("fontes") if isinstance(merged.get("fontes"), dict) else {}
    tenants = [_tenant(item) for item in _words(merged["inhire_empresas"], MAX_TENANTS)]
    return {
        "ativo": bool(merged["ativo"]),
        "intervalo_horas": hours,
        "titulos": _words(merged["titulos"], MAX_TERMS),
        "empresas": _words(merged["empresas"]),
        "palavras": _words(merged["palavras"]),
        "excluir": _words(merged["excluir"]),
        # "presencial" é de antes da divisão entre cidade atual e mudança.
        "modelos": [mode for mode in ("presencial_mudanca" if item == "presencial" else item for item in _words(merged["modelos"])) if mode in ACCEPTED_MODES],
        "local": clean_space(str(merged.get("local") or ""))[:80],
        "fontes": {name: bool(sources.get(name, DEFAULTS["fontes"][name])) for name in DEFAULTS["fontes"]},
        "inhire_empresas": [tenant for tenant in tenants if tenant],
        "ats_empresas": [company for company in (_ats_company(item) for item in _words(merged["ats_empresas"], MAX_COMPANIES)) if company],
        "expandir": bool(merged.get("expandir", True)),
        "ultima": merged.get("ultima"),
    }


# Pontuação: o quanto a vaga bate com o que a pessoa procura

def _mode(text: str) -> str:
    folded = fold(text)
    if re.search(r"remot|remote|home ?office", folded):
        return "remoto"
    if re.search(r"hibrid|hybrid", folded):
        return "hibrido"
    if re.search(r"presencial|on-?site", folded):
        return "presencial"
    return ""


def _has(haystack: str, needle: str) -> bool:
    return bool(re.search(rf"(?<![a-z0-9]){re.escape(fold(needle))}(?![a-z0-9])", haystack))


def score(item: dict[str, Any], config: dict[str, Any]) -> tuple[int, list[str]]:
    """0 a 100, com os motivos. Palavra excluída zera."""
    title = fold(item.get("title") or "")
    company = fold(item.get("company") or "")
    everything = " ".join(fold(item.get(key) or "") for key in ("title", "company", "location", "work_mode", "description"))
    for word in config["excluir"]:
        if _has(everything, word):
            return 0, [f"tem “{word}” (excluído)"]
    points, reasons = 0, []
    titles = [term for term in config["titulos"] if _has(title, term)]
    if titles:
        points += 50
        reasons.append("título: " + ", ".join(titles))
    similar = [term for term in search_terms(config) if term not in config["titulos"] and _has(title, term)]
    if not titles and similar:
        points += 45
        reasons.append("título similar: " + similar[0])
    elif not titles and config["titulos"]:
        # Parte das palavras do título procurado ("Engenheiro de Dados" → "Engenheira de Dados Sênior").
        # Cada título procurado conta sozinho; o começo da palavra (6 letras) aceita gênero e plural.
        for term in config["titulos"]:
            stems = {token[:6] for token in re.findall(r"[a-z0-9]{4,}", fold(term))}
            hits = [stem for stem in stems if stem in title]
            if stems and len(hits) >= max(1, len(stems) - (len(stems) // 3)):
                points += 30
                reasons.append("título parecido")
                break
    companies = [name for name in config["empresas"] if _has(company, name)]
    if companies:
        points += 40
        reasons.append("empresa: " + companies[0])
    words = [word for word in config["palavras"] if _has(everything, word)]
    if words:
        points += min(30, 10 * len(words))
        reasons.append("tem: " + ", ".join(words[:5]))
    mode = item.get("work_mode") or _mode(everything)
    if config["modelos"] and mode:
        wanted = mode in config["modelos"]
        if mode == "presencial":
            city = config.get("cidade") or ""
            here = bool(city) and _has(everything, city)
            wanted = "presencial_mudanca" in config["modelos"] or ("presencial_cidade" in config["modelos"] and here)
            label = "Presencial (na sua cidade)" if here else "Presencial (mudando de cidade)"
        else:
            label = WORK_MODES[mode]
        if wanted:
            points += 15
            reasons.append(label)
        else:
            points -= 30
            reasons.append(f"{label} (fora do que você quer)")
    if config["local"] and _has(everything, config["local"]):
        points += 10
        reasons.append(config["local"])
    return max(0, min(100, points)), reasons


# Fontes

def _get(url: str, opener: Callable[..., Any], headers: dict[str, str] | None = None, timeout: float = 20) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "pt-BR,pt;q=0.9", **(headers or {})})
    try:
        with opener(request, timeout=timeout) as response:
            return response.read().decode("utf-8", "replace")
    except HTTPError as exc:
        if exc.code == 429:
            raise SearchError("o site pediu para esperar (429); a próxima rodada tenta de novo") from exc
        raise SearchError(f"respondeu {exc.code}") from exc
    except (URLError, OSError) as exc:
        raise SearchError(f"sem conexão: {exc}") from exc


def _strip(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html.unescape(text or ""))
    return clean_space(text)


GUPY_MODES = {"remote": "remoto", "hybrid": "hibrido", "on-site": "presencial", "onsite": "presencial"}


def parse_gupy(page: str) -> list[dict[str, Any]]:
    match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', page, re.S)
    if not match:
        raise SearchError("a página da Gupy mudou (sem dados de vagas)")
    try:
        data = json.loads(match.group(1))
        jobs = data["props"]["pageProps"]["initialJobList"]["data"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise SearchError("a página da Gupy mudou (formato novo)") from exc
    result = []
    for job in jobs:
        url = str(job.get("jobUrl") or "").split("?")[0]
        if not url:
            continue
        place = ", ".join(part for part in (job.get("city"), job.get("state")) if part)
        result.append({
            "source": "gupy",
            "url": url,
            "title": clean_space(str(job.get("name") or "")),
            "company": clean_space(str(job.get("careerPageName") or "")),
            "location": place,
            "work_mode": GUPY_MODES.get(str(job.get("workplaceType") or "").lower(), ""),
            "description": _strip(str(job.get("description") or ""))[:3000],
            "published_at": job.get("publishedDate"),
        })
    return result


INHIRE_MODES = {"remote": "remoto", "hybrid": "hibrido", "on-site": "presencial", "onsite": "presencial"}


def parse_inhire(data: dict[str, Any], tenant: str) -> list[dict[str, Any]]:
    company = clean_space(str(data.get("tenantName") or tenant))
    result = []
    for job in data.get("jobsPage") or []:
        if job.get("status") not in (None, "published") or not job.get("jobId"):
            continue
        result.append({
            "source": "inhire",
            "url": INHIRE_JOB.format(tenant=tenant, job_id=job["jobId"]),
            "title": clean_space(str(job.get("displayName") or "")),
            "company": company,
            "location": clean_space(str(job.get("location") or "")),
            "work_mode": INHIRE_MODES.get(str(job.get("workplaceType") or "").lower(), ""),
            "description": "",
            "published_at": None,
        })
    return result


def parse_himalayas(data: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    for job in data.get("jobs") or []:
        url = job.get("applicationLink") or job.get("guid")
        if not url:
            continue
        places_open = job.get("locationRestrictions") or []
        result.append({
            "source": "himalayas", "url": url, "title": clean_space(str(job.get("title") or "")),
            "company": clean_space(str(job.get("companyName") or "")),
            "location": "Remoto: " + (", ".join(places_open[:3]) + ("…" if len(places_open) > 3 else "") if places_open else "qualquer país"),
            "work_mode": "remoto", "description": _strip(str(job.get("description") or job.get("excerpt") or ""))[:3000],
            "published_at": None,
        })
    return result


def parse_ats(system: str, slug: str, data: Any) -> list[dict[str, Any]]:
    """Quadro de vagas público de uma empresa, nos três formatos."""
    company = slug.replace("-", " ").title()
    result = []
    if system == "greenhouse":
        for job in (data.get("jobs") if isinstance(data, dict) else None) or []:
            place = clean_space(str((job.get("location") or {}).get("name") or ""))
            result.append({
                "source": "greenhouse", "url": job.get("absolute_url") or "", "title": clean_space(str(job.get("title") or "")),
                "company": clean_space(str(job.get("company_name") or company)), "location": place, "work_mode": _mode(place),
                "description": _strip(html.unescape(str(job.get("content") or "")))[:3000], "published_at": job.get("first_published"),
            })
    elif system == "lever":
        for job in data if isinstance(data, list) else []:
            place = clean_space(str((job.get("categories") or {}).get("location") or ""))
            result.append({
                "source": "lever", "url": job.get("hostedUrl") or "", "title": clean_space(str(job.get("text") or "")),
                "company": company, "location": place,
                "work_mode": {"remote": "remoto", "hybrid": "hibrido", "on-site": "presencial"}.get(str(job.get("workplaceType") or "").lower(), _mode(place)),
                "description": clean_space(str(job.get("descriptionPlain") or ""))[:3000], "published_at": None,
            })
    else:
        for job in (data.get("jobs") if isinstance(data, dict) else None) or []:
            if job.get("isListed") is False:
                continue
            kind = str(job.get("workplaceType") or "").lower()
            result.append({
                "source": "ashby", "url": job.get("jobUrl") or "", "title": clean_space(str(job.get("title") or "")),
                "company": company, "location": clean_space(str(job.get("location") or "")),
                "work_mode": {"remote": "remoto", "hybrid": "hibrido", "onsite": "presencial"}.get(kind, "remoto" if job.get("isRemote") else ""),
                "description": clean_space(str(job.get("descriptionPlain") or ""))[:3000], "published_at": job.get("publishedAt"),
            })
    return [item for item in result if item["url"]]


LINKEDIN_JOB = re.compile(r"linkedin\.com/(?:comm/)?jobs/view/(\d+)")


CALL_TO_ACTION = re.compile(r"^(ver vaga|ver todas|view job|see all|candidat|apply|easy apply|candidatura simplificada)", re.I)


def _html_lines(page: str) -> list[tuple[str, str]]:
    """O HTML do e-mail em linhas (texto, link): o texto do link fica junto do endereço dele."""
    page = re.sub(r"(?is)<(script|style).*?</\1>", " ", page)
    page = re.sub(
        r'(?is)<a[^>]+href="([^"]*)"[^>]*>(.*?)</a>',
        lambda match: "\n\x01" + match.group(1) + "\x02" + _strip(match.group(2)) + "\n",
        page,
    )
    page = re.sub(r"(?i)<br\s*/?>|</(p|div|li|td|tr|h\d|table)>", "\n", page)
    lines = []
    for raw in re.sub(r"<[^>]+>", " ", page).split("\n"):
        if raw.startswith("\x01"):
            href, _, text = raw[1:].partition("\x02")
            lines.append((clean_space(text), html.unescape(href)))
        elif clean_space(html.unescape(raw)):
            lines.append((clean_space(html.unescape(raw)), ""))
    return lines


def parse_linkedin_alert(message: dict[str, Any]) -> list[dict[str, Any]]:
    """Vagas de um e-mail de alerta do LinkedIn.

    No HTML, o título é o texto do link da vaga e empresa e local vêm nas linhas seguintes.
    No texto puro, título, empresa e local vêm nas linhas antes do link ("View job: https://...").
    """
    found: dict[str, dict[str, Any]] = {}
    if message.get("html"):
        lines = _html_lines(message["html"])
        for index, (text, href) in enumerate(lines):
            match = LINKEDIN_JOB.search(href)
            if not match or not text or CALL_TO_ACTION.match(text):
                continue
            entry = found.setdefault(match.group(1), {"title": text, "lines": []})
            if not entry["lines"]:
                after = []
                for following, link in lines[index + 1:index + 5]:
                    if LINKEDIN_JOB.search(link) or CALL_TO_ACTION.match(following):
                        break
                    if not link:
                        after.append(following)
                entry["lines"] = after[:2]
    if not found:
        lines = [line.strip() for line in str(message.get("corpo") or "").splitlines()]
        for index, line in enumerate(lines):
            match = LINKEDIN_JOB.search(line)
            if not match or match.group(1) in found:
                continue
            before = []
            for item in reversed(lines[max(0, index - 4):index]):
                # Linha vazia, separador ("-----") ou o link da vaga anterior fecham o bloco.
                if not re.search(r"\w", item) or LINKEDIN_JOB.search(item):
                    break
                before.insert(0, item)
            if before:
                found[match.group(1)] = {"title": before[0], "lines": before[1:3]}
    result = []
    for job_id, entry in found.items():
        details = [clean_space(item) for item in entry["lines"] if clean_space(item)]
        result.append({
            "source": "linkedin_email",
            "url": f"https://www.linkedin.com/jobs/view/{job_id}/",
            "title": entry["title"][:160],
            "company": details[0][:120] if details else "",
            "location": details[1][:120] if len(details) > 1 else "",
            "work_mode": _mode(" ".join(details)),
            "description": "",
            "published_at": message.get("recebido_em"),
        })
    return result


class JobSearch:
    """Roda as fontes, pontua, guarda o que é novo e avisa. Uma rodada por vez."""

    def __init__(self, store: Any, hub: Any, load: Callable[[], dict[str, Any]], save: Callable[[dict[str, Any]], Any],
                 alerts: Callable[[], list[dict[str, Any]]] | None = None, opener: Callable[..., Any] = urlopen,
                 pause: float = PAUSE_SECONDS, profile: Callable[[], dict[str, Any]] | None = None,
                 fit: Callable[[dict[str, Any]], int | None] | None = None) -> None:
        self.store = store
        self.hub = hub
        self.load = load
        self.save = save
        self.alerts = alerts
        self.opener = opener
        self.pause = pause
        self.profile = profile or dict
        self.fit = fit or (lambda item: None)
        self._lock = threading.Lock()
        self._stop = threading.Event()

    def _gupy(self, config: dict[str, Any], notes: list[str]) -> list[dict[str, Any]]:
        terms = search_terms(config) or config["empresas"]
        found = []
        for index, term in enumerate(terms[:MAX_TERMS]):
            if index:
                time.sleep(self.pause)
            try:
                found += parse_gupy(_get(GUPY_SEARCH.format(term=quote(term)), self.opener))
            except SearchError as exc:
                notes.append(f"Gupy ({term}): {exc}")
        return found

    def _himalayas(self, config: dict[str, Any], notes: list[str]) -> list[dict[str, Any]]:
        # Inglês primeiro: as vagas de lá são em inglês.
        terms = sorted(search_terms(config), key=lambda term: not re.fullmatch(r"[A-Za-z /-]+", term) or " de " in term)
        found = []
        country = config.get("pais_en") or ""
        for index, term in enumerate(terms[:MAX_HIMALAYAS]):
            if index:
                time.sleep(self.pause)
            url = HIMALAYAS_API.format(term=quote(term)) + (f"&country={quote(country)}" if country else "")
            try:
                found += parse_himalayas(json.loads(_get(url, self.opener)))
            except SearchError as exc:
                notes.append(f"Himalayas ({term}): {exc}")
            except json.JSONDecodeError:
                notes.append(f"Himalayas ({term}): resposta inesperada")
        return found

    def _ats(self, config: dict[str, Any], notes: list[str]) -> list[dict[str, Any]]:
        found = []
        for index, company in enumerate(config["ats_empresas"][:MAX_COMPANIES]):
            if index:
                time.sleep(self.pause)
            system, slug = company.split(":", 1)
            try:
                found += parse_ats(system, slug, json.loads(_get(ATS_API[system].format(slug=slug), self.opener)))
            except SearchError as exc:
                notes.append(f"{system.title()} ({slug}): {'empresa não encontrada' if '404' in str(exc) else exc}")
            except json.JSONDecodeError:
                notes.append(f"{system.title()} ({slug}): resposta inesperada")
        return found

    def _inhire(self, config: dict[str, Any], notes: list[str]) -> list[dict[str, Any]]:
        found = []
        for index, tenant in enumerate(config["inhire_empresas"][:MAX_TENANTS]):
            if index:
                time.sleep(self.pause)
            try:
                data = json.loads(_get(INHIRE_API, self.opener, {"X-Tenant": tenant}))
                found += parse_inhire(data, tenant)
            except SearchError as exc:
                notes.append(f"InHire ({tenant}): {'empresa não encontrada' if '404' in str(exc) else exc}")
            except json.JSONDecodeError:
                notes.append(f"InHire ({tenant}): resposta inesperada")
        return found

    def run(self, manual: bool = False) -> dict[str, Any]:
        if not self._lock.acquire(blocking=False):
            raise SearchError("Já tem uma busca rodando.")
        try:
            config = clean_config(self.load())
            if not (config["titulos"] or config["empresas"] or config["palavras"]):
                raise SearchError("Diga o que procurar: títulos, empresas ou palavras.")
            profile = self.profile() or {}
            config["cidade"] = str(profile.get("cidade") or "")
            config["pais_en"] = places.country(str(profile.get("pais") or ""), "en")
            # Sem modelo marcado na busca, vale o que o Perfil aceita.
            config["modelos"] = config["modelos"] or profile_modes(str(profile.get("modelos_trabalho") or ""))
            self.hub.activity("Busca de vagas: procurando…", "trabalhando")
            notes: list[str] = []
            items: list[dict[str, Any]] = []
            if config["fontes"]["gupy"]:
                items += self._gupy(config, notes)
            if config["fontes"]["himalayas"] and config["titulos"]:
                items += self._himalayas(config, notes)
            if config["fontes"]["inhire"] and config["inhire_empresas"]:
                items += self._inhire(config, notes)
            if config["fontes"]["ats"] and config["ats_empresas"]:
                items += self._ats(config, notes)
            if config["fontes"]["linkedin_email"] and self.alerts:
                try:
                    for message in self.alerts():
                        items += parse_linkedin_alert(message)
                except Exception as exc:  # noqa: BLE001 - o Gmail é uma das fontes, não pode parar as outras
                    notes.append(f"Alertas do LinkedIn: {exc}")
            saved_urls = {job["url"] for job in self.store.jobs()}
            new = []
            for item in items:
                if item["url"] in saved_urls:
                    continue
                points, reasons = score(item, config)
                if points < MIN_SCORE:
                    continue
                result_id = self.store.add_search_result({**item, "score": points, "reasons": reasons, "fit": self.fit(item)})
                if result_id:
                    new.append({**item, "id": result_id, "score": points})
            when = datetime.now().astimezone().isoformat(timespec="seconds")
            self.save({"ultima": when})
            summary = {"em": when, "olhadas": len(items), "novas": len(new), "avisos": notes, "manual": manual}
            level = "aviso" if new else "ok"
            text = f"Busca de vagas: {len(new)} vaga(s) nova(s) que combinam, de {len(items)} olhada(s)."
            if notes:
                text += " " + " · ".join(notes[:3])
            self.hub.activity(text, level)
            self.hub.publish("busca", novas=len(new))
            return summary
        finally:
            self._lock.release()

    def next_run(self, config: dict[str, Any]) -> datetime | None:
        if not config["ativo"]:
            return None
        if not config.get("ultima"):
            return datetime.now().astimezone()
        return datetime.fromisoformat(config["ultima"]) + timedelta(hours=config["intervalo_horas"])

    def start(self, check_every: int = 300) -> None:
        def loop() -> None:
            while not self._stop.wait(check_every):
                try:
                    config = clean_config(self.load())
                    due = self.next_run(config)
                    if due and due <= datetime.now().astimezone():
                        self.run()
                except SearchError as exc:
                    self.hub.activity(f"Busca de vagas: {exc}", "info")
                except Exception as exc:  # noqa: BLE001 - não derruba o servidor
                    self.hub.activity(f"Busca de vagas falhou: {exc}", "erro")

        threading.Thread(target=loop, daemon=True).start()

    def stop(self) -> None:
        self._stop.set()
