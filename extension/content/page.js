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

  function labelFor(element) {
    if (element.id) {
      const label = document.querySelector(`label[for="${CSS.escape(element.id)}"]`);
      if (label && text(label)) return text(label);
    }
    const wrapping = element.closest("label");
    if (wrapping && text(wrapping)) return text(wrapping);
    const labelledBy = element.getAttribute("aria-labelledby");
    if (labelledBy) {
      const joined = labelledBy.split(/\s+/).map((id) => text(document.getElementById(id))).join(" ").trim();
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

  // Lê o que está preenchido agora e junta ao que veio das etapas anteriores.
  function collectAnswers() {
    const root = adapter.formRoot();
    if (!root) return;
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
    for (const [question, value] of seenNow) collected.set(question, value);
  }

  function markFilled(element) {
    element.dataset.jobscoutPreenchido = "1";
    if (!document.getElementById("jobscout-style")) {
      const style = document.createElement("style");
      style.id = "jobscout-style";
      style.textContent = "[data-jobscout-preenchido]{outline:2px solid rgba(47,133,90,.6)!important;outline-offset:1px}";
      document.head.appendChild(style);
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
      setValue(element, remembered.valor);
    }
    markFilled(element);
    return true;
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

  async function scanForm() {
    const root = adapter.formRoot();
    if (!root) {
      // Formulário fechado sem envio: o que foi lido não vale para a próxima vaga.
      collected.clear();
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
    for (const element of elements) {
      const info = {
        tag: element.tagName.toLowerCase(),
        type: (element.getAttribute("type") || "text").toLowerCase(),
        label: core.cleanLabel(labelFor(element)),
      };
      if (SKIP_TYPES.includes(info.type)) continue;
      const id = fieldId(element);
      const standard = info.tag !== "select" && info.type !== "radio" ? core.matchStandard(info.label, standardFields) : null;
      if (standard) {
        if (settings.autofill !== false && !element.value && !element.dataset.jobscoutPreenchido) {
          setValue(element, standard.valor);
          markFilled(element);
        }
        continue;
      }
      if (settings.autofill !== false && fillFromHistory(element, info)) continue;
      if (core.isOpenQuestion(info) && !reported.has(id + info.label)) {
        reported.add(id + info.label);
        questions.push({ rotulo: info.label, campo: id });
      }
    }
    const job = adapter.currentJob();
    if (questions.length && job) {
      await emit({ tipo: "form_detected", vaga: job, perguntas: questions });
    }
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
      for (const item of (response && response.insercoes) || []) {
        if (answered.has(item.id)) continue;
        answered.add(item.id);
        let element = document.querySelector(`[data-jobscout-campo="${CSS.escape(item.field)}"]`);
        if (!element || core.fold(core.cleanLabel(labelFor(element))) !== core.fold(item.label)) {
          element = [...document.querySelectorAll("input, textarea")].find(
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
    const button = event.target.closest("button, input[type='submit'], [role='button']");
    if (!button) return;
    if (adapter.formRoot()) collectAnswers();
    if (!adapter.isSubmit(button)) return;
    const job = adapter.currentJob();
    const respostas = [...collected].map(([rotulo, valor]) => ({ rotulo, valor }));
    collected.clear();
    if (job) emit({ tipo: "application_submitted", vaga: job, quando: new Date().toISOString(), respostas });
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
      scheduleJob();
      scheduleForm();
    });
    observer.observe(document.documentElement, { childList: true, subtree: true });
    scheduleJob();
    scheduleForm();
  }

  globalThis.JobScoutPage = { start, text, pick, jsonLdJob, reportFailure };
})();
