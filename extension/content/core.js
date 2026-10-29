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
  const NOT_YOU = /\b(empresa|company|referencia|reference|emergencia|emergency|recrutador|recruiter|codigo|code|pais|country|indicacao|indicou|gestor|manager|contato de)\b/;

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

  const SUBMIT_TEXT = /^(enviar candidatura|submit application|enviar inscri[cç][aã]o|finalizar candidatura|concluir candidatura|enviar)$/i;

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

  const api = {
    fold, cleanLabel, matchStandard, isOpenQuestion, linkedinJobUrl, pageKey, isSubmitText, jobFromJsonLd, stripTags,
    matchHistory, pickOption,
  };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.JobScoutCore = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
