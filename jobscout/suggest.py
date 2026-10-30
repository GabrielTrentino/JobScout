"""Sugestão de resposta para perguntas curtas de formulário, só com regras.

Fontes, nesta ordem: as respostas rápidas do Perfil, o currículo (anos e skills) e o histórico,
que fica com o Assistant. Nunca responde perguntas sensíveis (gênero, raça, deficiência, idade...)
e nunca preenche nada sozinha: a extensão mostra a sugestão e a pessoa clica para usar.
"""

from __future__ import annotations

import math
import re
from datetime import date
from typing import Any

from jobscout import insights, places
from jobscout.activities import fold, list_activities

SENSITIVE = re.compile(
    r"\b(genero|gender|sexo|sex|raca|race|etnia|ethnic\w*|cor da pele|deficien\w*|disabilit\w*|pcd|neurodiverg\w*|"
    r"veteran\w*|orientacao sexual|sexual orientation|lgbt\w*|religi\w*|idade|age|nascimento|birth\w*|"
    r"cpf|rg|estado civil|marital|gravid\w*|pregnan\w*|filhos|children)\b"
)
YEARS = re.compile(
    r"(quantos anos|anos de experiencia|anos trabalh|tempo de experiencia|tempo de atuacao|"
    r"years of (?:professional |work |relevant )?experience|how many years|years have you|years working)"
)
HAS_EXPERIENCE = re.compile(
    r"(tem experiencia|possui experiencia|ja trabalhou com|ja atuou com|ja utilizou|experiencia com|experiencia em|"
    r"conhecimento em|conhecimentos em|do you have experience|have you worked with|experience (?:with|in)|familiar with)"
)
ENGLISH = re.compile(r"\b(ingles|english)\b")
SPANISH = re.compile(r"\b(espanhol|spanish|espanol)\b")
LEVEL_WORDS = re.compile(r"(nivel|level|proficien\w*|fluen\w*|dominio|rate your|avalie)")
AUTHORIZATION = re.compile(
    r"(autorizad\w* a trabalhar|autorizacao (?:de|para) trabalh|direito de trabalhar|permissao de trabalho|"
    r"authori[sz]ed to work|work authori[sz]ation|legally (?:authori[sz]ed|eligible|allowed)|eligible to work|work permit)"
)
VISA = re.compile(r"(visto|visa|sponsor\w*|patrocini\w*)")
RELOCATE = re.compile(r"(mudanca de cidade|mudar de cidade|se mudar|mudar para|realoca\w*|relocat\w*|mudanca para)")
MODE_WORDS = {
    "Remoto": re.compile(r"\b(remot\w*|home ?office|remote\w*)\b"),
    "Híbrido": re.compile(r"\b(hibrid\w*|hybrid)\b"),
    "Presencial": re.compile(r"\b(presencial|on-?site|in-?office|no escritorio|in person)\b"),
}
LOCATION = re.compile(
    r"(current (?:location|city)|where (?:are you|do you) (?:located|based|live)|"
    r"(?:localizacao|cidade) atual|onde (?:voce )?(?:mora|reside|esta localizad\w*)|cidade onde mora|em que cidade)"
)
COUNTRY = re.compile(r"\b(pais|country)\b")
# "Are you currently based in Latin America?", "Você mora no Brasil?": sim ou não pelo país do Perfil.
BASED_IN = re.compile(
    r"(based in|located in|living in|live in|reside in|residing in|resident of|"
    r"mora (?:n[ao]s?|em)|reside (?:n[ao]s?|em)|esta (?:baseado|baseada|localizado|localizada) (?:n[ao]s?|em)|vive (?:n[ao]s?|en|em)|vives en|resides en)"
)
SALARY = re.compile(r"(pretensao|expectativa salarial|salar\w*|remuneracao|compensation|expected pay)")
USD_MARK = re.compile(r"(us\$|u\$|\busd\b|\bdolar\w*|\bdollars?\b|(?<![a-z0-9r])\$)", re.I)
BRL_MARK = re.compile(r"(r\$|\breais\b|\breal\b|\bbrl\b)", re.I)
AVAILABILITY = re.compile(r"(disponibilidade para (?:inicio|comecar)|quando (?:voce )?pode comecar|start date|notice period|aviso previo|when can you start)")
NOT_EDUCATION = re.compile(r"(forma[cç]|educa|academ|curso|certific|idioma|language)")

YES = re.compile(r"^(sim|yes|s|y)\b")
NO = re.compile(r"^(nao|no|n)\b")

LEVELS = (
    (r"(nenhum|none|no proficiency|nao falo|nao possuo)", 0),
    (r"(basic|basico|beginner|iniciante|elementar|elementary|a1|a2)", 1),
    (r"(intermedi\w*|b1|b2|limited working)", 2),
    (r"(avancad\w*|advanced|professional working|c1|upper)", 3),
    (r"(fluente|fluent|full professional|c2)", 4),
    (r"(nativ\w*|native|bilingu\w*)", 5),
)

MONTHS = {
    "jan": 1, "fev": 2, "feb": 2, "mar": 3, "abr": 4, "apr": 4, "mai": 5, "may": 5, "jun": 6,
    "jul": 7, "ago": 8, "aug": 8, "set": 9, "sep": 9, "out": 10, "oct": 10, "nov": 11, "dez": 12, "dec": 12,
}
DATE = re.compile(
    r"(?P<mm>\d{1,2})/(?P<my>(?:19|20)\d{2})"
    r"|(?P<mon>jan|fev|feb|mar|abr|apr|mai|may|jun|jul|ago|aug|set|sep|out|oct|nov|dez|dec)\w*\.?\s*(?:de\s*)?(?P<ny>(?:19|20)\d{2})"
    r"|(?P<y>(?:19|20)\d{2})"
    r"|(?P<now>atual|atualmente|presente|present|current|hoje|now|o momento)"
)


def fits(value: str, kind: str, limit: int = 0) -> bool:
    """O campo aceitaria o valor? Número em campo numérico e dentro do limite de caracteres."""
    text = str(value or "").strip()
    if not text:
        return False
    if kind == "number" and not re.fullmatch(r"\d+(?:[.,]\d+)?", text):
        return False
    return not (limit and len(text) > limit)


COUNT_WORDS = re.compile(r"\b(how many|how much|quantos|quantas|cuantos|cuantas|number of|numero de)\b")


def numeric_question(question: str) -> bool:
    """Pergunta que pede uma contagem: o campo quase sempre só aceita número."""
    folded = fold(question)
    return bool(YEARS.search(folded) or COUNT_WORDS.search(folded)) and not SALARY.search(folded)


def profile_only(question: str) -> bool:
    """Perguntas que só o Perfil responde: sem a resposta lá, ninguém (nem a IA) deve chutar."""
    folded = fold(question)
    return bool(
        SENSITIVE.search(folded) or AUTHORIZATION.search(folded) or VISA.search(folded) or RELOCATE.search(folded)
        or SALARY.search(folded) or AVAILABILITY.search(folded) or LOCATION.search(folded) or COUNTRY.search(folded)
        or BASED_IN.search(folded)
        or ENGLISH.search(folded) or SPANISH.search(folded)
    )


def level_rank(text: str) -> int | None:
    folded = fold(text)
    for pattern, rank in reversed(LEVELS):
        if re.search(pattern, folded):
            return rank
    return None


def period_months(period: str, today: date | None = None) -> tuple[int, int] | None:
    """'jan 2021 – atual' -> (início, fim) em meses absolutos (ano * 12 + mês)."""
    today = today or date.today()
    points: list[tuple[int, bool]] = []
    for match in DATE.finditer(fold(period)):
        if match.group("mm"):
            month = min(max(int(match.group("mm")), 1), 12)
            points.append((int(match.group("my")) * 12 + month - 1, False))
        elif match.group("mon"):
            points.append((int(match.group("ny")) * 12 + MONTHS[match.group("mon")[:3]] - 1, False))
        elif match.group("y"):
            points.append((int(match.group("y")) * 12, True))
        else:
            points.append((today.year * 12 + today.month - 1, False))
    if not points:
        return None
    start, _ = points[0]
    end, year_only = points[1] if len(points) > 1 else points[0]
    if year_only:
        end += 11
    return (start, end) if end >= start else None


def _merged_months(spans: list[tuple[int, int]]) -> int:
    total, current = 0, None
    for start, end in sorted(spans):
        if current and start <= current[1] + 1:
            current = (current[0], max(current[1], end))
            continue
        if current:
            total += current[1] - current[0] + 1
        current = (start, end)
    if current:
        total += current[1] - current[0] + 1
    return total


def _year(month: int) -> int:
    return month // 12


def experience(resume: str, skill: str | None = None, today: date | None = None) -> dict[str, Any] | None:
    """Meses de experiência (no total ou com uma skill), juntando cargos que se sobrepõem."""
    spans, roles = [], []
    for group in list_activities(resume or ""):
        if NOT_EDUCATION.search(fold(str(group["secao"]))):
            continue
        span = period_months(str(group["periodo"]), today)
        if not span:
            continue
        if skill:
            text = " ".join([str(group["contexto"])] + [str(item) for item in group["atividades"]])
            if skill not in insights.skills(text):
                continue
        spans.append(span)
        roles.append(str(group["contexto"]))
    if not spans:
        return None
    months = _merged_months(spans)
    first, last = min(s for s, _ in spans), max(e for _, e in spans)
    current = (today or date.today())
    ongoing = last >= current.year * 12 + current.month - 1
    return {
        "meses": months,
        "cargos": len(roles),
        "de": _year(first),
        "ate": "hoje" if ongoing else str(_year(last)),
    }


def declared_years(profile: dict[str, Any], skill: str) -> dict[str, Any] | None:
    """Tempo de uso que a pessoa informou para a skill (tela Currículo)."""
    for extra in profile.get("skills_extras") or []:
        names = insights.skills(str(extra.get("skill") or "")) or [str(extra.get("skill") or "")]
        if skill in names or fold(str(extra.get("skill") or "")) == fold(skill):
            return extra
    return None


def whole_years(months: int) -> int | None:
    """Anos inteiros, para o campo de número. Menos de seis meses não vira resposta."""
    if months < 6:
        return None
    return max(1, math.floor(months / 12))


def _range(option: str) -> tuple[float, float] | None:
    folded = fold(option)
    numbers = [float(n.replace(",", ".")) for n in re.findall(r"\d+(?:[.,]\d+)?", folded)]
    if not numbers:
        return (0, 0.99) if re.search(r"(nenhum|none|sem experiencia|no experience)", folded) else None
    if re.search(r"(menos de|less than|under|abaixo de|<)", folded):
        return (0, numbers[0] - 0.01)
    if re.search(r"(\bate\b|up to)", folded) and len(numbers) == 1:
        return (0, numbers[0] + 0.99)
    if re.search(r"(mais de|more than|over|acima de)", folded):
        return (numbers[0] + 0.01, math.inf)
    if re.search(r"(\+|ou mais|or more)", folded):
        return (numbers[0], math.inf)
    if len(numbers) >= 2:
        return (numbers[0], numbers[1] + 0.99)
    return (numbers[0], numbers[0] + 0.99)


def fit_years(years: float, options: list[str]) -> int:
    for index, option in enumerate(options):
        span = _range(option)
        if span and span[0] <= years <= span[1]:
            return index
    return -1


def fit_yes_no(answer: bool, options: list[str]) -> int:
    rule = YES if answer else NO
    for index, option in enumerate(options):
        if rule.search(fold(option)):
            return index
    return -1


def fit_level(rank: int, options: list[str]) -> int:
    best, best_rank = -1, -1
    for index, option in enumerate(options):
        option_rank = level_rank(option)
        if option_rank is not None and best_rank < option_rank <= rank:
            best, best_rank = index, option_rank
    return best


def fit_text(value: str, options: list[str]) -> int:
    wanted = fold(value)
    for index, option in enumerate(options):
        if fold(option) == wanted:
            return index
    for index, option in enumerate(options):
        if wanted and (fold(option).startswith(wanted) or wanted.startswith(fold(option))):
            return index
    return -1


def _answer(value: str, origin: str, base: str, *, options: list[str], index: int | None = None) -> dict[str, str] | None:
    if options:
        if index is None:
            index = fit_text(value, options)
        if index < 0:
            return None
        value = options[index]
    if not str(value).strip():
        return None
    return {"valor": str(value), "origem": origin, "base": base}


def yes_no(raw: str) -> bool | None:
    folded = fold(raw)
    if YES.search(folded):
        return True
    if NO.search(folded):
        return False
    return None


def _language(question: str, raw: str, name: str, options: list[str], kind: str) -> dict[str, str] | None:
    rank = level_rank(raw) if raw else None
    if rank is None:
        return None
    base = f"Perfil: {name} {raw}"
    if options and any(level_rank(option) is not None for option in options):
        return _answer("", "perfil", base, options=options, index=fit_level(rank, options))
    if options or kind in {"radio", "select"} or not LEVEL_WORDS.search(question):
        # "Você fala inglês?" vira sim/não; intermediário para cima conta como sim.
        return _answer("Sim" if rank >= 2 else "Não", "perfil", base, options=options,
                       index=fit_yes_no(rank >= 2, options) if options else None)
    return _answer(raw, "perfil", base, options=[])


def _period_text(info: dict[str, Any]) -> str:
    years = info["meses"] / 12
    shown = f"{years:.1f}".replace(".", ",").replace(",0", "")
    return f"{info['cargos']} cargo{'s' if info['cargos'] > 1 else ''}, {info['de']}–{info['ate']} (~{shown} anos)"


def salary_currency(question: str, options: list[str] | None = None) -> tuple[str, bool]:
    """(moeda, dita na pergunta?). A pergunta e as opções mandam; sem moeda, inglês = dólar, senão real."""
    text = fold(" ".join([question, *(options or [])]))
    usd, brl = bool(USD_MARK.search(text)), bool(BRL_MARK.search(text))
    if usd != brl:
        return ("usd" if usd else "brl"), True
    return ("usd" if places.language(question) == "en" else "brl"), False


def salary_number(raw: str) -> str:
    """Só o número: "R$ 15.000,00" -> 15000; "US$ 4,000/mês" -> 4000; "4k" -> 4000."""
    match = re.search(r"\d[\d.,]*\s*k?", raw, re.I)
    if not match:
        return ""
    text = match.group(0).strip().lower()
    thousand = text.endswith("k")
    text = re.sub(r"[.,](\d{1,2})$", "", text.rstrip("k "))
    number = int(re.sub(r"\D", "", text) or 0)
    return str(number * 1000 if thousand else number)


def _salary(question: str, profile: dict[str, Any], options: list[str], kind: str) -> dict[str, str] | None:
    currency, stated = salary_currency(question, options)
    values = {"brl": str(profile.get("pretensao_salarial") or ""), "usd": str(profile.get("pretensao_usd") or "")}
    names = {"brl": "em real", "usd": "em dólar"}
    other = "brl" if currency == "usd" else "usd"
    raw, chosen = values[currency], currency
    if not raw:
        # Sem conversão: valor em outra moeda só como texto com a moeda, e só se a pergunta não pediu esta.
        if stated or kind == "number":
            return None
        raw, chosen = values[other], other
    value = salary_number(raw) if kind == "number" else raw
    base = f"Perfil: pretensão {names[chosen]}" + (f" (sem valor {names[currency]})" if chosen != currency else "")
    if not stated and values[other] and chosen == currency:
        base += f" · a pergunta não diz a moeda; {names[other]}: {values[other]}"
    return _answer(value, "perfil", base, options=options)


def suggest(question: str, profile: dict[str, Any], *, options: list[str] | None = None, kind: str = "text") -> dict[str, str] | None:
    """Sugestão para uma pergunta. kind: text, number, select, radio, checkbox, textarea."""
    options = [str(option).strip() for option in options or [] if str(option).strip()]
    folded = fold(question)
    if not folded or SENSITIVE.search(folded):
        return None
    resume = profile.get("curriculo") or ""
    asked_skills = insights.skills(question)

    if YEARS.search(folded):
        skill = asked_skills[0] if asked_skills else None
        info = experience(resume, skill)
        declared = declared_years(profile, skill) if skill else None
        # Tempo informado na tela Currículo vale quando passa do que os cargos mostram.
        if declared and (info is None or declared["anos"] * 12 > info["meses"]):
            base = f"Informado por você: {skill} {declared['anos']:g} anos" + (f" ({declared['nota']})" if declared.get("nota") else "")
            if options:
                return _answer("", "perfil", base, options=options, index=fit_years(declared["anos"], options))
            return _answer(str(int(declared["anos"])), "perfil", base, options=[])
        if info is None and skill is None and profile.get("anos_experiencia"):
            raw = str(profile["anos_experiencia"])
            number = float(re.sub(r"[^\d.]", "", raw.replace(",", ".")) or 0)
            index = fit_years(number, options) if options else None
            return _answer(raw, "perfil", "Perfil: anos de experiência", options=options, index=index)
        if info is None:
            # Skill que o currículo não cita: 0 anos (o campo costuma aceitar só número), dito na sugestão.
            if skill and resume.strip() and skill not in insights.skills(resume):
                base = f"Não consta no currículo: {skill} (0 anos)"
                if options:
                    return _answer("", "curriculo", base, options=options, index=fit_years(0, options))
                return _answer("0", "curriculo", base, options=[])
            return None
        years = whole_years(info["meses"])
        if years is None:
            base = f"Currículo: {skill + ' em ' if skill else ''}{_period_text(info)} (menos de 6 meses)"
            if options:
                return _answer("", "curriculo", base, options=options, index=fit_years(info["meses"] / 12, options))
            return _answer("0", "curriculo", base, options=[])
        base = f"Currículo: {skill + ' em ' if skill else ''}{_period_text(info)}"
        if options:
            return _answer("", "curriculo", base, options=options, index=fit_years(info["meses"] / 12, options))
        return _answer(str(years), "curriculo", base, options=[])

    if ENGLISH.search(folded) and not asked_skills:
        return _language(folded, profile.get("nivel_ingles") or "", "inglês", options, kind)
    if SPANISH.search(folded) and not asked_skills:
        return _language(folded, profile.get("nivel_espanhol") or "", "espanhol", options, kind)

    if BASED_IN.search(folded) and (kind in {"radio", "select", "checkbox"} or options):
        answer = places.in_region(question, str(profile.get("pais") or ""))
        if answer is None:
            return None
        where = ", ".join(part for part in (profile.get("cidade"), profile.get("pais")) if part)
        return _answer("Sim" if answer else "Não", "perfil", f"Perfil: você mora em {where}",
                       options=options, index=fit_yes_no(answer, options) if options else None)

    if AUTHORIZATION.search(folded):
        answer = yes_no(profile.get("autorizacao_trabalho") or "")
        if answer is None:
            return None
        return _answer("Sim" if answer else "Não", "perfil", "Perfil: autorização de trabalho",
                       options=options, index=fit_yes_no(answer, options) if options else None)
    if VISA.search(folded):
        answer = yes_no(profile.get("precisa_visto") or "")
        if answer is None:
            return None
        return _answer("Sim" if answer else "Não", "perfil", "Perfil: precisa de visto/patrocínio",
                       options=options, index=fit_yes_no(answer, options) if options else None)
    if RELOCATE.search(folded):
        answer = yes_no(profile.get("aceita_mudanca") or "")
        if answer is None and "mudando de cidade" in fold(profile.get("modelos_trabalho") or ""):
            answer = True
        if answer is None:
            return None
        return _answer("Sim" if answer else "Não", "perfil", "Perfil: aceita mudança de cidade",
                       options=options, index=fit_yes_no(answer, options) if options else None)

    modes = [mode for mode, pattern in MODE_WORDS.items() if pattern.search(folded)]
    accepted = fold(profile.get("modelos_trabalho") or "")
    if len(modes) == 1 and accepted and not SALARY.search(folded):
        answer = fold(modes[0]) in accepted
        return _answer("Sim" if answer else "Não", "perfil", f"Perfil: aceita {profile.get('modelos_trabalho')}",
                       options=options, index=fit_yes_no(answer, options) if options else None)

    if COUNTRY.search(folded) and profile.get("pais") and not LOCATION.search(folded):
        # Lista de países: casa com qualquer grafia conhecida (Brasil, Brazil...).
        lang = places.language(question)
        if options:
            names = {fold(name) for name in places.country_names(str(profile["pais"]))}
            index = next((i for i, option in enumerate(options) if fold(option) in names), -1)
            return _answer("", "perfil", "Perfil: país", options=options, index=index)
        return _answer(places.country(str(profile["pais"]), lang), "perfil", "Perfil: país", options=[])
    if LOCATION.search(folded) and profile.get("cidade"):
        lang = places.language(question)
        names = {"pt": "português", "en": "inglês", "es": "espanhol"}
        return _answer(places.location(profile, lang), "perfil", f"Perfil: cidade, estado e país ({names[lang]})", options=options)
    if SALARY.search(folded) and (profile.get("pretensao_salarial") or profile.get("pretensao_usd")):
        return _salary(question, profile, options, kind)
    if AVAILABILITY.search(folded) and profile.get("disponibilidade"):
        return _answer(str(profile["disponibilidade"]), "perfil", "Perfil: disponibilidade", options=options)

    if asked_skills and HAS_EXPERIENCE.search(folded):
        skill = asked_skills[0]
        info = experience(resume, skill)
        if info is None and skill not in insights.skills(resume) and not declared_years(profile, skill):
            return None
        base = f"Currículo: {skill}" + (f" em {_period_text(info)}" if info else " aparece no currículo")
        if kind in {"text", "textarea"} and not options:
            return None
        return _answer("Sim", "curriculo", base, options=options, index=fit_yes_no(True, options) if options else None)
    return None
