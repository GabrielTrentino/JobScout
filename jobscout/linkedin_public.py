"""Página pública da vaga do LinkedIn: plano B quando os seletores da página logada falham.

A versão pública (sem login) tem classes estáveis; o layout logado muda com frequência.
"""

from __future__ import annotations

import html
import re
from typing import Any, Callable
from urllib.error import URLError
from urllib.request import Request, urlopen

from jobscout.activities import clean_space, fold

PUBLIC_URL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{id}"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Safari/537.36"

PATTERNS = {
    "title": r'class="[^"]*top-card-layout__title[^"]*"[^>]*>(.*?)</h\d>',
    "company": r'class="[^"]*topcard__org-name-link[^"]*"[^>]*>(.*?)</a>',
    "location": r'class="topcard__flavor topcard__flavor--bullet"[^>]*>(.*?)</span>',
    "description": r'class="[^"]*show-more-less-html__markup[^"]*"[^>]*>(.*?)</div>',
}


class PublicPageError(RuntimeError):
    """A página pública não respondeu ou veio sem os dados da vaga."""


def job_id(url: str) -> str | None:
    match = re.search(r"linkedin\.com/jobs/view/(?:[^/]*?-)?(\d+)", url)
    return match.group(1) if match else None


def _text(fragment: str) -> str:
    fragment = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</h\d>", "\n", fragment)
    fragment = re.sub(r"(?i)<li[^>]*>", "• ", fragment)
    fragment = html.unescape(re.sub(r"<[^>]+>", " ", fragment))
    return "\n".join(clean_space(line) for line in fragment.splitlines() if line.strip())


CRITERIA = {
    "nivel de experiencia": "seniority",
    "seniority level": "seniority",
    "tipo de emprego": "employment_type",
    "employment type": "employment_type",
    "setores": "industry",
    "industries": "industry",
}

COMPANY_URL = re.compile(r'class="[^"]*topcard__org-name-link[^"]*"[^>]*href="([^"?]+)')

COMPANY_ABOUT = {
    "industry": "industry",
    "size": "size",
    "headquarters": "headquarters",
    "specialties": "specialties",
}


def parse(page: str) -> dict[str, str]:
    fields = {}
    for name, pattern in PATTERNS.items():
        match = re.search(pattern, page, re.S)
        if match:
            value = _text(match.group(1))
            fields[name] = value if name == "description" else clean_space(value)
    for item in re.findall(r'class="description__job-criteria-item"[^>]*>(.*?)</li>', page, re.S):
        head = re.search(r'job-criteria-subheader[^>]*>(.*?)</h3>', item, re.S)
        body = re.search(r'job-criteria-text[^>]*>(.*?)</span>', item, re.S)
        if head and body:
            name = CRITERIA.get(fold(clean_space(_text(head.group(1)))))
            if name:
                fields[name] = clean_space(_text(body.group(1)))
    company = COMPANY_URL.search(page)
    if company:
        slug = re.search(r"/company/([^/]+)", html.unescape(company.group(1)))
        if slug:
            fields["company_url"] = f"https://www.linkedin.com/company/{slug.group(1)}/"
    return fields


def parse_company(page: str) -> dict[str, str]:
    fields = {}
    for test_id, name in COMPANY_ABOUT.items():
        match = re.search(rf'data-test-id="about-us__{test_id}"[^>]*>.*?<dd[^>]*>(.*?)</dd>', page, re.S)
        if match:
            fields[name] = clean_space(_text(match.group(1)))
    match = re.search(r'data-test-id="about-us__description"[^>]*>(.*?)</p>', page, re.S)
    if match:
        fields["description"] = _text(match.group(1))[:4000]
    return fields


def fetch_company(url: str, opener: Callable[..., Any] = urlopen, timeout: float = 10) -> dict[str, str]:
    if not re.match(r"https://([a-z]+\.)?linkedin\.com/company/[^/]+", url or ""):
        raise PublicPageError("link de empresa do LinkedIn inválido")
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "pt-BR,pt;q=0.9"})
    try:
        with opener(request, timeout=timeout) as response:
            page = response.read().decode("utf-8", "replace")
    except (URLError, OSError) as exc:
        raise PublicPageError(f"LinkedIn não respondeu ({exc})") from exc
    fields = parse_company(page)
    if not fields:
        raise PublicPageError("a página da empresa pediu login ou mudou")
    return fields


def fetch(url: str, opener: Callable[..., Any] = urlopen, timeout: float = 10) -> dict[str, str]:
    identifier = job_id(url)
    if not identifier:
        raise PublicPageError("link sem número de vaga")
    request = Request(PUBLIC_URL.format(id=identifier), headers={"User-Agent": USER_AGENT, "Accept-Language": "pt-BR,pt;q=0.9"})
    try:
        with opener(request, timeout=timeout) as response:
            page = response.read().decode("utf-8", "replace")
    except (URLError, OSError) as exc:
        raise PublicPageError(f"LinkedIn não respondeu ({exc})") from exc
    fields = parse(page)
    if not fields.get("title"):
        raise PublicPageError("a página pública veio sem título")
    return fields
