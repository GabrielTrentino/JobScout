// Service worker: recebe os eventos das abas e fala com o JobScout neste computador.
"use strict";

const DEFAULTS = { backend: "http://127.0.0.1:8765", autofill: true };
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

async function handle(message) {
  switch (message.kind) {
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
});

chrome.runtime.onStartup.addListener(refreshBadge);

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === "badge") refreshBadge();
});
