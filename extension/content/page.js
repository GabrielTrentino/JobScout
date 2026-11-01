// Parte comum a todos os sites: observa a página, lê o formulário e conversa com o service worker.
// Só lê e preenche. Nunca clica em Enviar.
(function () {
  "use strict";

  const core = globalThis.JobScoutCore;
  const reported = new Set();
  const answered = new Set();
  let adapter = null;
  let lastJobKey = "";
  let jobTimer = null;
  let formTimer = null;
  let pollTimer = null;
  let fieldCounter = 0;
  let standardFields = null;
  let history = null;
  // Rótulo -> valor preenchido, acumulado entre as etapas do formulário (o LinkedIn some com a etapa anterior).
  const collected = new Map();
  // Campos que já ganharam sugestão: não viram rascunho de pergunta aberta nas próximas leituras.
  const withSuggestion = new Set();
  // Arquivos enviados (currículo, carta) ao longo das etapas: vão junto no clique em Enviar.
  const collectedDocs = new Set();
  let lastFailure = "";
  let misses = 0;

  function send(message) {
    return new Promise((resolve) => {
      try {
        chrome.runtime.sendMessage(message, (response) => {
          if (chrome.runtime.lastError) resolve(null);
          else resolve(response || null);
        });
      } catch (error) {
        // A extensão foi recarregada; esta aba precisa de refresh.
        resolve(null);
      }
    });
  }

  function emit(event) {
    return send({ kind: "event", event: { site: adapter.site, pagina: core.pageKey(location.href), ...event } });
  }

  function text(node) {
    return node ? (node.innerText || node.textContent || "").replace(/\s+\n/g, "\n").trim() : "";
  }

  function pick(selectors, scope) {
    for (const selector of selectors) {
      const node = (scope || document).querySelector(selector);
      if (node && text(node)) return node;
    }
    return null;
  }

  function jsonLdJob() {
    const blocks = [...document.querySelectorAll('script[type="application/ld+json"]')].map((node) => node.textContent);
    return core.jobFromJsonLd(blocks);
  }

  function reportFailure(detail) {
    const key = location.href + detail;
    if (key === lastFailure) return;
    lastFailure = key;
    emit({ tipo: "selector_failed", detalhe: detail });
  }

  // Vaga aberta

  function checkJob() {
    const job = adapter.currentJob();
    if (!job) return;
    if (!job.title && !job.company) {
      // A página pode ainda estar carregando; só desiste depois de algumas tentativas.
      // Com publicFallback, manda só o link e o JobScout busca a página pública da vaga.
      misses += 1;
      if (misses < (adapter.publicFallback ? 2 : 3)) {
        scheduleJob();
        return;
      }
      if (!adapter.publicFallback) {
        reportFailure("título e empresa não encontrados");
        return;
      }
    } else {
      misses = 0;
    }
    const key = job.url + "|" + job.title + "|" + job.company + "|" + (job.description || "").length;
    if (key === lastJobKey) return;
    lastJobKey = key;
    emit({ tipo: "job_viewed", vaga: job });
  }

  // Limita a frequência sem adiar para sempre: o LinkedIn muda o DOM o tempo todo.
  function scheduleJob() {
    if (jobTimer) return;
    jobTimer = setTimeout(() => {
      jobTimer = null;
      checkJob();
    }, 1500);
  }

  // Formulário

  // Shadow DOM aberto ou fechado: content scripts do Chrome alcançam os dois por chrome.dom.
  function shadowOf(host) {
    try {
      if (globalThis.chrome && chrome.dom && chrome.dom.openOrClosedShadowRoot) return chrome.dom.openOrClosedShadowRoot(host) || null;
    } catch (error) {
      // Sem acesso: segue com o shadowRoot aberto, se houver.
    }
    return host.shadowRoot || null;
  }

  // Documento ou shadow root onde o campo mora: rótulos e ids são procurados ali.
  function scopeOf(element) {
    const root = element.getRootNode();
    return root && root.querySelector ? root : document;
  }

  function labelFor(element) {
    const scope = scopeOf(element);
    if (element.id) {
      const label = scope.querySelector(`label[for="${CSS.escape(element.id)}"]`);
      if (label && text(label)) return text(label);
    }
    const wrapping = element.closest("label");
    if (wrapping && text(wrapping)) return text(wrapping);
    const labelledBy = element.getAttribute("aria-labelledby");
    if (labelledBy) {
      const joined = labelledBy.split(/\s+/).map((id) => text(scope.getElementById ? scope.getElementById(id) : document.getElementById(id))).join(" ").trim();
      if (joined) return joined;
    }
    if (element.getAttribute("aria-label")) return element.getAttribute("aria-label");
    const group = element.closest(adapter.fieldGroup || "fieldset, [role='group']");
    if (group) {
      const legend = group.querySelector("legend, label, span, p");
      if (legend && text(legend)) return text(legend);
    }
    return element.getAttribute("placeholder") || element.getAttribute("name") || "";
  }

  function visible(element) {
    return element.offsetParent !== null && !element.disabled && !element.readOnly;
  }

  const CONSENT = /consent|consentimento|concordo|i agree|aceito os|terms|termos|privacy|privacidade|opt[- ]?out|marketing|newsletter/i;
  const SKIP_TYPES = ["hidden", "submit", "button", "password", "search", "file", "image", "reset"];
  const PLACEHOLDER_OPTION = /^(selecion|select|escolh|choose|--)/i;

  function groupOf(element) {
    return element.closest("fieldset, [role='radiogroup'], [role='group']") || element.closest(adapter.fieldGroup || "fieldset");
  }

  // A pergunta de um rádio ou checkbox é a legenda do grupo; o rótulo dele é só a opção.
  function questionFor(element) {
    if (element.type === "radio" || element.type === "checkbox") {
      const group = groupOf(element);
      const legend = group && group.querySelector("legend, [role='heading'], h3, h4, span[aria-hidden='true'], p");
      if (legend && text(legend)) return text(legend);
    }
    return labelFor(element);
  }

  function valueOf(element) {
    if (element.tagName === "SELECT") {
      const option = element.options[element.selectedIndex];
      const label = option ? text(option) || option.value : "";
      return option && option.value !== "" && !PLACEHOLDER_OPTION.test(label) ? label : "";
    }
    if (element.type === "radio" || element.type === "checkbox") return element.checked ? core.cleanLabel(labelFor(element)) : "";
    return element.value || "";
  }

  const FILE_NAME = /[^\\/:*?"<>|\n]{1,120}\.(pdf|docx?|odt|rtf)\b/i;

  // Currículo enviado: arquivo escolhido agora ou o cartão selecionado entre os já salvos no site.
  function sentDocuments(root) {
    const found = [];
    for (const input of root.querySelectorAll("input[type='file']")) {
      for (const file of input.files || []) found.push(file.name);
    }
    const selected = root.querySelectorAll("input[type='radio']:checked, input[type='checkbox']:checked, [aria-checked='true'], [aria-selected='true'], [class*='selected'], [class*='--active']");
    for (const node of selected) {
      const scope = node.matches("input") ? node.closest("label, li, [class*='card'], [class*='document']") || node.parentElement : node;
      const match = text(scope).match(FILE_NAME) || (node.matches("input") ? labelFor(node).match(FILE_NAME) : null);
      if (match) found.push(match[0].trim());
    }
    return [...new Set(found)];
  }

  // Lê o que está preenchido agora e junta ao que veio das etapas anteriores.
  function collectAnswers() {
    const root = adapter.formRoot();
    if (!root) return;
    for (const name of sentDocuments(root)) collectedDocs.add(name);
    const seenNow = new Map();
    for (const element of root.querySelectorAll("input, textarea, select")) {
      const type = (element.getAttribute("type") || "text").toLowerCase();
      if (SKIP_TYPES.includes(type) || element.offsetParent === null) continue;
      const question = core.cleanLabel(questionFor(element));
      const value = String(valueOf(element)).trim();
      if (!question || !value || core.matchStandard(question, standardFields || [])) continue;
      if (type === "checkbox" && seenNow.has(question)) seenNow.set(question, seenNow.get(question) + "; " + value);
      else seenNow.set(question, value);
    }
    if (adapter.choiceButtons) {
      for (const group of choiceGroups(root)) {
        const chosen = chosenButton(group);
        const question = core.cleanLabel(choiceQuestion(group));
        if (chosen && question) seenNow.set(question, core.cleanLabel(text(chosen)));
      }
    }
    for (const [question, value] of seenNow) collected.set(question, value);
  }

  // O estilo do contorno verde precisa estar no mesmo documento ou shadow root do campo.
  function markFilled(element) {
    element.dataset.jobscoutPreenchido = "1";
    const scope = scopeOf(element);
    if (!scope.querySelector("style[data-jobscout-style]")) {
      const style = document.createElement("style");
      style.dataset.jobscoutStyle = "1";
      style.textContent = "[data-jobscout-preenchido]{outline:2px solid rgba(47,133,90,.6)!important;outline-offset:1px}";
      (scope === document ? document.head : scope).appendChild(style);
    }
  }

  // Preenche com a resposta dada antes a mesma pergunta. Textos longos continuam virando rascunho.
  function fillFromHistory(element, info) {
    if (!history || !history.length || element.dataset.jobscoutPreenchido) return false;
    if (info.type === "radio") {
      const group = groupOf(element);
      if (!group || group.dataset.jobscoutPreenchido) return false;
      const radios = [...group.querySelectorAll("input[type='radio']")];
      if (radios.some((radio) => radio.checked)) return false;
      const remembered = core.matchHistory(questionFor(element), history);
      if (!remembered) return false;
      const index = core.pickOption(radios.map((radio) => core.cleanLabel(labelFor(radio))), remembered.valor);
      if (index < 0) return false;
      radios[index].click();
      markFilled(group);
      return true;
    }
    if (info.type === "checkbox" || info.tag === "textarea") return false;
    const remembered = core.matchHistory(info.label, history);
    if (!remembered) return false;
    if (info.tag === "select") {
      if (valueOf(element)) return false;
      const index = core.pickOption([...element.options].map((option) => text(option) || option.value), remembered.valor);
      if (index < 0) return false;
      element.selectedIndex = index;
      element.dispatchEvent(new Event("input", { bubbles: true }));
      element.dispatchEvent(new Event("change", { bubbles: true }));
    } else {
      if (element.value) return false;
      // Resposta antiga em texto não entra em campo que só aceita número (ou acima do limite).
      if (!fits({ tipo: fieldKind(element, info), max: element.maxLength > 0 ? element.maxLength : 0 }, remembered.valor)) return false;
      setValue(element, remembered.valor);
    }
    markFilled(element);
    return true;
  }

  // Sugestões: perguntas curtas e de opção que o JobScout sabe responder pelo Perfil, currículo ou histórico.
  // Aparecem ao lado do campo; só preenche quando a pessoa clica em Usar.

  function optionsOf(element, info) {
    if (info.tag === "select") {
      return [...element.options]
        .filter((option) => option.value !== "" && !PLACEHOLDER_OPTION.test(text(option) || option.value))
        .map((option) => text(option) || option.value);
    }
    if (info.type === "radio") {
      const group = groupOf(element);
      return group ? [...group.querySelectorAll("input[type='radio']")].map((radio) => core.cleanLabel(labelFor(radio))) : [];
    }
    return [];
  }

  function hasAnswer(element, info) {
    if (info.type === "buttons") return Boolean(chosenButton(element));
    if (info.type === "checkboxes") return [...element.querySelectorAll("input[type='checkbox']")].some((box) => box.checked);
    if (info.type === "radio") {
      const group = groupOf(element);
      return Boolean(group && [...group.querySelectorAll("input[type='radio']")].some((radio) => radio.checked));
    }
    return Boolean(String(valueOf(element)).trim());
  }

  // Campo que só aceita número: tipo number, teclado numérico ou o "numeric" que o LinkedIn põe no id.
  const NUMERIC_HINT = /numeric|number|numero|integer|decimal/i;

  function fieldKind(element, info) {
    if (info.type === "radio") return "radio";
    if (info.tag === "select") return "select";
    if (info.tag === "textarea") return "textarea";
    const inputmode = element.getAttribute("inputmode") || "";
    const pattern = element.getAttribute("pattern") || "";
    if (info.type === "number" || /numeric|decimal/.test(inputmode) || /\\d|\[0-9/.test(pattern)
      || NUMERIC_HINT.test(`${element.id} ${element.getAttribute("name") || ""}`)) return "number";
    return info.type;
  }

  // O valor cabe no campo? Número em campo numérico e dentro do limite de caracteres.
  function fits(item, value) {
    const text = String(value || "");
    if (!text) return false;
    if (item.tipo === "number" && !/^\d+([.,]\d+)?$/.test(text.trim())) return false;
    if (item.max && text.length > item.max) return false;
    return true;
  }

  function applySuggestion(item, value) {
    if (!fits(item, value)) return false;
    if (item.info.type === "buttons") {
      const button = choiceButtons(item.target).find((node) => core.cleanLabel(text(node)) === value);
      if (!button) return false;
      button.click();
      item.target.dataset.jobscoutEscolha = value;
    } else if (item.info.type === "checkboxes") {
      const wanted = value.split(";").map((part) => part.trim());
      const boxes = [...item.target.querySelectorAll("input[type='checkbox']")].filter((box) => wanted.includes(core.cleanLabel(labelFor(box))));
      if (!boxes.length) return false;
      for (const box of boxes) if (!box.checked) box.click();
    } else if (item.tipo === "radio") {
      const radios = [...item.target.querySelectorAll("input[type='radio']")];
      const index = radios.findIndex((radio) => core.cleanLabel(labelFor(radio)) === value);
      if (index < 0) return false;
      radios[index].click();
    } else if (item.tipo === "select") {
      const index = [...item.element.options].findIndex((option) => (text(option) || option.value) === value);
      if (index < 0) return false;
      item.element.selectedIndex = index;
      item.element.dispatchEvent(new Event("input", { bubbles: true }));
      item.element.dispatchEvent(new Event("change", { bubbles: true }));
    } else {
      setValue(item.element, value);
      if (isListField(item.element)) pickFromList(item.element, value);
    }
    markFilled(item.target);
    return true;
  }

  // Lista com busca (Location da Ashby, por exemplo): digitar só filtra; é preciso escolher a opção.
  function isListField(element) {
    return element.getAttribute("role") === "combobox" || element.hasAttribute("aria-autocomplete") || /start typing|comece a digitar/i.test(element.placeholder || "");
  }

  async function pickFromList(element, value) {
    const words = core.fold(value).split(",").map((part) => part.trim()).filter(Boolean);
    element.focus();
    element.dispatchEvent(new Event("input", { bubbles: true }));
    for (let attempt = 0; attempt < 12; attempt += 1) {
      await new Promise((resolve) => setTimeout(resolve, 250));
      const options = [...document.querySelectorAll("[role='option']")].filter((node) => node.offsetParent !== null);
      if (!options.length) continue;
      const score = (node) => words.filter((word) => core.fold(text(node)).includes(word)).length;
      const best = options.reduce((top, node) => (score(node) > score(top) ? node : top), options[0]);
      if (score(best)) {
        best.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
        best.click();
        element.blur();
      }
      return;
    }
  }

  // Anexar o currículo: o PDF vem do JobScout e só entra no campo no clique em Anexar.
  const RESUME_FILE = /resume|curr[ií]culo|\bcv\b/i;

  function fileQuestion(input) {
    return core.cleanLabel(labelFor(input)) || input.getAttribute("aria-label") || input.name || input.id || "";
  }

  async function offerResume(root, job) {
    for (const input of root.querySelectorAll("input[type='file']")) {
      if (input.dataset.jobscoutAnexo || input.files.length || !RESUME_FILE.test(fileQuestion(input))) continue;
      input.dataset.jobscoutAnexo = "1";
      const response = await send({ kind: "resumes", url: job ? job.url : "" });
      const choices = (response && response.curriculos) || [];
      if (choices.length) showResumeChip(input, choices);
    }
  }

  function showResumeChip(input, choices) {
    const host = document.createElement("span");
    host.dataset.jobscoutSugestao = "1";
    const root = host.attachShadow({ mode: "open" });
    const style = document.createElement("style");
    style.textContent = CHIP_STYLE + " select{font:13px 'Segoe UI',system-ui,sans-serif;max-width:60%}";
    const chip = document.createElement("div");
    chip.className = "chip";
    const label = document.createElement("span");
    label.textContent = "Currículo:";
    const select = document.createElement("select");
    select.setAttribute("aria-label", "Currículo para anexar");
    for (const choice of choices) {
      const option = document.createElement("option");
      option.value = String(choice.versao);
      option.textContent = choice.nome;
      select.append(option);
    }
    const use = document.createElement("button");
    use.type = "button";
    use.className = "use";
    use.textContent = "Anexar";
    const note = document.createElement("span");
    note.className = "base";
    use.addEventListener("click", async (event) => {
      event.preventDefault();
      event.stopPropagation();
      use.disabled = true;
      note.textContent = "Gerando o PDF…";
      const file = await send({ kind: "resume_pdf", versao: Number(select.value) });
      if (!file || file.erro) {
        note.textContent = (file && file.erro) || "O JobScout não respondeu.";
        use.disabled = false;
        return;
      }
      const bytes = Uint8Array.from(atob(file.base64), (letter) => letter.charCodeAt(0));
      const transfer = new DataTransfer();
      transfer.items.add(new File([bytes], file.nome, { type: "application/pdf" }));
      input.files = transfer.files;
      input.dispatchEvent(new Event("input", { bubbles: true }));
      input.dispatchEvent(new Event("change", { bubbles: true }));
      collectedDocs.add(file.nome);
      note.textContent = `Anexado: ${file.nome}`;
      use.disabled = false;
    });
    chip.append(label, select, use, note);
    root.append(style, chip);
    (input.closest(adapter.fieldGroup) || input.parentElement).appendChild(host);
  }

  const CHIP_STYLE = `
    :host { all: initial; display: block; margin: 6px 0 2px; }
    .chip { display: flex; flex-wrap: wrap; align-items: center; gap: 4px 8px; padding: 6px 8px; border-radius: 8px;
      font: 13px/1.35 "Segoe UI", system-ui, sans-serif; color: #16202a; background: #eef4fb; border: 1px solid #c8d8ea; }
    .value { font-weight: 700; }
    .base { flex: 1 1 12rem; color: #4a5a68; font-size: 12px; }
    button { font: 600 12px "Segoe UI", system-ui, sans-serif; border-radius: 6px; cursor: pointer; padding: 3px 10px; }
    .use { color: #fff; background: #2f6fb3; border: 1px solid #2f6fb3; }
    .skip { color: #4a5a68; background: transparent; border: 1px solid transparent; padding: 3px 6px; }
    @media (prefers-color-scheme: dark) {
      .chip { color: #e6edf3; background: #1b2633; border-color: #33465a; }
      .base, .skip { color: #9fb0c0; }
    }`;

  function showSuggestion(item, suggestion) {
    const host = document.createElement("span");
    host.dataset.jobscoutSugestao = "1";
    const root = host.attachShadow({ mode: "open" });
    const style = document.createElement("style");
    style.textContent = CHIP_STYLE;
    const chip = document.createElement("div");
    chip.className = "chip";
    const label = document.createElement("span");
    label.append(suggestion.origem === "ia" ? "Sugestão da IA: " : "Sugestão: ");
    const value = document.createElement("span");
    value.className = "value";
    value.textContent = suggestion.valor;
    label.append(value);
    const base = document.createElement("span");
    base.className = "base";
    base.textContent = suggestion.base || "";
    const use = document.createElement("button");
    use.type = "button";
    use.className = "use";
    use.textContent = "Usar";
    const skip = document.createElement("button");
    skip.type = "button";
    skip.className = "skip";
    skip.textContent = "Agora não";
    skip.setAttribute("aria-label", "Dispensar sugestão");
    use.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      if (applySuggestion(item, suggestion.valor)) host.remove();
      else base.textContent = "Não achei essa opção no campo; preencha você.";
    });
    skip.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      host.remove();
    });
    // A sugestão não reflete a experiência real (ex.: poucos anos de SQL): vai para o backlog do currículo.
    const improve = document.createElement("button");
    improve.type = "button";
    improve.className = "skip";
    improve.textContent = "Ponto de melhoria";
    improve.title = "Anotar no backlog do currículo para completar depois e reprocessar";
    improve.addEventListener("click", async (event) => {
      event.preventDefault();
      event.stopPropagation();
      improve.disabled = true;
      const job = adapter.currentJob();
      const response = await send({
        kind: "improvement",
        dados: {
          pergunta: item.rotulo, opcoes: item.opcoes, tipo: item.tipo,
          sugestao: suggestion.valor, base: suggestion.base, origem: suggestion.origem,
          vaga: job ? { url: job.url, title: job.title, company: job.company } : null,
        },
      });
      if (response && !response.erro) {
        improve.textContent = "Anotado ✓";
        base.textContent = "No backlog do currículo (JobScout > Currículo). Use a sugestão agora ou preencha você.";
      } else {
        improve.disabled = false;
        base.textContent = "Não consegui anotar: o JobScout está aberto?";
      }
    });
    chip.append(label, base, use, improve, skip);
    root.append(style, chip);
    item.target.insertAdjacentElement("afterend", host);
  }

  // Pede sugestões para os campos ainda vazios e devolve os ids dos que receberam uma.
  async function suggestFor(items) {
    if (!items.length) return new Set();
    const response = await send({ kind: "suggest", campos: items.map(({ campo, rotulo, tipo, opcoes, max }) => ({ campo, rotulo, tipo, opcoes, max })) });
    const done = new Set();
    for (const suggestion of (response && response.sugestoes) || []) {
      const item = items.find((candidate) => candidate.campo === suggestion.campo);
      if (!item || !item.target.isConnected || hasAnswer(item.element, item.info) || !fits(item, suggestion.valor)) continue;
      showSuggestion(item, suggestion);
      done.add(item.campo);
      withSuggestion.add(item.campo);
    }
    return done;
  }

  // IA: só quando o JobScout tem um modelo ligado (Config > IA). Sem modelo, para de perguntar por um minuto.
  let aiOffUntil = 0;

  function showThinking(item) {
    const host = document.createElement("span");
    host.dataset.jobscoutSugestao = "1";
    const root = host.attachShadow({ mode: "open" });
    const style = document.createElement("style");
    style.textContent = CHIP_STYLE + " .chip{opacity:.75} .dot{display:inline-block;animation:p 1s infinite alternate} @keyframes p{to{opacity:.2}}";
    const chip = document.createElement("div");
    chip.className = "chip";
    const label = document.createElement("span");
    label.className = "base";
    label.innerHTML = 'IA pensando numa sugestão<span class="dot">…</span>';
    chip.append(label);
    root.append(style, chip);
    item.target.insertAdjacentElement("afterend", host);
    return host;
  }

  // A IA responde em lotes: formulário grande não estoura o limite nem o tempo de uma chamada só.
  const AI_BATCH = 6;

  async function suggestWithAI(items, job) {
    if (Date.now() < aiOffUntil) return;
    for (let start = 0; start < items.length; start += AI_BATCH) {
      const batch = items.slice(start, start + AI_BATCH);
      const waiting = batch.map((item) => showThinking(item));
      let response = null;
      try {
        response = await send({
          kind: "suggest_ai",
          campos: batch.map(({ campo, rotulo, tipo, opcoes, max }) => ({ campo, rotulo, tipo, opcoes, max })),
          vaga: job ? { url: job.url, title: job.title, company: job.company, description: (job.description || "").slice(0, 4000) } : null,
        });
      } finally {
        waiting.forEach((host) => host.remove());
      }
      if (!response || response.ia === false) {
        aiOffUntil = Date.now() + 60000;
        return;
      }
      for (const suggestion of response.sugestoes || []) {
        const item = batch.find((candidate) => candidate.campo === suggestion.campo);
        if (!item || !item.target.isConnected || hasAnswer(item.element, item.info) || !fits(item, suggestion.valor)) continue;
        showSuggestion(item, suggestion);
        withSuggestion.add(item.campo);
      }
    }
    // Pergunta que nem a IA respondeu com segurança não fica muda: a pessoa vê que foi lida.
    if (adapter.suggestAll) {
      for (const item of items) {
        if (!withSuggestion.has(item.campo) && item.target.isConnected && !hasAnswer(item.element, item.info)) showNoSuggestion(item);
      }
    }
  }

  function showNoSuggestion(item) {
    const host = document.createElement("span");
    host.dataset.jobscoutSugestao = "1";
    const root = host.attachShadow({ mode: "open" });
    const style = document.createElement("style");
    style.textContent = CHIP_STYLE;
    const chip = document.createElement("div");
    chip.className = "chip";
    const label = document.createElement("span");
    label.className = "base";
    label.textContent = "Sem sugestão: não achei isso no Perfil nem no currículo.";
    const skip = document.createElement("button");
    skip.type = "button";
    skip.className = "skip";
    skip.textContent = "Ok";
    skip.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      host.remove();
    });
    chip.append(label, skip);
    root.append(style, chip);
    item.target.insertAdjacentElement("afterend", host);
  }

  function fieldId(element) {
    if (!element.dataset.jobscoutCampo) {
      fieldCounter += 1;
      element.dataset.jobscoutCampo = "js-" + fieldCounter;
    }
    return element.dataset.jobscoutCampo;
  }

  function setValue(element, value) {
    const proto = element.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, "value").set;
    element.focus();
    setter.call(element, value);
    element.dispatchEvent(new Event("input", { bubbles: true }));
    element.dispatchEvent(new Event("change", { bubbles: true }));
    element.blur();
  }

  // Perguntas respondidas com botões (Sim/Não da Ashby, por exemplo): um bloco de pergunta sem campo,
  // com 2 a 6 botões curtos que não são de envio.
  function choiceButtons(group) {
    return [...group.querySelectorAll("button, [role='button']")].filter((button) => {
      const label = text(button);
      return label && label.length <= 40 && button.offsetParent !== null && !adapter.isSubmit(button);
    });
  }

  function choiceGroups(root) {
    if (!adapter.fieldGroup) return [];
    const groups = [];
    for (const group of root.querySelectorAll(adapter.fieldGroup)) {
      // A Ashby guarda a resposta num campo escondido dentro do bloco: só campo visível desqualifica.
      if ([...group.querySelectorAll("input:not([type='hidden']), textarea, select")].some((node) => node.offsetParent !== null)) continue;
      const buttons = choiceButtons(group);
      if (buttons.length < 2 || buttons.length > 6) continue;
      // Fica com o bloco mais de dentro: o de fora também "tem" os mesmos botões.
      if (groups.some((other) => group.contains(other))) continue;
      for (let i = groups.length - 1; i >= 0; i -= 1) if (groups[i].contains(group)) groups.splice(i, 1);
      group.dataset.jobscoutBotoes = "1";
      groups.push(group);
    }
    return groups;
  }

  function choiceQuestion(group) {
    const label = group.querySelector("label, legend, [class*='label' i], [class*='title' i], h3, h4, p");
    if (label && text(label) && !label.querySelector("button")) return text(label);
    return text(group).replace(choiceButtons(group).map((button) => text(button)).join(""), "").trim();
  }

  // Botão escolhido: marcado pela página (aria-pressed, classe "selected") ou clicado aqui.
  function chosenButton(group) {
    const buttons = choiceButtons(group);
    const marked = buttons.find((button) => button.getAttribute("aria-pressed") === "true" || button.getAttribute("aria-checked") === "true"
      || button.getAttribute("aria-selected") === "true" || /(^|[\s_-])(active|selected|checked|isSelected)/i.test(String(button.className)));
    if (marked) return marked;
    const remembered = group.dataset.jobscoutEscolha;
    return remembered ? buttons.find((button) => core.cleanLabel(text(button)) === remembered) || null : null;
  }

  async function scanForm() {
    const root = adapter.formRoot();
    if (!root) {
      // Formulário fechado sem envio: o que foi lido não vale para a próxima vaga.
      collected.clear();
      collectedDocs.clear();
      return;
    }
    const elements = [...root.querySelectorAll("input, textarea, select")].filter(visible);
    if (!elements.length) return;
    if (standardFields === null) {
      const response = await send({ kind: "fields" });
      standardFields = (response && response.campos) || [];
      history = (response && response.historico) || [];
    }
    const settings = (await send({ kind: "settings" })) || {};
    const questions = [];
    const candidates = [];
    for (const element of elements) {
      const info = {
        tag: element.tagName.toLowerCase(),
        type: (element.getAttribute("type") || "text").toLowerCase(),
        label: core.cleanLabel(labelFor(element)),
      };
      if (SKIP_TYPES.includes(info.type)) continue;
      const id = fieldId(element);
      let standard = info.tag !== "select" && info.type !== "radio" ? core.matchStandard(info.label, standardFields) : null;
      // Pretensão em campo de número vai pela sugestão, que tira só o número da moeda certa.
      if (standard && standard.chave === "pretensao_salarial" && fieldKind(element, info) === "number") standard = null;
      if (standard) {
        const value = core.standardValue(standard, info.label, document.documentElement.lang);
        if (settings.autofill !== false && value && !element.value && !element.dataset.jobscoutPreenchido) {
          setValue(element, value);
          if (isListField(element)) pickFromList(element, value);
          markFilled(element);
        }
        continue;
      }
      if (settings.autofill !== false && fillFromHistory(element, info)) continue;
      // Grupo de caixas ("Quais ferramentas você usa?"): uma pergunta só, com várias respostas possíveis.
      if (adapter.suggestAll && info.type === "checkbox") {
        const group = groupOf(element);
        const boxes = group ? [...group.querySelectorAll("input[type='checkbox']")].filter(visible) : [];
        const question = group ? core.cleanLabel(questionFor(element)) : "";
        if (boxes.length >= 2 && question && !CONSENT.test(question) && !group.dataset.jobscoutSugerido && settings.sugestoes !== false) {
          const groupInfo = { tag: "div", type: "checkboxes", label: question };
          if (!hasAnswer(group, groupInfo)) {
            group.dataset.jobscoutSugerido = "1";
            candidates.push({
              campo: fieldId(group), rotulo: question, tipo: "checkbox", max: 0,
              opcoes: boxes.map((box) => core.cleanLabel(labelFor(box))), element: group, target: group, info: groupInfo,
            });
          }
        }
        continue;
      }
      const target = info.type === "radio" ? groupOf(element) : element;
      // Consentimento (SMS, WhatsApp, termos, privacidade) é escolha da pessoa: sem sugestão.
      const consent = CONSENT.test(core.cleanLabel(questionFor(element)));
      if (settings.sugestoes !== false && target && !consent && info.type !== "checkbox" && !target.dataset.jobscoutSugerido && !hasAnswer(element, info)) {
        target.dataset.jobscoutSugerido = "1";
        candidates.push({
          campo: fieldId(target),
          rotulo: core.cleanLabel(questionFor(element)),
          tipo: fieldKind(element, info),
          max: element.maxLength > 0 ? element.maxLength : 0,
          opcoes: optionsOf(element, info),
          element, target, info,
        });
      }
      if (core.isOpenQuestion(info) && !reported.has(id + info.label)) {
        // Marca já: a próxima leitura não manda a mesma pergunta enquanto a IA pensa.
        reported.add(id + info.label);
        questions.push({ rotulo: info.label, campo: id, longa: info.tag === "textarea" });
      }
    }
    if (adapter.choiceButtons && settings.sugestoes !== false) {
      for (const group of choiceGroups(root)) {
        if (group.dataset.jobscoutSugerido || chosenButton(group)) continue;
        const question = core.cleanLabel(choiceQuestion(group));
        if (!question || CONSENT.test(question)) continue;
        group.dataset.jobscoutSugerido = "1";
        candidates.push({
          campo: fieldId(group), rotulo: question, tipo: "radio", max: 0,
          opcoes: choiceButtons(group).map((button) => core.cleanLabel(text(button))),
          element: group, target: group, info: { tag: "div", type: "buttons", label: question },
        });
      }
    }
    const job = adapter.currentJob();
    if (adapter.suggestAll) await offerResume(root, job);
    const toDrafts = (list) => list.filter((question) => !withSuggestion.has(question.campo)).map(({ rotulo, campo }) => ({ rotulo, campo }));
    // 1) Regras: Perfil, currículo e histórico. 2) Texto longo vai direto para o rascunho no painel.
    await suggestFor(candidates.filter((item) => item.rotulo));
    const long = toDrafts(questions.filter((question) => question.longa));
    if (long.length && job && !adapter.suggestAll) await emit({ tipo: "form_detected", vaga: job, perguntas: long });
    // 3) O que as regras não souberam vai para a IA; pergunta curta que nem ela souber vira rascunho.
    const remaining = candidates.filter(
      (item) => item.rotulo && (adapter.suggestAll || item.tipo !== "textarea") && !withSuggestion.has(item.campo) && item.target.isConnected && !hasAnswer(item.element, item.info),
    );
    if (settings.sugestoes !== false && remaining.length) await suggestWithAI(remaining, job);
    const short = toDrafts(questions.filter((question) => !question.longa));
    if (short.length && job) await emit({ tipo: "form_detected", vaga: job, perguntas: short });
    startPolling();
  }

  function scheduleForm() {
    if (formTimer) return;
    formTimer = setTimeout(() => {
      formTimer = null;
      scanForm();
    }, 800);
  }

  // Respostas aprovadas no painel voltam para o campo

  function startPolling() {
    if (pollTimer) return;
    pollTimer = setInterval(async () => {
      if (!adapter.formRoot()) {
        clearInterval(pollTimer);
        pollTimer = null;
        return;
      }
      const response = await send({ kind: "insertions", pagina: core.pageKey(location.href) });
      const root = adapter.formRoot() || document;
      for (const item of (response && response.insercoes) || []) {
        if (answered.has(item.id)) continue;
        answered.add(item.id);
        let element = root.querySelector(`[data-jobscout-campo="${CSS.escape(item.field)}"]`);
        if (!element || core.fold(core.cleanLabel(labelFor(element))) !== core.fold(item.label)) {
          element = [...root.querySelectorAll("input, textarea")].find(
            (node) => core.fold(core.cleanLabel(labelFor(node))) === core.fold(item.label),
          ) || element;
        }
        if (element) setValue(element, item.text);
        send({ kind: "insertion_done", id: item.id, ok: Boolean(element) });
      }
    }, 2000);
  }

  // Clique em Enviar: só registra; quem envia é o usuário.

  // Roda na captura, antes de a página trocar de etapa: dá tempo de ler o que foi preenchido.
  function onClick(event) {
    // Dentro de um shadow DOM o alvo chega trocado pelo hospedeiro; o caminho tem o botão de verdade.
    const origin = (event.composedPath && event.composedPath()[0]) || event.target;
    const button = origin && origin.closest ? origin.closest("button, input[type='submit'], [role='button']") : null;
    if (!button) return;
    const group = adapter.choiceButtons ? button.closest("[data-jobscout-botoes]") : null;
    if (group) group.dataset.jobscoutEscolha = core.cleanLabel(text(button));
    if (adapter.applyButton && adapter.applyButton.test(text(button))) checkFormOpened();
    if (adapter.formRoot()) collectAnswers();
    if (!adapter.isSubmit(button)) return;
    const job = adapter.currentJob();
    const respostas = [...collected].map(([rotulo, valor]) => ({ rotulo, valor }));
    const documentos = [...collectedDocs];
    collected.clear();
    collectedDocs.clear();
    if (job) emit({ tipo: "application_submitted", vaga: job, quando: new Date().toISOString(), respostas, documentos });
  }

  // Clique em Candidatura simplificada sem formulário reconhecível: vira falha em Config, com o que havia na tela.
  function checkFormOpened() {
    setTimeout(() => {
      if (adapter.formRoot()) return;
      reportFailure("formulário de candidatura não reconhecido" + (adapter.describeForm ? " — " + adapter.describeForm() : ""));
    }, 3000);
  }

  // Mudanças dentro do shadow DOM da candidatura não chegam ao observer do documento.
  const watchedRoots = new WeakSet();
  function watchShadowRoots(observer) {
    if (!adapter.shadowHosts) return;
    for (const host of document.querySelectorAll(adapter.shadowHosts)) {
      const root = shadowOf(host);
      if (!root || watchedRoots.has(root)) continue;
      watchedRoots.add(root);
      observer.observe(root, { childList: true, subtree: true });
      root.addEventListener("change", () => {
        if (adapter.formRoot()) collectAnswers();
      }, true);
      // O shadow root pode já vir com o formulário: lê sem esperar a próxima mudança.
      scheduleForm();
    }
  }

  function start(siteAdapter) {
    adapter = siteAdapter;
    document.addEventListener("click", onClick, true);
    document.addEventListener("change", () => {
      if (adapter.formRoot()) collectAnswers();
    }, true);
    let lastHref = location.href;
    const observer = new MutationObserver(() => {
      if (location.href !== lastHref) {
        lastHref = location.href;
        lastJobKey = "";
        misses = 0;
      }
      watchShadowRoots(observer);
      scheduleJob();
      scheduleForm();
    });
    observer.observe(document.documentElement, { childList: true, subtree: true });
    watchShadowRoots(observer);
    // attachShadow não dispara o observer do documento; uma checagem leve pega o shadow root que chegar depois.
    if (adapter.shadowHosts) setInterval(() => watchShadowRoots(observer), 2000);
    scheduleJob();
    scheduleForm();
  }

  globalThis.JobScoutPage = { start, text, pick, jsonLdJob, reportFailure, shadowOf };
})();
