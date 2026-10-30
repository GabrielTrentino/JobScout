// Barra de resposta nos chats (LinkedIn, WhatsApp Web, Gmail): lê a conversa, pede a resposta ao JobScout
// no formato do canal e insere no campo. Nunca envia: quem aperta Enviar é a pessoa.
(function () {
  "use strict";

  const core = globalThis.JobScoutCore;
  let adapter = null;
  const bars = new WeakMap();
  const floating = new Map();

  function send(message) {
    return new Promise((resolve) => {
      try {
        chrome.runtime.sendMessage(message, (response) => {
          if (chrome.runtime.lastError) resolve(null);
          else resolve(response || null);
        });
      } catch (error) {
        resolve(null);
      }
    });
  }

  function text(node) {
    return node ? (node.innerText || node.textContent || "").replace(/\s+/g, " ").trim() : "";
  }

  // Insere linha a linha: Enter no WhatsApp/LinkedIn envia, então a quebra entra como quebra de linha.
  function insertInto(composer, value) {
    composer.focus();
    const lines = String(value || "").split("\n");
    lines.forEach((line, index) => {
      if (line) document.execCommand("insertText", false, line);
      if (index < lines.length - 1) document.execCommand("insertLineBreak");
    });
    composer.dispatchEvent(new InputEvent("input", { bubbles: true }));
  }

  const STYLE = `
    :host { all: initial; display: block; margin: 4px 0; font: 13px/1.4 "Segoe UI", system-ui, sans-serif; color: #16202a; }
    [hidden] { display: none !important; }
    .pill { display: inline-flex; align-items: center; gap: 6px; padding: 3px 10px; border-radius: 999px; border: 1px solid #c8d8ea;
      background: #eef4fb; color: #1d4f86; font: 600 12px "Segoe UI", system-ui, sans-serif; cursor: pointer; }
    .bar { display: grid; gap: 6px; padding: 8px 10px; border: 1px solid #c8d8ea; border-radius: 10px; background: #f6f9fd; max-height: 70vh; overflow: auto; box-sizing: border-box; width: 100%; }
    :host([data-floating]) .bar, :host([data-floating]) .pill { box-shadow: 0 4px 14px rgba(0, 0, 0, .18); }
    .top { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; justify-content: space-between; }
    .title { font-weight: 700; color: #1d4f86; }
    .meta { color: #4a5a68; font-size: 12px; }
    .chips { display: flex; flex-wrap: wrap; gap: 4px; }
    button { font: 600 12px "Segoe UI", system-ui, sans-serif; border-radius: 999px; border: 1px solid #c8d8ea; background: #fff; color: #16202a; padding: 3px 9px; cursor: pointer; }
    button:hover { border-color: #2f6fb3; color: #1d4f86; }
    button.main { background: #2f6fb3; border-color: #2f6fb3; color: #fff; }
    button[disabled] { opacity: .6; cursor: default; }
    select, input, textarea { font: 13px "Segoe UI", system-ui, sans-serif; border: 1px solid #c8d8ea; border-radius: 6px; padding: 4px 6px; background: #fff; color: #16202a; }
    textarea { width: 100%; box-sizing: border-box; min-height: 72px; resize: vertical; }
    .row { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
    .x { border: 0; background: transparent; font-size: 15px; padding: 0 4px; }
    @media (prefers-color-scheme: dark) {
      :host { color: #e6edf3; }
      .bar { background: #16202b; border-color: #33465a; }
      .pill { background: #1b2633; border-color: #33465a; color: #8fbef0; }
      .title { color: #8fbef0; } .meta { color: #9fb0c0; }
      button, select, input, textarea { background: #0f1720; color: #e6edf3; border-color: #33465a; }
      button.main { background: #2f6fb3; color: #fff; }
    }`;

  function el(tag, attrs, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs || {})) {
      if (value === null || value === undefined || value === false) continue;
      if (key === "text") node.textContent = value;
      else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
      else node.setAttribute(key, value === true ? "" : value);
    }
    for (const child of children.flat()) if (child) node.append(child);
    return node;
  }

  function buildBar(composer) {
    const host = document.createElement("div");
    host.dataset.jobscoutChat = "1";
    const root = host.attachShadow({ mode: "open" });
    const style = el("style", { text: STYLE });
    const state = { context: null, last: null, intent: null };
    const pill = el("button", { class: "pill", type: "button", title: "Sugerir uma resposta para esta conversa" }, "JobScout · responder");
    const bar = el("div", { class: "bar", hidden: true });
    root.append(style, pill, bar);

    const meta = el("span", { class: "meta" });
    const jobSelect = el("select", { "aria-label": "Vaga desta conversa" });
    const detail = el("input", { placeholder: "Algo mais para dizer (opcional)", "aria-label": "Algo mais para dizer" });
    const chips = el("div", { class: "chips" });
    const status = el("span", { class: "meta" });
    const subject = el("input", { placeholder: "Assunto", hidden: adapter.canal !== "email" });
    const output = el("textarea", { "aria-label": "Resposta sugerida" });
    const result = el("div", { hidden: true }, subject, output);
    const insert = el("button", { class: "main", type: "button", text: "Inserir na conversa" });
    const again = el("button", { type: "button", text: "Outra versão" });
    const actions = el("div", { class: "row", hidden: true }, insert, again);
    const close = el("button", { class: "x", type: "button", title: "Fechar", text: "×" });
    bar.append(
      el("div", { class: "top" }, el("span", { class: "title", text: `JobScout · ${({ linkedin: "LinkedIn", whatsapp: "WhatsApp", email: "E-mail" })[adapter.canal]}` }), close),
      el("div", { class: "row" }, jobSelect, meta),
      chips, detail, result, actions, status,
    );

    async function loadContext() {
      const convo = adapter.read(composer);
      status.textContent = "Lendo a conversa…";
      const response = await send({ kind: "chat_context", dados: { nome: convo.nome, email: convo.email, linkedin: convo.linkedin, telefone: convo.telefone, texto: convo.turnos.map((turn) => turn.texto).join(" ").slice(0, 3000) } });
      if (!response || response.erro) {
        status.textContent = "O JobScout não respondeu. Ele está aberto?";
        return;
      }
      state.context = response;
      while (jobSelect.firstChild) jobSelect.firstChild.remove();
      jobSelect.append(el("option", { value: "", text: "Vaga: descobrir pela conversa" }));
      // O JobScout já escolheu: a empresa citada na conversa, senão a vaga vinculada à pessoa.
      const preferred = response.vaga_sugerida;
      for (const job of response.vagas) {
        jobSelect.append(el("option", { value: String(job.id), text: `${job.titulo || "(sem título)"} — ${job.empresa || ""}`, selected: preferred && preferred.id === job.id }));
      }
      meta.textContent = response.recrutador
        ? `${response.recrutador.name || convo.nome}: ${response.recrutador.vagas.length} vaga(s) vinculada(s)`
        : convo.nome ? `${convo.nome} ainda não está vinculada a uma vaga (escolha e ela fica vinculada)` : "";
      while (chips.firstChild) chips.firstChild.remove();
      for (const intent of response.intencoes) {
        chips.append(el("button", { type: "button", text: intent.nome, title: intent.instrucao, onclick: () => reply(intent.chave) }));
      }
      status.textContent = convo.turnos.length ? `${convo.turnos.length} mensagem(ns) lida(s) da conversa.` : "Não achei mensagens nesta conversa; a resposta sai do modelo.";
    }

    async function reply(intent) {
      state.intent = intent;
      const convo = adapter.read(composer);
      if (jobSelect.value && !(state.context.recrutador && state.context.recrutador.vagas.some((job) => String(job.id) === jobSelect.value)) && convo.nome) {
        // Escolheu a vaga desta conversa: a pessoa fica vinculada a ela.
        const linked = await send({ kind: "chat_link", dados: { nome: convo.nome, email: convo.email, linkedin: convo.linkedin, telefone: convo.telefone, vaga_id: Number(jobSelect.value) } });
        if (linked && !linked.erro) {
          state.context.recrutador = linked;
          meta.textContent = `${linked.name}: vinculada a ${linked.vagas.length} vaga(s)`;
        }
      }
      status.textContent = "Escrevendo a resposta…";
      for (const button of chips.querySelectorAll("button")) button.disabled = true;
      const response = await send({
        kind: "reply",
        dados: {
          intencao: intent, canal: adapter.canal, conversa: convo.turnos, recrutador: convo.nome,
          vaga_id: jobSelect.value ? Number(jobSelect.value) : null,
          contato_id: state.context.recrutador ? state.context.recrutador.id : null,
          detalhe: detail.value,
        },
      });
      for (const button of chips.querySelectorAll("button")) button.disabled = false;
      if (!response || response.erro) {
        status.textContent = (response && response.erro) || "O JobScout não respondeu. Ele está aberto?";
        return;
      }
      state.last = response;
      result.hidden = false;
      actions.hidden = false;
      output.value = response.texto;
      subject.value = response.assunto || "";
      status.textContent = response.origem === "ia" ? `Escrita por ${response.modelo}${response.vaga ? " · " + response.vaga : ""}. Confira antes de enviar.` : `Texto pronto${response.vaga ? " · " + response.vaga : ""}. Edite se quiser.`;
    }

    host.jobscout = { pill, status };
    pill.addEventListener("click", async () => {
      pill.hidden = true;
      bar.hidden = false;
      // A mesma caixa de mensagem serve a várias conversas (WhatsApp): relê sempre ao abrir.
      await loadContext();
    });
    close.addEventListener("click", () => {
      bar.hidden = true;
      pill.hidden = false;
    });
    again.addEventListener("click", () => state.intent && reply(state.intent));
    insert.addEventListener("click", () => {
      adapter.insert(composer, output.value, subject.value);
      status.textContent = "Inserida. Revise na caixa de mensagem e envie você mesmo.";
    });
    return host;
  }

  // Flutuante (WhatsApp): a página reorganiza e cobre o que entra no meio dela, então a barra fica
  // no <body>, presa logo acima da caixa de mensagem, abrindo para cima.
  function place(host, composer) {
    const anchor = adapter.anchor(composer) || composer;
    const box = anchor.getBoundingClientRect();
    const hide = !composer.isConnected || box.width === 0;
    host.style.display = hide ? "none" : "flex";
    if (hide) return;
    host.style.left = `${Math.max(8, box.left + 8)}px`;
    host.style.bottom = `${Math.max(8, window.innerHeight - box.top + 6)}px`;
    host.style.width = `${Math.min(520, Math.max(260, box.width - 16))}px`;
  }

  // Recrutador oferecendo vaga nova na conversa aberta: o JobScout cria um rascunho de oportunidade.
  // Só manda de novo quando a conversa muda (outra pessoa ou mensagem nova dela).
  const approached = new WeakMap();

  async function checkApproach(composer, host) {
    if (adapter.canal === "email" || !host.jobscout) return;
    let convo;
    try {
      convo = adapter.read(composer);
    } catch (error) {
      return;
    }
    const theirs = convo.turnos.filter((turn) => !turn.minha);
    if (!theirs.length) return;
    const key = `${convo.nome}|${convo.telefone}|${theirs.length}|${theirs[theirs.length - 1].texto.slice(0, 80)}`;
    if (approached.get(host) === key) return;
    approached.set(host, key);
    const response = await send({ kind: "chat_approach", dados: {
      canal: adapter.canal, nome: convo.nome, email: convo.email, linkedin: convo.linkedin, telefone: convo.telefone, conversa: convo.turnos,
    } });
    if (!response || response.erro || !host.jobscout) return;
    const { pill, status } = host.jobscout;
    const label = response.vaga ? [response.vaga.titulo, response.vaga.empresa].filter(Boolean).join(" — ") : "";
    if (response.estado === "novo" || response.estado === "rascunho") {
      pill.textContent = "JobScout · responder · oportunidade nova";
      pill.title = `${label || "Vaga oferecida nesta conversa"}: aprove em Rascunhos no JobScout para virar oportunidade.`;
      status.textContent = `Oportunidade detectada (${label}). Aprove em Rascunhos no JobScout.`;
    } else {
      pill.textContent = "JobScout · responder";
      pill.title = "Sugerir uma resposta para esta conversa";
    }
  }

  function scan() {
    for (const composer of adapter.composers()) {
      if (bars.has(composer) || !composer.isConnected) continue;
      const anchor = adapter.anchor(composer);
      if (!anchor || !anchor.parentElement) continue;
      const host = buildBar(composer);
      if (adapter.floating) {
        for (const [, other] of floating) other.remove();
        floating.clear();
        host.dataset.floating = "1";
        host.style.cssText = "position:fixed;z-index:2147483000;display:flex;flex-direction:column;align-items:flex-start;";
        document.body.append(host);
        floating.set(composer, host);
        place(host, composer);
      } else {
        anchor.parentElement.insertBefore(host, anchor);
      }
      bars.set(composer, host);
    }
    for (const composer of adapter.composers()) {
      const host = bars.get(composer);
      if (host) checkApproach(composer, host).catch(() => {});
    }
    for (const [composer, host] of floating) {
      if (!composer.isConnected) {
        host.remove();
        floating.delete(composer);
      } else {
        place(host, composer);
      }
    }
  }

  function start(siteAdapter) {
    adapter = { insert: (composer, value) => insertInto(composer, value), ...siteAdapter };
    const observer = new MutationObserver(() => {
      clearTimeout(start.timer);
      start.timer = setTimeout(scan, 600);
    });
    observer.observe(document.documentElement, { childList: true, subtree: true });
    setInterval(scan, 3000);
    if (adapter.floating) {
      const follow = () => { for (const [composer, host] of floating) place(host, composer); };
      window.addEventListener("resize", follow);
      setInterval(follow, 500);
    }
    scan();
  }

  // "hoje" ou "antes" a partir de um divisor ("Hoje", "Ontem", "29/10/2026") ou de uma data d/m/a.
  function dayOf(label) {
    const value = String(label || "").trim().toLowerCase();
    if (!value) return "";
    if (/^(hoje|today|hoy)/.test(value)) return "hoje";
    const match = value.match(/(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})/);
    if (match) {
      const now = new Date();
      const year = Number(match[3]) < 100 ? 2000 + Number(match[3]) : Number(match[3]);
      const a = Number(match[1]), b = Number(match[2]);
      const same = (day, month) => year === now.getFullYear() && month === now.getMonth() + 1 && day === now.getDate();
      return same(a, b) || same(b, a) ? "hoje" : "antes";
    }
    return "antes";
  }

  globalThis.JobScoutChat = { start, text, insertInto, dayOf, fold: core ? core.fold : (value) => String(value || "").toLowerCase() };
})();
