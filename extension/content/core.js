// Regras puras da extensão: sem DOM, para rodar também nos testes do Node.
(function (root) {
  "use strict";

  function fold(text) {
    return String(text || "")
      .normalize("NFD")
      .replace(/[̀-ͯ]/g, "")
      .toLowerCase()
      .replace(/\s+/g, " ")
      .trim();
  }

  function cleanLabel(text) {
    return String(text || "")
      .replace(/\s+/g, " ")
      .replace(/\s*\*\s*$/, "")
      .replace(/\b(obrigat[oó]rio|required)\b\s*$/i, "")
      .trim();
  }

  // Rótulo curto que é só um nome de campo ("Telefone") versus uma pergunta.
  // Rótulos que citam outra pessoa ou outra coisa: "Nome da empresa", "Telefone de emergência".
  // "Código do país" fica de fora pelo "codigo"; "País" e "Country" sozinhos são o seu país.
  const NOT_YOU = /\b(empresa|company|referencia|reference|emergencia|emergency|recrutador|recruiter|codigo|code|indicacao|indicou|gestor|manager|contato de|preferred|preferid\w*|preferencia|desired|desejad\w*|civil|marital)\b/;

  // Idioma de um rótulo curto, para escrever o país como a pergunta pede (Brasil / Brazil).
  const LANGUAGE_WORDS = {
    en: ["what", "your", "where", "are", "you", "is", "do", "does", "located", "live", "based", "city", "country", "state", "please", "which", "the", "location", "province"],
    pt: ["qual", "sua", "seu", "voce", "onde", "cidade", "mora", "pais", "estado", "localizacao", "atual", "reside", "esta", "localizado"],
    es: ["cual", "tu", "usted", "donde", "ciudad", "vives", "vive", "resides", "ubicacion", "provincia", "actualmente"],
  };

  function labelLanguage(text, fallback) {
    const words = fold(text).match(/[a-z]+/g) || [];
    let best = null;
    let bestScore = 0;
    for (const [lang, list] of Object.entries(LANGUAGE_WORDS)) {
      const score = words.filter((word) => list.includes(word)).length;
      if (score > bestScore) {
        best = lang;
        bestScore = score;
      }
    }
    if (best) return best;
    const page = String(fallback || "").slice(0, 2).toLowerCase();
    return ["pt", "en", "es"].includes(page) ? page : "pt";
  }

  // Valor do campo padrão no idioma do rótulo, quando o perfil tem variantes (país, localização).
  const USD_LABEL = /(us\$|u\$|\busd\b|\bdolar|\bdollar)/;
  const BRL_LABEL = /(r\$|\breais\b|\bbrl\b)/;

  function standardValue(field, label, pageLang) {
    const variants = field.valores || {};
    // Pretensão: rótulo que diz a moeda manda; sem valor nessa moeda, não preenche (não há conversão).
    if (field.chave === "pretensao_salarial") {
      const folded = fold(label);
      if (USD_LABEL.test(folded)) return variants.usd || "";
      if (BRL_LABEL.test(folded)) return variants.brl || "";
    }
    return variants[labelLanguage(label, pageLang)] || field.valor;
  }

  function matchStandard(label, fields) {
    const folded = fold(cleanLabel(label))
      .replace(/[^a-z0-9@. -]/g, " ")
      .replace(/\b(seu|sua|your|o|a|opcional|optional)\b/g, " ")
      .replace(/\s+/g, " ")
      .trim();
    if (!folded || folded.length > 60 || NOT_YOU.test(folded)) return null;
    const words = folded.split(" ");
    let best = null;
    for (const field of fields || []) {
      for (const pattern of field.rotulos || []) {
        const p = fold(pattern);
        let score = 0;
        if (folded === p) score = 100 + p.length;
        else if (p.includes(" ") && folded.includes(p)) score = p.length;
        else if (!p.includes(" ") && words.length <= 3 && words.includes(p)) score = p.length;
        if (score && (!best || score > best.score)) best = { field, score };
      }
    }
    return best ? best.field : null;
  }

  function isOpenQuestion(info) {
    const label = cleanLabel(info.label);
    if (!label) return false;
    if (info.tag === "select" || info.type === "checkbox" || info.type === "radio" || info.type === "file") return false;
    if (info.tag === "textarea") return true;
    return label.length >= 25 || label.includes("?");
  }

  function linkedinJobUrl(href) {
    let url;
    try {
      url = new URL(href);
    } catch (error) {
      return null;
    }
    const match = url.pathname.match(/\/jobs\/view\/(?:[^/]*?-)?(\d+)/);
    const id = match ? match[1] : url.searchParams.get("currentJobId");
    return id ? `https://www.linkedin.com/jobs/view/${id}/` : null;
  }

  function pageKey(href) {
    try {
      const url = new URL(href);
      return url.origin + url.pathname + url.search;
    } catch (error) {
      return String(href || "");
    }
  }

  function labelKey(text) {
    return fold(cleanLabel(text)).replace(/[^a-z0-9 ]/g, " ").replace(/\s+/g, " ").trim();
  }

  // Pergunta já respondida antes: mesmo rótulo, ou quase (troca de uma palavra numa pergunta longa).
  function matchHistory(label, history) {
    const key = labelKey(label);
    if (!key) return null;
    const words = new Set(key.split(" "));
    let best = null;
    for (const item of history || []) {
      const other = labelKey(item.rotulo);
      if (!other) continue;
      if (other === key) return item;
      const otherWords = new Set(other.split(" "));
      if (Math.min(words.size, otherWords.size) < 4) continue;
      let shared = 0;
      for (const word of words) if (otherWords.has(word)) shared += 1;
      const score = shared / (words.size + otherWords.size - shared);
      if (score >= 0.8 && (!best || score > best.score)) best = { item, score };
    }
    return best ? best.item : null;
  }

  // Opção de select/rádio que corresponde a uma resposta guardada.
  function pickOption(options, value) {
    const wanted = fold(value);
    if (!wanted) return -1;
    const texts = options.map((option) => fold(option));
    let index = texts.indexOf(wanted);
    if (index >= 0) return index;
    const yes = /^(sim|yes)\b/, no = /^(nao|no)\b/;
    for (const rule of [yes, no]) {
      if (rule.test(wanted)) {
        index = texts.findIndex((text) => rule.test(text));
        if (index >= 0) return index;
      }
    }
    return -1;
  }

  const SUBMIT_TEXT = /^(enviar candidatura|submit application|submit your application|submit|send application|apply for this job|enviar inscri[cç][aã]o|enviar aplica[cç][aã]o|finalizar candidatura|concluir candidatura|enviar)$/i;

  function isSubmitText(text) {
    return SUBMIT_TEXT.test(String(text || "").replace(/\s+/g, " ").trim());
  }

  // JSON-LD schema.org/JobPosting, usado por muitas páginas de vaga.
  function jobFromJsonLd(blocks) {
    for (const raw of blocks || []) {
      let data;
      try {
        data = JSON.parse(raw);
      } catch (error) {
        continue;
      }
      const items = [].concat(data && data["@graph"] ? data["@graph"] : data);
      for (const item of items) {
        if (!item || [].concat(item["@type"]).indexOf("JobPosting") < 0) continue;
        const org = item.hiringOrganization || {};
        const place = [].concat(item.jobLocation || [])[0] || {};
        const address = place.address || {};
        return {
          title: item.title || "",
          company: typeof org === "string" ? org : org.name || "",
          location: [address.addressLocality, address.addressRegion].filter(Boolean).join(", "),
          description: stripTags(item.description || ""),
        };
      }
    }
    return null;
  }

  function stripTags(html) {
    return String(html)
      .replace(/<br\s*\/?>|<\/p>|<\/li>/gi, "\n")
      .replace(/<[^>]+>/g, " ")
      .replace(/&nbsp;/g, " ")
      .replace(/&amp;/g, "&")
      .replace(/&lt;/g, "<")
      .replace(/&gt;/g, ">")
      .replace(/&quot;/g, '"')
      .replace(/&#39;/g, "'")
      .replace(/[ \t]+/g, " ")
      .replace(/\n\s*\n+/g, "\n")
      .trim();
  }

  // Sistemas de candidatura conhecidos: a empresa vem no endereço (jobs.ashbyhq.com/<empresa>/...).
  const ATS = [
    { name: "Ashby", host: /(^|\.)ashbyhq\.com$/, company: (url) => url.pathname.split("/")[1] },
    { name: "Greenhouse", host: /(^|\.)greenhouse\.io$/, company: (url) => url.pathname.split("/")[1] || new URLSearchParams(url.search).get("for") },
    { name: "Lever", host: /(^|\.)lever\.co$/, company: (url) => url.pathname.split("/")[1] },
    { name: "Workable", host: /(^|\.)workable\.com$/, company: (url) => url.pathname.split("/")[1] },
    { name: "Gupy", host: /\.gupy\.io$/, company: (url) => url.hostname.split(".")[0] },
    { name: "SmartRecruiters", host: /(^|\.)smartrecruiters\.com$/, company: (url) => url.pathname.split("/")[1] },
    { name: "Recruitee", host: /\.recruitee\.com$/, company: (url) => url.hostname.split(".")[0] },
    { name: "BambooHR", host: /\.bamboohr\.com$/, company: (url) => url.hostname.split(".")[0] },
    { name: "Workday", host: /\.myworkdayjobs\.com$/, company: (url) => url.hostname.split(".")[0] },
    { name: "Teamtailor", host: /\.teamtailor\.com$/, company: (url) => url.hostname.split(".")[0] },
    { name: "Breezy", host: /\.breezy\.hr$/, company: (url) => url.hostname.split(".")[0] },
    { name: "Solides", host: /\.solides\.jobs$/, company: (url) => url.hostname.split(".")[0] },
  ];

  function atsFor(href) {
    let url;
    try {
      url = new URL(href);
    } catch (error) {
      return null;
    }
    const ats = ATS.find((item) => item.host.test(url.hostname));
    if (!ats) return null;
    const raw = (ats.company(url) || "").replace(/[-_]+/g, " ").trim();
    // "truelogic" → "Truelogic"; o nome oficial vem do JSON-LD da página, quando houver.
    return { ats: ats.name, company: raw ? raw.replace(/\b\w/g, (letter) => letter.toUpperCase()) : "" };
  }

  // Endereço da vaga sem a etapa de candidatura nem rastreio (?utm_...).
  function jobUrlFrom(href) {
    try {
      const url = new URL(href);
      return url.origin + url.pathname.replace(/\/(application|apply|candidatar|candidatura|aplicar|inscricao)\/?$/i, "").replace(/\/$/, "");
    } catch (error) {
      return href;
    }
  }

  const JOB_SIGNAL = /\b(jobs?|careers?|carreiras?|vagas?|apply|application|candidat\w*|recruit\w*|talent|position|opening|hiring|trabalhe[- ]conosco|oportunidades?)\b/i;

  // A página parece uma candidatura? Vale para o modo "todos os sites": formulário de login,
  // compra ou contato não recebe preenchimento nem vira vaga.
  function looksLikeApplication({ href, title, heading, hasJobPosting, fieldLabels }) {
    if (hasJobPosting || atsFor(href)) return true;
    const where = `${href} ${title || ""} ${heading || ""}`;
    if (!JOB_SIGNAL.test(where.replace(/[/_.-]+/g, " "))) return false;
    const labels = fold((fieldLabels || []).join(" | "));
    // Precisa pedir coisas de candidatura: currículo, LinkedIn, experiência, pretensão...
    return /curriculo|resume|cv\b|linkedin|experien|salar|pretens|cover letter|carta|portfolio/.test(labels);
  }

  const api = {
    fold, cleanLabel, matchStandard, isOpenQuestion, linkedinJobUrl, pageKey, isSubmitText, jobFromJsonLd, stripTags,
    matchHistory, pickOption, labelLanguage, standardValue, atsFor, jobUrlFrom, looksLikeApplication,
  };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.JobScoutCore = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
