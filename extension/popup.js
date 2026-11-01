"use strict";

const DEFAULTS = { backend: "http://127.0.0.1:8765", autofill: true, sugestoes: true };
const LABELS = {
  vaga: "Nova vaga",
  vaga_alteracao: "Vaga alterada",
  status: "Mudança de status",
  resposta: "Resposta",
  mensagem: "Mensagem",
};

const list = document.getElementById("list");
const status = document.getElementById("status");
const backendInput = document.getElementById("backend");
const autofill = document.getElementById("autofill");
const suggestions = document.getElementById("suggestions");

function title(draft) {
  const p = draft.payload;
  if (draft.kind === "vaga") return [p.title, p.company].filter(Boolean).join(" — ");
  if (draft.kind === "resposta") return p.pergunta;
  if (draft.kind === "mensagem") return p.assunto || p.remetente_email;
  return p.vaga || "";
}

async function base() {
  const stored = await chrome.storage.local.get(DEFAULTS);
  return String(stored.backend || DEFAULTS.backend).replace(/\/+$/, "");
}

async function load() {
  const backend = await base();
  let summary;
  try {
    const response = await fetch(backend + "/api/extensao/resumo");
    summary = await response.json();
  } catch (error) {
    status.textContent = "JobScout fechado. Rode: python -m jobscout";
    status.className = "err";
    list.replaceChildren();
    return;
  }
  status.className = "muted";
  status.textContent = summary.pendentes ? `${summary.pendentes} rascunho(s) aguardando aprovação.` : "Nada aguardando. Tudo em dia.";
  list.replaceChildren();
  for (const draft of summary.rascunhos) {
    const item = document.createElement("li");
    const kind = document.createElement("span");
    kind.className = "kind";
    kind.textContent = LABELS[draft.kind] || draft.kind;
    const name = document.createElement("span");
    name.className = "title";
    name.textContent = title(draft);
    const ok = document.createElement("button");
    ok.textContent = "Aprovar";
    const no = document.createElement("button");
    no.className = "no";
    no.textContent = "Descartar";
    const error = document.createElement("span");
    error.className = "err";
    ok.addEventListener("click", () => decide(draft.id, "aprovar", error));
    no.addEventListener("click", () => decide(draft.id, "descartar", error));
    item.append(kind, name, ok, " ", no, " ", error);
    list.appendChild(item);
  }
}

async function decide(id, action, error) {
  const backend = await base();
  const response = await fetch(`${backend}/api/rascunhos/${id}/${action}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "{}",
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    error.textContent = (payload.erro || "Falhou.") + " Ajuste no painel.";
    return;
  }
  const summary = await (await fetch(backend + "/api/extensao/resumo")).json();
  chrome.action.setBadgeText({ text: summary.pendentes ? String(summary.pendentes) : "" });
  }

document.getElementById("open-panel").addEventListener("click", async (event) => {
  event.preventDefault();
  chrome.tabs.create({ url: (await base()) + "/#rascunhos" });
});

chrome.storage.local.get(DEFAULTS).then((stored) => {
  backendInput.value = stored.backend;
  autofill.checked = stored.autofill !== false;
  suggestions.checked = stored.sugestoes !== false;
});

backendInput.addEventListener("change", async () => {
  await chrome.storage.local.set({ backend: backendInput.value || DEFAULTS.backend });
  load();
});

autofill.addEventListener("change", () => chrome.storage.local.set({ autofill: autofill.checked }));
suggestions.addEventListener("change", () => chrome.storage.local.set({ sugestoes: suggestions.checked }));

// Formulários em outros sites: a flag por site (ou em todos) pede a permissão do Chrome só para ele.
const OWN = [/(^|\.)linkedin\.com$/, /\.inhire\.(app|com\.br)$/, /^web\.whatsapp\.com$/, /^mail\.google\.com$/];
const formsSite = document.getElementById("forms-site");
const formsAll = document.getElementById("forms-all");
const formsHost = document.getElementById("forms-host");
const formsHere = document.getElementById("forms-here");
const formsList = document.getElementById("forms-sites");
const formsError = document.getElementById("forms-error");
let tab = null;
let origin = "";

function ask(message) {
  return new Promise((resolve) => chrome.runtime.sendMessage(message, (response) => resolve(response || {})));
}

async function renderForms() {
  const state = await ask({ kind: "forms_state" });
  const sites = state.formSites || [];
  formsAll.checked = Boolean(state.formAll);
  let host = "";
  try {
    const url = new URL(tab && tab.url ? tab.url : "");
    if (/^https?:$/.test(url.protocol)) {
      origin = url.origin;
      host = url.hostname;
    }
  } catch (error) {
    origin = "";
  }
  const own = host && OWN.some((rule) => rule.test(host));
  formsHost.textContent = host || "neste site";
  formsSite.checked = Boolean(origin && sites.includes(origin));
  formsSite.disabled = !origin || own;
  formsHere.textContent = !origin ? "Abra a página do formulário para ligar neste site."
    : own ? "Neste site o JobScout já ajuda sempre."
      : formsSite.checked || formsAll.checked ? "Ligado aqui: sugestões aparecem ao lado das perguntas. O Enviar é sempre seu."
        : "Desligado aqui.";
  formsList.replaceChildren(...sites.map((site) => {
    const item = document.createElement("li");
    const name = document.createElement("span");
    name.textContent = site.replace(/^https?:\/\//, "");
    const remove = document.createElement("button");
    remove.className = "no";
    remove.textContent = "×";
    remove.title = "Desligar neste site";
    remove.addEventListener("click", async () => {
      await ask({ kind: "forms_set", origin: site, on: false });
      chrome.permissions.remove({ origins: [site + "/*"] });
      renderForms();
    });
    item.append(name, remove);
    return item;
  }));
}

formsSite.addEventListener("change", async () => {
  formsError.textContent = "";
  if (formsSite.checked) {
    // O pedido de permissão precisa sair direto do clique.
    const granted = await chrome.permissions.request({ origins: [origin + "/*"] });
    if (!granted) {
      formsSite.checked = false;
      formsError.textContent = "Sem a permissão do Chrome, o JobScout não lê esta página.";
      return;
    }
  }
  await ask({ kind: "forms_set", origin, on: formsSite.checked, tabId: tab && tab.id });
  renderForms();
});

formsAll.addEventListener("change", async () => {
  formsError.textContent = "";
  if (formsAll.checked) {
    const granted = await chrome.permissions.request({ origins: ["https://*/*", "http://*/*"] });
    if (!granted) {
      formsAll.checked = false;
      formsError.textContent = "Sem a permissão do Chrome para todos os sites, use a opção por site.";
      return;
    }
  }
  await ask({ kind: "forms_set", all: formsAll.checked, on: formsAll.checked, tabId: tab && tab.id });
  if (!formsAll.checked) chrome.permissions.remove({ origins: ["https://*/*", "http://*/*"] });
  renderForms();
});

chrome.tabs.query({ active: true, currentWindow: true }).then(([active]) => {
  tab = active || null;
  renderForms();
});

load();
