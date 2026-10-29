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
const WIDE_VIEWS = new Set(["kanban", "empresa"]);
const CLASSES = {
  entrevista: "Convite para entrevista",
  rejeicao: "Rejeição",
  documento: "Pedido de documento",
  outro: "Outro",
};
const SOURCES = { linkedin: "LinkedIn", inhire: "InHire", email: "E-mail", manual: "Manual", painel: "Painel" };
const PROFILE_FIELDS = [
  ["nome", "Nome completo"],
  ["email", "E-mail"],
  ["telefone", "Telefone"],
  ["cidade", "Cidade"],
  ["linkedin", "LinkedIn"],
  ["github", "GitHub"],
  ["portfolio", "Portfólio"],
  ["pretensao_salarial", "Pretensão salarial"],
  ["disponibilidade", "Disponibilidade"],
];

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
  if (!answers.length) return null;
  const keep = h("input", { type: "checkbox", checked: p.guardar_respostas !== false, disabled: !pending });
  const node = h("details", {},
    h("summary", { text: `Respostas do formulário (${answers.length})` }),
    h("ul", { class: "answers-list" }, answers.map((item) => h("li", {}, h("strong", { text: item.rotulo }), item.valor))),
    h("label", { class: "check" }, keep, "Guardar estas respostas para preencher formulários futuros"),
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
    state.throwUntil = Date.now() + 2400;
    setTimeout(renderBubble, 2450);
  }
  if (state.view === "agora") {
    renderFeed();
    renderStatusLine();
  }
  renderBubble();
  showToast(item);
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

// Overlay: bolha no canto, menu, pop-ups e painéis

function bridge() {
  return window.pywebview && window.pywebview.api ? window.pywebview.api : null;
}

// Pede à janela o tamanho do formato atual. Bolha e menu medem o próprio conteúdo.
function fitWindow() {
  if (!state.overlay) return;
  const api = bridge();
  if (!api) return;
  requestAnimationFrame(() => {
    const compact = state.mode === "bolha" || state.mode === "menu";
    const dock = document.getElementById("dock");
    const height = compact ? Math.ceil([...dock.children].reduce((sum, node) => sum + (node.hidden ? 0 : node.offsetHeight), 0) + 2) : 0;
    api.formato(state.mode, height);
  });
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
  count.textContent = String(pending);
  // Boneco: arremessa a maleta logo depois do envio, pensa enquanto lê uma vaga, senta quando está parado.
  const pose = Date.now() < state.throwUntil ? "throw" : working ? "think" : "idle";
  const stickman = document.getElementById("stickman");
  if (stickman.dataset.pose !== pose) stickman.dataset.pose = pose;
  const sub = document.getElementById("bubble-sub");
  sub.classList.toggle("has-pending", Boolean(pending) && !working);
  if (working && state.feed[0]) sub.textContent = state.feed[0].texto;
  else if (pending) sub.textContent = `${pending} rascunho${pending > 1 ? "s" : ""} pendente${pending > 1 ? "s" : ""}`;
  else sub.textContent = "Tudo em dia";
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
  document.getElementById("bubble").addEventListener("click", () => setMode(state.mode === "menu" ? "bolha" : "menu"));
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
    button.addEventListener("click", () => {
      if (!confirm("Fechar o JobScout? A extensão guarda o que capturar e envia quando você abrir de novo.")) return;
      const api = bridge();
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
  document.getElementById("kanban-lede").textContent =
    `Arraste o cartão para mudar o status. A coluna Rascunho espera a sua aprovação; vaga parada há ${state.diasFria} dias vira proposta para Fria.`;
  boardInto(document.getElementById("board"), state.vagas, state.rascunhos.filter((draft) => draft.kind === "vaga"));
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
      const open = ["candidatado", "em_analise", "entrevista", "proposta"].includes(job.status);
      const card = h("button", { type: "button", class: "card", draggable: "true", onclick: () => openJob(job.id) },
        h("strong", { text: job.title || "Vaga sem título" }),
        h("span", { class: "company", text: job.company || "" }),
        h("span", { class: "when", text: " · " + (job.seniority ? job.seniority + " · " : "") + when(job.status_at) }),
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
  fields.appendChild(h("label", { style: "grid-column: 1 / -1" }, "Texto do currículo", h("textarea", { name: "curriculo", rows: 6, value: profile.curriculo || "" })));
  const stories = document.getElementById("stories");
  clear(stories);
  for (const story of profile.historias || []) stories.appendChild(storyRow(story));
  await renderHistory();
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

function storyRow(story = { titulo: "", texto: "" }) {
  const row = h("div", { class: "story" },
    h("input", { "data-story": "titulo", value: story.titulo, placeholder: "Título (ex.: Migração para PostgreSQL)" }),
    h("button", { type: "button", class: "danger", text: "Remover", onclick: () => row.remove() }),
    h("textarea", { "data-story": "texto", value: story.texto, placeholder: "O que você fez e o resultado, com números reais" }),
  );
  return row;
}

function renderConfig() {
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
  const models = document.getElementById("models");
  clear(models);
  const names = { classificar: "Classificar e-mails", resumir: "Resumir", responder: "Respostas abertas", preparar: "Preparar entrevista" };
  for (const [task, value] of Object.entries(state.modelos)) {
    models.append(h("dt", { text: names[task] || task }), h("dd", { text: value }));
  }
  const gmail = document.getElementById("gmail");
  clear(gmail);
  const g = state.gmail;
  if (!g.configurado) {
    gmail.append(
      h("p", { text: "Desligado. Para ligar, crie um cliente OAuth do tipo “App para computador” no Google Cloud e preencha no .env:" }),
      h("p", {}, h("code", { text: "JOBSCOUT_GMAIL_CLIENT_ID" }), " e ", h("code", { text: "JOBSCOUT_GMAIL_CLIENT_SECRET" })),
      h("p", { class: "hint", text: "Escopo somente leitura. Enquanto isso, use “Importar e-mail (.eml)” na aba Rascunhos." }),
    );
  } else if (!g.conectado) {
    gmail.append(h("p", { text: "Configurado, ainda não conectado." }), h("a", { class: "file-button", href: "/api/gmail/conectar", text: "Conectar Gmail (somente leitura)" }));
  } else {
    const notice = h("p", { class: "notice", role: "status" });
    gmail.append(
      h("p", { text: `Conectado. Verifica a cada ${g.intervalo_min} min.` }),
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
    h("p", {}, h("a", { href: job.url, target: "_blank", rel: "noopener", text: "Abrir a vaga ↗" })),
    detail.parada_dias !== null && detail.parada_dias >= Math.ceil(state.diasFria / 2)
      ? h("p", { class: "chip is-warn", text: `Sem movimento há ${detail.parada_dias} dias` }) : null,
    h("label", {}, "Status", status),
  );
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
  body.appendChild(h("section", {},
    h("h3", { class: "tab", text: "Respostas enviadas" }),
    detail.respostas.length ? null : h("p", { class: "empty", text: "Nenhuma resposta salva." }),
    detail.respostas.map((answer) => h("div", { class: "qa" },
      h("p", {}, h("strong", { text: answer.question })),
      h("p", { text: answer.answer }),
      answer.suggested_by_llm ? h("span", { class: "chip", text: "sugerida pela IA, aprovada por você" }) : null,
      answer.origin === "formulario" ? h("span", { class: "chip", text: "lida do formulário no envio" }) : null,
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
    } else if (state.view === "config") renderConfig();
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
  });
  document.title = (state.rascunhos.length ? `(${state.rascunhos.length}) ` : "") + "JobScout — Painel";
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
  const live = document.getElementById("live");
  const source = new EventSource("/api/stream");
  const lives = [live, document.getElementById("overlay-live")];
  source.onopen = () => {
    lives.forEach((node) => {
      node.textContent = "ao vivo";
      node.classList.add("is-on");
    });
    loadFeed();
    scheduleRefresh();
  };
  source.onerror = () => {
    lives.forEach((node) => {
      node.textContent = "reconectando";
      node.classList.remove("is-on");
    });
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
    scheduleRefresh();
  };
}

function setup() {
  setupTheme();
  setupOverlay();
  const views = ["agora", "rascunhos", "linha", "kanban", "empresas", "busca", "perfil", "config"];
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

  document.getElementById("search-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const list = document.getElementById("results");
    clear(list);
    const rows = await api("/api/buscar?q=" + encodeURIComponent(document.getElementById("search-q").value));
    if (!rows.length) list.appendChild(h("li", { class: "empty", text: "Nada encontrado." }));
    const kinds = { vaga: "Vaga", resposta: "Resposta", mensagem: "Mensagem", nota: "Nota" };
    for (const row of rows) {
      list.appendChild(h("li", {},
        h("p", { class: "eyebrow", text: `${kinds[row.tipo]} · ${row.vaga} · ${when(row.quando)}` }),
        h("p", {}, h("strong", { text: row.titulo })),
        h("p", { text: row.texto }),
        row.job_id ? h("a", { href: "#", text: "Abrir vaga", onclick: (e) => {
          e.preventDefault();
          openJob(row.job_id);
        } }) : null,
      ));
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
    data.curriculo = form.elements.curriculo.value;
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
      const form = document.getElementById("profile-form");
      if (!form.elements.curriculo.value.trim()) form.elements.curriculo.value = result.texto || "";
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
