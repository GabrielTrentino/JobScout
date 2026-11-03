// Service worker: recebe os eventos das abas e fala com o JobScout neste computador.
"use strict";

const DEFAULTS = { backend: "http://127.0.0.1:8765", autofill: true, sugestoes: true };
let fieldsCache = { at: 0, campos: [], historico: [] };

async function settings() {
  const stored = await chrome.storage.local.get(DEFAULTS);
  return { ...DEFAULTS, ...stored, backend: String(stored.backend || DEFAULTS.backend).replace(/\/+$/, "") };
}

async function call(path, options = {}) {
  const { backend } = await settings();
  const init = { ...options };
  if (init.json !== undefined) {
    init.method = init.method || "POST";
    init.body = JSON.stringify(init.json);
    init.headers = { "Content-Type": "application/json" };
    delete init.json;
  }
  const response = await fetch(backend + path, init);
  const payload = await response.json().catch(() => null);
  if (!response.ok) throw new Error((payload && payload.erro) || `JobScout respondeu ${response.status}`);
  return payload;
}

async function setBadge(count) {
  if (count === null) {
    await chrome.action.setBadgeText({ text: "off" });
    await chrome.action.setBadgeBackgroundColor({ color: "#6b7a82" });
    return;
  }
  await chrome.action.setBadgeText({ text: count ? String(count) : "" });
  await chrome.action.setBadgeBackgroundColor({ color: "#c5362b" });
}

async function refreshBadge() {
  try {
    await flushQueue();
    const summary = await call("/api/extensao/resumo");
    await setBadge(summary.pendentes);
  } catch (error) {
    await setBadge(null);
  }
}

// Fila de eventos para quando o JobScout está fechado: nada se perde, vai tudo quando ele abrir.
const QUEUE_LIMIT = 200;

function queueKey(event) {
  return [event.tipo, event.pagina, event.vaga && event.vaga.url, event.quando || ""].join("|");
}

async function enqueue(event) {
  const { fila = [] } = await chrome.storage.local.get("fila");
  const key = queueKey(event);
  const next = fila.filter((item) => queueKey(item) !== key);
  next.push(event);
  await chrome.storage.local.set({ fila: next.slice(-QUEUE_LIMIT) });
  return next.length;
}

let flushing = false;

async function flushQueue() {
  if (flushing) return;
  flushing = true;
  try {
    let { fila = [] } = await chrome.storage.local.get("fila");
    while (fila.length) {
      try {
        await call("/api/eventos", { json: fila[0] });
      } catch (error) {
        // Sem conexão: tenta de novo depois. Recusado pelo JobScout: descarta esse evento.
        if (error instanceof TypeError) break;
      }
      fila = fila.slice(1);
      await chrome.storage.local.set({ fila });
    }
  } finally {
    flushing = false;
  }
}

// Formulários em outros sites: o popup liga por site (ou em todos os sites de vagas) e pede a permissão;
// aqui o script genérico é registrado para esses endereços e injetado na aba aberta na hora.
const FORM_SCRIPT = "jobscout-formularios";
const FORM_FILES = ["content/core.js", "content/page.js", "content/generic.js", "content/assist.js"];
// Esses já têm adaptador próprio (ou são chats): o genérico não roda neles.
const OWN_SITES = ["https://www.linkedin.com/*", "https://*.inhire.app/*", "https://*.inhire.com.br/*", "https://web.whatsapp.com/*", "https://mail.google.com/*"];

async function formState() {
  return chrome.storage.local.get({ formSites: [], formAll: false, assistAny: false });
}

async function syncFormScripts() {
  const { formSites, formAll, assistAny } = await formState();
  const matches = formAll || assistAny ? ["https://*/*", "http://*/*"] : formSites.map((origin) => origin + "/*");
  // Só registra o que tem permissão: se a pessoa tirou a permissão no Chrome, o site sai sozinho.
  const allowed = [];
  for (const pattern of matches) {
    if (await chrome.permissions.contains({ origins: [pattern] })) allowed.push(pattern);
  }
  const existing = await chrome.scripting.getRegisteredContentScripts({ ids: [FORM_SCRIPT] });
  if (existing.length) await chrome.scripting.unregisterContentScripts({ ids: [FORM_SCRIPT] });
  if (!allowed.length) return { ativos: [] };
  await chrome.scripting.registerContentScripts([{
    id: FORM_SCRIPT, matches: allowed, excludeMatches: OWN_SITES, js: FORM_FILES, runAt: "document_idle", persistAcrossSessions: true,
    // Muitos sites de empresa embutem o formulário (Greenhouse, Lever...) num iframe.
    allFrames: true,
  }]);
  return { ativos: allowed };
}

async function injectNow(tabId) {
  if (!tabId) return;
  try {
    await chrome.scripting.executeScript({ target: { tabId, allFrames: true }, files: FORM_FILES });
  } catch (error) {
    // Página do Chrome ou sem permissão: vale a partir do próximo carregamento.
  }
}

async function setFormSite({ origin, on, all, assist, tabId }) {
  const state = await formState();
  if (assist !== undefined) {
    state.assistAny = Boolean(assist);
  } else if (all !== undefined) {
    state.formAll = Boolean(all);
  } else if (origin) {
    const sites = new Set(state.formSites);
    if (on) sites.add(origin);
    else sites.delete(origin);
    state.formSites = [...sites].sort();
  }
  await chrome.storage.local.set(state);
  const result = await syncFormScripts();
  if ((on || all || assist) && tabId) await injectNow(tabId);
  return { ...state, ...result };
}

async function handle(message) {
  switch (message.kind) {
    case "forms_state":
      return formState();
    case "forms_set":
      return setFormSite(message);
    case "event": {
      let result;
      try {
        result = await call("/api/eventos", { json: message.event });
      } catch (error) {
        if (!(error instanceof TypeError)) throw error;
        const waiting = await enqueue(message.event);
        await setBadge(null);
        return { enfileirado: true, aguardando: waiting };
      }
      await setBadge(result.pendentes);
      flushQueue();
      return result;
    }
    case "fields": {
      if (Date.now() - fieldsCache.at > 60000) {
        const [campos, historico] = await Promise.all([call("/api/perfil/campos"), call("/api/extensao/historico")]);
        fieldsCache = { at: Date.now(), campos, historico };
      }
      return { campos: fieldsCache.campos, historico: fieldsCache.historico };
    }
    case "settings":
      return settings();
    case "suggest":
      return call("/api/extensao/sugestoes", { json: { campos: message.campos } });
    // Barra de resposta dos chats (LinkedIn, WhatsApp Web, Gmail)
    case "chat_context":
      return call("/api/extensao/chat", { json: message.dados });
    case "chat_link":
      return call("/api/extensao/chat/vincular", { json: message.dados });
    case "chat_record":
      return call("/api/extensao/chat/registrar", { json: message.dados });
    case "resumes":
      return call("/api/extensao/curriculos", { json: { url: message.url } });
    case "resume_pdf":
      return call("/api/extensao/curriculo-pdf", { json: { versao: message.versao } });
    case "chat_approach":
      return call("/api/extensao/chat/abordagem", { json: message.dados });
    // Assistente da página: só chega aqui depois do clique da pessoa
    case "page_context":
      return call("/api/extensao/pagina", { json: message.dados });
    case "page_save":
      return call("/api/extensao/pagina/salvar", { json: message.dados });
    case "page_ai":
      return call("/api/extensao/pagina/ia", { json: message.dados });
    case "reply":
      return call("/api/mensagens/responder", { json: message.dados });
    case "improvement":
      return call("/api/melhorias", { json: message.dados });
    case "suggest_ai":
      // A IA local pode levar alguns segundos (mais na primeira vez, enquanto carrega o modelo).
      return call("/api/extensao/sugestoes-ia", { json: { campos: message.campos, vaga: message.vaga } });
    case "insertions":
      return { insercoes: await call("/api/extensao/insercoes?pagina=" + encodeURIComponent(message.pagina)) };
    case "insertion_done":
      return call(`/api/extensao/insercoes/${message.id}`, { json: { ok: message.ok } });
    default:
      return null;
  }
}

chrome.runtime.onMessage.addListener((message, _sender, reply) => {
  handle(message)
    .then(reply)
    .catch((error) => {
      setBadge(null);
      reply({ erro: error.message });
    });
  return true;
});

chrome.runtime.onInstalled.addListener(() => {
  chrome.alarms.create("badge", { periodInMinutes: 1 });
  refreshBadge();
  syncFormScripts().catch(() => {});
});

chrome.runtime.onStartup.addListener(() => {
  refreshBadge();
  syncFormScripts().catch(() => {});
});

// Permissão tirada pelo Chrome (Detalhes da extensão > Acesso ao site): o registro acompanha.
chrome.permissions.onRemoved.addListener(() => syncFormScripts().catch(() => {}));

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === "badge") refreshBadge();
});
