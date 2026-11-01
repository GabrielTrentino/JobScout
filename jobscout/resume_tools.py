"""Editor de currículo: o que o JobScout entendeu, o que falta e o que dá para achar na internet.

Leitura e checagens são por regras. A revisão pela IA e a busca online só rodam quando a pessoa pede.
Nada aqui muda o currículo: sugere, e a pessoa decide o que entra.
"""

from __future__ import annotations

import html
import json
import re
from datetime import date
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from jobscout import insights, llm, suggest
from jobscout.activities import fold, list_activities

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Safari/537.36"
NUMBER = re.compile(r"\d")
GITHUB_URL = re.compile(r"github\.com/([A-Za-z0-9-]{1,39})(?:[/?#]|$)", re.I)
LINKEDIN_URL = re.compile(r"linkedin\.com/in/([A-Za-z0-9\-_%]{3,100})", re.I)

# Linguagem do GitHub -> skill do JobScout (o que não está aqui entra com o próprio nome).
GITHUB_SKILLS = {
    "Jupyter Notebook": "Python", "HCL": "Terraform", "PLpgSQL": "SQL", "TSQL": "SQL", "PLSQL": "SQL",
    "Dockerfile": "Docker", "Shell": "Shell", "C#": "C#", "Vue": "Vue",
}

REVIEW_SYSTEM = (
    "Você revisa currículos de tecnologia. Use só o que está no texto; não invente experiências. "
    "Aponte lacunas que atrapalham formulários de candidatura: cargos sem data, skills sem contexto ou tempo de uso, "
    "resultados sem números, tecnologias citadas sem onde foram usadas. Para cada ponto, faça uma pergunta curta "
    "para a pessoa responder e completar o currículo. Responda no idioma do currículo. "
    'Responda só com JSON: {"resumo": "duas frases", "pontos": [{"tipo": "lacuna|melhoria|pergunta", "texto": "...", "pergunta": "..."}]}'
)


def understood(profile: dict[str, Any], today: date | None = None) -> dict[str, Any]:
    """Cargos com período e anos por skill, como as sugestões vão calcular."""
    resume = profile.get("curriculo") or ""
    roles = []
    for group in list_activities(resume):
        span = suggest.period_months(str(group["periodo"]), today)
        text = " ".join([str(group["contexto"])] + [str(item) for item in group["atividades"]])
        roles.append({
            "secao": group["secao"],
            "cargo": group["contexto"],
            "periodo": group["periodo"],
            "meses": span[1] - span[0] + 1 if span else None,
            "atividades": len(group["atividades"]),
            "skills": insights.skills(text),
            "conta": not suggest.NOT_EDUCATION.search(fold(str(group["secao"]))),
        })
    skills = []
    names = list(dict.fromkeys(insights.skills(resume) + [extra["skill"] for extra in profile.get("skills_extras") or []]))
    for name in names:
        info = suggest.experience(resume, name, today)
        extra = suggest.declared_years(profile, name)
        months = info["meses"] if info else 0
        skills.append({
            "skill": name,
            "meses": months,
            "anos_curriculo": round(months / 12, 1),
            "cargos": info["cargos"] if info else 0,
            "de": info["de"] if info else None,
            "ate": info["ate"] if info else None,
            "anos_informados": extra["anos"] if extra else None,
            "nota": extra.get("nota", "") if extra else "",
            "vale": max(months / 12, extra["anos"] if extra else 0),
        })
    skills.sort(key=lambda item: -item["vale"])
    return {"cargos": roles, "skills": skills}


def checks(profile: dict[str, Any], today: date | None = None) -> list[dict[str, str]]:
    """Pontos que dá para ver sem IA."""
    data = understood(profile, today)
    points: list[dict[str, str]] = []
    resume = profile.get("curriculo") or ""
    if not resume.strip():
        return [{"tipo": "lacuna", "texto": "O currículo está vazio. Importe o PDF/DOCX ou cole o texto.", "pergunta": ""}]
    work = [role for role in data["cargos"] if role["conta"]]
    if not work:
        points.append({"tipo": "lacuna", "texto": "Não achei cargos com período. Use uma linha por cargo, como “Cargo | Empresa” e logo abaixo “jan 2021 – atual”.", "pergunta": ""})
    for role in work:
        if role["meses"] is None:
            points.append({"tipo": "lacuna", "texto": f"“{role['cargo'] or 'Cargo sem nome'}” está sem período. Sem data, os anos de experiência ficam de fora.", "pergunta": "Quando começou e quando terminou?"})
        elif not role["skills"]:
            points.append({"tipo": "melhoria", "texto": f"“{role['cargo']}” não cita ferramentas. Perguntas como “quantos anos com X” não contam esse período.", "pergunta": "Quais ferramentas você usava nesse cargo?"})
    for skill in data["skills"]:
        if skill["skill"] in insights.skills(resume) and skill["meses"] == 0 and not skill["anos_informados"]:
            points.append({"tipo": "melhoria", "texto": f"{skill['skill']} aparece no currículo, mas fora de um cargo com data: nos formulários vira 0 anos.", "pergunta": f"Há quanto tempo você usa {skill['skill']}?"})
    activities = sum(role["atividades"] for role in work)
    with_numbers = sum(1 for group in list_activities(resume) for item in group["atividades"] if NUMBER.search(str(item)))
    if activities >= 4 and with_numbers / activities < 0.25:
        points.append({"tipo": "melhoria", "texto": f"Só {with_numbers} de {activities} atividades têm números (volume, %, tempo, dinheiro).", "pergunta": "Que resultado medível cada atividade trouxe?"})
    if not (profile.get("linkedin") or LINKEDIN_URL.search(resume)):
        points.append({"tipo": "lacuna", "texto": "Sem link do LinkedIn no Perfil.", "pergunta": ""})
    if not (profile.get("github") or GITHUB_URL.search(resume)):
        points.append({"tipo": "melhoria", "texto": "Sem GitHub no Perfil. Se tiver, ele ajuda a mostrar há quanto tempo você usa cada linguagem.", "pergunta": ""})
    return points


MISSING_DATES = re.compile(r"(sem data|sem per[ií]odo|datas? (?:de inicio|de início|espec[ií]ficas)|without dates|missing dates)", re.I)


def review(profile_text: str, profile: dict[str, Any] | None = None) -> dict[str, Any]:
    """Revisão pela IA. Levanta llm.LLMUnavailable se não houver modelo.

    Modelos pequenos às vezes dizem que faltam datas quando não faltam: com o perfil, as regras conferem.
    """
    raw = llm.ask_llm("curriculo", f"Currículo e perfil:\n{profile_text[:12000]}", system=REVIEW_SYSTEM, as_json=True, timeout=180)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.S)
        data = json.loads(match.group(0)) if match else {}
    all_dated = bool(profile) and all(
        role["meses"] is not None for role in understood(profile)["cargos"] if role["conta"]
    ) and bool(understood(profile)["cargos"])
    points = []
    for item in data.get("pontos") or []:
        if all_dated and isinstance(item, dict) and MISSING_DATES.search(f"{item.get('texto', '')} {item.get('pergunta', '')}"):
            continue
        if isinstance(item, dict) and str(item.get("texto") or "").strip():
            points.append({
                "tipo": str(item.get("tipo") or "melhoria")[:20],
                "texto": " ".join(str(item["texto"]).split())[:400],
                "pergunta": " ".join(str(item.get("pergunta") or "").split())[:300],
            })
    return {"resumo": " ".join(str(data.get("resumo") or "").split())[:600], "pontos": points[:15], "modelo": llm.model_name("curriculo")}


# Na internet

Opener = Callable[..., Any]


def _get(url: str, opener: Opener, timeout: float, accept: str = "text/html") -> tuple[int, str]:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept, "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8"})
    try:
        with opener(request, timeout=timeout) as response:
            return response.status, response.read(2_000_000).decode("utf-8", "replace")
    except HTTPError as exc:
        return exc.code, ""
    except (URLError, TimeoutError, OSError):
        return 0, ""


def github_user(profile: dict[str, Any]) -> str:
    for source in (profile.get("github") or "", profile.get("curriculo") or ""):
        match = GITHUB_URL.search(source)
        if match and match.group(1).lower() not in {"orgs", "topics", "features", "about"}:
            return match.group(1)
    raw = (profile.get("github") or "").strip().lstrip("@")
    return raw if re.fullmatch(r"[A-Za-z0-9-]{1,39}", raw) else ""


def github(user: str, opener: Opener = urlopen, timeout: float = 10) -> dict[str, Any]:
    """Repositórios públicos: linguagens com a quantidade e os anos de uso (do primeiro ao último push)."""
    status, body = _get(f"https://api.github.com/users/{user}", opener, timeout, "application/vnd.github+json")
    if status != 200:
        return {"ok": False, "usuario": user, "erro": "Usuário não encontrado no GitHub." if status == 404 else f"GitHub não respondeu ({status or 'sem conexão'})."}
    account = json.loads(body)
    status, body = _get(f"https://api.github.com/users/{user}/repos?per_page=100&sort=pushed", opener, timeout, "application/vnd.github+json")
    repos = json.loads(body) if status == 200 else []
    languages: dict[str, dict[str, Any]] = {}
    for repo in repos:
        if repo.get("fork") or not repo.get("language"):
            continue
        name = GITHUB_SKILLS.get(repo["language"], repo["language"])
        first, last = int(str(repo.get("created_at") or "0")[:4] or 0), int(str(repo.get("pushed_at") or "0")[:4] or 0)
        item = languages.setdefault(name, {"skill": name, "repos": 0, "de": first, "ate": last, "estrelas": 0, "exemplos": []})
        item["repos"] += 1
        item["de"] = min(item["de"], first) if first else item["de"]
        item["ate"] = max(item["ate"], last)
        item["estrelas"] += int(repo.get("stargazers_count") or 0)
        if len(item["exemplos"]) < 3:
            item["exemplos"].append(repo.get("name") or "")
    ranked = sorted(languages.values(), key=lambda item: (-item["repos"], item["skill"]))
    for item in ranked:
        item["anos"] = max(1, item["ate"] - item["de"] + 1) if item["de"] and item["ate"] else None
    return {
        "ok": True,
        "usuario": user,
        "nome": account.get("name") or "",
        "bio": account.get("bio") or "",
        "site": account.get("blog") or "",
        "desde": str(account.get("created_at") or "")[:4],
        "repositorios": account.get("public_repos") or 0,
        "linguagens": ranked,
        "url": account.get("html_url") or f"https://github.com/{user}",
    }


def _meta(page: str, name: str) -> str:
    match = re.search(rf'<meta[^>]+(?:property|name)="{re.escape(name)}"[^>]+content="([^"]*)"', page, re.I) or re.search(
        rf'<meta[^>]+content="([^"]*)"[^>]+(?:property|name)="{re.escape(name)}"', page, re.I
    )
    return html.unescape(match.group(1)).strip() if match else ""


def linkedin(url_or_slug: str, opener: Opener = urlopen, timeout: float = 10) -> dict[str, Any]:
    """Perfil público do LinkedIn. Quase sempre pede login; nesse caso diz como trazer os dados."""
    match = LINKEDIN_URL.search(url_or_slug or "")
    slug = match.group(1) if match else (url_or_slug or "").strip().strip("/")
    if not slug:
        return {"ok": False, "erro": "Sem link do LinkedIn no Perfil."}
    url = f"https://www.linkedin.com/in/{slug}/"
    status, page = _get(url, opener, timeout)
    title = _meta(page, "og:title") if status == 200 else ""
    if not title or "authwall" in page[:5000].lower():
        return {
            "ok": False,
            "url": url,
            "erro": "O LinkedIn não mostra o perfil sem login. Para trazer os dados: no seu perfil, clique em “Mais” > “Salvar em PDF” e importe o PDF aqui.",
        }
    return {"ok": True, "url": url, "titulo": title, "descricao": _meta(page, "og:description") or _meta(page, "description")}


def website(url: str, opener: Opener = urlopen, timeout: float = 10) -> dict[str, Any]:
    if urlparse(url).scheme not in {"http", "https"}:
        url = "https://" + url.strip().lstrip("/")
    status, page = _get(url, opener, timeout)
    if status != 200:
        return {"ok": False, "url": url, "erro": f"O site não respondeu ({status or 'sem conexão'})."}
    title = re.search(r"<title[^>]*>(.*?)</title>", page, re.I | re.S)
    return {
        "ok": True,
        "url": url,
        "titulo": html.unescape(" ".join(title.group(1).split()))[:200] if title else "",
        "descricao": (_meta(page, "description") or _meta(page, "og:description"))[:400],
        "skills": insights.skills(re.sub(r"<[^>]+>", " ", page))[:15],
    }


def online(profile: dict[str, Any], opener: Opener = urlopen) -> dict[str, Any]:
    result: dict[str, Any] = {}
    user = github_user(profile)
    result["github"] = github(user, opener) if user else {"ok": False, "erro": "Sem GitHub no Perfil (campo GitHub ou link no currículo)."}
    linked = profile.get("linkedin") or ""
    if not linked:
        match = LINKEDIN_URL.search(profile.get("curriculo") or "")
        linked = match.group(0) if match else ""
    result["linkedin"] = linkedin(linked, opener)
    site = profile.get("portfolio") or (result["github"].get("site") if result["github"].get("ok") else "")
    result["site"] = website(site, opener) if site else {"ok": False, "erro": "Sem site pessoal ou portfólio no Perfil."}
    return result
