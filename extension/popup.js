"use strict";

const DEFAULTS = { backend: "http://127.0.0.1:8765", autofill: true };
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
  load();
}

document.getElementById("open-panel").addEventListener("click", async (event) => {
  event.preventDefault();
  chrome.tabs.create({ url: (await base()) + "/#rascunhos" });
});

chrome.storage.local.get(DEFAULTS).then((stored) => {
  backendInput.value = stored.backend;
  autofill.checked = stored.autofill !== false;
});

backendInput.addEventListener("change", async () => {
  await chrome.storage.local.set({ backend: backendInput.value || DEFAULTS.backend });
  load();
});

autofill.addEventListener("change", () => chrome.storage.local.set({ autofill: autofill.checked }));

load();
