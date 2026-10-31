"use strict";

const LABELS = {
  vaga: "Nova vaga",
  vaga_alteracao: "Vaga alterada",
  status: "Mudança de status",
  resposta: "Resposta de formulário",
  mensagem: "Mensagem de recrutador",
};
const FIELD_LABELS = { title: "Título", company: "Empresa", location: "Local", description: "Descrição" };
const EXTRA_LABELS = {
  seniority: "Senioridade",
  employment_type: "Contrato",
  work_mode: "Modalidade",
  english: "Inglês",
  region: "Região",
  salary: "Salário citado",
  industry: "Setor",
};
const KIND_NAMES = {
  rascunho_criado: "Rascunho criado",
  rascunho_aprovado: "Aprovação",
  rascunho_descartado: "Descarte",
  vaga_criada: "Vaga salva",
  vaga_alterada: "Vaga alterada",
  status: "Mudança de status",
  resposta: "Resposta",
  respostas_formulario: "Respostas do formulário",
  mensagem: "Mensagem",
  nota: "Nota",
  empresa_cadastrada: "Empresa cadastrada",
};
// Avisos que podem virar pop-up na bolha, por nível da atividade.
const TOAST_LEVELS = [
  ["aviso", "Rascunhos novos e o que precisa de você", true],
  ["erro", "Falhas (leitura de página, Gmail, IA)", true],
  ["ok", "Aprovações e cadastros feitos", false],
  ["trabalhando", "Processamento em andamento", false],
  ["info", "Itens ignorados e o motivo", false],
];
// Larguras do overlay (overlay.py) e a faixa extra do painel de pontos de melhoria.
const PANEL_WIDTHS = { painel: 400, amplo: 880 };
const IMPROVE_WIDTH = 400;
const WIDE_VIEWS = new Set(["kanban", "empresa", "curriculo", "resultados", "vagas", "busca"]);
// Bolha sozinha e janela compacta (menu, pop-ups), em pixels lógicos; batem com BUBBLE e MODES do overlay.py.
const BUBBLE_SIZE = 72;
const DOCK_WIDTH = 300;
// Arremesso: uma volta inteira e a segunda até ele ficar de mãos vazias (iteration-count 1.65 de 2,4 s).
const THROW_MS = 3960;
const CLASSES = {
  entrevista: "Convite para entrevista",
  rejeicao: "Rejeição",
  documento: "Pedido de documento",
  outro: "Outro",
};
const SOURCES = { linkedin: "LinkedIn", inhire: "InHire", email: "E-mail", manual: "Manual", painel: "Painel", whatsapp: "WhatsApp", jobscout: "JobScout", busca: "Busca automática", web: "Outro site" };
const PROFILE_FIELDS = [
  ["nome", "Nome completo"],
  ["email", "E-mail"],
  ["telefone", "Telefone"],
  ["cidade", "Cidade"],
  ["estado", "Estado (ex.: SP)"],
  ["pais", "País (ex.: Brasil)"],
  ["linkedin", "LinkedIn"],
  ["github", "GitHub"],
  ["portfolio", "Portfólio"],
  ["pretensao_salarial", "Pretensão salarial em real (ex.: R$ 15.000 CLT)"],
  ["pretensao_usd", "Pretensão salarial em dólar (ex.: US$ 4,000/mês)"],
  ["disponibilidade", "Disponibilidade"],
];

// Respostas rápidas do Perfil: base das sugestões nos formulários (suggest.py).
const LEVELS = ["", "Nenhum", "Básico", "Intermediário", "Avançado", "Fluente", "Nativo"];
const QUICK_FIELDS = [
  ["nivel_ingles", "Nível de inglês", LEVELS],
  ["nivel_espanhol", "Nível de espanhol", LEVELS],
  ["autorizacao_trabalho", "Autorizado(a) a trabalhar no Brasil?", ["", "Sim", "Não"]],
  ["precisa_visto", "Precisa de visto ou patrocínio?", ["", "Não", "Sim"]],
  ["aceita_mudanca", "Aceita mudar de cidade?", ["", "Sim", "Não"]],
  ["anos_experiencia", "Anos de experiência no total", null],
];
const WORK_MODES = ["Remoto", "Híbrido", "Presencial (na cidade atual)", "Presencial (mudando de cidade)"];

const state = {
  status: [],
  vagas: [],
  rascunhos: [],
  modelos: {},
  gmail: {},
  view: "rascunhos",
  filter: "pendente",
  snoozed: new Set(),
  popups: readPref("popups", "on") === "on",
  drawerJob: null,
  feed: [],
  overlay: new URLSearchParams(location.search).has("overlay"),
  mode: "bolha",
  workingUntil: 0,
  throwUntil: 0,
  moves: [],
  companyId: null,
  minhasSkills: [],
  diasFria: 14,
  toastPrefs: readToastPrefs(),
  appName: "JobScout",
  prefs: null,
  exportSheets: [],
};

// Utilidades

function readPref(name, fallback) {
  try {
    return localStorage.getItem("jobscout." + name) || fallback;
  } catch (error) {
    return fallback;
  }
}

function writePref(name, value) {
  try {
    localStorage.setItem("jobscout." + name, value);
  } catch (error) {
    // Sem armazenamento local: a preferência vale só nesta aba.
  }
}

function readToastPrefs() {
  const defaults = Object.fromEntries(TOAST_LEVELS.map(([level, , on]) => [level, on]));
  try {
    return { ...defaults, ...JSON.parse(readPref("toasts", "{}")) };
  } catch (error) {
    return defaults;
  }
}

// Tema: escolha manual (chave Noturno) ou o do sistema.
const darkQuery = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;

function effectiveDark() {
  const chosen = document.documentElement.dataset.theme;
  if (chosen) return chosen === "dark";
  return Boolean(darkQuery && darkQuery.matches);
}

function applyTheme(choice, save = true) {
  if (choice) document.documentElement.dataset.theme = choice;
  else delete document.documentElement.dataset.theme;
  // O padrão do overlay (escuro) não é escolha sua: só grava quando você mexe na chave.
  if (save) writePref("theme", choice || "auto");
  for (const toggle of document.querySelectorAll(".theme-toggle")) toggle.checked = effectiveDark();
}

function setupTheme() {
  const saved = readPref("theme", state.overlay ? "dark" : "auto");
  applyTheme(saved === "auto" ? "" : saved, false);
  for (const toggle of document.querySelectorAll(".theme-toggle")) {
    toggle.addEventListener("change", () => applyTheme(toggle.checked ? "dark" : "light"));
  }
  if (darkQuery) darkQuery.addEventListener("change", () => applyTheme(document.documentElement.dataset.theme || "", false));
  document.getElementById("theme-auto").addEventListener("click", () => applyTheme(""));
}

function h(tag, attrs, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === undefined || value === null || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else if (key === "value") node.value = value;
    else if (key === "checked") node.checked = Boolean(value);
    else node.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.appendChild(typeof child === "string" ? document.createTextNode(child) : child);
  }
  return node;
}

function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
}

async function api(path, options = {}) {
  const init = { ...options };
  if (init.json !== undefined) {
    init.body = JSON.stringify(init.json);
    init.headers = { "Content-Type": "application/json" };
    delete init.json;
  }
  const response = await fetch(path, init);
  const text = await response.text();
  let payload = null;
  try {
    payload = text ? JSON.parse(text) : null;
  } catch (error) {
    payload = null;
  }
  if (!response.ok) throw new Error((payload && payload.erro) || "Falha na operação.");
  return payload;
}

const dateFmt = new Intl.DateTimeFormat("pt-BR", { day: "2-digit", month: "short" });
const timeFmt = new Intl.DateTimeFormat("pt-BR", { hour: "2-digit", minute: "2-digit" });
const dayFmt = new Intl.DateTimeFormat("pt-BR", { weekday: "long", day: "numeric", month: "long" });

function when(iso) {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  const today = new Date();
  if (date.toDateString() === today.toDateString()) return timeFmt.format(date);
  return dateFmt.format(date) + " " + timeFmt.format(date);
}

function statusName(key) {
  const found = state.status.find((item) => item.chave === key);
  return found ? found.nome : key || "—";
}

function jobLabel(job) {
  if (!job) return "";
  return job.company ? `${job.title || "Vaga sem título"} — ${job.company}` : job.title || "Vaga sem título";
}

function describe(draft) {
  const p = draft.payload;
  switch (draft.kind) {
    case "vaga":
      return jobLabel(p);
    case "vaga_alteracao":
      return `${p.vaga}: ${Object.keys(p.mudancas || {}).map((name) => FIELD_LABELS[name] || name).join(", ")}`;
    case "status":
      return `${p.vaga}: ${statusName(p.de)} → ${statusName(p.para)}`;
    case "resposta":
      return p.pergunta;
    case "mensagem":
      return p.assunto || p.remetente_email || "Mensagem";
    default:
      return draft.kind;
  }
}

function idleDays(iso) {
  if (!iso) return null;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  return Math.floor((Date.now() - date.getTime()) / 86400000);
}

function skillList(value) {
  return String(value || "").split(",").map((item) => item.trim()).filter(Boolean);
}

// Chips com o que foi extraído da vaga (senioridade, inglês, modalidade…) e as skills com aderência.
function insightChips(job) {
  const chips = [];
  for (const [name, label] of Object.entries(EXTRA_LABELS)) {
    const value = job[name];
    if (!value) continue;
    let tone = "chip";
    if (name === "english" && /obrigat|inglês/.test(value)) tone = "chip is-warn";
    if (name === "region" && value !== "Brasil") tone = "chip is-accent";
    if (name === "salary") tone = "chip is-ok";
    chips.push(h("span", { class: tone, title: label, text: name === "english" ? "Inglês: " + value : value }));
  }
  return chips.length ? h("div", { class: "chips" }, chips) : null;
}

function skillsBlock(job) {
  const wanted = skillList(job.skills);
  if (!wanted.length) return null;
  const mine = new Set(state.minhasSkills.map((item) => item.toLowerCase()));
  const has = wanted.filter((item) => mine.has(item.toLowerCase()));
  return h("div", {},
    h("p", { class: "hint", text: mine.size
      ? `Skills pedidas: você tem ${has.length} de ${wanted.length} (pelo currículo do Perfil).`
      : "Skills pedidas na vaga:" }),
    h("div", { class: "skills" }, wanted.map((item) => h("span", {
      class: mine.size ? (mine.has(item.toLowerCase()) ? "chip is-ok" : "chip") : "chip is-accent",
      text: (mine.size && mine.has(item.toLowerCase()) ? "✓ " : "") + item,
    }))),
  );
}

// Respostas lidas do formulário no envio, com a opção de não guardar.
function answersBlock(p, pending) {
  const answers = p.respostas || [];
  const documents = p.documentos || [];
  if (!answers.length && !documents.length) return null;
  const keep = h("input", { type: "checkbox", checked: p.guardar_respostas !== false, disabled: !pending });
  const node = h("details", {},
    h("summary", { text: `Enviado no formulário: ${documents.length ? documents.join(", ") + " · " : ""}${answers.length} resposta(s)` }),
    documents.length ? h("p", {}, h("strong", { text: "Currículo enviado: " }), documents.join(", ")) : null,
    h("ul", { class: "answers-list" }, answers.map((item) => h("li", {}, h("strong", { text: item.rotulo }), item.valor))),
    answers.length ? h("label", { class: "check" }, keep, "Reusar estas respostas para preencher formulários futuros (no histórico da vaga elas ficam de qualquer jeito)") : null,
  );
  return { node, collect: () => ({ guardar_respostas: keep.checked }) };
}

function statusSelect(value, { allowEmpty = false, name } = {}) {
  const select = h("select", { name });
  if (allowEmpty) select.appendChild(h("option", { value: "", text: "Não mudar" }));
  for (const item of state.status) {
    select.appendChild(h("option", { value: item.chave, text: item.nome }));
  }
  select.value = value || "";
  return select;
}

function toLocalInput(iso) {
  if (!iso) return "";
  return String(iso).slice(0, 16);
}

// Cartão de rascunho: o mesmo em todas as telas e no popup

function draftCard(draft, { inQueue = false, position = "" } = {}) {
  const pending = draft.state === "pendente";
  const p = draft.payload;
  const card = h("article", { class: "draft is-" + draft.state, "data-id": draft.id, "data-updated": draft.updated_at });
  card.dirty = false;
  const markDirty = () => {
    card.dirty = true;
  };
  card.addEventListener("input", markDirty);
  card.addEventListener("change", markDirty);

  card.appendChild(
    h("div", { class: "draft-head" },
      h("p", { class: "eyebrow", text: (position ? position + " · " : "") + LABELS[draft.kind] }),
      h("span", { class: "when", text: when(draft.created_at) }),
    ),
  );
  card.appendChild(h("h3", { class: "draft-title", text: describe(draft) }));
  const chips = h("div", { class: "row" }, h("span", { class: "chip", text: SOURCES[draft.source] || draft.source }));
  if (draft.edited) chips.appendChild(h("span", { class: "chip", text: "editado" }));
  if (!pending) chips.appendChild(h("span", { class: "chip", text: draft.state }));
  card.appendChild(chips);

  const body = h("div", { class: "fields" });
  card.appendChild(body);
  const collectors = [];

  if (draft.kind === "vaga") {
    const inputs = {};
    for (const name of ["title", "company", "location"]) {
      inputs[name] = h("input", { value: p[name] || "", disabled: !pending });
    }
    const status = statusSelect(p.status);
    status.disabled = !pending;
    body.append(
      h("label", {}, "Título", inputs.title),
      h("div", { class: "two" }, h("label", {}, "Empresa", inputs.company), h("label", {}, "Local", inputs.location)),
      h("label", {}, "Status ao salvar", status),
      h("p", { class: "hint" }, h("a", { href: p.url, target: "_blank", rel: "noopener", text: p.url })),
    );
    const chips = insightChips(p);
    if (chips) body.appendChild(chips);
    const skills = skillsBlock(p);
    if (skills) body.appendChild(skills);
    const extras = {};
    const extraFields = h("div", { class: "fields" });
    for (const name of ["seniority", "work_mode", "english", "region", "salary", "skills"]) {
      extras[name] = h("input", { value: p[name] || "", disabled: !pending });
      extraFields.appendChild(h("label", {}, name === "skills" ? "Skills" : EXTRA_LABELS[name], extras[name]));
    }
    body.appendChild(h("details", {}, h("summary", { text: "Ajustar o que foi extraído" }), extraFields));
    const description = h("textarea", { rows: 6, disabled: !pending, value: p.description || "" });
    body.appendChild(h("details", {}, h("summary", { text: "Descrição" }), description));
    const answers = answersBlock(p, pending);
    if (answers) {
      body.appendChild(answers.node);
      collectors.push(answers.collect);
    }
    collectors.push(() => ({
      title: inputs.title.value.trim(),
      company: inputs.company.value.trim(),
      location: inputs.location.value.trim(),
      description: description.value,
      status: status.value,
      ...Object.fromEntries(Object.entries(extras).map(([name, input]) => [name, input.value.trim()])),
    }));
  } else if (draft.kind === "vaga_alteracao") {
    const rows = [];
    for (const [name, change] of Object.entries(p.mudancas || {})) {
      const keep = h("input", { type: "checkbox", checked: true, disabled: !pending });
      const input = name === "description"
        ? h("textarea", { rows: 5, value: change.para, disabled: !pending })
        : h("input", { value: change.para, disabled: !pending });
      rows.push({ name, keep, input, original: change.para });
      body.appendChild(
        h("div", { class: "change" },
          h("label", { class: "check" }, keep, FIELD_LABELS[name] || name),
          h("del", { text: change.de || "(vazio)" }),
          input,
        ),
      );
    }
    collectors.push(() => {
      const mudancas = {};
      for (const row of rows) mudancas[row.name] = row.keep.checked ? { para: row.input.value } : null;
      return { mudancas };
    });
  } else if (draft.kind === "status") {
    const select = statusSelect(p.para);
    select.disabled = !pending;
    body.append(
      h("p", {}, "De ", h("strong", { text: statusName(p.de) }), " para:"),
      select,
      h("p", { class: "hint", text: p.motivo ? `${p.motivo} Proposto em ${when(p.quando)}.` : "Detectado em " + when(p.quando) }),
    );
    const answers = answersBlock(p, pending);
    if (answers) {
      body.appendChild(answers.node);
      collectors.push(answers.collect);
    }
    collectors.push(() => ({ para: select.value }));
  } else if (draft.kind === "resposta") {
    const answer = h("textarea", { rows: 6, value: p.resposta || "", disabled: !pending, placeholder: "Escreva a resposta" });
    const insert = h("input", { type: "checkbox", checked: p.inserir, disabled: !pending });
    let origin = "Sem sugestão. Escreva com base no perfil.";
    if (p.sugerida_por === "historico") origin = p.base || "Resposta reaproveitada do histórico.";
    if (p.sugerida_por === "llm") origin = "Sugestão da IA. Confira cada fato antes de aprovar.";
    body.append(
      h("p", { class: "hint", text: p.vaga }),
      h("p", { class: p.sugerida_por === "llm" ? "chip is-warn" : "hint", text: origin }),
      answer,
      h("label", { class: "check" }, insert, "Inserir no formulário ao aprovar (o envio continua com você)"),
    );
    collectors.push(() => ({ resposta: answer.value, inserir: insert.checked }));
  } else if (draft.kind === "mensagem") {
    const job = h("select", { disabled: !pending });
    job.appendChild(h("option", { value: "", text: "Escolha a vaga" }));
    for (const item of state.vagas) job.appendChild(h("option", { value: String(item.id), text: jobLabel(item) }));
    job.value = p.job_id ? String(p.job_id) : "";
    const kind = h("select", { disabled: !pending });
    for (const [key, name] of Object.entries(CLASSES)) kind.appendChild(h("option", { value: key, text: name }));
    kind.value = p.classificacao || "outro";
    const target = statusSelect(p.status_proposto, { allowEmpty: true });
    target.disabled = !pending;
    const eventAt = h("input", { type: "datetime-local", value: toLocalInput(p.data_evento), disabled: !pending });
    const summary = h("textarea", { rows: 2, value: p.resumo || "", disabled: !pending });
    body.append(
      h("p", { class: "hint", text: `${p.remetente_nome || ""} <${p.remetente_email || ""}> · ${when(p.recebido_em)}` }),
      h("label", {}, "Vaga", job),
      h("div", { class: "two" }, h("label", {}, "Classificação", kind), h("label", {}, "Mudar status para", target)),
      h("label", {}, "Data e hora citadas", eventAt),
      h("label", {}, "Resumo", summary),
      h("details", {}, h("summary", { text: "E-mail completo" }), h("div", { class: "body-text", text: p.corpo || "" })),
    );
    if (p.classificado_por === "llm") body.appendChild(h("p", { class: "chip is-warn", text: "classificado pela IA local" }));
    collectors.push(() => ({
      job_id: job.value ? Number(job.value) : null,
      classificacao: kind.value,
      status_proposto: target.value,
      data_evento: eventAt.value,
      resumo: summary.value,
    }));
  }

  const error = h("p", { class: "draft-error", role: "alert" });
  card.appendChild(error);
  card.showError = (message) => {
    error.textContent = message;
  };
  card.collect = () => {
    const payload = Object.assign({}, ...collectors.map((collect) => collect()));
    return card.dirty ? payload : null;
  };

  if (pending) {
    const actions = h("div", { class: "draft-actions" },
      h("button", { type: "button", class: "approve", text: "Aprovar", onclick: () => decide(card, draft, "aprovar") }),
      h("button", { type: "button", class: "danger", text: "Descartar", onclick: () => decide(card, draft, "descartar") }),
    );
    if (inQueue) {
      actions.appendChild(h("button", { type: "button", class: "ghost", text: "Depois", onclick: () => later(card, draft) }));
    }
    card.appendChild(actions);
  }
  return card;
}

async function decide(card, draft, action) {
  card.showError("");
  const buttons = card.querySelectorAll("button");
  buttons.forEach((button) => {
    button.disabled = true;
  });
  try {
    const payload = action === "aprovar" ? card.collect() : null;
    await api(`/api/rascunhos/${draft.id}/${action}`, { method: "POST", json: payload ? { payload } : {} });
    card.dirty = false;
    state.snoozed.delete(draft.id);
    const drawer = document.getElementById("drawer");
    if (drawer.open && !state.drawerJob && drawer.contains(card)) drawer.close();
    await refresh();
  } catch (error) {
    card.showError(error.message);
    buttons.forEach((button) => {
      button.disabled = false;
    });
  }
}

async function later(card, draft) {
  const payload = card.collect();
  if (payload) {
    try {
      await api(`/api/rascunhos/${draft.id}`, { method: "PATCH", json: { payload } });
    } catch (error) {
      card.showError(error.message);
      return;
    }
  }
  card.dirty = false;
  state.snoozed.add(draft.id);
  renderQueue();
  if (state.view === "agora") renderAgora();
}

// Atualiza a lista sem apagar o que o usuário está digitando.
function syncCards(container, drafts, options = {}) {
  const existing = new Map([...container.querySelectorAll(":scope > .draft")].map((node) => [Number(node.dataset.id), node]));
  const ordered = [];
  for (const draft of drafts) {
    let node = existing.get(draft.id);
    if (node && node.dataset.updated !== draft.updated_at) {
      if (node.dirty) {
        if (!node.querySelector(".stale")) {
          node.insertBefore(
            h("p", { class: "stale", text: "A captura trouxe novidades. Aprove o que você editou ou descarte e recarregue." }),
            node.querySelector(".fields"),
          );
        }
      } else {
        node = null;
      }
    }
    ordered.push(node || draftCard(draft, options));
    existing.delete(draft.id);
  }
  for (const node of existing.values()) node.remove();
  ordered.forEach((node, index) => {
    if (container.children[index] !== node) container.insertBefore(node, container.children[index] || null);
  });
}

// Fila de popups

function renderQueue() {
  const queue = document.getElementById("queue");
  const waiting = state.rascunhos.filter((draft) => !state.snoozed.has(draft.id));
  if (state.overlay || !state.popups || !waiting.length || state.view === "rascunhos" || state.view === "agora") {
    queue.hidden = true;
    clear(queue);
    return;
  }
  const draft = waiting[0];
  const current = queue.querySelector(".draft");
  if (current && Number(current.dataset.id) === draft.id && (current.dataset.updated === draft.updated_at || current.dirty)) {
    queue.querySelector(".queue-count").textContent = `Rascunho 1 de ${waiting.length}`;
    queue.hidden = false;
    return;
  }
  clear(queue);
  queue.append(
    h("div", { class: "queue-head" },
      h("span", { class: "queue-count", text: `Rascunho 1 de ${waiting.length}` }),
      h("button", { type: "button", "aria-label": "Fechar popups", text: "×", onclick: () => setPopups(false) }),
    ),
    draftCard(draft, { inQueue: true }),
  );
  queue.hidden = false;
}

function setPopups(on) {
  state.popups = on;
  writePref("popups", on ? "on" : "off");
  document.getElementById("popup-toggle").checked = on;
  renderQueue();
}

// Telas

// Agora: o próximo rascunho e o que o JobScout está fazendo

const LEVEL_NAMES = { ok: "feito", aviso: "atenção", erro: "erro", trabalhando: "processando", info: "info" };

function renderAgora() {
  renderReminders().catch(console.error);
  const waiting = state.rascunhos.filter((draft) => !state.snoozed.has(draft.id));
  const slot = document.getElementById("now-draft");
  const count = document.getElementById("now-waiting-count");
  count.textContent = state.rascunhos.length ? `${Math.min(1, waiting.length)} de ${state.rascunhos.length}` : "";
  if (!waiting.length) {
    clear(slot);
    const snoozed = state.rascunhos.length - waiting.length;
    slot.appendChild(h("p", { class: "empty", text: snoozed
      ? `${snoozed} rascunho(s) deixado(s) para depois. Veja em Rascunhos.`
      : "Nada esperando aprovação." }));
  } else {
    if (slot.querySelector(".empty")) clear(slot);
    syncCards(slot, waiting.slice(0, 1), { inQueue: true });
  }
  renderStatusLine();
  renderFeed();
}

function renderStatusLine() {
  const line = document.getElementById("now-status");
  const last = state.feed[0];
  const working = Date.now() < state.workingUntil;
  line.classList.toggle("working", working);
  if (working && last) line.textContent = last.texto;
  else if (state.rascunhos.length) line.textContent = `Ocioso. ${state.rascunhos.length} rascunho(s) esperando você.`;
  else line.textContent = "Ocioso. Navegue no LinkedIn ou na InHire; eu acompanho daqui.";
}

function renderFeed() {
  const list = document.getElementById("feed");
  const shown = new Set([...list.children].map((node) => Number(node.dataset.id)));
  if (!state.feed.length) {
    clear(list);
    list.appendChild(h("li", { class: "empty", text: "Sem atividade ainda." }));
    return;
  }
  const empty = list.querySelector(".empty");
  if (empty) empty.remove();
  const fresh = state.feed.filter((item) => !shown.has(item.id)).reverse();
  for (const item of fresh) {
    const row = h("li", { class: "n-" + item.nivel, "data-id": item.id, title: LEVEL_NAMES[item.nivel] || item.nivel },
      h("span", { class: "when", text: timeFmt.format(new Date(item.em)) }),
      h("span", {}, item.texto,
        item.rascunho ? h("a", { href: "#rascunhos", text: " · revisar" }) : null,
        item.vaga ? h("a", { href: "#", text: " · abrir vaga", onclick: (event) => {
          event.preventDefault();
          openJob(item.vaga);
        } }) : null,
      ),
    );
    list.insertBefore(row, list.firstChild);
  }
  while (list.children.length > 120) list.lastChild.remove();
}

function onActivity(item) {
  if (state.feed.some((known) => known.id === item.id)) return;
  state.feed.unshift(item);
  state.feed.length = Math.min(state.feed.length, 150);
  state.workingUntil = item.nivel === "trabalhando" ? Date.now() + 4000 : 0;
  if (item.acao === "envio") {
    state.throwUntil = Date.now() + THROW_MS;
    setTimeout(renderBubble, THROW_MS + 50);
  }
  if (state.view === "agora") {
    renderFeed();
    renderStatusLine();
  }
  renderBubble();
  showToast(item);
  if (state.overlay && item.nivel === "aviso" && bridge()) bridge().avisar(item.texto);
  const orb = document.getElementById("orb");
  if (item.nivel === "aviso") {
    orb.classList.remove("is-alert");
    void orb.offsetWidth;
    orb.classList.add("is-alert");
  }
  setTimeout(() => {
    if (state.view === "agora") renderStatusLine();
    renderBubble();
  }, 4100);
}

// Confirmação dentro da página. O confirm() nativo abre fora da janela pequena do overlay
// (aparece "sumido"); este fica no meio do que está na tela.
function ask(message, hint = "", okLabel = "Confirmar") {
  const dialog = document.getElementById("ask");
  document.getElementById("ask-text").textContent = message;
  document.getElementById("ask-hint").textContent = hint;
  document.getElementById("ask-ok").textContent = okLabel;
  return new Promise((resolve) => {
    dialog.addEventListener("close", () => resolve(dialog.returnValue === "ok"), { once: true });
    dialog.returnValue = "";
    dialog.showModal();
    document.getElementById("ask-ok").focus();
  });
}

// Overlay: bolha no canto, menu, pop-ups e painéis

function bridge() {
  return window.pywebview && window.pywebview.api ? window.pywebview.api : null;
}

// Pede à janela o tamanho do formato atual. Bolha e menu medem o próprio conteúdo.
// Bolha sem pop-ups: janela do tamanho do boneco, recortada em círculo (overlay.py, BUBBLE).
function fitWindow() {
  if (!state.overlay) return;
  const api = bridge();
  if (!api) return;
  requestAnimationFrame(() => {
    const compact = state.mode === "bolha" || state.mode === "menu";
    const dock = document.getElementById("dock");
    const orbOnly = state.mode === "bolha" && !document.getElementById("toasts").children.length;
    document.body.classList.toggle("orb-only", orbOnly);
    if (orbOnly) {
      api.formato("bolha", BUBBLE_SIZE, BUBBLE_SIZE, state.rascunhos.length ? "orb-badge" : "orb");
      return;
    }
    const height = compact ? Math.ceil([...dock.children].reduce((sum, node) => sum + (node.hidden ? 0 : node.offsetHeight), 0) + 2) : 0;
    // Pontos de melhoria abertos no Currículo: a janela cresce para a esquerda e o painel ocupa
    // essa faixa nova, sem cobrir o currículo (que fica com a mesma largura de antes).
    const side = !compact && ((state.improveOpen && state.view === "curriculo") || (state.presetsOpen && state.view === "vagas"));
    document.body.classList.toggle("improve-side", side);
    const width = compact ? DOCK_WIDTH : side ? (PANEL_WIDTHS[state.mode] || PANEL_WIDTHS.painel) + IMPROVE_WIDTH : 0;
    api.formato(state.mode, height, width, "");
  });
}

// Arrastar a bolha: depois de 5 px com o botão apertado, o Python move a janela até soltar
// (e prende no canto ou na borda direita). O clique que vem junto com o soltar é ignorado.
function setupDrag() {
  const bubble = document.getElementById("bubble");
  let start = null;
  bubble.addEventListener("pointerdown", (event) => {
    if (event.button !== 0) return;
    start = { x: event.screenX, y: event.screenY, grabX: event.clientX, grabY: event.clientY };
    state.dragged = false;
  });
  bubble.addEventListener("pointermove", (event) => {
    if (!start || Math.hypot(event.screenX - start.x, event.screenY - start.y) < 5) return;
    const api = bridge();
    const { grabX, grabY } = start;
    start = null;
    if (!api) return;
    state.dragged = true;
    api.arrastar(grabX, grabY);
  });
  bubble.addEventListener("pointerup", () => { start = null; });
}

function setMode(mode) {
  if (!state.overlay) return;
  state.mode = mode;
  for (const name of ["bolha", "menu", "painel", "amplo"]) document.body.classList.toggle("mode-" + name, name === mode);
  document.getElementById("menu").hidden = mode !== "menu";
  document.getElementById("bubble").setAttribute("aria-expanded", String(mode === "menu"));
  const wide = document.getElementById("ov-wide");
  wide.textContent = mode === "amplo" ? "⇥" : "⇔";
  wide.title = mode === "amplo" ? "Estreitar" : "Expandir (cobrir mais tela)";
  if (mode !== "bolha" && mode !== "menu") clear(document.getElementById("toasts"));
  fitWindow();
}

function go(view) {
  const target = view.startsWith("empresa/") ? "empresa" : view;
  if (state.overlay) setMode(WIDE_VIEWS.has(target) ? "amplo" : "painel");
  if (location.hash.slice(1) === view) showView(target);
  else location.hash = view;
}

// Nome que a pessoa escolheu para o assistente: topo do menu, barra do painel e título da aba.
function applyName(name) {
  state.appName = name || "JobScout";
  for (const node of document.querySelectorAll("[data-app-name]")) node.textContent = state.appName;
  document.title = (state.rascunhos.length ? `(${state.rascunhos.length}) ` : "") + state.appName + " — Painel";
}

function renderBubble() {
  const pending = state.rascunhos.length;
  const working = Date.now() < state.workingUntil;
  for (const id of ["badge", "menu-badge"]) {
    const node = document.getElementById(id);
    node.hidden = !pending;
    node.textContent = String(pending);
  }
  if (!state.overlay) return;
  const count = document.getElementById("bubble-count");
  count.hidden = !pending;
  count.textContent = pending > 99 ? "99+" : String(pending);
  const tip = `${state.appName} · ${pending ? `${pending} rascunho(s) pendente(s)` : "tudo em dia"}`;
  if (state.overlay && state.trayTip !== tip && bridge()) {
    state.trayTip = tip;
    bridge().dica(tip);
  }
  // Boneco: arremessa a maleta logo depois do envio, pensa enquanto lê uma vaga, senta quando está parado.
  const pose = Date.now() < state.throwUntil ? "throw" : working ? "think" : "idle";
  const stickman = document.getElementById("stickman");
  if (stickman.dataset.pose !== pose) {
    stickman.dataset.pose = pose;
    showAvatarPose();
  }
  // O status vai para a dica do mouse; a bolha mostra só o boneco e o contador.
  let status = "Tudo em dia";
  if (working && state.feed[0]) status = state.feed[0].texto;
  else if (pending) status = `${pending} rascunho${pending > 1 ? "s" : ""} pendente${pending > 1 ? "s" : ""}`;
  document.getElementById("bubble").title = `${state.appName} · ${status}\nClique para abrir o menu; arraste para mover`;
  // Com ou sem contador, o recorte da janela muda.
  if (state.bubbleBadge !== Boolean(pending)) {
    state.bubbleBadge = Boolean(pending);
    fitWindow();
  }
  const agora = document.getElementById("menu-agora");
  agora.textContent = working ? "processando…" : "";
}

function showToast(item) {
  if (!state.overlay || (state.mode !== "bolha" && state.mode !== "menu")) return;
  if (!state.toastPrefs[item.nivel]) return;
  const box = document.getElementById("toasts");
  const close = () => {
    toast.classList.add("is-leaving");
    setTimeout(() => {
      toast.remove();
      fitWindow();
    }, 200);
  };
  const toast = h("div", { class: "toast n-" + item.nivel, role: "status", onclick: (event) => {
    if (event.target.closest("button")) return;
    close();
    if (item.rascunho) go("rascunhos");
    else if (item.vaga) {
      go("agora");
      openJob(item.vaga);
    } else go("agora");
  } },
    h("span", { class: "toast-text", text: item.texto }),
    h("button", { type: "button", "aria-label": "Dispensar", text: "×", onclick: close }),
    h("span", { class: "toast-meta" }, timeFmt.format(new Date(item.em)), item.rascunho ? h("strong", { text: " · revisar" }) : null),
  );
  box.appendChild(toast);
  while (box.children.length > 3) box.firstChild.remove();
  setTimeout(close, item.rascunho ? 12000 : 7000);
  fitWindow();
}

function setupOverlay() {
  if (!state.overlay) return;
  document.body.classList.add("overlay");
  setMode("bolha");
  window.addEventListener("pywebviewready", () => fitWindow());
  setupDrag();
  document.getElementById("bubble").addEventListener("click", () => {
    if (state.dragged) {
      state.dragged = false;
      return;
    }
    setMode(state.mode === "menu" ? "bolha" : "menu");
  });
  for (const item of document.querySelectorAll("[data-go]")) item.addEventListener("click", () => go(item.dataset.go));
  document.getElementById("ov-min").addEventListener("click", () => setMode("bolha"));
  document.getElementById("ov-wide").addEventListener("click", () => setMode(state.mode === "amplo" ? "painel" : "amplo"));
  for (const button of document.querySelectorAll("[data-browser]")) {
    button.addEventListener("click", () => {
      const api = bridge();
      const view = state.view === "agora" ? "rascunhos" : state.view === "empresa" ? "empresa/" + state.companyId : state.view;
      if (api) api.abrir_painel(view);
      else window.open("/#" + view, "_blank");
    });
  }
  for (const button of document.querySelectorAll("[data-close]")) {
    button.addEventListener("click", async () => {
      const api = bridge();
      // Com o ícone na bandeja, o × só esconde: quem encerra é o Sair do menu do ícone.
      if (api && await api.ocultar()) return;
      if (!(await ask(`Fechar o ${state.appName}?`, "A extensão guarda o que capturar e envia quando você abrir de novo.", "Fechar"))) return;
      if (api) api.fechar();
      else window.close();
    });
  }
  const pins = [...document.querySelectorAll("[data-pin]")];
  for (const pin of pins) {
    pin.addEventListener("click", async () => {
      const on = pin.getAttribute("aria-pressed") !== "true";
      const api = bridge();
      if (!api) return;
      try {
        if (!(await api.fixar(on))) return;
      } catch (error) {
        console.error(error);
        return;
      }
      for (const other of pins) {
        other.setAttribute("aria-pressed", String(on));
        other.title = on ? "Sempre por cima (clique para soltar)" : "Solto (clique para fixar por cima)";
      }
    });
  }
  // Esc volta para a bolha.
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !document.querySelector("dialog[open]") && state.mode !== "bolha") setMode("bolha");
  });
  // Links externos vão para o navegador padrão, não para dentro do overlay.
  document.addEventListener("click", (event) => {
    const link = event.target.closest('a[target="_blank"]');
    const api = bridge();
    if (!link || !api) return;
    event.preventDefault();
    api.abrir_link(link.href);
  });
}

async function renderDrafts() {
  const list = document.getElementById("draft-list");
  const notice = document.getElementById("drafts-notice");
  let drafts = state.rascunhos;
  if (state.filter !== "pendente") {
    drafts = await api("/api/rascunhos?estado=" + state.filter);
  }
  if (!drafts.length) {
    clear(list);
    notice.textContent = state.filter === "pendente" ? "Nenhum rascunho esperando. Tudo em dia." : "Nada por aqui.";
    return;
  }
  notice.textContent = state.filter === "pendente" ? `${drafts.length} aguardando aprovação.` : "";
  syncCards(list, drafts);
}

const filters = { empresa: "", vaga: "", senioridade: "", tipo: "" };

function fillFilter(id, options, current, everything) {
  const select = document.getElementById(id);
  clear(select);
  select.appendChild(h("option", { value: "", text: everything }));
  for (const [value, label] of options) select.appendChild(h("option", { value, text: label }));
  select.value = options.some(([value]) => value === current) ? current : "";
}

async function renderTimeline() {
  const strip = document.getElementById("timeline-pending");
  clear(strip);
  if (state.rascunhos.length) {
    strip.append(
      h("strong", { text: `${state.rascunhos.length} rascunho(s) aguardando` }),
      ...state.rascunhos.slice(0, 3).map((draft) => h("span", { class: "chip", text: LABELS[draft.kind] })),
      h("a", { href: "#rascunhos", text: "Revisar" }),
    );
  }
  state.moves = await api("/api/movimentos?limite=1000");
  const byName = (a, b) => a[1].localeCompare(b[1], "pt-BR");
  const companies = new Map(), jobs = new Map(), levels = new Map(), kinds = new Map();
  for (const move of state.moves) {
    if (move.job_company) companies.set(move.job_company, move.job_company);
    if (move.job_id && move.job_title !== null) jobs.set(String(move.job_id), jobLabel({ title: move.job_title, company: move.job_company }));
    if (move.job_seniority) levels.set(move.job_seniority, move.job_seniority);
    kinds.set(move.kind, KIND_NAMES[move.kind] || move.kind);
  }
  fillFilter("f-empresa", [...companies].sort(byName), filters.empresa, "Todas");
  fillFilter("f-vaga", [...jobs].sort(byName), filters.vaga, "Todas");
  fillFilter("f-senioridade", [...levels].sort(byName), filters.senioridade, "Todas");
  fillFilter("f-tipo", [...kinds].sort(byName), filters.tipo, "Todos");
  renderMoves();
}

function renderMoves() {
  const list = document.getElementById("timeline");
  clear(list);
  if (!state.moves.length) {
    list.appendChild(h("li", { class: "empty", text: "Nenhum movimento ainda. Abra uma vaga no LinkedIn ou na InHire com a extensão ligada." }));
    return;
  }
  const shown = state.moves.filter((move) =>
    (!filters.empresa || move.job_company === filters.empresa)
    && (!filters.vaga || String(move.job_id) === filters.vaga)
    && (!filters.senioridade || move.job_seniority === filters.senioridade)
    && (!filters.tipo || move.kind === filters.tipo));
  if (!shown.length) {
    list.appendChild(h("li", { class: "empty", text: "Nenhum movimento com esses filtros." }));
    return;
  }
  appendMoves(list, shown, { showJob: true });
}

function appendMoves(list, moves, { showJob }) {
  let day = "";
  for (const move of moves) {
    const date = new Date(move.at);
    const label = dayFmt.format(date);
    if (label !== day) {
      day = label;
      list.appendChild(h("li", { class: "day" }, h("p", { class: "eyebrow", text: label })));
    }
    const what = h("div", { class: "what" }, move.summary);
    if (showJob && move.job_id && move.job_title !== null) {
      what.appendChild(h("a", { class: "job", href: "#", text: jobLabel({ title: move.job_title, company: move.job_company }), onclick: (event) => {
        event.preventDefault();
        openJob(move.job_id);
      } }));
    }
    what.appendChild(h("span", { class: "chip", text: SOURCES[move.source] || move.source }));
    list.appendChild(h("li", { class: "move k-" + move.kind }, h("span", { class: "when", text: timeFmt.format(date) }), what));
  }
}

function renderBoard() {
  loadBoardChoices().catch(console.error);
  if (state.boardCompany) {
    renderCompanyBoard().catch((error) => alert(error.message));
    return;
  }
  document.getElementById("board-edit").hidden = true;
  document.getElementById("board-editor").hidden = true;
  document.getElementById("kanban-lede").textContent =
    `Arraste o cartão para mudar o status. A coluna Rascunho espera a sua aprovação; vaga parada há ${state.diasFria} dias vira proposta para Fria.`;
  const jobs = state.vagas.filter((job) => boardMatch(job.title, job.company, job.location, job.work_mode));
  const drafts = state.rascunhos.filter((draft) => draft.kind === "vaga"
    && boardMatch(draft.payload.title, draft.payload.company, draft.payload.location, draft.payload.work_mode));
  boardCount(jobs.length, state.vagas.length);
  boardInto(document.getElementById("board"), jobs, drafts);
}

// Filtro do Kanban: texto em nome da empresa, vaga e localidade, e modelo de trabalho.
function boardMatch(title, company, place, mode) {
  const fold = (text) => String(text || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
  const query = fold(document.getElementById("board-q").value).trim();
  const wanted = document.getElementById("board-mode").value;
  const text = fold(`${title} ${company} ${place}`);
  if (query && !query.split(/\s+/).every((word) => text.includes(word))) return false;
  if (wanted === "-") return !mode;
  return !wanted || fold(mode).startsWith(wanted);
}

function boardCount(shown, total) {
  document.getElementById("board-count").textContent = shown === total ? "" : `${shown} de ${total} vagas`;
}

function fitPercent(job) {
  const wanted = skillList(job.skills);
  if (!wanted.length || !state.minhasSkills.length) return null;
  const mine = new Set(state.minhasSkills.map((item) => item.toLowerCase()));
  return Math.round(100 * wanted.filter((item) => mine.has(item.toLowerCase())).length / wanted.length);
}

// Busca automática de vagas (aba Busca)

const SEARCH_SOURCES = { gupy: "Gupy", himalayas: "Himalayas", inhire: "InHire", greenhouse: "Greenhouse", lever: "Lever", ashby: "Ashby", linkedin_email: "Alerta do LinkedIn" };
const MODE_NAMES = { remoto: "Remoto", hibrido: "Híbrido", presencial: "Presencial" };

async function renderAutoSearch() {
  const form = document.getElementById("as-form");
  const data = await api("/api/busca/config");
  const config = data.config;
  if (!form.contains(document.activeElement)) {
    fillSearchForm(config);
  }
  document.getElementById("as-similar").textContent = data.similares.length ? `Também procura: ${data.similares.join(", ")}.` : "";
  renderPresets(data);
  const last = config.ultima ? `Última busca ${when(config.ultima)}` : "Ainda não buscou";
  document.getElementById("as-next").textContent = config.ativo && data.proxima ? `${last} · próxima ${when(data.proxima)}` : `${last} · busca sozinha desligada`;
  if (!data.gmail) form.querySelector('[name="fonte"][value="linkedin_email"]').parentElement.title = "Conecte o Gmail em Config para ler os alertas.";
  const showDone = document.getElementById("as-show-done").checked;
  const rows = await api("/api/busca/resultados");
  const done = showDone ? [...await api("/api/busca/resultados?estado=salvo"), ...await api("/api/busca/resultados?estado=descartado")] : [];
  const list = document.getElementById("as-results");
  clear(list);
  document.getElementById("as-results-title").textContent = `Encontradas (${rows.length})`;
  if (!rows.length && !done.length) {
    list.appendChild(h("li", { class: "empty", text: "Nada novo. Diga o que procurar acima e clique em “Buscar agora”." }));
  }
  for (const row of [...rows, ...done]) {
    const notice = h("span", { class: "notice" });
    const decide = (action) => async () => {
      try {
        const job = await api(`/api/busca/resultados/${row.id}/${action}`, { method: "POST", json: {} });
        await refresh();
        await renderAutoSearch();
        if (action === "salvar" && job.id) openJob(job.id);
      } catch (error) {
        notice.textContent = error.message;
      }
    };
    list.appendChild(h("li", { class: "as-result" + (row.state !== "novo" ? " is-done" : "") },
      h("div", { class: "as-score", title: "Quanto combina com o que você procura", text: String(row.score) }),
      h("div", { class: "as-body" },
        h("a", { href: row.url, target: "_blank", rel: "noopener", class: "as-title", text: row.title || "Vaga sem título" }),
        h("span", { class: "hint", text: [row.company, row.location, MODE_NAMES[row.work_mode], SEARCH_SOURCES[row.source], row.fit !== null && row.fit !== undefined ? `encaixe ${row.fit}%` : ""].filter(Boolean).join(" · ") }),
        row.reasons.length ? h("span", { class: "as-why", text: row.reasons.join(" · ") }) : null,
      ),
      row.state === "novo"
        ? h("div", { class: "row" },
          h("button", { type: "button", text: "Salvar vaga", onclick: decide("salvar") }),
          h("button", { type: "button", class: "ghost", text: "Descartar", onclick: decide("descartar") }),
          notice)
        : h("span", { class: "chip", text: row.state === "salvo" ? "salva" : "descartada" }),
    ));
  }
}

function setupAutoSearch() {
  const form = document.getElementById("as-form");
  const notice = document.getElementById("as-notice");
  const read = () => ({
    titulos: form.elements.titulos.value, empresas: form.elements.empresas.value, palavras: form.elements.palavras.value,
    excluir: form.elements.excluir.value, inhire_empresas: form.elements.inhire_empresas.value, local: form.elements.local.value,
    ats_empresas: form.elements.ats_empresas.value, expandir: form.elements.expandir.checked,
    intervalo_horas: Number(form.elements.intervalo_horas.value || 6), ativo: form.elements.ativo.checked,
    modelos: [...form.querySelectorAll('[name="modelo"]:checked')].map((box) => box.value),
    fontes: Object.fromEntries([...form.querySelectorAll('[name="fonte"]')].map((box) => [box.value, box.checked])),
  });
  const save = async () => {
    await api("/api/busca/config", { method: "PUT", json: read() });
  };
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await save();
      document.activeElement.blur();
      notice.textContent = "Busca salva.";
      await renderAutoSearch();
    } catch (error) {
      notice.textContent = error.message;
    }
  });
  document.getElementById("as-run").addEventListener("click", async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    notice.textContent = "Buscando… (alguns segundos por fonte)";
    try {
      await save();
      const summary = await api("/api/busca/rodar", { method: "POST", json: {} });
      notice.textContent = `${summary.novas} nova(s) de ${summary.olhadas} olhada(s).${summary.avisos.length ? " " + summary.avisos.join(" · ") : ""}`;
      document.activeElement.blur();
      await renderAutoSearch();
    } catch (error) {
      notice.textContent = error.message;
    } finally {
      button.disabled = false;
    }
  });
  document.getElementById("as-show-done").addEventListener("change", () => renderAutoSearch().catch(console.error));
  searchState.read = read;
  const toggle = document.getElementById("as-presets-toggle");
  toggle.addEventListener("click", () => setPresetsPanel(document.getElementById("as-presets").hidden));
  document.getElementById("as-presets-close").addEventListener("click", () => setPresetsPanel(false));
  document.getElementById("as-preset-save").addEventListener("click", async () => {
    const input = document.getElementById("as-preset-name");
    const name = input.value.trim();
    const presetNotice = document.getElementById("as-preset-notice");
    if (!name) {
      presetNotice.textContent = "Dê um nome ao preset.";
      return;
    }
    const others = searchState.presets.filter((item) => item.nome !== name);
    try {
      renderPresets(await api("/api/busca/presets", { method: "PUT", json: { presets: [...others, { nome: name, config: read() }] } }));
      input.value = "";
      presetNotice.textContent = `Preset “${name}” salvo.`;
    } catch (error) {
      presetNotice.textContent = error.message;
    }
  });
  setPresetsPanel(readPref("presets", "fechado") === "aberto");
}

const searchState = { presets: [], read: null };

function fillSearchForm(config) {
  const form = document.getElementById("as-form");
  for (const key of ["titulos", "empresas", "palavras", "excluir", "inhire_empresas", "ats_empresas"]) form.elements[key].value = config[key].join(", ");
  form.elements.local.value = config.local;
  form.elements.intervalo_horas.value = config.intervalo_horas;
  form.elements.ativo.checked = config.ativo;
  form.elements.expandir.checked = config.expandir !== false;
  for (const box of form.querySelectorAll('[name="modelo"]')) box.checked = config.modelos.includes(box.value);
  for (const box of form.querySelectorAll('[name="fonte"]')) box.checked = config.fontes[box.value] !== false;
}

function setPresetsPanel(open) {
  document.getElementById("as-presets").hidden = !open;
  document.getElementById("as-workspace").classList.toggle("has-improve", open);
  document.getElementById("as-presets-toggle").setAttribute("aria-expanded", String(open));
  writePref("presets", open ? "aberto" : "fechado");
  state.presetsOpen = open;
  fitWindow();
}

function renderPresets(data) {
  searchState.presets = data.presets;
  const count = document.getElementById("as-presets-count");
  count.hidden = !data.presets.length;
  count.textContent = String(data.presets.length);
  const list = document.getElementById("as-preset-list");
  clear(list);
  if (!data.presets.length) list.appendChild(h("li", { class: "empty", text: "Nenhum preset ainda. Preencha a busca e salve com um nome." }));
  for (const preset of data.presets) {
    const summary = [...preset.config.titulos, ...preset.config.empresas].slice(0, 4).join(", ") || preset.config.palavras.join(", ");
    list.appendChild(h("li", {},
      h("span", { class: "q", text: preset.nome }),
      h("p", { class: "was", text: [summary, preset.config.modelos.map((mode) => data.modelos[mode]).join(", ")].filter(Boolean).join(" · ") }),
      h("div", { class: "row" },
        h("button", { type: "button", text: "Usar e buscar", onclick: () => { fillSearchForm(preset.config); document.getElementById("as-run").click(); } }),
        h("button", { type: "button", class: "ghost", text: "Só preencher", onclick: () => fillSearchForm(preset.config) }),
        h("label", { class: "check", title: "Roda junto com a busca automática, no intervalo salvo" },
          h("input", { type: "checkbox", checked: Boolean(preset.auto), onchange: async (event) => {
            preset.auto = event.target.checked;
            renderPresets(await api("/api/busca/presets", { method: "PUT", json: { presets: searchState.presets } }));
          } }), "Buscar sozinho"),
        h("button", { type: "button", class: "danger", text: "Excluir", onclick: async () => {
          renderPresets(await api("/api/busca/presets", { method: "PUT", json: { presets: searchState.presets.filter((item) => item !== preset) } }));
        } }),
      ),
    ));
  }
}

// Busca: chat sobre o histórico, com as conversas guardadas

const chatState = { thread: null };

async function renderChat() {
  const threads = await api("/api/chat");
  const list = document.getElementById("chat-threads");
  clear(list);
  if (!threads.length) list.appendChild(h("li", { class: "empty", text: "Nenhuma conversa ainda." }));
  for (const thread of threads) {
    list.appendChild(h("li", { class: thread.id === chatState.thread ? "is-on" : "" },
      h("button", { type: "button", class: "chat-open", title: thread.title, text: thread.title || "Conversa", onclick: () => openChat(thread.id) }),
      h("button", { type: "button", class: "chat-del", title: "Apagar conversa", "aria-label": "Apagar conversa", text: "×", onclick: async () => {
        await api(`/api/chat/${thread.id}/remover`, { method: "POST", json: {} });
        if (chatState.thread === thread.id) {
          chatState.thread = null;
          renderChatLog([]);
        }
        await renderChat();
      } }),
    ));
  }
}

function renderChatLog(messages) {
  const log = document.getElementById("chat-log");
  clear(log);
  if (!messages.length) log.appendChild(h("li", { class: "empty", text: "Pergunte o que quiser sobre as suas vagas: o que respondeu, quem falou com você, em que etapa está cada processo." }));
  const kinds = { vaga: "Vaga", resposta: "Resposta", mensagem: "Mensagem", nota: "Nota" };
  for (const message of messages) {
    log.appendChild(h("li", { class: "chat-msg is-" + message.role },
      h("p", { class: "chat-text", text: message.text }),
      message.sources.length ? h("details", { class: "chat-sources" },
        h("summary", { text: `${message.sources.length} fonte(s) do histórico` }),
        h("ul", {}, message.sources.map((source) => h("li", {},
          h("strong", { text: `${kinds[source.tipo] || source.tipo}: ${source.titulo}` }),
          source.vaga ? ` · ${source.vaga}` : "",
          source.quando ? ` · ${when(source.quando)}` : "",
          source.job_id ? [" · ", h("a", { href: "#", text: "abrir vaga", onclick: (event) => { event.preventDefault(); openJob(source.job_id); } })] : null,
          h("span", { class: "hint chat-snippet", text: source.texto }),
        ))),
      ) : null,
    ));
  }
  log.scrollTop = log.scrollHeight;
}

async function openChat(id) {
  chatState.thread = id;
  const thread = await api(`/api/chat/${id}`);
  renderChatLog(thread.mensagens);
  await renderChat();
}

function setupChat() {
  const form = document.getElementById("chat-form");
  const input = document.getElementById("chat-text");
  document.getElementById("chat-new").addEventListener("click", () => {
    chatState.thread = null;
    renderChatLog([]);
    renderChat().catch(console.error);
    input.focus();
  });
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      form.requestSubmit();
    }
  });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const text = input.value.trim();
    if (!text) return;
    const log = document.getElementById("chat-log");
    if (log.querySelector(".empty")) clear(log);
    log.appendChild(h("li", { class: "chat-msg is-pessoa" }, h("p", { class: "chat-text", text })));
    log.appendChild(h("li", { class: "chat-msg is-jobscout is-typing" }, h("p", { class: "chat-text", text: "Procurando no histórico…" })));
    log.scrollTop = log.scrollHeight;
    input.value = "";
    try {
      const thread = await api("/api/chat", { method: "POST", json: { conversa: chatState.thread, texto: text } });
      chatState.thread = thread.id;
      renderChatLog(thread.mensagens);
      await renderChat();
    } catch (error) {
      log.lastElementChild.querySelector(".chat-text").textContent = error.message;
    }
  });
  renderChatLog([]);
}

// Aparência: tema importado e personagem no lugar do boneco

const look = { avatar: null, template: null };

function appPasswordForm() {
  const email = h("input", { type: "email", placeholder: "seu.email@gmail.com", "aria-label": "E-mail", autocomplete: "off" });
  const secret = h("input", { type: "password", placeholder: "Senha de app (16 letras)", "aria-label": "Senha de app", autocomplete: "off" });
  const server = h("input", { placeholder: "Servidor IMAP (só se não for Gmail)", "aria-label": "Servidor IMAP" });
  const notice = h("p", { class: "notice", role: "status" });
  return h("form", { class: "profile", onsubmit: async (event) => {
    event.preventDefault();
    notice.textContent = "Testando o login…";
    try {
      await api("/api/email/conectar", { method: "POST", json: { email: email.value, senha: secret.value, servidor: server.value } });
      await refresh();
    } catch (error) {
      notice.textContent = error.message;
    }
  } }, email, secret, server, h("button", { type: "submit", text: "Conectar e-mail" }), notice);
}

function setupBackground() {
  const hidden = document.getElementById("bg-hidden");
  const autostart = document.getElementById("bg-autostart");
  const read = () => {
    hidden.checked = Boolean(state.prefs && state.prefs.iniciar_oculto);
    autostart.checked = Boolean(state.prefs && state.prefs.iniciar_com_windows);
  };
  document.querySelector('[data-view="config"]').addEventListener("click", read);
  read();
  const save = async (data) => {
    state.prefs = { ...state.prefs, ...(await api("/api/segundo-plano", { method: "POST", json: data })) };
    read();
  };
  hidden.addEventListener("change", () => save({ iniciar_oculto: hidden.checked }));
  autostart.addEventListener("change", () => save({ iniciar_com_windows: autostart.checked }));
}

function googleForm() {
  const id = h("input", { placeholder: "ID do cliente (…apps.googleusercontent.com)", "aria-label": "ID do cliente", autocomplete: "off" });
  const secret = h("input", { type: "password", placeholder: "Chave secreta do cliente", "aria-label": "Chave do cliente", autocomplete: "off" });
  const notice = h("p", { class: "notice", role: "status" });
  return h("form", { class: "profile", onsubmit: async (event) => {
    event.preventDefault();
    try {
      await api("/api/preferencias", { method: "PUT", json: { google_cliente: id.value.trim(), google_chave: secret.value.trim() } });
      await refresh();
    } catch (error) {
      notice.textContent = error.message;
    }
  } }, id, secret, h("button", { type: "submit", text: "Salvar" }), notice);
}

function themeCss(theme) {
  const rules = (colors) => Object.entries(colors || {}).map(([name, value]) => `--${name}: ${value};`).join(" ");
  const dark = rules(theme.escuro);
  return `:root { ${rules(theme.claro)} }\n`
    + (dark ? `@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { ${dark} } }\n:root[data-theme="dark"] { ${dark} }\n` : "");
}

function applyLook(data) {
  let style = document.getElementById("custom-theme");
  if (!style) {
    style = document.createElement("style");
    style.id = "custom-theme";
    document.head.appendChild(style);
  }
  style.textContent = data.tema ? themeCss(data.tema) : "";
  look.avatar = data.boneco;
  showAvatarPose();
  document.getElementById("theme-state").textContent = data.tema ? `Tema importado: ${data.tema.nome}.` : "Tema padrão do JobScout.";
  document.getElementById("avatar-state").textContent = data.boneco ? "Personagem importado." : "Boneco padrão do JobScout.";
  document.getElementById("theme-format").textContent = JSON.stringify(data.modelo_tema, null, 2);
  document.getElementById("theme-tokens").textContent = "Cores aceitas (todas opcionais): " + data.cores.join(", ") + ". Valores: #rrggbb, rgb() ou hsl().";
  look.template = data.modelo_tema;
}

function showAvatarPose() {
  const image = document.getElementById("avatar-custom");
  const stickman = document.getElementById("stickman");
  image.hidden = !look.avatar;
  stickman.style.display = look.avatar ? "none" : "";
  if (!look.avatar) return;
  const source = look.avatar[stickman.dataset.pose] || look.avatar.idle;
  if (image.getAttribute("src") !== source) image.src = source;
}

function readImage(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(new Error("Não consegui ler o arquivo."));
    reader.readAsDataURL(file);
  });
}

function setupLook() {
  const themeNotice = document.getElementById("theme-notice");
  const avatarNotice = document.getElementById("avatar-notice");
  api("/api/aparencia").then(applyLook).catch(console.error);
  document.getElementById("theme-import").addEventListener("change", async (event) => {
    const file = event.target.files[0];
    event.target.value = "";
    if (!file) return;
    try {
      const tema = JSON.parse(await file.text());
      applyLook(await api("/api/aparencia/tema", { method: "PUT", json: { tema } }));
      themeNotice.textContent = "Tema aplicado.";
    } catch (error) {
      themeNotice.textContent = error instanceof SyntaxError ? "O arquivo não é um JSON válido." : error.message;
    }
  });
  document.getElementById("theme-reset").addEventListener("click", async () => {
    applyLook(await api("/api/aparencia/tema/restaurar", { method: "POST", json: {} }));
    themeNotice.textContent = "Voltou ao tema padrão.";
  });
  document.getElementById("theme-template").addEventListener("click", () => {
    const link = h("a", { href: URL.createObjectURL(new Blob([JSON.stringify(look.template, null, 2)], { type: "application/json" })), download: "tema-jobscout.json" });
    link.click();
    URL.revokeObjectURL(link.href);
  });
  document.getElementById("avatar-save").addEventListener("click", async () => {
    const data = {};
    try {
      for (const pose of ["idle", "think", "throw"]) {
        const file = document.getElementById("avatar-" + pose).files[0];
        if (file) data[pose] = await readImage(file);
      }
      applyLook(await api("/api/aparencia/boneco", { method: "PUT", json: data }));
      avatarNotice.textContent = "Personagem aplicado.";
    } catch (error) {
      avatarNotice.textContent = error.message;
    }
  });
  document.getElementById("avatar-reset").addEventListener("click", async () => {
    applyLook(await api("/api/aparencia/boneco/restaurar", { method: "POST", json: {} }));
    avatarNotice.textContent = "Voltou ao boneco padrão.";
  });
}

// Quadro de uma empresa: as colunas são as etapas que ela usa (desenhadas pela pessoa).

async function loadBoardChoices() {
  const select = document.getElementById("board-pick");
  if (select.contains(document.activeElement)) return;
  const boards = await api("/api/quadros");
  const chosen = state.boardCompany ? String(state.boardCompany) : "";
  for (const option of [...select.options].slice(1)) option.remove();
  for (const board of boards) {
    select.appendChild(h("option", { value: String(board.id), text: `${board.nome} (${board.vagas} vaga${board.vagas > 1 ? "s" : ""})${board.personalizado ? " · quadro próprio" : ""}` }));
  }
  select.value = boards.some((board) => String(board.id) === chosen) ? chosen : "";
  if (!select.value && state.boardCompany) {
    state.boardCompany = null;
    renderBoard();
  }
}

async function renderCompanyBoard() {
  const data = await api(`/api/empresas/${state.boardCompany}/quadro`);
  const board = document.getElementById("board");
  document.getElementById("board-edit").hidden = false;
  document.getElementById("kanban-lede").textContent =
    `Quadro da ${data.empresa.nome}${data.personalizado ? "" : " (padrão do JobScout)"}: arraste a vaga para a etapa em que ela está. O status geral acompanha o tipo da etapa.`;
  clear(board);
  const columns = [...data.quadro.map((stage) => ({ key: stage.name.toLowerCase(), name: stage.name, kind: stage.kind })),
    { key: "", name: "Fora do quadro", kind: "" }];
  const fold = (text) => text.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
  const shownJobs = data.vagas.filter((job) => boardMatch(job.titulo, job.empresa, job.local, job.modo));
  boardCount(shownJobs.length, data.vagas.length);
  for (const column of columns) {
    const own = shownJobs.filter((job) => (column.key ? job.coluna === fold(column.name) : !data.quadro.some((stage) => fold(stage.name) === job.coluna)));
    if (!column.key && !own.length) continue;
    const col = h("section", { class: "col" + (column.key ? "" : " is-cold") },
      h("div", { class: "col-head" }, h("span", { text: column.name, title: column.kind ? data.tipos[column.kind] : "" }), h("span", { text: String(own.length) })),
    );
    if (column.key) {
      col.addEventListener("dragover", (event) => { event.preventDefault(); col.classList.add("is-over"); });
      col.addEventListener("dragleave", () => col.classList.remove("is-over"));
      col.addEventListener("drop", async (event) => {
        event.preventDefault();
        col.classList.remove("is-over");
        const id = Number(event.dataTransfer.getData("text/plain"));
        if (!id) return;
        try {
          await api(`/api/vagas/${id}/etapas/mover`, { method: "POST", json: { etapa: column.name } });
          await refresh();
        } catch (error) {
          alert(error.message);
        }
      });
    }
    for (const job of own) {
      const card = h("button", { type: "button", class: "card", draggable: "true", onclick: () => openJob(job.id) },
        h("strong", { text: job.titulo || "Vaga sem título" }),
        h("span", { class: "when", text: " · " + (state.status.find((item) => item.chave === job.status) || {}).nome }),
        job.proxima ? h("span", { class: "flag", text: " · " + when(job.proxima) }) : null,
      );
      card.addEventListener("dragstart", (event) => event.dataTransfer.setData("text/plain", String(job.id)));
      col.appendChild(card);
    }
    board.appendChild(col);
  }
}

function openBoardEditor(data) {
  const box = document.getElementById("board-editor");
  clear(box);
  box.hidden = false;
  box.dataset.company = String(data.empresa.id);
  const editor = stageEditor(data.quadro, data.tipos, data.sugestoes, false);
  const apply = h("input", { type: "checkbox", checked: true });
  const notice = h("span", { class: "notice", role: "status" });
  box.append(
    h("h2", { class: "tab", text: `Etapas da ${data.empresa.nome}` }),
    h("p", { class: "hint", text: "Desenhe o processo como a empresa contou: testes, conversas, visita presencial… O tipo de cada etapa diz em que coluna do quadro geral a vaga aparece." }),
    editor.node,
    h("label", { class: "check" }, apply, ` Aplicar às vagas da ${data.empresa.nome} que já estão salvas (mantém o que já foi feito)`),
    h("div", { class: "row" },
      h("button", { type: "button", text: "Salvar quadro", onclick: async () => {
        try {
          const saved = await api(`/api/empresas/${data.empresa.id}/quadro`, { method: "PUT", json: {
            quadro: editor.read().map((stage) => ({ nome: stage.nome, tipo: stage.tipo })), aplicar: apply.checked,
          } });
          notice.textContent = `Quadro salvo${saved.vagas_atualizadas ? `; ${saved.vagas_atualizadas} vaga(s) atualizada(s)` : ""}.`;
          delete box.dataset.company;
          box.hidden = true;
          await renderCompanyBoard();
        } catch (error) {
          notice.textContent = error.message;
        }
      } }),
      h("button", { type: "button", class: "ghost", text: "Voltar ao padrão", onclick: () => {
        openBoardEditor({ ...data, quadro: DEFAULT_BOARD });
      } }),
      h("button", { type: "button", class: "ghost", text: "Fechar", onclick: () => { box.hidden = true; delete box.dataset.company; } }),
      notice,
    ),
  );
}

const DEFAULT_BOARD = [
  { name: "Visualizada", kind: "visualizada" }, { name: "Currículo enviado", kind: "candidatado" },
  { name: "Triagem com RH", kind: "entrevista" }, { name: "Teste técnico", kind: "em_analise" },
  { name: "Entrevista técnica", kind: "entrevista" }, { name: "Entrevista com gestor", kind: "entrevista" },
  { name: "Visita presencial", kind: "entrevista" }, { name: "Proposta", kind: "proposta" },
];

function setupKanbanBoards() {
  const select = document.getElementById("board-pick");
  select.addEventListener("change", () => {
    state.boardCompany = select.value ? Number(select.value) : null;
    const editor = document.getElementById("board-editor");
    editor.hidden = true;
    delete editor.dataset.company;
    renderBoard();
  });
  for (const id of ["board-q", "board-mode"]) {
    document.getElementById(id).addEventListener("input", renderBoard);
  }
  document.getElementById("board-edit").addEventListener("click", async () => {
    openBoardEditor(await api(`/api/empresas/${state.boardCompany}/quadro`));
  });
}

function boardInto(board, jobs, draftJobs) {
  clear(board);
  const pendingByJob = {};
  for (const draft of state.rascunhos) {
    if (draft.job_id) pendingByJob[draft.job_id] = (pendingByJob[draft.job_id] || 0) + 1;
  }
  if (draftJobs) {
    const draftCol = h("section", { class: "col is-draft" },
      h("div", { class: "col-head" }, h("span", { text: "Rascunho" }), h("span", { text: String(draftJobs.length) })),
    );
    for (const draft of draftJobs) {
      draftCol.appendChild(h("button", { type: "button", class: "card is-draft", onclick: () => openDraft(draft) },
        h("strong", { text: draft.payload.title || "Vaga sem título" }),
        h("span", { class: "company", text: draft.payload.company || "" }),
        h("span", { class: "flag", text: " · aprovar" }),
      ));
    }
    board.appendChild(draftCol);
  }
  for (const status of state.status) {
    const own = jobs.filter((job) => job.status === status.chave);
    const col = h("section", { class: "col" + (status.chave === "fria" ? " is-cold" : ""), "data-status": status.chave },
      h("div", { class: "col-head" }, h("span", { text: status.nome }), h("span", { text: String(own.length) })),
    );
    col.addEventListener("dragover", (event) => {
      event.preventDefault();
      col.classList.add("is-over");
    });
    col.addEventListener("dragleave", () => col.classList.remove("is-over"));
    col.addEventListener("drop", async (event) => {
      event.preventDefault();
      col.classList.remove("is-over");
      const id = Number(event.dataTransfer.getData("text/plain"));
      if (!id) return;
      try {
        await api(`/api/vagas/${id}/status`, { method: "PATCH", json: { status: status.chave } });
        await refresh();
      } catch (error) {
        alert(error.message);
      }
    });
    for (const job of own) {
      const idle = idleDays(job.status_at || job.updated_at);
      const fit = fitPercent(job);
      const open = ["candidatado", "em_analise", "entrevista", "proposta"].includes(job.status);
      const card = h("button", { type: "button", class: "card", draggable: "true", onclick: () => openJob(job.id) },
        h("strong", { text: job.title || "Vaga sem título" }),
        h("span", { class: "company", text: job.company || "" }),
        h("span", { class: "when", text: " · " + (job.seniority ? job.seniority + " · " : "") + when(job.status_at) }),
        fit !== null ? h("span", { class: "fit", title: "Skills da vaga que o seu perfil tem", text: ` · encaixe ${fit}%` }) : null,
        pendingByJob[job.id] ? h("span", { class: "flag", text: ` · ${pendingByJob[job.id]} pendente(s)` }) : null,
        open && idle !== null && idle >= Math.ceil(state.diasFria / 2) ? h("span", { class: "cold", text: `sem novidade há ${idle} dias` }) : null,
      );
      card.addEventListener("dragstart", (event) => event.dataTransfer.setData("text/plain", String(job.id)));
      col.appendChild(card);
    }
    board.appendChild(col);
  }
}

// Empresas

async function renderCompanies() {
  const list = document.getElementById("company-list");
  const rows = await api("/api/empresas");
  const query = document.getElementById("company-q").value.trim().toLowerCase();
  const shown = rows.filter((row) => !query
    || [row.name, row.industry, row.headquarters, row.specialties].join(" ").toLowerCase().includes(query));
  clear(list);
  if (!rows.length) {
    list.appendChild(h("p", { class: "empty", text: "Nenhuma empresa ainda. Elas aparecem quando você aprova uma vaga." }));
    return;
  }
  if (!shown.length) list.appendChild(h("p", { class: "empty", text: "Nenhuma empresa com esse filtro." }));
  for (const row of shown) {
    list.appendChild(h("button", { type: "button", class: "company-card", onclick: () => go("empresa/" + row.id) },
      h("h3", { text: row.name }),
      h("p", { class: "hint", text: [row.industry, row.size].filter(Boolean).join(" · ") || "Sem dados públicos ainda" }),
      row.headquarters ? h("p", { class: "hint", text: row.headquarters }) : null,
      h("div", { class: "chips" },
        h("span", { class: "chip is-accent", text: `${row.vagas} vaga(s)` }),
        row.candidaturas ? h("span", { class: "chip is-ok", text: `${row.candidaturas} candidatura(s)` }) : null,
        row.status.includes("fria") ? h("span", { class: "chip", text: "tem vaga fria" }) : null,
      ),
      row.ultima ? h("p", { class: "when", text: "Último movimento " + when(row.ultima) }) : null,
    ));
  }
}

async function renderCompany() {
  const page = document.getElementById("company-page");
  if (!state.companyId) return;
  const detail = await api("/api/empresas/" + state.companyId);
  const company = detail.empresa;
  clear(page);
  const notice = h("p", { class: "notice", role: "status" });
  const refreshButton = h("button", { type: "button", class: "ghost", text: "Atualizar do LinkedIn", disabled: !company.linkedin_url, onclick: async () => {
    refreshButton.disabled = true;
    notice.textContent = "Buscando a página pública da empresa…";
    try {
      await api(`/api/empresas/${company.id}/atualizar`, { method: "POST", json: {} });
      await renderCompany();
    } catch (error) {
      notice.textContent = error.message;
      refreshButton.disabled = false;
    }
  } });
  const facts = [
    ["Setor", company.industry], ["Tamanho", company.size], ["Sede", company.headquarters], ["Especializações", company.specialties],
  ].filter(([, value]) => value);
  page.append(
    h("div", { class: "company-head" },
      h("div", {},
        h("p", { class: "eyebrow" }, h("a", { href: "#empresas", text: "← Empresas" })),
        h("h1", { text: company.name }),
        h("p", { class: "lede", text: company.fetched_at ? "Dados públicos de " + when(company.fetched_at) : "Ainda sem os dados públicos da empresa." }),
      ),
      h("div", { class: "row" },
        company.linkedin_url ? h("a", { class: "file-button", href: company.linkedin_url, target: "_blank", rel: "noopener", text: "Página no LinkedIn ↗" }) : null,
        refreshButton,
      ),
    ),
    notice,
    facts.length ? h("dl", { class: "facts" }, facts.map(([label, value]) => h("div", {}, h("dt", { text: label }), h("dd", { text: value })))) : null,
    company.description ? h("details", {}, h("summary", { text: "Sobre a empresa" }), h("div", { class: "body-text", text: company.description })) : null,
  );

  const rows = h("div", { class: "job-rows" });
  const applied = detail.vagas.filter((job) => job.status !== "visualizada");
  for (const job of detail.vagas) {
    rows.appendChild(h("div", { class: "job-row" },
      h("a", { class: "title", href: "#", text: job.title || "Vaga sem título", onclick: (event) => {
        event.preventDefault();
        openJob(job.id);
      } }),
      h("a", { href: job.url, target: "_blank", rel: "noopener", text: "abrir vaga ↗" }),
      h("div", { class: "meta" },
        h("span", { class: job.status === "fria" ? "chip" : job.status === "visualizada" ? "chip" : "chip is-ok", text: statusName(job.status) }),
        job.applied_at ? h("span", { class: "when", text: "candidatura " + when(job.applied_at) }) : null,
        job.seniority ? h("span", { class: "chip", text: job.seniority }) : null,
        job.work_mode ? h("span", { class: "chip", text: job.work_mode }) : null,
        job.parada_dias !== null && job.parada_dias >= Math.ceil(state.diasFria / 2) && job.status !== "fria"
          ? h("span", { class: "chip is-warn", text: `parada há ${job.parada_dias} dias` }) : null,
      ),
    ));
  }
  page.appendChild(h("section", { class: "section" },
    h("h2", { class: "tab", text: `Vagas (${detail.vagas.length}) · candidaturas (${applied.length})` }),
    detail.vagas.length ? rows : h("p", { class: "empty", text: "Nenhuma vaga salva desta empresa." }),
  ));

  const board = h("div", { class: "board" });
  boardInto(board, detail.vagas, null);
  page.appendChild(h("section", { class: "section" },
    h("h2", { class: "tab", text: "Kanban da empresa" }),
    h("p", { class: "hint", text: "Arraste para mudar o status. Vagas esquecidas ficam em Fria." }),
    board,
  ));

  const notes = h("textarea", { rows: 3, value: company.notes || "", placeholder: "Contatos, impressões, o que pesquisar antes da entrevista" });
  const saved = h("span", { class: "notice" });
  page.appendChild(h("section", { class: "section" },
    h("h2", { class: "tab", text: "Notas sobre a empresa" }),
    notes,
    h("div", { class: "row" },
      h("button", { type: "button", text: "Salvar notas", onclick: async () => {
        await api(`/api/empresas/${company.id}`, { method: "PATCH", json: { notas: notes.value } });
        saved.textContent = "Salvo.";
      } }),
      saved,
    ),
  ));

  const timeline = h("ol", { class: "timeline" });
  if (detail.movimentos.length) appendMoves(timeline, detail.movimentos, { showJob: true });
  else timeline.appendChild(h("li", { class: "empty", text: "Sem movimentos." }));
  page.appendChild(h("section", { class: "section" }, h("h2", { class: "tab", text: "Linha do tempo da empresa" }), timeline));
}

async function renderProfile() {
  const profile = await api("/api/perfil");
  const fields = document.getElementById("profile-fields");
  clear(fields);
  for (const [key, label] of PROFILE_FIELDS) {
    fields.appendChild(h("label", {}, label, h("input", { name: key, value: profile[key] || "" })));
  }
  fields.appendChild(h("p", { class: "hint", style: "grid-column: 1 / -1" },
    "O texto do currículo, os anos por skill e os pontos de melhoria ficam em ", h("a", { href: "#curriculo", text: "Currículo" }), "."));
  const quick = document.getElementById("quick-fields");
  clear(quick);
  for (const [key, label, options] of QUICK_FIELDS) {
    const value = profile[key] || "";
    const input = options
      ? h("select", { name: key }, options.map((option) => h("option", { value: option, text: option || "—", selected: option === value })))
      : h("input", { name: key, value, placeholder: "Vazio: calcula pelo currículo", inputmode: "decimal" });
    quick.appendChild(h("label", {}, label, input));
  }
  // "Presencial" sozinho é de antes da divisão: conta como na cidade atual.
  const convert = h("button", { type: "button", class: "ghost", text: "Completar a outra moeda pela cotação de hoje", onclick: () => fillOtherCurrency(convert) });
  quick.appendChild(h("div", { class: "salary-convert" }, convert, h("span", { class: "hint", id: "salary-rate" })));
  const accepted = (profile.modelos_trabalho || "").split(",").map((item) => (item.trim() === "Presencial" ? "Presencial (na cidade atual)" : item.trim()));
  quick.appendChild(h("fieldset", { class: "modes" },
    h("legend", { text: "Modelos de trabalho que aceita" }),
    WORK_MODES.map((mode) => h("label", { class: "check" }, h("input", { type: "checkbox", "data-mode": mode, checked: accepted.includes(mode) }), mode)),
  ));
  const stories = document.getElementById("stories");
  clear(stories);
  for (const story of profile.historias || []) stories.appendChild(storyRow(story));
  await renderHistory();
}

// Pretensão: preenche o campo vazio convertendo o outro; a pessoa confere e salva.
async function fillOtherCurrency(button) {
  const form = document.getElementById("profile-form");
  const real = form.elements.pretensao_salarial;
  const dollar = form.elements.pretensao_usd;
  const note = document.getElementById("salary-rate");
  const number = (text) => Number(String(text).replace(/[^\d.,]/g, "").replace(/[.,](\d{3})/g, "$1").replace(",", "."));
  button.disabled = true;
  try {
    const { usd_brl: rate } = await api("/api/cotacao");
    if (real.value.trim() && !dollar.value.trim()) dollar.value = `US$ ${Math.round(number(real.value) / rate / 100) * 100}/mês`;
    else if (dollar.value.trim() && !real.value.trim()) real.value = `R$ ${(Math.round(number(dollar.value) * rate / 100) * 100).toLocaleString("pt-BR")}`;
    else {
      note.textContent = "Deixe uma das duas vazia para eu preencher.";
      return;
    }
    note.textContent = `US$ 1 = R$ ${rate.toFixed(2).replace(".", ",")}. Valor arredondado: confira e salve.`;
  } catch (error) {
    note.textContent = error.message;
  } finally {
    button.disabled = false;
  }
}

async function renderHistory() {
  const list = document.getElementById("history-list");
  const rows = await api("/api/extensao/historico");
  clear(list);
  if (!rows.length) list.appendChild(h("li", { class: "empty", text: "Nenhuma resposta guardada ainda. Elas entram quando você aprova uma candidatura ou uma resposta." }));
  for (const row of rows) {
    list.appendChild(h("li", {},
      h("strong", { text: row.rotulo }),
      row.valor,
      h("span", { class: "when", text: ` · ${row.vaga} · ${when(row.quando)}${row.origem === "formulario" ? " · do formulário" : ""}` }),
    ));
  }
}

// Resultados: retorno e conversão por currículo, fonte, senioridade e salário informado

const kpi = { rows: [], filters: { periodo: "365", fonte: "", documento: "", senioridade: "", modelo: "" } };
const PERIODS = [["30", "Últimos 30 dias"], ["90", "Últimos 90 dias"], ["180", "Últimos 6 meses"], ["365", "Último ano"], ["", "Tudo"]];

// "R$ 12.000", "12k", "12 mil" -> 12000. Abaixo de 300 lê como milhares.
function salaryNumber(raw) {
  const text = String(raw || "").toLowerCase().replace(/\s/g, "");
  const match = text.match(/(\d+(?:[.,]\d{3})*(?:[.,]\d+)?)(k|mil)?/);
  if (!match) return null;
  let value = Number(match[1].replace(/[.,](?=\d{3}\b)/g, "").replace(",", "."));
  if (match[2] || value < 300) value *= 1000;
  return Number.isFinite(value) ? value : null;
}

function salaryBand(raw) {
  const value = salaryNumber(raw);
  if (value === null) return "Não informado";
  // Dólar fica à parte: não dá para comparar com as faixas em real.
  if (/us\$|u\$|usd|d[oó]lar|dollar/i.test(raw)) return "Em dólar";
  if (value <= 8000) return "Até R$ 8 mil";
  if (value <= 12000) return "R$ 8–12 mil";
  if (value <= 16000) return "R$ 12–16 mil";
  if (value <= 20000) return "R$ 16–20 mil";
  return "Acima de R$ 20 mil";
}

function kpiFiltered() {
  const { periodo, fonte, documento, senioridade, modelo } = kpi.filters;
  const since = periodo ? Date.now() - Number(periodo) * 86400000 : 0;
  return kpi.rows.filter((row) => {
    const when = Date.parse(row.candidatado_em || "") || 0;
    if (since && when && when < since) return false;
    if (fonte && row.fonte !== fonte) return false;
    if (documento && (row.documentos || "Não registrado") !== documento) return false;
    if (senioridade && (row.senioridade || "Não identificada") !== senioridade) return false;
    if (modelo && (row.modelo || "Não identificado") !== modelo) return false;
    return true;
  });
}

function rate(part, total) {
  return total ? Math.round((part / total) * 100) : 0;
}

function renderKpiFilters() {
  const box = document.getElementById("kpi-filters");
  clear(box);
  const distinct = (key, empty) => [...new Set(kpi.rows.map((row) => row[key] || empty))].sort();
  const control = (key, label, options) => {
    const select = h("select", { "aria-label": label }, options.map(([value, text]) => h("option", { value, text, selected: kpi.filters[key] === value })));
    select.addEventListener("change", () => {
      kpi.filters[key] = select.value;
      renderKpiBody();
    });
    return h("label", {}, label, select);
  };
  const all = (values) => [["", "Todos"], ...values.map((value) => [value, value])];
  box.append(
    control("periodo", "Período", PERIODS),
    control("fonte", "Fonte", all(distinct("fonte", ""))),
    control("documento", "Currículo enviado", all(distinct("documentos", "Não registrado"))),
    control("senioridade", "Senioridade", all(distinct("senioridade", "Não identificada"))),
    control("modelo", "Modelo de trabalho", all(distinct("modelo", "Não identificado"))),
  );
}

function kpiTile(label, value, sub) {
  return h("article", { class: "kpi-tile" }, h("p", { class: "label", text: label }), h("p", { class: "value", text: value }), h("p", { class: "sub", text: sub }));
}

function rateBar(part, total, title) {
  const pct = rate(part, total);
  return h("div", { class: "kpi-bar", title },
    h("span", { class: "track" }, h("span", { class: "fill", style: `width:${pct}%` })),
    h("span", { class: "pct", text: `${pct}%` }),
  );
}

function breakdown(title, rows, keyOf) {
  const groups = new Map();
  for (const row of rows) {
    const key = keyOf(row);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(row);
  }
  const sorted = [...groups].sort((a, b) => b[1].length - a[1].length);
  return h("article", { class: "sheet" },
    h("h2", { class: "tab", text: title }),
    sorted.length
      ? h("table", { class: "cv-table" },
        h("thead", {}, h("tr", {}, ["", "Candid.", "Retorno", "Entrevista", "Proposta"].map((label) => h("th", { text: label })))),
        h("tbody", {}, sorted.map(([key, items]) => {
          const back = items.filter((row) => row.retorno).length;
          const interview = items.filter((row) => row.entrevista).length;
          const offer = items.filter((row) => row.proposta).length;
          return h("tr", {},
            h("td", {}, key, items.length < 5 ? h("span", { class: "kpi-few", text: "poucos dados", title: "Menos de 5 candidaturas: a taxa ainda varia muito" }) : null),
            h("td", { text: String(items.length) }),
            h("td", { class: "kpi-bar-cell" }, rateBar(back, items.length, `${key}: ${back} de ${items.length} tiveram retorno`)),
            h("td", { text: `${rate(interview, items.length)}%`, title: `${interview} de ${items.length}` }),
            h("td", { text: `${rate(offer, items.length)}%`, title: `${offer} de ${items.length}` }),
          );
        })),
      )
      : h("p", { class: "empty", text: "Sem candidaturas no filtro." }),
  );
}

function renderKpiBody() {
  const rows = kpiFiltered();
  const total = rows.length;
  const back = rows.filter((row) => row.retorno).length;
  const interview = rows.filter((row) => row.entrevista).length;
  const offer = rows.filter((row) => row.proposta).length;
  const tiles = document.getElementById("kpi-tiles");
  clear(tiles);
  tiles.append(
    kpiTile("Candidaturas", String(total), `${total - back} ainda sem retorno`),
    kpiTile("Taxa de retorno", `${rate(back, total)}%`, `${back} de ${total} responderam`),
    kpiTile("Chegaram à entrevista", `${rate(interview, total)}%`, `${interview} de ${total}`),
    kpiTile("Propostas", `${rate(offer, total)}%`, `${offer} de ${total}`),
  );
  const grid = document.getElementById("kpi-breakdowns");
  clear(grid);
  grid.append(
    breakdown("Por tipo de currículo", rows, (row) => row.curriculo.tipo || "Não registrado"),
    breakdown("Por currículo enviado", rows, (row) => resumeLabel(row.curriculo)),
    breakdown("Por salário informado", rows, (row) => salaryBand(row.salario_informado)),
    breakdown("Por fonte", rows, (row) => row.fonte || "—"),
    breakdown("Por senioridade", rows, (row) => row.senioridade || "Não identificada"),
  );
  const list = document.getElementById("kpi-list");
  clear(list);
  const statusName = (key) => (state.status.find((item) => item.chave === key) || {}).nome || key;
  list.append(
    h("thead", {}, h("tr", {}, ["Candidatado em", "Vaga", "Empresa", "Fonte", "Currículo enviado", "Salário informado", "Status", "Retorno"].map((label) => h("th", { text: label })))),
    h("tbody", {}, [...rows].sort((a, b) => (b.candidatado_em || "").localeCompare(a.candidatado_em || "")).map((row) => h("tr", {},
      h("td", { text: row.candidatado_em ? when(row.candidatado_em) : "—" }),
      h("td", { class: "wrap" }, h("a", { text: row.titulo || "(sem título)", onclick: () => openJob(row.id) })),
      h("td", { class: "wrap", text: row.empresa }),
      h("td", { text: row.fonte }),
      h("td", { class: "wrap", text: row.curriculo.tipo ? resumeLabel(row.curriculo) : "—" }),
      h("td", { text: row.salario_informado || "—" }),
      h("td", { text: statusName(row.status) }),
      h("td", { text: row.proposta ? "Proposta" : row.entrevista ? "Entrevista" : row.retorno ? "Sim" : "—" }),
    ))),
  );
  if (!rows.length) list.appendChild(h("tbody", {}, h("tr", {}, h("td", { colspan: "8", class: "empty", text: "Nenhuma candidatura no filtro." }))));
}

function resumeLabel(info) {
  return info.tipo ? `${info.tipo}: ${info.nome}` : "Não registrado";
}

async function renderResultados() {
  kpi.rows = await api("/api/resultados");
  renderKpiFilters();
  renderKpiBody();
}

// Bolinha de status: ligação com o JobScout (SSE) + saúde das ferramentas ligadas.
const health = { connected: false, data: null };

function renderLive() {
  const items = health.data ? health.data.itens : [];
  const warn = health.data && health.data.geral === "aviso";
  const lines = [health.connected ? "JobScout: conectado (atualiza na hora)" : "JobScout: sem ligação, tentando de novo…"]
    .concat(items.map((item) => `${item.estado === "ok" ? "●" : item.estado === "aviso" ? "▲" : "○"} ${item.nome}: ${item.detalhe}`));
  for (const node of [document.getElementById("live"), document.getElementById("overlay-live")]) {
    node.classList.toggle("is-on", health.connected && !warn);
    node.classList.toggle("is-warn", health.connected && warn);
    node.title = lines.join("\n");
    node.setAttribute("aria-label", lines.join(". "));
    node.textContent = "";
  }
}

async function loadHealth() {
  try {
    health.data = await api("/api/saude");
  } catch (error) {
    health.data = null;
  }
  renderLive();
}

// Currículo completo: editor por seções. A estrutura é a fonte; o texto que as sugestões leem sai dela.

const cvx = { data: null, profile: {}, versions: [], current: null, dirty: false };

function cvxEmpty() {
  return { titulo: "", resumo: "", experiencias: [], formacao: [], habilidades: [], idiomas: [], certificacoes: [], projetos: [] };
}

function bind(input, read, write) {
  input.value = read() ?? "";
  input.addEventListener("input", () => {
    write(input.type === "checkbox" ? input.checked : input.value);
    cvx.dirty = true;
  });
  return input;
}

function cvxSection(title, body, addLabel, onAdd) {
  return h("section", { class: "cvx-section sheet" },
    h("h2", { class: "tab" }, title, onAdd ? h("button", { type: "button", class: "ghost", text: addLabel, onclick: () => { onAdd(); cvx.dirty = true; renderCvx(); } }) : null),
    body,
  );
}

function moveItem(list, index, step) {
  const target = index + step;
  if (target < 0 || target >= list.length) return;
  [list[index], list[target]] = [list[target], list[index]];
  cvx.dirty = true;
  renderCvx();
}

function removeItem(list, index) {
  list.splice(index, 1);
  cvx.dirty = true;
  renderCvx();
}

function cvxTools(list, index) {
  return h("div", { class: "cvx-tools" },
    h("button", { type: "button", class: "ghost", text: "↑", title: "Subir", onclick: () => moveItem(list, index, -1) }),
    h("button", { type: "button", class: "ghost", text: "↓", title: "Descer", onclick: () => moveItem(list, index, 1) }),
    h("button", { type: "button", class: "danger", text: "Remover", onclick: () => removeItem(list, index) }),
  );
}

function renderCvx() {
  const box = document.getElementById("cvx");
  const data = cvx.data;
  clear(box);
  const p = cvx.profile;
  const contact = [p.email, p.telefone, [p.cidade, p.estado, p.pais].filter(Boolean).join(", "), p.linkedin, p.github].filter(Boolean).join(" · ");
  box.appendChild(cvxSection("Cabeçalho", h("div", {},
    h("p", {}, h("strong", { text: p.nome || "Seu nome (preencha no Perfil)" }), h("span", { class: "hint", text: contact ? " · " + contact : " · contato vem do Perfil" })),
    h("label", {}, "Título profissional", bind(h("input", { placeholder: "Ex.: Engenheira de Dados Sênior" }), () => data.titulo, (v) => { data.titulo = v; })),
    h("label", {}, "Resumo", bind(h("textarea", { rows: 4, placeholder: "2 a 4 frases: o que você faz, em que contexto e com que resultado." }), () => data.resumo, (v) => { data.resumo = v; })),
  )));

  const skillInput = h("input", { placeholder: "Nova habilidade e Enter", "aria-label": "Nova habilidade" });
  skillInput.addEventListener("keydown", (event) => {
    if (event.key !== "Enter") return;
    event.preventDefault();
    const name = skillInput.value.trim();
    if (name && !data.habilidades.some((skill) => skill.nome.toLowerCase() === name.toLowerCase())) data.habilidades.push({ nome: name, principal: true });
    cvx.dirty = true;
    renderCvx();
    document.querySelector("#cvx input[aria-label='Nova habilidade']").focus();
  });
  box.appendChild(cvxSection("Principais habilidades", h("div", {},
    h("p", { class: "hint", text: "★ marca as principais: elas vão para o topo do PDF e de cada versão. As que combinam com a vaga sobem sozinhas nas versões." }),
    h("div", { class: "cvx-skills" }, data.habilidades.map((skill, index) => h("span", { class: "cvx-skill" + (skill.principal ? " is-key" : "") },
      skill.nome,
      h("button", { type: "button", title: skill.principal ? "Tirar das principais" : "Marcar como principal", text: skill.principal ? "★" : "☆", onclick: () => { skill.principal = !skill.principal; cvx.dirty = true; renderCvx(); } }),
      h("button", { type: "button", title: "Remover", text: "×", onclick: () => removeItem(data.habilidades, index) }),
    ))),
    skillInput,
  )));

  box.appendChild(cvxSection("Experiência", h("div", {}, data.experiencias.map((role, index) => {
    const items = h("div", {}, role.itens.map((item, itemIndex) => h("div", { class: "cvx-item" },
      bind(h("textarea", { rows: 2, placeholder: "O que você fez, com ferramenta e resultado (ex.: Reduzi 30% do custo com Airflow e BigQuery)" }), () => item, (v) => { role.itens[itemIndex] = v; }),
      h("button", { type: "button", class: "ghost", text: "×", title: "Remover item", onclick: () => removeItem(role.itens, itemIndex) }),
      h("button", { type: "button", class: "ghost cvx-ai", text: "✨ Melhorar", title: "Pedir à IA uma versão melhor deste item", onclick: (event) => improveItem(event.currentTarget, role, itemIndex) }),
    )));
    role.habilidades = role.habilidades || [];
    role.clientes = role.clientes || [];
    const roleSkill = h("input", { placeholder: "Habilidade usada aqui e Enter", "aria-label": "Habilidade desta experiência", list: "cvx-skill-names" });
    roleSkill.addEventListener("keydown", (event) => {
      if (event.key !== "Enter") return;
      event.preventDefault();
      const name = roleSkill.value.trim();
      if (name && !role.habilidades.some((skill) => skill.toLowerCase() === name.toLowerCase())) role.habilidades.push(name);
      cvx.dirty = true;
      renderCvx();
    });
    const clients = h("div", {}, role.clientes.map((client, clientIndex) => h("div", { class: "cvx-row" },
      h("label", {}, "Empresa atendida", bind(h("input"), () => client.nome, (v) => { client.nome = v; })),
      h("label", {}, "Início", bind(h("input", { type: "month" }), () => client.inicio, (v) => { client.inicio = v; })),
      h("label", {}, "Fim", bind(h("input", { type: "month" }), () => client.fim, (v) => { client.fim = v; })),
      h("label", {}, "O que fez lá", bind(h("input", { placeholder: "Opcional" }), () => client.descricao, (v) => { client.descricao = v; })),
      h("button", { type: "button", class: "ghost", text: "×", title: "Remover", onclick: () => removeItem(role.clientes, clientIndex) }),
    )));
    return h("div", { class: "cvx-card" },
      cvxTools(data.experiencias, index),
      h("div", { class: "grid" },
        h("label", {}, "Cargo", bind(h("input"), () => role.cargo, (v) => { role.cargo = v; })),
        h("label", {}, "Empresa", bind(h("input"), () => role.empresa, (v) => { role.empresa = v; })),
        h("label", {}, "Local", bind(h("input", { placeholder: "Opcional" }), () => role.local, (v) => { role.local = v; })),
        h("label", {}, "Início", bind(h("input", { type: "month" }), () => role.inicio, (v) => { role.inicio = v; })),
        h("label", {}, "Fim", bind(h("input", { type: "month", disabled: role.atual }), () => role.fim, (v) => { role.fim = v; })),
        h("label", { class: "check" }, bind(h("input", { type: "checkbox", checked: role.atual }), () => undefined, (v) => { role.atual = v; if (v) role.fim = ""; renderCvx(); }), "Trabalho aqui atualmente"),
      ),
      items,
      h("button", { type: "button", class: "ghost", text: "+ Item", onclick: () => { role.itens.push(""); cvx.dirty = true; renderCvx(); } }),
      h("h3", { class: "tab", text: "Habilidades destacadas nesta experiência" }),
      h("div", { class: "cvx-skills" }, role.habilidades.map((skill, skillIndex) => h("span", { class: "cvx-skill is-key" }, skill,
        h("button", { type: "button", title: "Remover", text: "×", onclick: () => removeItem(role.habilidades, skillIndex) })))),
      roleSkill,
      h("h3", { class: "tab", text: "Consultoria: empresas onde esteve" }),
      clients,
      h("button", { type: "button", class: "ghost", text: "+ Empresa atendida", onclick: () => { role.clientes.push({ nome: "", inicio: "", fim: "", descricao: "" }); cvx.dirty = true; renderCvx(); } }),
    );
  })), "+ Experiência", () => data.experiencias.unshift({ cargo: "", empresa: "", local: "", inicio: "", fim: "", atual: false, itens: [""], habilidades: [], clientes: [] })));
  box.appendChild(h("datalist", { id: "cvx-skill-names" }, data.habilidades.map((skill) => h("option", { value: skill.nome }))));
  box.appendChild(skillCheckSection());

  const simple = (title, key, fields, blank) => cvxSection(title, h("div", {}, data[key].map((row, index) => h("div", { class: "cvx-row" },
    fields.map(([field, label, attrs]) => h("label", {}, label, field === "nivel" && key === "idiomas"
      ? bind(h("select", {}, [...new Set([...LEVELS, row[field] || ""])].map((level) => h("option", { value: level, text: level || "—" }))), () => row[field], (v) => { row[field] = v; })
      : bind(h("input", attrs || {}), () => row[field], (v) => { row[field] = v; }))),
    h("button", { type: "button", class: "ghost", text: "×", title: "Remover", onclick: () => removeItem(data[key], index) }),
  ))), "+ Adicionar", () => data[key].push({ ...blank }));
  const education = (title, tipo, placeholder) => cvxSection(title, h("div", {}, data.formacao.map((row, index) => (((row.tipo || "graduacao") === tipo) ? h("div", { class: "cvx-row" },
    h("label", {}, "Curso", bind(h("input", { placeholder }), () => row.curso, (v) => { row.curso = v; })),
    h("label", {}, "Instituição", bind(h("input"), () => row.instituicao, (v) => { row.instituicao = v; })),
    h("label", {}, "Início", bind(h("input", { type: "month" }), () => row.inicio, (v) => { row.inicio = v; })),
    h("label", {}, "Fim", bind(h("input", { type: "month" }), () => row.fim, (v) => { row.fim = v; })),
    h("button", { type: "button", class: "ghost", text: "×", title: "Remover", onclick: () => removeItem(data.formacao, index) }),
  ) : null))), "+ Adicionar", () => data.formacao.push({ curso: "", instituicao: "", inicio: "", fim: "", tipo }));
  box.appendChild(education("Graduação", "graduacao", "Ex.: Bacharelado em Sistemas de Informação"));
  box.appendChild(education("Pós-graduação", "pos", "Ex.: MBA em Engenharia de Dados"));
  box.appendChild(simple("Idiomas", "idiomas", [["idioma", "Idioma"], ["nivel", "Nível"]], { idioma: "", nivel: "" }));
  box.appendChild(simple("Certificações", "certificacoes", [["nome", "Nome"], ["emissor", "Emissor"], ["ano", "Ano", { inputmode: "numeric", maxlength: "4" }]], { nome: "", emissor: "", ano: "" }));
  box.appendChild(simple("Projetos", "projetos", [["nome", "Nome"], ["descricao", "Descrição"], ["link", "Link"]], { nome: "", descricao: "", link: "" }));
}

// IA sugere uma versão melhor do item; a pessoa decide se usa.
async function improveItem(button, role, index) {
  const row = button.closest(".cvx-item");
  const old = row.querySelector(".cvx-ai-out");
  if (old) old.remove();
  const out = h("div", { class: "cvx-ai-out" }, h("span", { class: "hint", text: "A IA está reescrevendo o item…" }));
  row.appendChild(out);
  button.disabled = true;
  try {
    const result = await api("/api/curriculo/melhorar-item", { method: "POST", json: {
      item: role.itens[index], experiencia: role,
    } });
    clear(out);
    if (!result.texto) {
      out.appendChild(h("span", { class: "hint", text: result.motivo }));
      return;
    }
    out.append(
      h("p", { class: "cvx-ai-text", text: result.texto }),
      result.motivo ? h("p", { class: "hint", text: `${result.motivo} · ${result.modelo}` }) : null,
      h("div", { class: "row" },
        h("button", { type: "button", text: "Usar", onclick: () => { role.itens[index] = result.texto; cvx.dirty = true; renderCvx(); } }),
        h("button", { type: "button", class: "ghost", text: "Agora não", onclick: () => out.remove() }),
      ),
    );
  } catch (error) {
    clear(out);
    out.appendChild(h("span", { class: "notice", text: error.message }));
  } finally {
    button.disabled = false;
  }
}

function skillCheckSection() {
  const out = h("div", { id: "cvx-check" });
  const run = async () => {
    const result = await api("/api/curriculo/conferir", { method: "POST", json: { cv: cvx.data } });
    clear(out);
    const roles = cvx.data.experiencias.filter((role) => role.cargo || role.empresa);
    const missing = result.fora_do_perfil.map((entry) => h("li", {},
      h("strong", { text: entry.nome }), h("span", { class: "hint", text: ` · ${entry.experiencias.join("; ")}` }), " ",
      h("button", { type: "button", class: "ghost", text: "+ Perfil", onclick: () => {
        cvx.data.habilidades.push({ nome: entry.nome, principal: false });
        cvx.dirty = true;
        renderCvx();
      } }),
    ));
    const unused = result.fora_das_experiencias.map((name) => {
      const pick = h("select", { "aria-label": `Citar ${name} em qual experiência` }, h("option", { value: "", text: "Citar em…" }),
        roles.map((role, index) => h("option", { value: String(index), text: [role.cargo, role.empresa].filter(Boolean).join(" — ") })));
      pick.addEventListener("change", () => {
        const role = roles[Number(pick.value)];
        role.habilidades = [...(role.habilidades || []), name];
        cvx.dirty = true;
        renderCvx();
      });
      return h("li", {}, h("strong", { text: name }), " ", pick);
    });
    out.append(
      h("h3", { class: "tab", text: `Nas experiências, mas não no perfil (${missing.length})` }),
      missing.length ? h("ul", { class: "cvx-check" }, missing) : h("p", { class: "hint", text: "Nenhuma: tudo o que aparece nas experiências está nas habilidades." }),
      h("h3", { class: "tab", text: `No perfil, mas em nenhuma experiência (${unused.length})` }),
      unused.length ? h("ul", { class: "cvx-check" }, unused) : h("p", { class: "hint", text: "Nenhuma: toda habilidade tem uma experiência que a comprova." }),
    );
  };
  return cvxSection("Conferir habilidades", h("div", {},
    h("p", { class: "hint", text: "Compara as habilidades destacadas e citadas nas experiências com as Principais habilidades. Usa o que está na tela, mesmo sem salvar." }),
    h("button", { type: "button", class: "ghost", text: "Conferir agora", onclick: () => run().catch((error) => { out.textContent = error.message; }) }),
    out,
  ));
}

async function loadCvx(force = false) {
  // Atualização automática não redesenha o editor no meio da edição.
  if (!force && (cvx.dirty || document.getElementById("cvx").contains(document.activeElement))) return;
  const result = await api("/api/curriculo/completo");
  cvx.profile = result.perfil;
  cvx.versions = result.versoes;
  cvx.data = result.cv || result.sugerido || cvxEmpty();
  cvx.dirty = false;
  const banner = document.getElementById("cvx-banner");
  banner.hidden = Boolean(result.cv);
  banner.textContent = result.cv ? "" : "Montei esta primeira versão a partir do texto do seu currículo. Revise, complete e clique em Salvar currículo completo.";
  renderCvx();
  renderVersions();
}

function openLocal(path) {
  const win = bridge();
  const url = location.origin + path;
  if (win) win.abrir_link(url);
  else window.open(url, "_blank", "noopener");
}

async function exportPdf(versionId, notice) {
  notice.textContent = "Gerando o PDF…";
  try {
    const result = await api("/api/curriculo/pdf", { method: "POST", json: { versao: versionId || 0 } });
    clear(notice);
    notice.append(`PDF salvo: ${result.nome} `, h("button", { type: "button", class: "ghost", text: "Abrir PDF", onclick: () => openInFolder({ arquivo: result.arquivo }, notice) }));
  } catch (error) {
    notice.textContent = error.message;
  }
}

// Versões por vaga

function renderVersions() {
  const select = document.getElementById("cvv-job");
  const chosen = select.value;
  clear(select);
  const jobs = state.vagas.filter((job) => job.title || job.company);
  select.appendChild(h("option", { value: "", text: jobs.length ? "Escolha a vaga" : "Nenhuma vaga salva ainda" }));
  for (const job of jobs) select.appendChild(h("option", { value: String(job.id), text: `${job.title || "(sem título)"} — ${job.company || ""}`, selected: String(job.id) === chosen }));
  const list = document.getElementById("cvv-list");
  clear(list);
  if (!cvx.versions.length) list.appendChild(h("li", { class: "empty", text: "Nenhuma versão ainda." }));
  for (const version of cvx.versions) {
    list.appendChild(h("li", {}, h("button", { type: "button", class: cvx.current && cvx.current.id === version.id ? "is-on" : "", onclick: () => openVersion(version.id) },
      version.name,
      h("small", { text: `${version.job_id ? version.job_title || "vaga removida" : "Modelo padrão"} · ${when(version.updated_at)}${version.pdf ? " · PDF" : ""}` }),
    )));
  }
}

async function openVersion(id) {
  cvx.current = await api(`/api/curriculo/versoes/${id}`);
  renderVersions();
  renderVersionEditor();
}

function renderVersionEditor() {
  const box = document.getElementById("cvv-editor");
  clear(box);
  const version = cvx.current;
  if (!version) {
    box.appendChild(h("p", { class: "hint", text: "Escolha uma versão à esquerda ou gere uma nova para uma vaga." }));
    return;
  }
  const data = version.data;
  const target = data.alvo || {};
  const notice = h("p", { class: "notice", role: "status" });
  const name = h("input", { value: version.name, "aria-label": "Nome da versão" });
  const lang = h("select", { "aria-label": "Idioma das seções" }, [["pt", "Seções em português"], ["en", "Seções em inglês"], ["es", "Seções em espanhol"]].map(([value, text]) => h("option", { value, text, selected: value === version.lang })));
  const summary = h("textarea", { rows: 4, value: data.resumo || "" });
  summary.addEventListener("input", () => { data.resumo = summary.value; });
  const skills = h("div", { class: "cvx-skills" }, (data.habilidades || []).map((skill) => {
    const box2 = h("input", { type: "checkbox", checked: skill.mostrar !== false });
    box2.addEventListener("change", () => { skill.mostrar = box2.checked; });
    return h("label", { class: "cvx-skill" + (skill.vaga ? " is-key" : ""), title: skill.vaga ? "Pedida na vaga" : "" }, box2, skill.nome);
  }));
  const roles = (data.experiencias || []).map((role) => h("div", { class: "cvx-card" },
    h("strong", { text: `${role.cargo}${role.empresa ? " — " + role.empresa : ""}` }),
    (role.itens || []).map((item, index) => {
      const keep = h("input", { type: "checkbox", checked: (role.mostrar_itens || [])[index] !== false });
      keep.addEventListener("change", () => {
        role.mostrar_itens = role.mostrar_itens || role.itens.map(() => true);
        role.mostrar_itens[index] = keep.checked;
      });
      return h("label", { class: "cvv-check" + ((role.destaques || [])[index] ? " is-match" : "") }, keep, item);
    }),
  ));
  const save = async () => {
    const saved = await api(`/api/curriculo/versoes/${version.id}`, { method: "PUT", json: { dados: data, nome: name.value, idioma: lang.value } });
    cvx.current = saved;
    const fresh = await api("/api/curriculo/completo");
    cvx.versions = fresh.versoes;
    renderVersions();
    return saved;
  };
  box.append(
    h("div", { class: "sheet" },
      h("div", { class: "row" }, name, lang),
      h("p", { class: "cvv-meta", text: `Para: ${target.vaga || "—"}` }),
      target.skills_da_vaga ? h("p", { class: "cvv-meta" },
        "Combina: ", h("strong", { text: (target.combinam || []).join(", ") || "nada" }),
        (target.faltam || []).length ? ` · A vaga pede e o currículo não mostra: ${target.faltam.join(", ")}` : "") : null,
      h("h3", { class: "tab", text: "Resumo" + (target.resumo_por ? ` (reescrito por ${target.resumo_por})` : "") }),
      summary,
      h("h3", { class: "tab", text: "Habilidades (marcadas vão para o PDF; em azul, pedidas na vaga)" }),
      skills,
      h("h3", { class: "tab", text: "Itens de experiência (em negrito, os que combinam com a vaga)" }),
      roles,
      h("div", { class: "row cvx-actions" },
        h("button", { type: "button", text: "Salvar versão", onclick: async () => { await save(); notice.textContent = "Versão salva."; } }),
        h("button", { type: "button", class: "ghost", text: "Prévia", onclick: async () => { await save(); openLocal(`/api/curriculo/previa?versao=${version.id}`); } }),
        h("button", { type: "button", class: "ghost", text: "Exportar PDF", onclick: async () => { await save(); await exportPdf(version.id, notice); } }),
        h("button", { type: "button", class: "danger", text: "Remover versão", onclick: async () => {
          if (!(await ask("Remover esta versão?", "O currículo completo não muda.", "Remover"))) return;
          await api(`/api/curriculo/versoes/${version.id}/remover`, { method: "POST", json: {} });
          cvx.current = null;
          await loadCvx(true);
          renderVersionEditor();
        } }),
      ),
      notice,
    ),
  );
}

async function saveCvx() {
  const notice = document.getElementById("cvx-notice");
  try {
    const result = await api("/api/curriculo/completo", { method: "PUT", json: { cv: cvx.data } });
    cvx.data = result.cv;
    cvx.dirty = false;
    document.getElementById("cvx-banner").hidden = true;
    notice.textContent = "Currículo completo salvo. O texto e os anos por skill foram atualizados.";
    renderCvx();
    await renderCurriculo();
    return true;
  } catch (error) {
    notice.textContent = error.message;
    return false;
  }
}

function setupCvx() {
  for (const tab of document.querySelectorAll("[data-cvtab]")) {
    tab.addEventListener("click", () => {
      for (const other of document.querySelectorAll("[data-cvtab]")) other.classList.toggle("is-on", other === tab);
      for (const panel of document.querySelectorAll("[data-cvpanel]")) panel.hidden = panel.dataset.cvpanel !== tab.dataset.cvtab;
      if (tab.dataset.cvtab === "versoes") renderVersionEditor();
    });
  }
  const notice = document.getElementById("cvx-notice");
  document.getElementById("cvx-save").addEventListener("click", saveCvx);
  document.getElementById("cvx-preview").addEventListener("click", () => {
    if (cvx.dirty) notice.textContent = "A prévia mostra o que está salvo. Salve antes para ver as mudanças.";
    openLocal("/api/curriculo/previa");
  });
  document.getElementById("cvx-pdf").addEventListener("click", async () => {
    if (cvx.dirty) {
      notice.textContent = "Salve o currículo completo antes de exportar.";
      return;
    }
    await exportPdf(0, notice);
  });
  document.getElementById("cvx-from-text").addEventListener("click", async () => {
    if (!(await ask("Montar o currículo completo a partir do texto?", "O editor completo é substituído pelo que eu conseguir ler do texto (aba Texto). Você revisa antes de salvar.", "Montar"))) return;
    cvx.data = await api("/api/curriculo/completo/do-texto", { method: "POST", json: { texto: document.getElementById("cv-text").value } });
    cvx.dirty = true;
    notice.textContent = "Montado a partir do texto. Revise e salve.";
    renderCvx();
  });
  document.getElementById("cvv-model-new").addEventListener("click", async () => {
    const input = document.getElementById("cvv-model");
    const cvvNotice = document.getElementById("cvv-notice");
    try {
      const created = await api("/api/curriculo/versoes", { method: "POST", json: { modelo: input.value } });
      input.value = "";
      await loadCvx(true);
      await openVersion(created.id);
      cvvNotice.textContent = `Modelo “${created.name}” criado. Ajuste e exporte o PDF.`;
    } catch (error) {
      cvvNotice.textContent = error.message;
    }
  });
  document.getElementById("cvv-create").addEventListener("click", async () => {
    const select = document.getElementById("cvv-job");
    const cvvNotice = document.getElementById("cvv-notice");
    if (!select.value) {
      cvvNotice.textContent = "Escolha uma vaga.";
      return;
    }
    cvvNotice.textContent = document.getElementById("cvv-ai").checked ? "Gerando a versão… a IA leva alguns segundos." : "Gerando a versão…";
    try {
      const version = await api("/api/curriculo/versoes", { method: "POST", json: { vaga_id: Number(select.value), ia: document.getElementById("cvv-ai").checked } });
      cvvNotice.textContent = version.aviso || "Versão criada. Ajuste o que entra e exporte.";
      cvx.versions = (await api("/api/curriculo/completo")).versoes;
      await openVersion(version.id);
    } catch (error) {
      cvvNotice.textContent = error.message;
    }
  });
}

// Mensagens a recrutador

const CHANNELS = [["whatsapp", "WhatsApp"], ["linkedin", "LinkedIn"], ["email", "E-mail"]];

// Modelos de mensagem e recrutadores (aba Mensagens) e o vínculo vaga ⇄ recrutador(a)

const msgState = { models: [], contacts: [], styleChannel: "chat", presetJob: null, presetIntent: null };

function renderIntentChips() {
  const box = document.getElementById("msg-intents");
  // Vindo de um lembrete ("Cobrar retorno"), a intenção já chega escolhida.
  const chosen = msgState.presetIntent || (box.querySelector("input:checked") || {}).value;
  msgState.presetIntent = null;
  for (const node of [...box.querySelectorAll("label")]) node.remove();
  const active = msgState.models.filter((model) => model.ativo);
  active.forEach((model, index) => box.appendChild(h("label", { title: model.instrucao },
    h("input", { type: "radio", name: "intencao", value: model.chave, checked: chosen ? chosen === model.chave : index === 0 }), model.nome)));
}

function renderMsgModels() {
  const box = document.getElementById("msg-models");
  if (box.contains(document.activeElement)) return;
  const open = new Set([...box.querySelectorAll("details[open]")].map((node) => node.dataset.key));
  clear(box);
  for (const model of msgState.models) {
    const name = h("input", { value: model.nome });
    const instruction = h("textarea", { rows: 3, value: model.instrucao, placeholder: "O que a IA deve fazer nesta intenção" });
    const pt = h("textarea", { rows: 3, value: model.pt, placeholder: "Texto pronto em português" });
    const en = h("textarea", { rows: 3, value: model.en, placeholder: "Texto pronto em inglês (opcional)" });
    const active = h("input", { type: "checkbox", checked: model.ativo });
    const notice = h("span", { class: "notice" });
    const save = async () => {
      try {
        await api(`/api/mensagens/modelos/${model.chave}`, { method: "PUT", json: { nome: name.value, instrucao: instruction.value, pt: pt.value, en: en.value, ativo: active.checked } });
        notice.textContent = "Salvo.";
        document.activeElement.blur();
        await loadMsgModels();
      } catch (error) {
        notice.textContent = error.message;
      }
    };
    active.addEventListener("change", save);
    box.appendChild(h("details", { class: "msg-model", "data-key": model.chave, open: open.has(model.chave) },
      h("summary", {}, model.nome,
        !model.ativo ? h("span", { class: "chip", text: "desligado" }) : null,
        model.padrao ? (model.editado ? h("span", { class: "chip", text: "padrão editado" }) : h("span", { class: "chip", text: "padrão" })) : h("span", { class: "chip is-accent", text: "seu" })),
      h("label", { class: "check" }, active, "Aparece nas opções (app e barra do chat)"),
      h("label", {}, "Nome", name),
      h("label", {}, "Instrução para a IA", instruction),
      h("label", {}, "Texto pronto — português", pt),
      h("label", {}, "Texto pronto — inglês", en),
      h("div", { class: "row" },
        h("button", { type: "button", text: "Salvar", onclick: save }),
        h("button", { type: "button", class: "ghost", text: model.padrao ? "Restaurar padrão" : "Remover", onclick: async () => {
          if (!(await ask(model.padrao ? `Restaurar “${model.nome}”?` : `Remover “${model.nome}”?`, model.padrao ? "Volta ao texto e à instrução originais." : "O modelo sai das opções.", model.padrao ? "Restaurar" : "Remover"))) return;
          await api(`/api/mensagens/modelos/${model.chave}/restaurar`, { method: "POST", json: {} });
          await loadMsgModels();
        } }),
        notice,
      ),
    ));
  }
}

async function loadMsgModels() {
  msgState.models = await api("/api/mensagens/modelos");
  renderIntentChips();
  renderMsgModels();
  renderMsgStyle(await api(`/api/mensagens/estilo?canal=${msgState.styleChannel}`));
}

function renderMsgStyle(style) {
  const text = document.getElementById("msg-style-text");
  if (document.activeElement !== text) text.value = style.texto;
  text.maxLength = style.limite;
  const where = style.canal === "email" ? "E-mail" : "WhatsApp e LinkedIn";
  document.getElementById("msg-style-state").textContent = `· ${where}: ${style.padrao ? "padrão do JobScout" : "editado por você"}`;
}

function setupMsgStyle() {
  const text = document.getElementById("msg-style-text");
  const notice = document.getElementById("msg-style-notice");
  msgState.styleChannel = "chat";
  for (const tab of document.querySelectorAll("[data-style-channel]")) {
    tab.addEventListener("click", async () => {
      msgState.styleChannel = tab.dataset.styleChannel;
      for (const other of document.querySelectorAll("[data-style-channel]")) other.classList.toggle("is-on", other === tab);
      notice.textContent = "";
      text.blur();
      renderMsgStyle(await api(`/api/mensagens/estilo?canal=${msgState.styleChannel}`));
    });
  }
  document.getElementById("msg-style-save").addEventListener("click", async () => {
    try {
      const saved = await api(`/api/mensagens/estilo?canal=${msgState.styleChannel}`, { method: "PUT", json: { texto: text.value } });
      text.blur();
      renderMsgStyle(saved);
      notice.textContent = "Estilo salvo. Vale para a próxima resposta.";
    } catch (error) {
      notice.textContent = error.message;
    }
  });
  document.getElementById("msg-style-restore").addEventListener("click", async () => {
    if (!(await ask("Restaurar o estilo padrão?", "O texto que você editou é substituído pelo padrão do JobScout.", "Restaurar"))) return;
    text.blur();
    renderMsgStyle(await api(`/api/mensagens/estilo/restaurar?canal=${msgState.styleChannel}`, { method: "POST", json: {} }));
    notice.textContent = "Estilo padrão restaurado.";
  });
}

function contactForm(contact, onSaved) {
  const fields = [["nome", "Nome", contact.name], ["empresa", "Empresa", contact.company], ["email", "E-mail", contact.email], ["linkedin", "LinkedIn", contact.linkedin], ["telefone", "WhatsApp / telefone", contact.phone], ["cargo", "Cargo", contact.role]];
  const inputs = Object.fromEntries(fields.map(([key, , value]) => [key, h("input", { value: value || "" })]));
  const notes = h("textarea", { rows: 2, value: contact.notes || "", placeholder: "Notas (como chegou, combinados, próximos passos)" });
  const notice = h("span", { class: "notice" });
  return h("form", { class: "profile", onsubmit: async (event) => {
    event.preventDefault();
    const data = Object.fromEntries(Object.entries(inputs).map(([key, input]) => [key, input.value]));
    data.notas = notes.value;
    try {
      if (contact.id) await api(`/api/recrutadores/${contact.id}`, { method: "PATCH", json: data });
      else await api(contact.vaga_id ? `/api/vagas/${contact.vaga_id}/recrutadores` : "/api/recrutadores", { method: "POST", json: contact.vaga_id ? { novo: data } : data });
      notice.textContent = "Salvo.";
      await onSaved();
    } catch (error) {
      notice.textContent = error.message;
    }
  } },
    h("div", { class: "grid" }, fields.map(([key, label]) => h("label", {}, label, inputs[key]))),
    notes,
    h("div", { class: "row" }, h("button", { type: "submit", text: contact.id ? "Salvar" : "Cadastrar" }), notice),
  );
}

function jobLabel(job) {
  return `${job.title || job.titulo || "(sem título)"} — ${job.company || job.empresa || ""}`;
}

function renderRecruiters() {
  const box = document.getElementById("recruiters");
  if (box.contains(document.activeElement)) return;
  clear(box);
  if (!msgState.contacts.length) box.appendChild(h("p", { class: "empty", text: "Nenhum(a) recrutador(a) ainda." }));
  for (const contact of msgState.contacts) {
    const linkSelect = h("select", { "aria-label": "Vincular vaga" }, h("option", { value: "", text: "Vincular a uma vaga…" }),
      state.vagas.filter((job) => (job.title || job.company) && !contact.vagas.some((linked) => linked.id === job.id)).map((job) => h("option", { value: String(job.id), text: jobLabel(job) })));
    linkSelect.addEventListener("change", async () => {
      if (!linkSelect.value) return;
      await api(`/api/vagas/${linkSelect.value}/recrutadores`, { method: "POST", json: { contato_id: contact.id } });
      await loadContacts();
    });
    box.appendChild(h("article", { class: "recruiter" },
      h("span", { class: "who", text: contact.name || contact.email || "(sem nome)" }),
      h("span", { class: "facts", text: [contact.role, contact.company, contact.email, contact.phone, contact.linkedin].filter(Boolean).join(" · ") || "Sem dados de contato" }),
      h("div", { class: "linked-jobs" }, contact.vagas.length
        ? contact.vagas.map((job) => h("span", { class: "chip" },
          h("a", { href: "#", text: jobLabel(job), onclick: (event) => { event.preventDefault(); openJob(job.id); } }),
          h("button", { type: "button", text: "×", title: "Desvincular", onclick: async () => {
            await api(`/api/vagas/${job.id}/recrutadores/${contact.id}/remover`, { method: "POST", json: {} });
            await loadContacts();
          } })))
        : h("span", { class: "hint", text: "Nenhuma vaga vinculada." })),
      linkSelect,
      h("details", {}, h("summary", { text: "Editar" }), contactForm(contact, loadContacts)),
    ));
  }
  const select = document.getElementById("msg-contact");
  const chosen = select.value;
  clear(select);
  select.appendChild(h("option", { value: "", text: "Nenhum" }));
  for (const contact of msgState.contacts) select.appendChild(h("option", { value: String(contact.id), text: contact.name || contact.email, selected: String(contact.id) === chosen }));
}

async function loadContacts() {
  msgState.contacts = await api("/api/recrutadores");
  renderRecruiters();
}

// Detalhe da vaga: quem é o contato desta vaga
function recruitersSection(job, contacts) {
  const section = h("section", {}, h("h3", { class: "tab", text: "Recrutador(a)" }));
  const list = h("div", { class: "linked-jobs" }, contacts.length
    ? contacts.map((contact) => h("span", { class: "chip" }, contact.name || contact.email,
      contact.email || contact.phone ? h("span", { class: "hint", text: " · " + (contact.email || contact.phone) }) : null,
      h("button", { type: "button", text: "×", title: "Desvincular", onclick: async () => {
        await api(`/api/vagas/${job.id}/recrutadores/${contact.id}/remover`, { method: "POST", json: {} });
        await renderJob();
      } })))
    : h("span", { class: "hint", text: "Ninguém vinculado ainda." }));
  const existing = h("select", { "aria-label": "Vincular recrutador(a)" }, h("option", { value: "", text: "Vincular alguém já cadastrado…" }));
  api("/api/recrutadores").then((all) => {
    for (const contact of all.filter((item) => !contacts.some((linked) => linked.id === item.id))) {
      existing.appendChild(h("option", { value: String(contact.id), text: `${contact.name || contact.email}${contact.company ? " — " + contact.company : ""}` }));
    }
  }).catch(() => {});
  existing.addEventListener("change", async () => {
    if (!existing.value) return;
    await api(`/api/vagas/${job.id}/recrutadores`, { method: "POST", json: { contato_id: Number(existing.value) } });
    await renderJob();
  });
  section.append(list, h("div", { class: "row" }, existing),
    h("details", {}, h("summary", { text: "+ Cadastrar recrutador(a) para esta vaga" }), contactForm({ vaga_id: job.id, company: job.company }, renderJob)));
  return section;
}

// Etapas do processo: o quadro da empresa aplicado a esta vaga

const STAGE_STATES = { pendente: "Pendente", atual: "Atual", feita: "Feita", pulada: "Pulada" };

function stageRow(stage, kinds, onRemove, withState) {
  const row = h("li", { class: "stage-row" });
  const name = h("input", { value: stage.name || stage.nome || "", "aria-label": "Nome da etapa", "data-field": "name" });
  const kind = h("select", { "aria-label": "Tipo da etapa", "data-field": "kind", title: "Em que coluna do quadro geral a vaga fica nesta etapa" },
    Object.entries(kinds).map(([key, label]) => h("option", { value: key, text: label, selected: key === (stage.kind || stage.tipo) })));
  const move = (delta) => () => {
    const sibling = delta < 0 ? row.previousElementSibling : row.nextElementSibling;
    if (sibling) delta < 0 ? row.parentElement.insertBefore(row, sibling) : row.parentElement.insertBefore(sibling, row);
  };
  // append() escreveria "null" para o que estiver vazio.
  row.append(...[
    h("span", { class: "grip", text: "⋮⋮", "aria-hidden": "true" }),
    name, kind,
    withState ? h("select", { "aria-label": "Estado", "data-field": "state" },
      Object.entries(STAGE_STATES).map(([key, label]) => h("option", { value: key, text: label, selected: key === (stage.state || "pendente") }))) : null,
    withState ? h("input", { type: "datetime-local", "aria-label": "Quando", "data-field": "scheduled_at", value: (stage.scheduled_at || "").slice(0, 16) }) : null,
    h("button", { type: "button", class: "ghost", text: "↑", title: "Subir", onclick: move(-1) }),
    h("button", { type: "button", class: "ghost", text: "↓", title: "Descer", onclick: move(1) }),
    h("button", { type: "button", class: "danger", text: "×", title: "Remover etapa", onclick: () => { row.remove(); if (onRemove) onRemove(); } }),
  ].filter(Boolean));
  row.dataset.notes = stage.notes || "";
  return row;
}

function readStages(list) {
  return [...list.querySelectorAll(".stage-row")].map((row) => {
    const value = (field) => (row.querySelector(`[data-field="${field}"]`) || {}).value || "";
    return { nome: value("name"), tipo: value("kind"), estado: value("state") || "pendente", quando: value("scheduled_at"), notas: row.dataset.notes };
  }).filter((stage) => stage.nome.trim());
}

// Editor de etapas: usado no detalhe da vaga e no quadro da empresa (Kanban).
function stageEditor(stages, kinds, suggestions, withState) {
  const list = h("ol", { class: "stage-list" }, stages.map((stage) => stageRow(stage, kinds, null, withState)));
  const pick = h("select", { "aria-label": "Adicionar etapa" }, h("option", { value: "", text: "+ Etapa…" }),
    suggestions.map((item) => h("option", { value: JSON.stringify(item), text: item.nome })),
    h("option", { value: "__nova", text: "Outra (escrever o nome)" }));
  pick.addEventListener("change", () => {
    if (!pick.value) return;
    const item = pick.value === "__nova" ? { nome: "", tipo: "entrevista" } : JSON.parse(pick.value);
    const same = [...list.querySelectorAll('[data-field="name"]')].find((input) => item.nome && input.value.trim().toLowerCase() === item.nome.toLowerCase());
    if (same) {
      // Já está no quadro: não duplica, só mostra onde está.
      pick.value = "";
      same.focus();
      same.select();
      return;
    }
    const row = stageRow({ name: item.nome, kind: item.tipo, state: "pendente" }, kinds, null, withState);
    // Antes da "Proposta", que costuma ser a última.
    const last = list.lastElementChild;
    if (last && (last.querySelector('[data-field="kind"]') || {}).value === "proposta") list.insertBefore(row, last);
    else list.appendChild(row);
    pick.value = "";
    row.querySelector("input").focus();
  });
  return { node: h("div", { class: "stage-editor" }, list, h("div", { class: "row" }, pick)), read: () => readStages(list) };
}

async function stagesSection(job) {
  const section = h("section", { class: "stages" }, h("h3", { class: "tab", text: "Etapas do processo" }));
  let view;
  try {
    view = await api(`/api/vagas/${job.id}/etapas`);
  } catch (error) {
    section.appendChild(h("p", { class: "notice", text: error.message }));
    return section;
  }
  const notice = h("p", { class: "notice", role: "status" });
  const track = h("ol", { class: "stage-track" }, view.etapas.map((stage, index) => h("li", { class: "is-" + stage.state },
    h("button", { type: "button", title: stage.state === "atual" ? "Etapa atual" : "Mover a vaga para esta etapa", onclick: async () => {
      if (stage.state === "atual") return;
      try {
        await api(`/api/vagas/${job.id}/etapas/mover`, { method: "POST", json: { etapa: index } });
        await refresh();
        await renderJob();
      } catch (error) {
        notice.textContent = error.message;
      }
    } },
    h("span", { class: "dot", "aria-hidden": "true" }),
    h("span", { class: "name", text: stage.name }),
    stage.scheduled_at ? h("span", { class: "when", text: when(stage.scheduled_at) }) : null),
  )));
  const editor = stageEditor(view.etapas, view.tipos, view.sugestoes, true);
  const company = view.empresa;
  const edit = h("details", { class: "stage-edit" }, h("summary", { text: "Editar etapas desta vaga" }),
    h("p", { class: "hint", text: "Como foi combinado na entrevista: inclua testes, conversas e visitas. O tipo diz em que coluna do quadro geral a vaga fica." }),
    editor.node,
    h("div", { class: "row" },
      h("button", { type: "button", text: "Salvar etapas", onclick: async () => {
        try {
          await api(`/api/vagas/${job.id}/etapas`, { method: "PUT", json: { etapas: editor.read() } });
          await refresh();
          await renderJob();
        } catch (error) {
          notice.textContent = error.message;
        }
      } }),
      company ? h("button", { type: "button", class: "ghost", text: `Usar como quadro da ${company.nome}`, onclick: async () => {
        const stages = editor.read().map((stage) => ({ nome: stage.nome, tipo: stage.tipo }));
        await api(`/api/empresas/${company.id}/quadro`, { method: "PUT", json: { quadro: stages, aplicar: false } });
        notice.textContent = `Quadro da ${company.nome} salvo. As próximas vagas dela começam com essas etapas (veja no Kanban).`;
      } }) : null,
    ),
  );
  section.append(track, edit, notice);
  return section;
}

// Lembretes: cobrar retorno, pedir feedback... com repetição e Google Agenda

function reminderLine(reminder, due, onChange) {
  const late = due.includes(reminder.id);
  const act = (action, label, cls = "ghost") => h("button", { type: "button", class: cls, text: label, onclick: async () => {
    await api(`/api/lembretes/${reminder.id}/${action}`, { method: "POST", json: {} });
    await onChange();
  } });
  const repeat = reminder.every_days ? ` · a cada ${reminder.every_days} dia(s), faltam ${reminder.remaining}` : "";
  return h("li", { class: "reminder" + (late ? " is-due" : "") },
    h("div", {},
      h("strong", { text: reminder.title }),
      h("span", { class: "hint", text: ` · ${late ? "venceu " : ""}${when(reminder.next_at)}${repeat}${reminder.calendar_id ? " · na agenda" : ""}` }),
    ),
    h("div", { class: "row" },
      reminder.calendar_id ? null : h("a", { class: "ghost file-button", href: reminder.agenda_link, target: "_blank", rel: "noopener", title: "Abre o Google Agenda com o evento pronto; é só salvar", text: "Agenda" }),
      reminder.calendar_id ? null : h("a", { class: "ghost file-button", href: `/api/lembretes/${reminder.id}/agenda.ics`, download: "lembrete.ics", title: "Arquivo para Outlook e outras agendas", text: ".ics" }),
      reminder.intent && reminder.job_id && !reminder.intent.startsWith("etapa:") ? h("button", { type: "button", class: late ? "" : "ghost", text: "Escrever mensagem", onclick: () => {
        msgState.presetJob = String(reminder.job_id);
        msgState.presetIntent = reminder.intent;
        document.getElementById("drawer").close();
        go("mensagens");
      } }) : null,
      act("feito", reminder.every_days && reminder.remaining > 1 ? "Feito (próxima)" : "Feito"),
      act("adiar", "Adiar 1 dia"),
      act("parar", "Parar", "danger"),
    ),
  );
}

function reminderForm(job, data, onSaved) {
  const notice = h("span", { class: "notice", role: "status" });
  const preset = h("select", { "aria-label": "Tipo de lembrete" }, data.modelos.map((item) => h("option", { value: item.chave, text: item.nome })));
  const title = h("input", { "aria-label": "Título", placeholder: "Título" });
  const whenInput = h("input", { type: "datetime-local", "aria-label": "Quando" });
  const every = h("input", { type: "number", min: "0", max: "90", "aria-label": "Repetir a cada (dias)" });
  const times = h("input", { type: "number", min: "1", max: "30", "aria-label": "Quantas vezes" });
  const toCalendar = h("input", { type: "checkbox", checked: data.agenda.conectada, disabled: !data.agenda.conectada });
  const fill = () => {
    const item = data.modelos.find((row) => row.chave === preset.value);
    title.value = item.titulo;
    whenInput.value = item.quando.slice(0, 16);
    every.value = item.cada;
    times.value = item.vezes;
  };
  preset.addEventListener("change", fill);
  fill();
  const calendarNote = data.agenda.conectada ? "Também vai para o Google Agenda."
    : "Depois de criar, o botão Agenda abre o evento pronto no Google Agenda; é só salvar.";
  return h("form", { class: "reminder-form", onsubmit: async (event) => {
    event.preventDefault();
    const item = data.modelos.find((row) => row.chave === preset.value);
    try {
      const saved = await api("/api/lembretes", { method: "POST", json: {
        vaga_id: job ? job.id : null, titulo: title.value, quando: whenInput.value, cada_dias: Number(every.value || 0),
        vezes: Number(times.value || 1), intencao: item.intent, agenda: toCalendar.checked,
      } });
      notice.textContent = saved.aviso || "Lembrete criado.";
      await onSaved();
    } catch (error) {
      notice.textContent = error.message;
    }
  } },
    h("div", { class: "row" }, preset, title),
    h("div", { class: "row" },
      h("label", {}, "Quando", whenInput),
      h("label", {}, "Repetir a cada (dias, 0 = não)", every),
      h("label", {}, "Vezes", times),
    ),
    h("label", { class: "check" }, toCalendar, " Google Agenda"),
    h("p", { class: "hint", text: calendarNote }),
    h("div", { class: "row" }, h("button", { type: "submit", text: "Criar lembrete" }), notice),
  );
}

async function remindersSection(job) {
  const section = h("section", { class: "reminders" }, h("h3", { class: "tab", text: "Lembretes" }));
  const data = await api(`/api/lembretes?vaga=${job.id}`);
  const reload = async () => { await renderJob(); await renderReminders(); };
  section.append(
    data.lembretes.length
      ? h("ul", { class: "reminder-list" }, data.lembretes.map((reminder) => reminderLine(reminder, data.vencidos, reload)))
      : h("p", { class: "hint", text: "Nenhum lembrete. Ex.: cobrar retorno em 7 dias, repetindo a cada 7 dias até 3 vezes; ao fechar a vaga, os lembretes param." }),
    h("details", {}, h("summary", { text: "+ Lembrete para esta vaga" }), reminderForm(job, data, reload)),
  );
  return section;
}

// Lembretes vencidos e próximos (aba Agora)
async function renderReminders() {
  const box = document.getElementById("reminders-now");
  if (!box) return;
  let data;
  try {
    data = await api("/api/lembretes");
  } catch (error) {
    return;
  }
  clear(box);
  const soon = data.lembretes.filter((reminder) => data.vencidos.includes(reminder.id) || new Date(reminder.next_at) - Date.now() < 3 * 86400000);
  box.hidden = !soon.length;
  if (!soon.length) return;
  box.append(
    h("h2", { class: "tab", text: `Lembretes (${data.vencidos.length} vencido(s))` }),
    h("ul", { class: "reminder-list" }, soon.map((reminder) => {
      const line = reminderLine(reminder, data.vencidos, renderReminders);
      if (reminder.job_id) {
        line.querySelector("strong").append(" ", h("a", { href: "#", class: "hint", text: "abrir vaga", onclick: (event) => { event.preventDefault(); openJob(reminder.job_id); } }));
      }
      return line;
    })),
  );
}

function renderMensagens() {
  loadMsgModels().catch(console.error);
  loadContacts().catch(console.error);
  const select = document.getElementById("msg-job");
  const chosen = msgState.presetJob || select.value;
  msgState.presetJob = null;
  clear(select);
  select.appendChild(h("option", { value: "", text: "Sem vaga específica" }));
  for (const job of state.vagas.filter((item) => item.title || item.company)) {
    select.appendChild(h("option", { value: String(job.id), text: `${job.title || "(sem título)"} — ${job.company || ""}`, selected: String(job.id) === chosen }));
  }
}

function setupMensagens() {
  const channels = document.getElementById("msg-channel");
  CHANNELS.forEach(([value, label], index) => channels.appendChild(h("label", {}, h("input", { type: "radio", name: "canal", value, checked: index === 0 }), label)));
  const intents = document.getElementById("msg-intents");
  // As intenções vêm da biblioteca (padrões + editadas); ver loadMsgModels.
  document.getElementById("msg-contact").addEventListener("change", (event) => {
    const contact = msgState.contacts.find((item) => String(item.id) === event.target.value);
    if (!contact) return;
    const form = document.getElementById("msg-form");
    form.elements.recrutador.value = contact.name || "";
    if (contact.vagas.length) form.elements.vaga_id.value = String(contact.vagas[0].id);
  });
  document.getElementById("msg-model-new").addEventListener("click", async () => {
    const created = await api("/api/mensagens/modelos", { method: "POST", json: { nome: "Novo modelo", instrucao: "", pt: "Olá[, {recrutador}]! {extra}" } });
    await loadMsgModels();
    const node = document.querySelector(`#msg-models details[data-key="${created.chave}"]`);
    if (node) {
      node.open = true;
      node.scrollIntoView({ block: "center" });
    }
  });
  document.getElementById("recruiter-new").addEventListener("click", () => {
    const box = document.getElementById("recruiters");
    box.prepend(h("article", { class: "recruiter" }, h("span", { class: "who", text: "Novo(a) recrutador(a)" }), contactForm({}, loadContacts)));
  });
  const form = document.getElementById("msg-form");
  const out = document.getElementById("msg-out");
  const notice = document.getElementById("msg-notice");
  const write = async () => {
    const data = Object.fromEntries(new FormData(form).entries());
    notice.textContent = "Escrevendo…";
    try {
      const result = await api("/api/mensagens/responder", { method: "POST", json: data });
      notice.textContent = result.aviso || "";
      out.hidden = false;
      document.getElementById("msg-subject-wrap").hidden = data.canal !== "email";
      document.getElementById("msg-subject").value = result.assunto || "";
      document.getElementById("msg-text").value = result.texto;
      document.getElementById("msg-origin").textContent = result.origem === "ia"
        ? `Escrita por ${result.modelo}. Confira antes de enviar.`
        : "Modelo pronto (sem IA). Ligue a IA de “Respostas a recrutador” em Config para adaptar à mensagem recebida.";
    } catch (error) {
      notice.textContent = error.message;
    }
  };
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    write();
  });
  document.getElementById("msg-again").addEventListener("click", write);
  document.getElementById("msg-copy").addEventListener("click", async () => {
    const subject = document.getElementById("msg-subject").value;
    const body = document.getElementById("msg-text").value;
    const text = !document.getElementById("msg-subject-wrap").hidden && subject ? `Assunto: ${subject}\n\n${body}` : body;
    try {
      await navigator.clipboard.writeText(text);
    } catch (error) {
      const area = document.getElementById("msg-text");
      area.select();
      document.execCommand("copy");
    }
    document.getElementById("msg-origin").textContent = "Copiado. Cole no WhatsApp, LinkedIn ou e-mail.";
  });
  document.getElementById("msg-note").addEventListener("click", async () => {
    const jobId = document.getElementById("msg-job").value;
    if (!jobId) {
      notice.textContent = "Escolha a vaga para salvar a resposta como nota.";
      return;
    }
    const channel = (new FormData(form)).get("canal");
    await api(`/api/vagas/${jobId}/notas`, { method: "POST", json: { texto: `Resposta ao recrutador (${channel}):\n${document.getElementById("msg-text").value}` } });
    notice.textContent = "Salva como nota na vaga.";
  });
}

// Currículo: editor, o que o JobScout entendeu, backlog de melhoria, revisão e perfis na internet

const cv = { analysis: null, improvements: [], panelRestored: false, backlogTab: "pendentes" };

function yearsText(value) {
  return value === null || value === undefined ? "—" : String(Math.round(value * 10) / 10).replace(".", ",");
}

async function renderCurriculo() {
  const [profile, analysis, improvements] = await Promise.all([api("/api/perfil"), api("/api/curriculo/analise"), api("/api/melhorias")]);
  const text = document.getElementById("cv-text");
  if (!text.dataset.dirty && document.activeElement !== text) text.value = profile.curriculo || "";
  cv.analysis = analysis;
  cv.improvements = improvements;
  renderCvSkills(analysis);
  renderCvRoles(analysis);
  renderCvChecks(analysis.pontos);
  renderBacklog();
  if (!cv.panelRestored) {
    cv.panelRestored = true;
    restoreImprovePanel();
  }
}

function skillRow(skill) {
  const low = skill.meses === 0 && !skill.anos_informados;
  const inCv = skill.meses
    ? `${yearsText(skill.anos_curriculo)} anos · ${skill.cargos} cargo${skill.cargos > 1 ? "s" : ""}, ${skill.de}–${skill.ate}`
    : "fora de cargo com data (0)";
  return h("tr", { "data-skill": skill.skill },
    h("td", {}, skill.novo ? h("input", { "data-field": "skill", value: skill.skill, placeholder: "Ex.: SQL" }) : h("strong", { text: skill.skill })),
    h("td", { class: low ? "is-low" : "", text: skill.novo ? "—" : inCv }),
    h("td", {}, h("input", { "data-field": "anos", type: "number", min: "0", max: "60", step: "0.5", value: skill.anos_informados ?? "", placeholder: "anos" })),
    h("td", {}, h("input", { "data-field": "nota", value: skill.nota || "", placeholder: "de onde vem (opcional)" })),
  );
}

function renderCvSkills(analysis) {
  const box = document.getElementById("cv-skills");
  if (box.dataset.dirty || box.contains(document.activeElement)) return;
  clear(box);
  if (!analysis.skills.length) {
    box.appendChild(h("p", { class: "hint", text: "Nenhuma skill reconhecida ainda. Cite as ferramentas nas atividades ou use “+ Skill”." }));
    return;
  }
  box.appendChild(h("table", { class: "cv-table" },
    h("thead", {}, h("tr", {}, ["Skill", "No currículo", "Tempo real", "Nota"].map((label) => h("th", { text: label })))),
    h("tbody", {}, analysis.skills.map(skillRow)),
  ));
}

function cvSkillRows() {
  return [...document.querySelectorAll("#cv-skills tbody tr")];
}

function addSkillRow(skill = { skill: "", meses: 0, novo: true }) {
  const box = document.getElementById("cv-skills");
  let body = box.querySelector("tbody");
  if (!body) {
    clear(box);
    box.appendChild(h("table", { class: "cv-table" },
      h("thead", {}, h("tr", {}, ["Skill", "No currículo", "Tempo real", "Nota"].map((label) => h("th", { text: label })))),
      h("tbody"),
    ));
    body = box.querySelector("tbody");
  }
  const existing = cvSkillRows().find((row) => row.dataset.skill && row.dataset.skill.toLowerCase() === (skill.skill || "").toLowerCase());
  if (existing) {
    if (skill.anos_informados) existing.querySelector('[data-field="anos"]').value = skill.anos_informados;
    if (skill.nota) existing.querySelector('[data-field="nota"]').value = skill.nota;
    box.dataset.dirty = "1";
    existing.scrollIntoView({ block: "nearest" });
    return existing;
  }
  const row = skillRow({ ...skill, novo: !skill.skill || skill.novo });
  body.appendChild(row);
  box.dataset.dirty = "1";
  return row;
}

function renderCvRoles(analysis) {
  const list = document.getElementById("cv-roles");
  clear(list);
  if (!analysis.cargos.length) list.appendChild(h("li", { class: "empty", text: "Nenhum cargo lido." }));
  for (const role of analysis.cargos) {
    list.appendChild(h("li", {},
      h("strong", { text: role.cargo || "(sem nome)" }),
      ` · ${role.periodo || "sem período"}`,
      role.conta ? "" : " · formação (não conta)",
      h("span", { class: "when", text: ` · ${role.atividades} atividade(s)${role.skills.length ? " · " + role.skills.join(", ") : ""}` }),
    ));
  }
}

function pointItem(point, withButton) {
  const li = h("li", {}, point.texto, point.pergunta ? h("span", { class: "ask-me", text: "→ " + point.pergunta }) : null);
  if (withButton) {
    const button = h("button", { type: "button", class: "ghost", text: "Anotar no backlog", onclick: async () => {
      button.disabled = true;
      await api("/api/melhorias", { method: "POST", json: { pergunta: point.pergunta || point.texto, base: point.texto, origem: "revisao" } });
      button.textContent = "Anotado ✓";
      await renderCurriculo();
    } });
    li.append(" ", button);
  }
  return li;
}

function renderCvChecks(points) {
  const list = document.getElementById("cv-checks");
  clear(list);
  if (!points.length) list.appendChild(h("li", { class: "empty", text: "Nada óbvio faltando. A IA pode olhar com mais detalhe." }));
  for (const point of points) list.appendChild(pointItem(point, Boolean(point.pergunta)));
}

function renderBacklog() {
  const list = document.getElementById("cv-backlog");
  const pending = cv.backlogTab !== "resolvidas";
  clear(list);
  const items = cv.improvements.filter((item) => (item.state === "aberto") === pending);
  if (!items.length) {
    list.appendChild(h("li", { class: "empty", text: pending
      ? "Nenhum ponto pendente. No formulário, clique em “Ponto de melhoria” na sugestão que não refletir a sua experiência."
      : "Nenhum ponto resolvido ainda. Quando a resposta refletir a sua experiência, marque o ponto como resolvido." }));
  }
  for (const item of items) {
    const latest = item.latest || {};
    const notice = h("span", { class: "notice" });
    const act = (label, handler, cls = "ghost") => h("button", { type: "button", class: cls, text: label, onclick: async () => {
      notice.textContent = "…";
      try {
        await handler();
        notice.textContent = "";
        cv.improvements = await api("/api/melhorias");
        renderBacklog();
      } catch (error) {
        notice.textContent = error.message;
      }
    } });
    const patchState = (estado) => () => api(`/api/melhorias/${item.id}`, { method: "PATCH", json: { estado } });
    const term = improvementTerm(item);
    list.appendChild(h("li", { class: item.state === "descartado" ? "is-done" : "" },
      h("span", { class: "q", text: item.question }),
      item.state === "descartado" ? h("span", { class: "state-tag", text: "descartado" }) : null,
      h("p", { class: "was", text: `Sugerido antes: ${item.suggestion || "—"}${item.basis ? " · " + item.basis : ""}${item.job ? " · " + item.job : ""}` }),
      latest.em ? h("p", { class: "now" + (latest.mudou ? " is-changed" : ""), text: `${latest.mudou ? "Agora mudou para" : "Agora"}: ${latest.valor || "sem resposta"} · ${latest.base}` }) : null,
      h("div", { class: "row" },
        item.state === "aberto"
          ? [
            h("button", { type: "button", class: "ghost", text: term ? `Editar “${term}” no currículo` : "Editar no currículo", onclick: () => locateInCv(term) }),
            act("Reprocessar", () => api(`/api/melhorias/${item.id}/reprocessar`, { method: "POST", json: {} }), ""),
            act("Resolvido", patchState("resolvido")),
            act("Descartar", patchState("descartado")),
          ]
          : act("Reabrir", patchState("aberto")),
        notice,
      ),
    ));
  }
  const open = cv.improvements.filter((item) => item.state === "aberto").length;
  document.getElementById("cv-count-pendentes").textContent = String(open);
  document.getElementById("cv-count-resolvidas").textContent = String(cv.improvements.length - open);
  for (const id of ["menu-cv-badge", "cv-improve-count"]) {
    const badge = document.getElementById(id);
    badge.hidden = !open;
    badge.textContent = String(open);
  }
  document.getElementById("cv-reprocess-all").disabled = !open;
}

// A skill (ou palavra) da pergunta que vale procurar no currículo: "Quantos anos com Kafka?" → Kafka.
function improvementTerm(item) {
  const question = item.question || "";
  const folded = question.toLowerCase();
  const skills = ((cv.analysis && cv.analysis.skills) || []).map((skill) => skill.skill).sort((a, b) => b.length - a.length);
  const known = skills.find((skill) => new RegExp(`(^|[^\\p{L}\\p{N}])${skill.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}($|[^\\p{L}\\p{N}])`, "iu").test(folded));
  if (known) return known;
  // Sem skill conhecida: um nome próprio ou termo técnico escrito com maiúscula fora do início.
  const words = question.replace(/[?¿!.,:;()"“”]/g, " ").split(/\s+/).filter(Boolean);
  const named = words.slice(1).find((word) => /^[A-Z][\p{L}\p{N}+#.-]{1,}$/u.test(word) || /^[\p{L}]*[A-Z]{2,}[\p{L}\p{N}]*$/u.test(word));
  return named || "";
}

function currentCvTab() {
  const tab = document.querySelector("[data-cvtab].is-on");
  return tab ? tab.dataset.cvtab : "completo";
}

function showCvTab(name) {
  const tab = document.querySelector(`[data-cvtab="${name}"]`);
  if (tab && !tab.classList.contains("is-on")) tab.click();
}

function flash(node) {
  node.classList.remove("is-found");
  void node.offsetWidth;
  node.classList.add("is-found");
  setTimeout(() => node.classList.remove("is-found"), 1800);
}

// Leva ao ponto do currículo onde o termo aparece: no editor completo (o campo que cita) ou no texto
// (seleciona a palavra). Sem o termo, abre o editor no fim para escrever a experiência que falta.
function locateInCv(term) {
  const needle = (term || "").toLowerCase();
  if (currentCvTab() !== "texto") {
    showCvTab("completo");
    const fields = [...document.querySelectorAll("#cvx input, #cvx textarea")].filter((field) => field.type !== "checkbox");
    const field = needle ? fields.find((node) => node.value.toLowerCase().includes(needle)) : null;
    if (field) {
      field.scrollIntoView({ block: "center", behavior: "smooth" });
      field.focus({ preventScroll: true });
      const at = field.value.toLowerCase().indexOf(needle);
      if (field.setSelectionRange) field.setSelectionRange(at, at + needle.length);
      flash(field);
      setImproveNotice(`“${term}” aparece aqui. Detalhe o tempo e o que você fez, salve e reprocesse.`);
      return;
    }
    if (needle) setImproveNotice(`“${term}” ainda não aparece no currículo completo. Acrescente numa experiência (ou nas habilidades), salve e reprocesse.`);
    const target = document.querySelector("#cvx textarea") || fields[0];
    if (target) {
      target.scrollIntoView({ block: "center", behavior: "smooth" });
      target.focus({ preventScroll: true });
      flash(target);
    }
    return;
  }
  const text = document.getElementById("cv-text");
  const at = needle ? text.value.toLowerCase().indexOf(needle) : -1;
  text.focus({ preventScroll: true });
  if (at >= 0) {
    text.setSelectionRange(at, at + needle.length);
    // Rola o textarea até a linha selecionada.
    const line = text.value.slice(0, at).split("\n").length;
    text.scrollTop = Math.max(0, (line - 4) * parseFloat(getComputedStyle(text).lineHeight || "20"));
    setImproveNotice(`“${term}” selecionado no texto. Detalhe o tempo e o que você fez, salve e reprocesse.`);
  } else {
    text.setSelectionRange(text.value.length, text.value.length);
    text.scrollTop = text.scrollHeight;
    setImproveNotice(needle ? `“${term}” ainda não aparece no texto. Acrescente numa atividade com período, salve e reprocesse.` : "Escreva a experiência que falta, salve e reprocesse.");
  }
  text.scrollIntoView({ block: "nearest", behavior: "smooth" });
  flash(text);
}

function setImproveNotice(message) {
  document.getElementById("cv-improve-notice").textContent = message;
}

async function saveCvText() {
  const text = document.getElementById("cv-text");
  const notice = document.getElementById("cv-notice");
  try {
    await api("/api/perfil", { method: "PUT", json: { curriculo: text.value } });
    delete text.dataset.dirty;
    notice.textContent = "Currículo salvo. Reprocesse os pontos de melhoria para ver o efeito.";
    await renderCurriculo();
    return true;
  } catch (error) {
    notice.textContent = error.message;
    return false;
  }
}

function setImprovePanel(open) {
  const panel = document.getElementById("cv-improve");
  panel.hidden = !open;
  document.getElementById("cv-workspace").classList.toggle("has-improve", open);
  document.getElementById("cv-improve-toggle").setAttribute("aria-expanded", String(open));
  writePref("melhorias", open ? "aberto" : "fechado");
  state.improveOpen = open;
  fitWindow();
}

function setupImprovePanel() {
  // O topo fixo muda de altura quando as abas quebram linha; os painéis grudam logo abaixo dele.
  const top = document.querySelector(".top");
  if (top && "ResizeObserver" in window) {
    new ResizeObserver(() => document.documentElement.style.setProperty("--top-h", `${top.offsetHeight}px`)).observe(top);
  }
  const toggle = document.getElementById("cv-improve-toggle");
  toggle.addEventListener("click", () => setImprovePanel(document.getElementById("cv-improve").hidden));
  document.getElementById("cv-improve-close").addEventListener("click", () => {
    setImprovePanel(false);
    toggle.focus();
  });
  document.getElementById("cv-improve").addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      setImprovePanel(false);
      toggle.focus();
    }
  });
  document.getElementById("cv-reprocess-all").addEventListener("click", async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    try {
      // O que estiver sem salvar vai antes, senão o reprocesso lê o currículo antigo.
      const text = document.getElementById("cv-text");
      if (text.dataset.dirty) {
        setImproveNotice("Salvando o texto…");
        if (!(await saveCvText())) return setImproveNotice("Não consegui salvar o texto; veja o aviso no editor.");
      } else if (cvx.dirty) {
        setImproveNotice("Salvando o currículo completo…");
        if (!(await saveCvx())) return setImproveNotice("Não consegui salvar o currículo completo; veja o aviso no editor.");
      }
      const open = cv.improvements.filter((item) => item.state === "aberto");
      for (const [index, item] of open.entries()) {
        setImproveNotice(`Reprocessando ${index + 1} de ${open.length}…`);
        await api(`/api/melhorias/${item.id}/reprocessar`, { method: "POST", json: {} });
      }
      cv.improvements = await api("/api/melhorias");
      const changed = cv.improvements.filter((item) => item.state === "aberto" && item.latest && item.latest.mudou).length;
      renderBacklog();
      setImproveNotice(changed ? `${changed} resposta(s) mudaram com o currículo novo. Confira e marque como resolvido.` : "Nenhuma resposta mudou ainda. Detalhe mais a experiência e tente de novo.");
    } catch (error) {
      setImproveNotice(error.message);
    } finally {
      button.disabled = !cv.improvements.some((item) => item.state === "aberto");
    }
  });
}

// Aberto por padrão quando há pontos em aberto; depois vale a última escolha da pessoa.
function restoreImprovePanel() {
  const saved = readPref("melhorias", "");
  const hasOpen = cv.improvements.some((item) => item.state === "aberto");
  setImprovePanel(saved ? saved === "aberto" : hasOpen);
}

function renderOnline(result) {
  const out = document.getElementById("cv-online-out");
  clear(out);
  const gh = result.github;
  const ghBlock = h("div", { class: "cv-online-block" }, h("h3", { class: "tab", text: "GitHub" }));
  if (!gh.ok) ghBlock.appendChild(h("p", { class: "hint", text: gh.erro }));
  else {
    // append() escreveria "null" para o que estiver vazio; h() já ignora.
    ghBlock.append(...[
      h("p", {}, h("a", { href: gh.url, target: "_blank", rel: "noopener", text: gh.nome || gh.usuario }), ` · ${gh.repositorios} repositório(s) público(s) · conta desde ${gh.desde}`),
      gh.bio ? h("p", { class: "hint", text: gh.bio }) : null,
      gh.linguagens.length
        ? h("table", { class: "cv-table" },
          h("thead", {}, h("tr", {}, ["Linguagem", "Repos", "Anos de uso", ""].map((label) => h("th", { text: label })))),
          h("tbody", {}, gh.linguagens.map((lang) => h("tr", {},
            h("td", {}, h("strong", { text: lang.skill })),
            h("td", { text: String(lang.repos) }),
            h("td", { text: lang.anos ? `${lang.de}–${lang.ate} (${lang.anos})` : "—" }),
            h("td", {}, h("button", { type: "button", class: "ghost", text: "Usar como tempo real", onclick: () => {
              addSkillRow({ skill: lang.skill, meses: 0, anos_informados: lang.anos || "", nota: `GitHub: ${lang.repos} repo(s), ${lang.de}–${lang.ate}` });
              document.getElementById("cv-skills-notice").textContent = `${lang.skill} entrou na tabela de tempos. Confira os anos (uso no GitHub não é o mesmo que experiência profissional) e salve.`;
            } })),
          ))),
        )
        : h("p", { class: "hint", text: "Sem repositórios próprios com linguagem definida." }),
    ].filter(Boolean));
  }
  const li = result.linkedin;
  const liBlock = h("div", { class: "cv-online-block" }, h("h3", { class: "tab", text: "LinkedIn" }),
    li.ok ? h("p", {}, h("strong", { text: li.titulo }), li.descricao ? " · " + li.descricao : "") : h("p", { class: "hint", text: li.erro }));
  const site = result.site;
  const siteBlock = h("div", { class: "cv-online-block" }, h("h3", { class: "tab", text: "Site pessoal" }),
    site.ok
      ? h("p", {}, h("a", { href: site.url, target: "_blank", rel: "noopener", text: site.titulo || site.url }), site.descricao ? " · " + site.descricao : "",
        site.skills && site.skills.length ? h("span", { class: "hint", text: " · cita: " + site.skills.join(", ") }) : null)
      : h("p", { class: "hint", text: site.erro }));
  out.append(ghBlock, liBlock, siteBlock);
}

function setupCurriculo() {
  const text = document.getElementById("cv-text");
  const notice = document.getElementById("cv-notice");
  text.addEventListener("input", () => { text.dataset.dirty = "1"; });
  document.getElementById("cv-save").addEventListener("click", saveCvText);
  setupImprovePanel();
  document.getElementById("cv-import").addEventListener("change", async (event) => {
    const file = event.target.files[0];
    event.target.value = "";
    if (!file) return;
    notice.textContent = "Lendo o arquivo neste computador…";
    const body = new FormData();
    body.append("arquivo", file, file.name);
    try {
      const result = await api("/api/analisar", { method: "POST", body });
      if (text.value.trim() && !(await ask("Substituir o texto do editor pelo do arquivo?", `${result.arquivo}: ${result.total} atividade(s) lidas.`, "Substituir"))) {
        notice.textContent = "Mantive o texto atual.";
        return;
      }
      text.value = result.texto || "";
      text.dataset.dirty = "1";
      notice.textContent = `${result.arquivo} importado (${result.total} atividade(s)). Revise e clique em Salvar currículo.`;
    } catch (error) {
      notice.textContent = error.message;
    }
  });
  const skills = document.getElementById("cv-skills");
  skills.addEventListener("input", () => { skills.dataset.dirty = "1"; });
  document.getElementById("cv-add-skill").addEventListener("click", () => {
    const row = addSkillRow();
    row.querySelector("input").focus();
  });
  document.getElementById("cv-save-skills").addEventListener("click", async () => {
    const skillsNotice = document.getElementById("cv-skills-notice");
    const extras = cvSkillRows().map((row) => ({
      skill: (row.querySelector('[data-field="skill"]') || {}).value || row.dataset.skill,
      anos: row.querySelector('[data-field="anos"]').value,
      nota: row.querySelector('[data-field="nota"]').value,
    })).filter((item) => item.skill && Number(String(item.anos).replace(",", ".")) > 0);
    try {
      await api("/api/perfil", { method: "PUT", json: { skills_extras: extras } });
      delete skills.dataset.dirty;
      skillsNotice.textContent = `${extras.length} tempo(s) salvo(s). Eles valem quando passam do que os cargos mostram.`;
      await renderCurriculo();
    } catch (error) {
      skillsNotice.textContent = error.message;
    }
  });
  for (const tab of document.querySelectorAll("[data-backlog]")) {
    tab.addEventListener("click", () => {
      cv.backlogTab = tab.dataset.backlog;
      for (const other of document.querySelectorAll("[data-backlog]")) {
        other.classList.toggle("is-on", other === tab);
        other.setAttribute("aria-selected", String(other === tab));
      }
      setImproveNotice("");
      renderBacklog();
    });
  }
  document.getElementById("cv-review").addEventListener("click", async () => {
    const out = document.getElementById("cv-review-out");
    clear(out);
    out.appendChild(h("p", { class: "hint", text: "A IA está lendo o currículo… (alguns segundos)" }));
    try {
      const result = await api("/api/curriculo/revisar-ia", { method: "POST", json: {} });
      clear(out);
      out.append(...[
        result.resumo ? h("p", { text: result.resumo }) : null,
        h("ul", { class: "cv-points" }, result.pontos.map((point) => pointItem(point, true))),
        h("p", { class: "hint", text: `Revisão feita por ${result.modelo}. Confira: ela só vê o texto do currículo.` }),
      ].filter(Boolean));
    } catch (error) {
      clear(out);
      out.appendChild(h("p", { class: "notice", text: error.message.includes("IA indisponível") ? error.message + " Ligue a IA em Config." : error.message }));
    }
  });
  document.getElementById("cv-online").addEventListener("click", async () => {
    const out = document.getElementById("cv-online-out");
    clear(out);
    out.appendChild(h("p", { class: "hint", text: "Buscando…" }));
    try {
      renderOnline(await api("/api/curriculo/online", { method: "POST", json: {} }));
    } catch (error) {
      clear(out);
      out.appendChild(h("p", { class: "notice", text: error.message }));
    }
  });
}

function storyRow(story = { titulo: "", texto: "" }) {
  const row = h("div", { class: "story" },
    h("input", { "data-story": "titulo", value: story.titulo, placeholder: "Título (ex.: Migração para PostgreSQL)" }),
    h("button", { type: "button", class: "danger", text: "Remover", onclick: () => row.remove() }),
    h("textarea", { "data-story": "texto", value: story.texto, placeholder: "O que você fez e o resultado, com números reais" }),
  );
  return row;
}

// Nome e pasta: não sobrescreve o que a pessoa está digitando.
function renderPrefs() {
  const form = document.getElementById("prefs-form");
  if (!state.prefs || form.contains(document.activeElement)) return;
  form.elements.nome.value = state.prefs.nome;
  form.elements.pasta.value = state.prefs.pasta;
  document.getElementById("prefs-pick").hidden = !bridge();
}

function renderExportChoices() {
  const sheets = document.getElementById("export-sheets");
  if (!sheets.children.length) {
    for (const sheet of state.exportSheets) {
      sheets.appendChild(h("label", { class: "check" }, h("input", { type: "checkbox", "data-sheet": sheet.chave, checked: true }), sheet.nome));
    }
  }
  const statuses = document.getElementById("export-status");
  if (!statuses.children.length) {
    for (const status of state.status) {
      statuses.appendChild(h("label", { class: "check" }, h("input", { type: "checkbox", "data-status": status.chave }), status.nome));
    }
  }
}

async function openInFolder(body, notice) {
  try {
    await api("/api/pasta/abrir", { method: "POST", json: body });
  } catch (error) {
    notice.textContent = error.message;
  }
}

function setupPrefs() {
  const form = document.getElementById("prefs-form");
  const notice = document.getElementById("prefs-notice");
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    notice.textContent = "Salvando e preparando a pasta…";
    try {
      state.prefs = await api("/api/preferencias", { method: "PUT", json: { nome: form.elements.nome.value, pasta: form.elements.pasta.value } });
      applyName(state.prefs.nome);
      document.activeElement.blur();
      renderPrefs();
      notice.textContent = `Pronto. A extensão está em ${state.prefs.extensao}`;
    } catch (error) {
      notice.textContent = error.message;
    }
  });
  document.getElementById("prefs-pick").addEventListener("click", async () => {
    const win = bridge();
    if (!win) return;
    const chosen = await win.escolher_pasta(form.elements.pasta.value);
    if (!chosen) return;
    // Uma pasta nova ganha uma subpasta própria, para não misturar com o que já existe nela.
    form.elements.pasta.value = /jobscout$/i.test(chosen) ? chosen : chosen.replace(/[\\/]+$/, "") + "\\JobScout";
    form.requestSubmit();
  });
  for (const button of document.querySelectorAll("[data-open]")) {
    button.addEventListener("click", () => openInFolder({ alvo: button.dataset.open }, notice));
  }

  const exportForm = document.getElementById("export-form");
  const exportNotice = document.getElementById("export-notice");
  exportForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const abas = [...exportForm.querySelectorAll("[data-sheet]")].filter((box) => box.checked).map((box) => box.dataset.sheet);
    const status = [...exportForm.querySelectorAll("[data-status]")].filter((box) => box.checked).map((box) => box.dataset.status);
    clear(exportNotice);
    exportNotice.textContent = "Gerando a planilha…";
    try {
      const result = await api("/api/exportar", { method: "POST", json: { abas, status } });
      clear(exportNotice);
      exportNotice.append(
        `Salvo: ${result.nome} `,
        h("button", { type: "button", class: "ghost", text: "Abrir planilha", onclick: () => openInFolder({ arquivo: result.arquivo }, exportNotice) }),
        " ",
        h("button", { type: "button", class: "ghost", text: "Abrir pasta", onclick: () => openInFolder({ alvo: "exportacoes" }, exportNotice) }),
      );
    } catch (error) {
      exportNotice.textContent = error.message;
    }
  });
}

async function renderAI() {
  const status = document.getElementById("ai-status");
  const select = document.getElementById("ai-model");
  if (document.getElementById("ai-form").contains(document.activeElement)) return;
  let info;
  try {
    info = await api("/api/ia");
  } catch (error) {
    status.textContent = error.message;
    return;
  }
  const options = [["", "Desligada (só regras)"]];
  for (const name of info.ollama || []) options.push([`ollama:${name}`, `${name} (Ollama, neste computador)`]);
  if (info.escolhido && !options.some(([value]) => value === info.escolhido)) options.push([info.escolhido, `${info.escolhido} (não encontrado)`]);
  clear(select);
  for (const [value, label] of options) select.appendChild(h("option", { value, text: label, selected: value === (info.escolhido || "") }));
  if (info.ollama === null) status.textContent = "Ollama não está rodando. Abra o Ollama (menu Iniciar) e volte aqui.";
  else if (!info.ollama.length) status.textContent = "Ollama rodando, mas sem modelo baixado. Baixe um em “Modelos por tarefa”.";
  else status.textContent = info.ativo ? `Ligada: ${info.ativo}.` : "Ollama pronto. Escolha um modelo para ligar.";
  renderTaskModels(info);
}

// Modelos por tarefa: padrão, desligado, qualquer modelo do Ollama ou do Gemini (tarefas privadas só local).
function renderTaskModels(info) {
  const box = document.getElementById("task-models");
  if (box.contains(document.activeElement)) return;
  clear(box);
  const fallback = info.escolhido ? `Padrão (${info.escolhido.replace(/^ollama:/, "")})` : "Padrão (desligada)";
  const choices = (privada) => [
    ["", fallback],
    ["off", "Desligada (só regras)"],
    ...(info.ollama || []).map((name) => [`ollama:${name}`, `${name} · Ollama`]),
    ...(privada ? [] : (info.gemini || []).map((name) => [`gemini:${name}`, `${name} · Gemini (nuvem)`])),
  ];
  const list = h("div", { class: "task-models" });
  for (const task of info.tarefas) {
    const options = choices(task.privada);
    if (task.escolhido && !options.some(([value]) => value === task.escolhido)) options.push([task.escolhido, `${task.escolhido} (não encontrado)`]);
    const select = h("select", { "data-task": task.tarefa, disabled: Boolean(task.fixado_no_env), "aria-label": task.nome },
      options.map(([value, label]) => h("option", { value, text: label, selected: value === (task.escolhido || "") })));
    select.addEventListener("change", async () => {
      const chosen = {};
      for (const node of box.querySelectorAll("[data-task]")) if (node.value) chosen[node.dataset.task] = node.value;
      try {
        await api("/api/preferencias", { method: "PUT", json: { ia_tarefas: chosen } });
        select.blur();
        await renderAI();
      } catch (error) {
        document.getElementById("pull-status").textContent = error.message;
      }
    });
    list.appendChild(h("div", { class: "task-model" },
      h("div", {}, h("strong", { text: task.nome }),
        h("small", { text: task.fixado_no_env ? `Fixado no .env: ${task.fixado_no_env}` : task.em_uso ? `Em uso: ${task.em_uso}` : "Sem IA: só regras" + (task.privada ? " · só modelo local" : "") })),
      select,
    ));
  }
  box.appendChild(list);
  const pull = info.baixando || {};
  const pullStatus = document.getElementById("pull-status");
  if (pull.estado === "baixando") pullStatus.textContent = `Baixando ${pull.modelo}: ${pull.pct}%…`;
  else if (pull.estado === "pronto") pullStatus.textContent = `${pull.modelo} pronto. Escolha nas tarefas acima.`;
  else if (pull.estado === "erro") pullStatus.textContent = pull.erro;
  document.getElementById("gemini-status").textContent = (state.prefs && state.prefs.gemini_chave)
    ? "Chave do Gemini salva neste computador. Os modelos do Gemini aparecem nas tarefas que não são privadas."
    : "A chave fica só neste computador (preferências do JobScout).";
}

function setupAI() {
  document.getElementById("pull-go").addEventListener("click", async () => {
    const input = document.getElementById("pull-name");
    const pullStatus = document.getElementById("pull-status");
    if (!input.value.trim()) return;
    try {
      await api("/api/ia/baixar", { method: "POST", json: { modelo: input.value.trim() } });
      pullStatus.textContent = `Baixando ${input.value.trim()}… o andamento aparece aqui e na atividade.`;
      input.value = "";
    } catch (error) {
      pullStatus.textContent = error.message;
    }
  });
  document.getElementById("gemini-save").addEventListener("click", async () => {
    const input = document.getElementById("gemini-key");
    try {
      state.prefs = await api("/api/preferencias", { method: "PUT", json: { gemini_chave: input.value.trim() } });
      input.value = "";
      await renderAI();
    } catch (error) {
      document.getElementById("gemini-status").textContent = error.message;
    }
  });
  const form = document.getElementById("ai-form");
  const notice = document.getElementById("ai-notice");
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      state.prefs = await api("/api/preferencias", { method: "PUT", json: { ia: form.elements.ia.value } });
      notice.textContent = form.elements.ia.value ? "IA ligada. Use Testar para ver o tempo de resposta." : "IA desligada; ficam só as regras.";
      document.activeElement.blur();
      await refresh();
      await renderAI();
    } catch (error) {
      notice.textContent = error.message;
    }
  });
  document.getElementById("ai-test").addEventListener("click", async () => {
    notice.textContent = "Testando… a primeira resposta demora mais, enquanto o modelo carrega.";
    try {
      const result = await api("/api/ia/testar", { method: "POST", json: {} });
      notice.textContent = `${result.modelo} respondeu “${result.resposta}” em ${String(result.segundos).replace(".", ",")} s.`;
    } catch (error) {
      notice.textContent = error.message;
    }
  });
}

function renderConfig() {
  renderPrefs();
  renderAI();
  renderExportChoices();
  const prefs = document.getElementById("toast-prefs");
  clear(prefs);
  for (const [level, label] of TOAST_LEVELS) {
    const box = h("input", { type: "checkbox", checked: state.toastPrefs[level] });
    box.addEventListener("change", () => {
      state.toastPrefs[level] = box.checked;
      writePref("toasts", JSON.stringify(state.toastPrefs));
    });
    prefs.appendChild(h("label", { class: "check" }, box, label));
  }
  document.getElementById("cold-info").textContent = `Prazo atual: ${state.diasFria} dias sem movimento.`;
  const gmail = document.getElementById("gmail");
  clear(gmail);
  const g = state.gmail;
  const oauth = document.getElementById("gmail-oauth");
  clear(oauth);
  if (!g.conectado) gmail.appendChild(appPasswordForm());
  if (g.conectado && g.metodo === "senha_app") {
    const notice = h("p", { class: "notice", role: "status" });
    gmail.append(
      h("p", { text: `Conectado por senha de app: ${g.email}. Verifica a cada ${g.intervalo_min} min, só leitura.` }),
      h("p", { class: "hint", text: g.ultima_verificacao ? "Última verificação: " + when(g.ultima_verificacao) : "Ainda não verificou." }),
      g.erro ? h("p", { class: "notice is-error", text: g.erro }) : null,
      h("div", { class: "row" },
        h("button", { type: "button", text: "Verificar agora", onclick: async () => {
          notice.textContent = "Verificando…";
          try {
            const result = await api("/api/gmail/verificar", { method: "POST", json: {} });
            notice.textContent = `${result.novos} e-mail(s) viraram rascunho.`;
          } catch (error) {
            notice.textContent = error.message;
          }
        } }),
        h("button", { type: "button", class: "danger", text: "Desconectar", onclick: async () => {
          await api("/api/gmail/desconectar", { method: "POST", json: {} });
          await refresh();
        } }),
      ),
      notice,
    );
  } else if (!g.conectado && !g.configurado) {
    oauth.append(
      h("p", { text: "Desligado. Siga o passo a passo e cole aqui o ID e a chave do cliente:" }),
      googleForm(),
      h("p", { class: "hint", text: "Permissões: ler o Gmail (só leitura) e criar os eventos dos lembretes no Google Agenda. Ative também a Google Calendar API no mesmo projeto. Enquanto isso, use “Importar e-mail (.eml)” na aba Rascunhos." }),
    );
  } else if (!g.conectado) {
    oauth.append(h("p", { text: "Configurado, ainda não conectado." }), h("a", { class: "file-button", href: "/api/gmail/conectar", text: "Conectar Google (Gmail só leitura + Agenda)" }));
  } else {
    const notice = h("p", { class: "notice", role: "status" });
    gmail.append(
      h("p", { text: `Conectado. Verifica a cada ${g.intervalo_min} min. E-mails que não são de recrutamento e seleção (newsletter, curso, marketing) são ignorados; os duvidosos passam pela IA local.` }),
      g.agenda
        ? h("p", { class: "chip is-ok", text: "Google Agenda ligado: lembretes viram eventos." })
        : h("p", { class: "notice", text: "Google Agenda ainda sem permissão. Clique em Desconectar e conecte de novo para os lembretes irem para a agenda." }),
      h("p", { class: "hint", text: g.ultima_verificacao ? "Última verificação: " + when(g.ultima_verificacao) : "Ainda não verificou." }),
      g.erro ? h("p", { class: "notice is-error", text: g.erro }) : null,
      h("div", { class: "row" },
        h("button", { type: "button", text: "Verificar agora", onclick: async () => {
          notice.textContent = "Verificando…";
          try {
            const result = await api("/api/gmail/verificar", { method: "POST", json: {} });
            notice.textContent = `${result.novos} e-mail(s) viraram rascunho.`;
          } catch (error) {
            notice.textContent = error.message;
          }
        } }),
        h("button", { type: "button", class: "danger", text: "Desconectar", onclick: async () => {
          await api("/api/gmail/desconectar", { method: "POST", json: {} });
          await refresh();
        } }),
      ),
      notice,
    );
  }
  api("/api/falhas").then((rows) => {
    const list = document.getElementById("failures");
    clear(list);
    if (!rows.length) list.appendChild(h("li", { class: "empty", text: "Nenhuma falha registrada." }));
    for (const row of rows) list.appendChild(h("li", { text: `${when(row.at)} · ${row.site} · ${row.detail}` }));
  });
}

// Gaveta da vaga

function resumePicker(job, detail) {
  const current = detail.curriculo.tipo ? resumeLabel(detail.curriculo) : "Não registrado";
  const select = h("select", { "aria-label": "Currículo enviado" },
    h("option", { value: "", text: current }),
    detail.curriculos.map((item) => h("option", { value: item.valor, text: item.nome })));
  select.addEventListener("change", async () => {
    if (!select.value) return;
    await api(`/api/vagas/${job.id}/curriculo`, { method: "POST", json: { documento: select.value } });
    await refresh();
    await renderJob();
  });
  return select;
}

function fitSection(job, detail) {
  const ai = detail.encaixe_ia;
  const out = h("div");
  const list = (title, items, cls) => (items.length ? h("div", {}, h("p", { class: "hint", text: title }),
    h("div", { class: "skills" }, items.map((item) => h("span", { class: cls, text: item })))) : null);
  if (ai) {
    out.append(...[
      h("p", {}, h("strong", { text: `Nota da IA: ${ai.nota}/100` }), h("span", { class: "hint", text: ` · ${ai.modelo} · ${when(ai.em)}` })),
      ai.resumo ? h("p", { text: ai.resumo }) : null,
      list("Combina", ai.combina, "chip is-ok"),
      list("Falta ou não aparece no perfil", ai.faltam, "chip is-warn"),
    ].filter(Boolean));
  }
  const notice = h("p", { class: "notice", role: "status" });
  return h("section", { class: "fit-block" },
    h("h3", { class: "tab", text: "Encaixe com o seu perfil" }),
    detail.encaixe !== null ? h("p", {}, h("strong", { text: `${detail.encaixe}%` }), " das skills citadas na vaga estão no seu perfil.") : h("p", { class: "hint", text: "A vaga não cita skills conhecidas; a IA pode avaliar pelo texto." }),
    out,
    h("button", { type: "button", class: "ghost", text: ai ? "Avaliar de novo com IA" : "Avaliar encaixe com IA", onclick: async (event) => {
      event.currentTarget.disabled = true;
      notice.textContent = "A IA está comparando o perfil com a vaga…";
      try {
        await api(`/api/vagas/${job.id}/encaixe`, { method: "POST", json: {} });
        await renderJob();
      } catch (error) {
        notice.textContent = error.message;
      }
    } }),
    notice,
  );
}

async function openJob(id) {
  state.drawerJob = id;
  const drawer = document.getElementById("drawer");
  if (!drawer.open) drawer.showModal();
  await renderJob();
}

async function renderJob() {
  const body = document.getElementById("drawer-body");
  if (body.querySelector(".draft") && [...body.querySelectorAll(".draft")].some((node) => node.dirty)) return;
  const detail = await api("/api/vagas/" + state.drawerJob);
  const job = detail.vaga;
  clear(body);
  const status = statusSelect(job.status);
  status.addEventListener("change", async () => {
    await api(`/api/vagas/${job.id}/status`, { method: "PATCH", json: { status: status.value } });
    await refresh();
  });
  body.append(
    h("div", { class: "row", style: "justify-content: space-between" },
      h("p", { class: "eyebrow", text: (SOURCES[job.source] || job.source) + " · capturada " + when(job.captured_at) }),
      h("button", { type: "button", class: "ghost", text: "Fechar", onclick: () => document.getElementById("drawer").close() }),
    ),
    h("h2", { class: "title", text: job.title || "Vaga sem título" }),
    h("p", {},
      detail.empresa ? h("a", { href: "#", text: job.company, onclick: (event) => {
        event.preventDefault();
        document.getElementById("drawer").close();
        go("empresa/" + detail.empresa.id);
      } }) : job.company || "",
      job.location ? " · " + job.location : "",
    ),
    detail.empresa && (detail.empresa.industry || detail.empresa.size)
      ? h("p", { class: "hint", text: [detail.empresa.industry, detail.empresa.size].filter(Boolean).join(" · ") }) : null,
    insightChips(job),
    skillsBlock(job),
    // Oportunidade vinda de abordagem no chat não tem página: o endereço é só um identificador.
    job.url.startsWith("https://jobscout.local/")
      ? h("p", { class: "hint", text: `Oportunidade recebida por ${SOURCES[job.source] || job.source} (sem página da vaga).` })
      : h("p", {}, h("a", { href: job.url, target: "_blank", rel: "noopener", text: "Abrir a vaga ↗" })),
    detail.parada_dias !== null && detail.parada_dias >= Math.ceil(state.diasFria / 2)
      ? h("p", { class: "chip is-warn", text: `Sem movimento há ${detail.parada_dias} dias` }) : null,
    h("label", {}, "Status", status),
  );
  body.appendChild(fitSection(job, detail));
  const stagesSlot = h("div");
  const remindersSlot = h("div");
  body.append(stagesSlot, remindersSlot);
  stagesSection(job).then((node) => stagesSlot.replaceWith(node)).catch(console.error);
  remindersSection(job).then((node) => remindersSlot.replaceWith(node)).catch(console.error);
  if (detail.rascunhos.length) {
    const section = h("section", {}, h("h3", { class: "tab", text: `Rascunhos desta vaga (${detail.rascunhos.length})` }));
    for (const draft of detail.rascunhos) section.appendChild(draftCard(draft));
    body.appendChild(section);
  }
  const prep = h("div");
  body.appendChild(h("section", {},
    h("h3", { class: "tab", text: "Preparar entrevista" }),
    h("p", { class: "hint", text: "Para estudar antes. Não use durante a entrevista." }),
    h("button", { type: "button", class: "ghost", text: "Montar preparação", onclick: () => renderPrep(job.id, prep) }),
    prep,
  ));
  const noteInput = h("textarea", { rows: 2, placeholder: "Nova nota" });
  body.appendChild(h("section", {},
    h("h3", { class: "tab", text: "Notas" }),
    h("ul", {}, detail.notas.map((note) => h("li", { text: `${when(note.created_at)} — ${note.text}` }))),
    noteInput,
    h("button", { type: "button", text: "Adicionar nota", onclick: async () => {
      await api(`/api/vagas/${job.id}/notas`, { method: "POST", json: { texto: noteInput.value } });
      await renderJob();
    } }),
  ));
  body.appendChild(recruitersSection(job, detail.recrutadores || []));
  const salaryAnswer = detail.respostas.find((answer) => /pretens|salar|remunera|compensation/i.test(answer.question));
  body.appendChild(h("section", {},
    h("h3", { class: "tab", text: "Enviado nesta candidatura" }),
    h("dl", { class: "sent-facts" },
      h("dt", { text: "Candidatado em" }), h("dd", { text: job.applied_at ? when(job.applied_at) : "—" }),
      h("dt", { text: "Currículo enviado" }), h("dd", {}, resumePicker(job, detail)),
      h("dt", { text: "Salário informado" }), h("dd", { text: job.salary_informed || (salaryAnswer ? salaryAnswer.answer : "Não informado") }),
    ),
    detail.respostas.length ? null : h("p", { class: "empty", text: "Nenhuma resposta salva." }),
    detail.respostas.map((answer) => h("div", { class: "qa" },
      h("p", {}, h("strong", { text: answer.question })),
      h("p", { text: answer.answer }),
      answer.suggested_by_llm ? h("span", { class: "chip", text: "sugerida pela IA, aprovada por você" }) : null,
      answer.origin === "formulario" ? h("span", { class: "chip", text: "lida do formulário no envio" }) : null,
      answer.origin === "registro" ? h("span", { class: "chip", text: "só registro (não reusa no preenchimento)" }) : null,
    )),
  ));
  body.appendChild(h("section", {},
    h("h3", { class: "tab", text: "Mensagens" }),
    detail.mensagens.length ? null : h("p", { class: "empty", text: "Nenhuma mensagem vinculada." }),
    detail.mensagens.map((message) => h("div", { class: "qa" },
      h("p", {}, h("strong", { text: message.subject || "(sem assunto)" }), " · ", CLASSES[message.classification] || message.classification),
      h("p", { class: "hint", text: `${message.contact_name || ""} <${message.contact_email || ""}> · ${when(message.received_at)}` }),
      message.event_at ? h("p", { text: "Data citada: " + when(message.event_at) }) : null,
      h("p", { text: message.summary }),
      h("details", {}, h("summary", { text: "Texto" }), h("div", { class: "body-text", text: message.body })),
    )),
  ));
  body.appendChild(h("section", {},
    h("h3", { class: "tab", text: "Movimentos" }),
    h("ol", { class: "timeline" }, detail.movimentos.map((move) => h("li", { class: "move k-" + move.kind },
      h("span", { class: "when", text: when(move.at) }),
      h("div", { class: "what", text: move.summary }),
    ))),
  ));
  if (job.description) {
    body.appendChild(h("section", {}, h("h3", { class: "tab", text: "Descrição" }), h("div", { class: "body-text", text: job.description })));
  }
}

async function renderPrep(id, container) {
  clear(container);
  container.appendChild(h("p", { class: "hint", text: "Montando…" }));
  const prep = await api(`/api/vagas/${id}/preparo`);
  clear(container);
  container.append(
    prep.ferramentas.length ? h("p", { text: "Ferramentas citadas na vaga: " + prep.ferramentas.join(", ") }) : null,
    h("p", { class: "eyebrow", text: prep.fonte_perguntas === "llm" ? "Perguntas prováveis (IA)" : "Perguntas prováveis (regras)" }),
    h("ol", {}, prep.perguntas.map((question) => h("li", { text: question }))),
    prep.respostas.length ? h("p", { class: "eyebrow", text: "O que você já respondeu" }) : null,
    h("ul", {}, prep.respostas.map((answer) => h("li", {}, h("strong", { text: answer.question + ": " }), answer.answer))),
  );
}

function openDraft(draft) {
  state.drawerJob = null;
  const drawer = document.getElementById("drawer");
  const body = document.getElementById("drawer-body");
  clear(body);
  body.append(
    h("div", { class: "row", style: "justify-content: flex-end" },
      h("button", { type: "button", class: "ghost", text: "Fechar", onclick: () => drawer.close() }),
    ),
    draftCard(draft),
  );
  if (!drawer.open) drawer.showModal();
}

// Navegação, dados e tempo real

function showView(view) {
  state.view = view;
  if (state.overlay) fitWindow();
  const tab = view === "empresa" ? "empresas" : view;
  for (const link of document.querySelectorAll(".tablink")) link.classList.toggle("is-on", link.dataset.view === tab);
  for (const section of document.querySelectorAll(".view")) section.hidden = section.id !== "view-" + view;
  renderView();
  renderQueue();
}

async function renderView() {
  try {
    if (state.view === "agora") renderAgora();
    else if (state.view === "rascunhos") await renderDrafts();
    else if (state.view === "linha") await renderTimeline();
    else if (state.view === "kanban") renderBoard();
    else if (state.view === "empresas") await renderCompanies();
    else if (state.view === "empresa") await renderCompany();
    else if (state.view === "perfil") {
      if (!document.getElementById("profile-fields").children.length) await renderProfile();
    } else if (state.view === "curriculo") {
      await loadCvx();
      await renderCurriculo();
    } else if (state.view === "mensagens") renderMensagens();
    else if (state.view === "resultados") await renderResultados();
    else if (state.view === "vagas") await renderAutoSearch();
    else if (state.view === "busca") await renderChat();
    else if (state.view === "config") renderConfig();
  } catch (error) {
    console.error(error);
  }
}

async function refresh() {
  const data = await api("/api/estado");
  const before = new Set(state.rascunhos.map((draft) => draft.id));
  Object.assign(state, {
    status: data.status, vagas: data.vagas, rascunhos: data.rascunhos, modelos: data.modelos, gmail: data.gmail,
    diasFria: data.dias_fria || 14, minhasSkills: data.minhas_skills || [],
    prefs: data.preferencias || null, exportSheets: data.abas_exportacao || [],
  });
  applyName(state.prefs ? state.prefs.nome : "JobScout");
  const cvBadge = document.getElementById("menu-cv-badge");
  cvBadge.hidden = !data.melhorias_abertas;
  cvBadge.textContent = String(data.melhorias_abertas || 0);
  for (const id of state.snoozed) if (!data.rascunhos.some((draft) => draft.id === id)) state.snoozed.delete(id);
  const fresh = state.rascunhos.some((draft) => !before.has(draft.id));
  await renderView();
  renderQueue();
  renderBubble();
  const drawer = document.getElementById("drawer");
  if (drawer.open && state.drawerJob) await renderJob();
  return fresh;
}

let refreshTimer = null;
function scheduleRefresh() {
  clearTimeout(refreshTimer);
  refreshTimer = setTimeout(() => refresh().catch(console.error), 120);
}

async function loadFeed() {
  try {
    const items = await api("/api/atividade");
    for (const item of items) {
      if (!state.feed.some((known) => known.id === item.id)) state.feed.push(item);
    }
    state.feed.sort((a, b) => b.id - a.id);
    if (state.view === "agora") renderAgora();
  } catch (error) {
    console.error(error);
  }
}

function connect() {
  const source = new EventSource("/api/stream");
  renderLive();
  setInterval(loadHealth, 60000);
  source.onopen = () => {
    health.connected = true;
    loadHealth();
    loadFeed();
    scheduleRefresh();
  };
  source.onerror = () => {
    health.connected = false;
    renderLive();
  };
  source.onmessage = (event) => {
    let message = {};
    try {
      message = JSON.parse(event.data);
    } catch (error) {
      return;
    }
    if (message.tipo === "atividade") {
      onActivity(message.item);
      return;
    }
    if (message.tipo === "rascunhos" && !state.popups && state.view !== "rascunhos") {
      document.getElementById("badge").animate([{ transform: "scale(1.4)" }, { transform: "none" }], 400);
    }
    if (message.tipo === "empresa" && (state.view === "empresas" || state.view === "empresa")) renderView();
    if (message.tipo === "lembretes") renderReminders().catch(console.error);
    if (message.tipo === "busca" && state.view === "vagas") renderAutoSearch().catch(console.error);
    scheduleRefresh();
  };
}

function setup() {
  setupTheme();
  setupOverlay();
  setupPrefs();
  setupAI();
  setupCurriculo();
  setupCvx();
  setupMensagens();
  setupMsgStyle();
  setupKanbanBoards();
  setupAutoSearch();
  setupChat();
  setupLook();
  setupBackground();
  const views = ["agora", "rascunhos", "linha", "kanban", "empresas", "busca", "vagas", "mensagens", "resultados", "curriculo", "perfil", "config"];
  const fallback = state.overlay ? "agora" : "rascunhos";
  const fromHash = () => {
    const name = location.hash.slice(1);
    const company = name.match(/^empresa\/(\d+)$/);
    if (company) {
      state.companyId = Number(company[1]);
      return "empresa";
    }
    return views.includes(name) ? name : fallback;
  };
  window.addEventListener("hashchange", () => {
    const view = fromHash();
    if (state.overlay && (state.mode === "bolha" || state.mode === "menu")) setMode(WIDE_VIEWS.has(view) ? "amplo" : "painel");
    else if (state.overlay && view === "empresa" && state.mode === "painel") setMode("amplo");
    showView(view);
  });
  for (const [id, key] of [["f-empresa", "empresa"], ["f-vaga", "vaga"], ["f-senioridade", "senioridade"], ["f-tipo", "tipo"]]) {
    document.getElementById(id).addEventListener("change", (event) => {
      filters[key] = event.target.value;
      renderMoves();
    });
  }
  document.getElementById("f-limpar").addEventListener("click", () => {
    Object.keys(filters).forEach((key) => {
      filters[key] = "";
    });
    renderTimeline();
  });
  document.getElementById("company-q").addEventListener("input", () => renderCompanies());
  document.getElementById("cold-check").addEventListener("click", async () => {
    const notice = document.getElementById("cold-notice");
    notice.textContent = "Verificando…";
    try {
      const result = await api("/api/frias/verificar", { method: "POST", json: {} });
      notice.textContent = result.rascunhos.length ? `${result.rascunhos.length} vaga(s) propostas para Fria. Veja em Rascunhos.` : "Nenhuma vaga parada.";
    } catch (error) {
      notice.textContent = error.message;
    }
  });
  for (const button of document.querySelectorAll(".seg")) {
    button.addEventListener("click", () => {
      state.filter = button.dataset.filter;
      document.querySelectorAll(".seg").forEach((item) => item.classList.toggle("is-on", item === button));
      clear(document.getElementById("draft-list"));
      renderDrafts();
    });
  }
  const toggle = document.getElementById("popup-toggle");
  toggle.checked = state.popups;
  toggle.addEventListener("change", () => setPopups(toggle.checked));

  document.getElementById("eml").addEventListener("change", async (event) => {
    const file = event.target.files[0];
    event.target.value = "";
    if (!file) return;
    const notice = document.getElementById("drafts-notice");
    const body = new FormData();
    body.append("arquivo", file, file.name);
    try {
      await api("/api/emails/importar", { method: "POST", body });
      notice.classList.remove("is-error");
      notice.textContent = `${file.name} virou rascunho.`;
      await refresh();
    } catch (error) {
      notice.classList.add("is-error");
      notice.textContent = error.message;
    }
  });


  document.getElementById("add-story").addEventListener("click", () => {
    document.getElementById("stories").appendChild(storyRow());
  });

  document.getElementById("profile-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.target;
    const data = {};
    for (const [key] of PROFILE_FIELDS) data[key] = form.elements[key].value;
    for (const [key] of QUICK_FIELDS) data[key] = form.elements[key].value;
    data.modelos_trabalho = [...form.querySelectorAll("[data-mode]")].filter((box) => box.checked).map((box) => box.dataset.mode).join(", ");
    data.historias = [...document.querySelectorAll("#stories .story")].map((row) => ({
      titulo: row.querySelector('[data-story="titulo"]').value,
      texto: row.querySelector('[data-story="texto"]').value,
    }));
    const notice = document.getElementById("profile-notice");
    try {
      await api("/api/perfil", { method: "PUT", json: data });
      notice.textContent = "Perfil salvo.";
      clear(document.getElementById("profile-fields"));
      await renderProfile();
    } catch (error) {
      notice.textContent = error.message;
    }
  });

  document.getElementById("resume").addEventListener("change", async (event) => {
    const file = event.target.files[0];
    event.target.value = "";
    if (!file) return;
    const notice = document.getElementById("profile-notice");
    notice.textContent = "Lendo o currículo neste computador…";
    const body = new FormData();
    body.append("arquivo", file, file.name);
    try {
      const result = await api("/api/analisar", { method: "POST", body });
      const saved = await api("/api/perfil");
      if (!(saved.curriculo || "").trim()) await api("/api/perfil", { method: "PUT", json: { curriculo: result.texto || "" } });
      let added = 0;
      for (const group of result.grupos) {
        for (const activity of group.atividades) {
          document.getElementById("stories").appendChild(storyRow({ titulo: group.contexto || group.secao, texto: activity }));
          added += 1;
        }
      }
      notice.textContent = `${added} atividade(s) viraram histórias. Remova as que não quiser e salve.`;
    } catch (error) {
      notice.textContent = error.message;
    }
  });

  const modal = document.getElementById("job-modal");
  document.getElementById("add-job").addEventListener("click", () => {
    const select = document.getElementById("job-form-status");
    clear(select);
    for (const item of state.status) select.appendChild(h("option", { value: item.chave, text: item.nome }));
    document.getElementById("job-form").reset();
    document.getElementById("job-form-notice").textContent = "";
    modal.showModal();
  });
  document.getElementById("job-cancel").addEventListener("click", () => modal.close());
  document.getElementById("job-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.target;
    const data = Object.fromEntries(new FormData(form).entries());
    try {
      const job = await api("/api/vagas", { method: "POST", json: data });
      modal.close();
      await refresh();
      openJob(job.id);
    } catch (error) {
      document.getElementById("job-form-notice").textContent = error.message;
    }
  });

  showView(fromHash());
  refresh().catch(console.error);
  connect();
}

setup();
