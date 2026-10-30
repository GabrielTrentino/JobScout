"""Currículo completo: estrutura editável, texto para as sugestões, versões por vaga e PDF.

A estrutura (profile["cv"]) é a fonte; dela sai o texto que o resto do JobScout já lê (cargos com período
e atividades), então anos por skill e sugestões continuam funcionando igual.
"""

from __future__ import annotations

import html
import json
import re
import shutil
import subprocess
import tempfile
import uuid
from datetime import date
from pathlib import Path
from typing import Any

from jobscout import insights, llm, places, replies, suggest
from jobscout.activities import clean_space, fold, list_activities

MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
LIMITS = {"experiencias": 30, "itens": 25, "formacao": 15, "habilidades": 60, "idiomas": 10, "certificacoes": 30, "projetos": 20, "clientes": 20, "habilidades_cargo": 25}
POS_GRADUACAO = re.compile(r"\b(pos|especializa\w*|mba|mestrado|doutorado|master|masters|msc|phd|postgraduate)\b")
SHOWN_ITEMS = 5
SHOWN_SKILLS = 14
MONTHS_PT = ("jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez")
MONTHS_EN = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

LABELS = {
    "pt": {"resumo": "Resumo", "experiencia": "Experiência", "habilidades": "Principais habilidades", "formacao": "Formação",
           "idiomas": "Idiomas", "certificacoes": "Certificações", "projetos": "Projetos", "atual": "atual",
           "graduacao": "Graduação", "pos": "Pós-graduação", "clientes": "Empresas atendidas", "cargo_skills": "Habilidades"},
    "en": {"resumo": "Summary", "experiencia": "Experience", "habilidades": "Key skills", "formacao": "Education",
           "idiomas": "Languages", "certificacoes": "Certifications", "projetos": "Projects", "atual": "present",
           "graduacao": "Education", "pos": "Postgraduate", "clientes": "Clients", "cargo_skills": "Skills"},
    "es": {"resumo": "Resumen", "experiencia": "Experiencia", "habilidades": "Habilidades principales", "formacao": "Formación",
           "idiomas": "Idiomas", "certificacoes": "Certificaciones", "projetos": "Proyectos", "atual": "actual",
           "graduacao": "Grado", "pos": "Posgrado", "clientes": "Clientes", "cargo_skills": "Habilidades"},
}

ITEM_SYSTEM = (
    "Você melhora um item de experiência de currículo. Comece com verbo de ação na primeira pessoa do passado (Construí, Reduzi, Implantei), deixe claro o que foi feito, com que "
    "ferramenta e para quê, em uma frase objetiva. Reescreva só este item, mantendo o assunto e os fatos dele: nunca troque de "
    "assunto nem invente número, ferramenta, empresa ou resultado. Se um número ajudaria, escreva [quanto?] no lugar dele. "
    "Mantenha o idioma do item. Responda só com JSON: {\"texto\": \"item melhorado\", \"motivo\": \"o que mudou, em poucas palavras\"}"
)

SUMMARY_SYSTEM = (
    "Você reescreve o resumo de um currículo para uma vaga. Use só os fatos do currículo; nunca invente "
    "experiência, empresa, número ou ferramenta. Destaque o que combina com a vaga. 2 a 4 frases, em primeira pessoa implícita, "
    "no idioma pedido. Responda só com JSON: {\"resumo\": \"...\"}"
)


def _text(value: Any, limit: int = 300) -> str:
    return clean_space(str(value or ""))[:limit]


def _month(value: Any) -> str:
    value = str(value or "").strip()
    return value if MONTH.match(value) else ""


def _unique(raw: Any, limit: int) -> list[str]:
    names, seen = [], set()
    for item in raw if isinstance(raw, list) else []:
        name = _text(item, 60)
        if name and fold(name) not in seen:
            seen.add(fold(name))
            names.append(name)
    return names[:limit]


def education_kind(course: str) -> str:
    """"MBA em Dados", "Pós-graduação...", "Mestrado..." são pós; o resto é graduação."""
    return "pos" if POS_GRADUACAO.search(fold(course).replace("-", " ")) else "graduacao"


def empty() -> dict[str, Any]:
    return {"titulo": "", "resumo": "", "experiencias": [], "formacao": [], "habilidades": [], "idiomas": [], "certificacoes": [], "projetos": []}


def clean(data: Any) -> dict[str, Any]:
    """Só os campos conhecidos, com tamanho limitado; cada experiência ganha um id estável."""
    if not isinstance(data, dict):
        return empty()
    result = empty()
    result["titulo"] = _text(data.get("titulo"), 120)
    result["resumo"] = clean_space(str(data.get("resumo") or ""))[:1500]
    for item in (data.get("experiencias") or [])[: LIMITS["experiencias"]]:
        if not isinstance(item, dict):
            continue
        role = {
            "id": _text(item.get("id"), 40) or uuid.uuid4().hex[:10],
            "cargo": _text(item.get("cargo"), 120),
            "empresa": _text(item.get("empresa"), 120),
            "local": _text(item.get("local"), 120),
            "inicio": _month(item.get("inicio")),
            "fim": "" if item.get("atual") else _month(item.get("fim")),
            "atual": bool(item.get("atual")),
            "itens": [_text(line, 500) for line in (item.get("itens") or [])[: LIMITS["itens"]] if _text(line, 500)],
            # Habilidades destacadas nesta experiência.
            "habilidades": _unique(item.get("habilidades"), LIMITS["habilidades_cargo"]),
            # Consultoria: empresas onde a pessoa esteve alocada.
            "clientes": [
                {"nome": _text(client.get("nome"), 120), "inicio": _month(client.get("inicio")), "fim": _month(client.get("fim")),
                 "descricao": _text(client.get("descricao"), 300)}
                for client in (item.get("clientes") or [])[: LIMITS["clientes"]]
                if isinstance(client, dict) and _text(client.get("nome"))
            ],
        }
        if role["cargo"] or role["empresa"] or role["itens"]:
            result["experiencias"].append(role)
    for item in (data.get("formacao") or [])[: LIMITS["formacao"]]:
        if isinstance(item, dict) and (_text(item.get("curso")) or _text(item.get("instituicao"))):
            result["formacao"].append({
                "curso": _text(item.get("curso"), 160), "instituicao": _text(item.get("instituicao"), 160),
                "inicio": _month(item.get("inicio")), "fim": _month(item.get("fim")),
                "tipo": item.get("tipo") if item.get("tipo") in {"graduacao", "pos"} else education_kind(_text(item.get("curso"), 160)),
            })
    seen: set[str] = set()
    for item in (data.get("habilidades") or [])[: LIMITS["habilidades"]]:
        name = _text(item.get("nome") if isinstance(item, dict) else item, 60)
        if name and fold(name) not in seen:
            seen.add(fold(name))
            result["habilidades"].append({"nome": name, "principal": bool(isinstance(item, dict) and item.get("principal"))})
    for item in (data.get("idiomas") or [])[: LIMITS["idiomas"]]:
        if isinstance(item, dict) and _text(item.get("idioma")):
            result["idiomas"].append({"idioma": _text(item.get("idioma"), 40), "nivel": _text(item.get("nivel"), 40)})
    for item in (data.get("certificacoes") or [])[: LIMITS["certificacoes"]]:
        if isinstance(item, dict) and _text(item.get("nome")):
            result["certificacoes"].append({"nome": _text(item.get("nome"), 160), "emissor": _text(item.get("emissor"), 120), "ano": _text(item.get("ano"), 4)})
    for item in (data.get("projetos") or [])[: LIMITS["projetos"]]:
        if isinstance(item, dict) and _text(item.get("nome")):
            result["projetos"].append({"nome": _text(item.get("nome"), 160), "descricao": _text(item.get("descricao"), 600), "link": _text(item.get("link"), 300)})
    return result


def _period(start: str, end: str, current: bool, lang: str = "pt", for_parser: bool = False) -> str:
    def show(value: str) -> str:
        if not value:
            return ""
        year, month = value.split("-")
        if for_parser:
            return f"{month}/{year}"
        names = MONTHS_EN if lang == "en" else MONTHS_PT
        return f"{names[int(month) - 1]} {year}"

    first = show(start)
    last = LABELS.get(lang, LABELS["pt"])["atual"] if current else show(end)
    if for_parser and current:
        last = "atual"
    return f"{first} - {last}" if first and last else first or last


def role_skills(role: dict[str, Any]) -> list[str]:
    clients = [client.get("descricao", "") for client in role.get("clientes") or []]
    return insights.skills(" ".join([role.get("cargo", ""), *role.get("itens", []), *clients, ", ".join(role.get("habilidades") or [])]))


def skill_check(data: dict[str, Any]) -> dict[str, Any]:
    """Habilidades das experiências x habilidades do perfil: o que falta de cada lado."""
    profile = {fold(skill["nome"]): skill["nome"] for skill in data.get("habilidades") or []}
    in_roles: dict[str, dict[str, Any]] = {}
    texts = []
    for role in data.get("experiencias") or []:
        label = " — ".join(part for part in (role.get("cargo"), role.get("empresa")) if part) or "Experiência"
        texts.append(fold(" ".join([*role.get("itens", []), *(client.get("descricao", "") for client in role.get("clientes") or [])])))
        for name in [*(role.get("habilidades") or []), *role_skills(role)]:
            entry = in_roles.setdefault(fold(name), {"nome": name, "experiencias": []})
            if label not in entry["experiencias"]:
                entry["experiencias"].append(label)
    written = " ".join(texts)
    only_profile = [
        name for key, name in profile.items()
        if key not in in_roles and not re.search(rf"(?<![a-z0-9]){re.escape(key)}(?![a-z0-9])", written)
    ]
    return {
        "fora_do_perfil": [entry for key, entry in in_roles.items() if key not in profile],
        "fora_das_experiencias": only_profile,
    }


def to_text(data: dict[str, Any]) -> str:
    """O mesmo currículo no formato que o leitor de cargos entende (e que a IA recebe)."""
    lines: list[str] = []
    if data["titulo"]:
        lines.append(data["titulo"])
    if data["resumo"]:
        lines += ["", "RESUMO", data["resumo"]]
    if data["experiencias"]:
        lines += ["", "EXPERIÊNCIA"]
        for role in data["experiencias"]:
            head = " | ".join(part for part in (role["cargo"], role["empresa"]) if part)
            lines.append(head + (f" ({role['local']})" if role["local"] else ""))
            period = _period(role["inicio"], role["fim"], role["atual"], for_parser=True)
            if period:
                lines.append(period)
            lines += [f"- {item}" for item in role["itens"]]
            for client in role.get("clientes") or []:
                dates = _period(client["inicio"], client["fim"], False)
                lines.append(f"- Cliente {client['nome']}" + (f" ({dates})" if dates else "") + (f": {client['descricao']}" if client["descricao"] else ""))
            if role.get("habilidades"):
                lines.append("- Habilidades: " + ", ".join(role["habilidades"]))
    if data["formacao"]:
        lines += ["", "FORMAÇÃO"]
        for item in data["formacao"]:
            lines.append(" | ".join(part for part in (item["curso"], item["instituicao"]) if part))
            period = _period(item["inicio"], item["fim"], False, for_parser=True)
            if period:
                lines.append(period)
    if data["habilidades"]:
        lines += ["", "HABILIDADES", ", ".join(skill["nome"] for skill in data["habilidades"])]
    if data["idiomas"]:
        lines += ["", "IDIOMAS"] + [f"{item['idioma']}: {item['nivel']}".rstrip(": ") for item in data["idiomas"]]
    if data["certificacoes"]:
        lines += ["", "CERTIFICAÇÕES"] + [
            " — ".join(part for part in (item["nome"], item["emissor"], item["ano"]) if part) for item in data["certificacoes"]
        ]
    if data["projetos"]:
        lines += ["", "PROJETOS"] + [
            f"- {item['nome']}: {item['descricao']}".rstrip(": ") + (f" ({item['link']})" if item["link"] else "") for item in data["projetos"]
        ]
    return "\n".join(lines).strip()


def _month_of(index: int) -> str:
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


SECTION_NAMES = {
    "resumo": r"(resumo|sobre mim|perfil profissional|summary|about me|objetivo)",
    "formacao": r"(formacao|formacao academica|educacao|education|escolaridade)",
    "idiomas": r"(idiomas|languages|linguas)",
    "habilidades": r"(habilidades|competencias|skills|tecnologias|ferramentas|conhecimentos)",
    "certificacoes": r"(certificacoes|certificados|certifications|cursos)",
    "projetos": r"(projetos|projects|portfolio)",
    "experiencia": r"(experiencia|experiencias|experiencia profissional|experience|historico profissional)",
}


def _section_of(line: str) -> str:
    folded = fold(line).strip(" :")
    if len(folded) > 40:
        return ""
    for name, pattern in SECTION_NAMES.items():
        if re.fullmatch(pattern, folded):
            return name
    return ""


def _split_sections(text: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current = ""
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        name = _section_of(line)
        if name:
            current = name
            sections.setdefault(name, [])
            continue
        if current:
            sections[current].append(line)
    return sections


def _date_only(line: str) -> bool:
    return bool(suggest.period_months(line)) and not re.search(r"[a-zA-Z]{6,}", re.sub(r"(atual|presente|present|current|janeiro|fevereiro|marco|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro)", "", fold(line)))


def _parts(line: str) -> list[str]:
    return [part.strip() for part in re.split(r"\s[|—–·]\s|\s-\s|\|", line) if part.strip()]


def from_text(text: str, today: date | None = None) -> dict[str, Any]:
    """Primeira versão da estrutura a partir do texto atual. A pessoa revisa no editor."""
    today = today or date.today()
    now_index = today.year * 12 + today.month - 1
    data = empty()
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    if lines and not list_activities(lines[0]) and len(lines[0]) <= 80 and not lines[0].isupper():
        data["titulo"] = lines[0]
    for group in list_activities(text or ""):
        context = str(group["contexto"])
        parts = [part.strip() for part in re.split(r"\s[|—–·]\s|\s-\s", context) if part.strip()]
        span = suggest.period_months(str(group["periodo"]), today)
        start = _month_of(span[0]) if span else ""
        end_index = span[1] if span else None
        current = bool(span) and end_index >= now_index and bool(re.search(r"(atual|present|current|hoje|momento)", fold(str(group["periodo"]))))
        if suggest.NOT_EDUCATION.search(fold(str(group["secao"]))):
            data["formacao"].append({
                "curso": parts[0] if parts else context, "instituicao": parts[1] if len(parts) > 1 else "",
                "inicio": start, "fim": _month_of(end_index) if span else "",
            })
            continue
        data["experiencias"].append({
            "id": uuid.uuid4().hex[:10],
            "cargo": parts[0] if parts else context,
            "empresa": parts[1] if len(parts) > 1 else "",
            "local": "",
            "inicio": start,
            "fim": "" if current or not span else _month_of(end_index),
            "atual": current,
            "itens": [str(item) for item in group["atividades"]],
        })
    # Seções que o leitor de cargos não cobre: formação, idiomas, habilidades, resumo, certificações e projetos.
    sections = _split_sections(text)
    if sections.get("resumo"):
        data["resumo"] = " ".join(sections["resumo"])
    if sections.get("formacao") and not data["formacao"]:
        for line in sections["formacao"]:
            if line.startswith(("-", "•", "*")):
                continue
            if _date_only(line) and data["formacao"]:
                span = suggest.period_months(line, today)
                data["formacao"][-1]["inicio"], data["formacao"][-1]["fim"] = _month_of(span[0]), _month_of(span[1])
                continue
            parts = _parts(line)
            data["formacao"].append({"curso": parts[0] if parts else line, "instituicao": parts[1] if len(parts) > 1 else "", "inicio": "", "fim": ""})
    for line in sections.get("idiomas", []):
        match = re.match(r"^[-•*]?\s*([^:(\-–]+?)\s*[:(\-–]\s*([^)]+)\)?$", line)
        if match:
            data["idiomas"].append({"idioma": match.group(1).strip(), "nivel": match.group(2).strip()})
    for line in sections.get("certificacoes", []):
        parts = _parts(line.lstrip("-•* "))
        year = next((part for part in parts if re.fullmatch(r"(19|20)\d{2}", part)), "")
        rest = [part for part in parts if part != year]
        data["certificacoes"].append({"nome": rest[0] if rest else line, "emissor": rest[1] if len(rest) > 1 else "", "ano": year})
    for line in sections.get("projetos", []):
        body = line.lstrip("-•* ")
        link = re.search(r"\(?(https?://[^\s)]+|github\.com/[^\s)]+)\)?", body)
        name, _, description = body.partition(":")
        data["projetos"].append({
            "nome": name.strip(), "descricao": description.replace(link.group(0), "").strip() if link else description.strip(),
            "link": link.group(1) if link else "",
        })
    found = insights.skills(text or "")
    listed = [
        item.strip() for line in sections.get("habilidades", []) for item in re.split(r"[,;•|/]", line.lstrip("-* ")) if 1 < len(item.strip()) <= 40
    ]
    names = list(dict.fromkeys(found + [item for item in listed if fold(item) not in {fold(name) for name in found}]))
    data["habilidades"] = [{"nome": name, "principal": index < 8} for index, name in enumerate(names)]
    return clean(data)


def job_skills(job: dict[str, Any]) -> list[str]:
    listed = [item.strip() for item in str(job.get("skills") or "").split(",") if item.strip()]
    return listed or insights.skills(" ".join([str(job.get("title") or ""), str(job.get("description") or "")]))


def tailor(data: dict[str, Any], job: dict[str, Any]) -> dict[str, Any]:
    """Versão para a vaga: habilidades e itens que combinam vêm primeiro; o resto fica oculto, não apagado."""
    wanted = job_skills(job)
    wanted_folded = {fold(name) for name in wanted}
    version = json.loads(json.dumps(data))
    skills = version["habilidades"]
    for skill in skills:
        skill["vaga"] = fold(skill["nome"]) in wanted_folded
    skills.sort(key=lambda skill: (not skill["vaga"], not skill["principal"]))
    for index, skill in enumerate(skills):
        skill["mostrar"] = skill["vaga"] or skill["principal"] or index < SHOWN_SKILLS
    words = {word for word in re.findall(r"[a-z0-9+#]{4,}", fold(str(job.get("description") or "")))}
    for role in version["experiencias"]:
        scored = []
        for position, item in enumerate(role["itens"]):
            hits = sum(1 for name in insights.skills(item) if fold(name) in wanted_folded)
            overlap = len(words & set(re.findall(r"[a-z0-9+#]{4,}", fold(item))))
            scored.append((-(hits * 3 + overlap), position, item, hits))
        scored.sort()
        role["itens"] = [item for _, _, item, _ in scored]
        role["destaques"] = [hits > 0 for _, _, _, hits in scored]
        role["mostrar_itens"] = [index < SHOWN_ITEMS or hits > 0 for index, (_, _, _, hits) in enumerate(scored)]
        # As habilidades da experiência que a vaga pede vêm primeiro.
        role["habilidades"] = sorted(role.get("habilidades") or [], key=lambda name: fold(name) not in wanted_folded)
    version["alvo"] = {
        "vaga": f"{job.get('title') or ''} — {job.get('company') or ''}".strip(" —"),
        "skills_da_vaga": wanted,
        "combinam": [skill["nome"] for skill in skills if skill["vaga"]],
        "faltam": [name for name in wanted if fold(name) not in {fold(skill["nome"]) for skill in skills}],
    }
    return version


def ai_item(item: str, role: dict[str, Any]) -> dict[str, str]:
    """Item de experiência melhorado pela IA (tarefa "curriculo"). Levanta llm.LLMUnavailable."""
    prompt = (
        f"Cargo: {role.get('cargo') or ''} — {role.get('empresa') or ''}\n"
        f"Item para melhorar:\n{item}"
    )
    raw = llm.ask_llm("curriculo", prompt, system=ITEM_SYSTEM, as_json=True, timeout=120)
    try:
        answer = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise llm.LLMUnavailable("A IA não devolveu um texto válido. Tente de novo.") from exc
    text = clean_space(str(answer.get("texto") or ""))[:500]
    if not text:
        raise llm.LLMUnavailable("A IA não devolveu texto. Tente de novo.")
    invented = replies.invented_numbers(text, [prompt])
    known = {fold(name) for name in insights.skills(f"{item} {role.get('cargo') or ''}")}
    invented += [name for name in insights.skills(text) if fold(name) not in known]
    if invented:
        return {"texto": "", "motivo": f"A IA citou {', '.join(invented[:3])}, que este item não menciona; descartei a sugestão. Tente de novo."}
    return {"texto": text, "motivo": clean_space(str(answer.get("motivo") or ""))[:200]}


def ai_summary(data: dict[str, Any], job: dict[str, Any], lang: str) -> str:
    """Resumo reescrito para a vaga pela IA (tarefa "curriculo"). Levanta llm.LLMUnavailable."""
    names = {"pt": "português", "en": "inglês", "es": "espanhol"}
    prompt = (
        f"Currículo:\n{to_text(data)[:8000]}\n\n"
        f"Vaga: {job.get('title') or ''} — {job.get('company') or ''}\n{str(job.get('description') or '')[:3000]}\n\n"
        f"Escreva o resumo em {names.get(lang, 'português')}."
    )
    raw = llm.ask_llm("curriculo", prompt, system=SUMMARY_SYSTEM, as_json=True, timeout=180)
    try:
        text = json.loads(raw).get("resumo", "")
    except (json.JSONDecodeError, AttributeError):
        text = raw
    return clean_space(str(text or ""))[:900]


def language_for(job: dict[str, Any] | None) -> str:
    """Idioma da versão: vaga escrita em inglês recebe currículo com seções em inglês."""
    if not job:
        return "pt"
    if insights.english(str(job.get("title") or ""), str(job.get("description") or "")) == "vaga em inglês":
        return "en"
    return places.language(" ".join([str(job.get("title") or ""), str(job.get("description") or "")[:1500]]))


# Exportação

CSS = """
@page { size: A4; margin: 15mm 16mm; }
* { box-sizing: border-box; }
body { margin: 0; font: 10.2pt/1.42 "Segoe UI", Calibri, Arial, sans-serif; color: #1b2430; }
header { border-bottom: 2px solid #2f6fb3; padding-bottom: 8pt; margin-bottom: 10pt; }
h1 { margin: 0; font-size: 21pt; letter-spacing: -0.01em; color: #10202f; }
.headline { margin: 2pt 0 0; font-size: 11.5pt; color: #2f6fb3; font-weight: 600; }
.contact { margin: 5pt 0 0; font-size: 9pt; color: #4a5866; }
.contact span + span::before { content: "  ·  "; color: #9aa6b2; }
h2 { margin: 12pt 0 5pt; font-size: 9pt; letter-spacing: 0.12em; text-transform: uppercase; color: #2f6fb3; border-bottom: 1px solid #d5dde6; padding-bottom: 2pt; }
p { margin: 0 0 4pt; }
.role { margin-bottom: 7pt; break-inside: avoid; }
.role-head { display: flex; justify-content: space-between; gap: 10pt; }
.role-title { font-weight: 700; }
.role-company { color: #3a4856; }
.dates { color: #5a6876; white-space: nowrap; font-size: 9pt; }
ul { margin: 2pt 0 0; padding-left: 13pt; }
li { margin: 0 0 1.5pt; }
.skills { display: flex; flex-wrap: wrap; gap: 3pt 5pt; }
.skill { padding: 1pt 6pt; border: 1px solid #c9d6e3; border-radius: 8pt; font-size: 9pt; }
.skill.key { border-color: #2f6fb3; color: #1d4f86; font-weight: 600; }
.two { display: grid; grid-template-columns: 1fr 1fr; gap: 0 16pt; }
.muted { color: #5a6876; }
.role-extra { margin: 2pt 0 0; font-size: 9pt; color: #3a4856; }
.subhead { margin: 6pt 0 2pt; font-size: 8.5pt; font-weight: 700; color: #3a4856; }
a { color: inherit; text-decoration: none; }
"""


def _e(value: Any) -> str:
    return html.escape(str(value or ""))


def _clients_html(role: dict[str, Any], label: dict[str, str], lang: str) -> str:
    rows = []
    for client in role.get("clientes") or []:
        dates = _period(client["inicio"], client["fim"], False, lang)
        rows.append(f"<li><strong>{_e(client['nome'])}</strong>" + (f' <span class="muted">({_e(dates)})</span>' if dates else "")
                    + (f": {_e(client['descricao'])}" if client["descricao"] else "") + "</li>")
    return f'<p class="subhead">{label["clientes"]}</p><ul>{"".join(rows)}</ul>' if rows else ""


def render_html(data: dict[str, Any], profile: dict[str, Any], lang: str = "pt") -> str:
    """Página A4 pronta para imprimir. Itens e habilidades ocultos na versão ficam de fora."""
    label = LABELS.get(lang, LABELS["pt"])
    location = places.location(profile, lang)
    contact = [profile.get("email"), profile.get("telefone"), location, profile.get("linkedin"), profile.get("github"), profile.get("portfolio")]
    contact_html = "".join(f"<span>{_e(item)}</span>" for item in contact if item)
    parts = [f"<header><h1>{_e(profile.get('nome') or 'Seu nome')}</h1>"]
    if data.get("titulo"):
        parts.append(f'<p class="headline">{_e(data["titulo"])}</p>')
    if contact_html:
        parts.append(f'<p class="contact">{contact_html}</p>')
    parts.append("</header>")
    if data.get("resumo"):
        parts.append(f"<h2>{label['resumo']}</h2><p>{_e(data['resumo'])}</p>")
    skills = [skill for skill in data.get("habilidades") or [] if skill.get("mostrar", True)]
    if skills:
        chips = "".join(f'<span class="skill{" key" if skill.get("principal") or skill.get("vaga") else ""}">{_e(skill["nome"])}</span>' for skill in skills)
        parts.append(f'<h2>{label["habilidades"]}</h2><div class="skills">{chips}</div>')
    if data.get("experiencias"):
        parts.append(f"<h2>{label['experiencia']}</h2>")
        for role in data["experiencias"]:
            shown = role.get("mostrar_itens") or [True] * len(role["itens"])
            items = "".join(f"<li>{_e(item)}</li>" for item, keep in zip(role["itens"], shown) if keep)
            company = " · ".join(part for part in (role.get("empresa"), role.get("local")) if part)
            parts.append(
                '<div class="role"><div class="role-head"><div>'
                f'<span class="role-title">{_e(role["cargo"])}</span>'
                + (f' <span class="role-company">— {_e(company)}</span>' if company else "")
                + f'</div><span class="dates">{_e(_period(role["inicio"], role["fim"], role["atual"], lang))}</span></div>'
                + (f"<ul>{items}</ul>" if items else "")
                + _clients_html(role, label, lang)
                + (f'<p class="role-extra"><strong>{label["cargo_skills"]}:</strong> {_e(", ".join(role["habilidades"]))}</p>' if role.get("habilidades") else "")
                + "</div>"
            )
    blocks = []
    if data.get("formacao"):
        def education(items: list[dict[str, Any]]) -> str:
            return "".join(
                f'<p><strong>{_e(item["curso"])}</strong><br><span class="muted">{_e(item["instituicao"])}'
                + (f' · {_e(_period(item["inicio"], item["fim"], False, lang))}' if item["inicio"] or item["fim"] else "")
                + "</span></p>"
                for item in items
            )

        degrees = [item for item in data["formacao"] if item.get("tipo") != "pos"]
        postgrad = [item for item in data["formacao"] if item.get("tipo") == "pos"]
        if degrees:
            blocks.append(f"<div><h2>{label['graduacao']}</h2>{education(degrees)}</div>")
        if postgrad:
            blocks.append(f"<div><h2>{label['pos']}</h2>{education(postgrad)}</div>")
    if data.get("idiomas"):
        rows = "".join(f'<p>{_e(item["idioma"])}<span class="muted"> · {_e(item["nivel"])}</span></p>' for item in data["idiomas"])
        blocks.append(f"<div><h2>{label['idiomas']}</h2>{rows}</div>")
    if data.get("certificacoes"):
        rows = "".join(
            f'<p>{_e(item["nome"])}<span class="muted">{" · " + _e(item["emissor"]) if item["emissor"] else ""}{" · " + _e(item["ano"]) if item["ano"] else ""}</span></p>'
            for item in data["certificacoes"]
        )
        blocks.append(f"<div><h2>{label['certificacoes']}</h2>{rows}</div>")
    if data.get("projetos"):
        rows = "".join(
            f'<p><strong>{_e(item["nome"])}</strong>{": " + _e(item["descricao"]) if item["descricao"] else ""}'
            + (f' <span class="muted">({_e(item["link"])})</span>' if item["link"] else "") + "</p>"
            for item in data["projetos"]
        )
        blocks.append(f"<div><h2>{label['projetos']}</h2>{rows}</div>")
    if blocks:
        parts.append(f'<div class="two">{"".join(blocks)}</div>')
    title = _e(f"Currículo — {profile.get('nome') or ''}")
    return f'<!doctype html><html lang="{lang}"><head><meta charset="utf-8"><title>{title}</title><style>{CSS}</style></head><body>{"".join(parts)}</body></html>'


BROWSERS = (
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
)


def browser() -> Path | None:
    for path in BROWSERS:
        if path.is_file():
            return path
    found = shutil.which("msedge") or shutil.which("chrome")
    return Path(found) if found else None


def to_pdf(page: str, target: Path, timeout: float = 60) -> Path:
    """Imprime a página em PDF com o Edge (ou Chrome) do Windows, sem janela."""
    exe = browser()
    if exe is None:
        raise RuntimeError("Não achei o Edge nem o Chrome para gerar o PDF.")
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="jobscout-pdf-") as work:
        source = Path(work) / "curriculo.html"
        source.write_text(page, encoding="utf-8")
        if target.exists():
            target.unlink()
        command = [
            str(exe), "--headless", "--disable-gpu", "--no-first-run", "--no-pdf-header-footer", "--print-to-pdf-no-header",
            f"--user-data-dir={Path(work) / 'perfil'}", f"--print-to-pdf={target}", source.as_uri(),
        ]
        subprocess.run(command, timeout=timeout, capture_output=True, check=False)
    if not target.is_file() or target.stat().st_size < 1000:
        raise RuntimeError("O navegador não gerou o PDF.")
    return target


def custom_label(job: dict[str, Any] | None) -> str:
    """Nome do currículo customizado: cargo_empresa (ex.: Data_Engineer_Sr_Acme)."""
    parts = [str((job or {}).get("title") or ""), str((job or {}).get("company") or "")]
    return "_".join(re.sub(r"[^\w]+", "_", part, flags=re.UNICODE).strip("_") for part in parts if part)[:90]


def file_name(profile: dict[str, Any], label: str = "") -> str:
    name = re.sub(r'[\\/:*?"<>|]+', " ", f"CV {profile.get('nome') or 'JobScout'}" + (f" - {label}" if label else ""))
    return " ".join(name.split())[:120] + ".pdf"


def resume_kind(documents: str, versions: list[dict[str, Any]]) -> dict[str, str]:
    """De onde veio o currículo enviado: {"tipo": Padrão/Customizado, "nome": modelo x ou cargo_empresa}."""
    document = str(documents or "").split(",")[0].strip()
    if not document:
        return {"tipo": "", "nome": ""}
    wanted = fold(document)
    for version in versions:
        names = {fold(str(version.get(key) or "")) for key in ("pdf", "name", "label")}
        if wanted in names or wanted == fold(f"{version.get('label') or ''}.pdf"):
            return {"tipo": "Customizado", "nome": version.get("label") or version.get("name") or document}
    return {"tipo": "Padrão", "nome": re.sub(r"\.(pdf|docx?|odt|rtf)$", "", document, flags=re.I)}
