// Assistente da página aberta: um botão discreto no canto. O texto da página só vai para o JobScout
// (neste computador) quando a pessoa abre o painel. Só roda com a opção ligada no popup.
(function () {
  "use strict";

  // 127.0.0.1 e localhost: é o próprio painel do JobScout.
  if (globalThis.__jobscoutAssist || window.top !== window || /^(127\.0\.0\.1|localhost)$/.test(location.hostname)) return;
  globalThis.__jobscoutAssist = true;

  const LABELS = { vaga: "Vaga", freela: "Freela", outra: "Página" };
  const STYLE = `
    :host { all: initial; position: fixed; right: 16px; bottom: 16px; z-index: 2147483000; font: 13px/1.4 "Segoe UI", system-ui, sans-serif; color: #16202a; }
    [hidden] { display: none !important; }
    button { font: 600 12px "Segoe UI", system-ui, sans-serif; border-radius: 999px; border: 1px solid #c8d8ea; background: #fff; color: #16202a; padding: 4px 10px; cursor: pointer; }
    button:hover { border-color: #2f6fb3; color: #1d4f86; }
    button.main { background: #2f6fb3; border-color: #2f6fb3; color: #fff; }
    button[disabled] { opacity: .6; cursor: default; }
    .pill { background: #eef4fb; color: #1d4f86; box-shadow: 0 3px 12px rgba(0,0,0,.2); padding: 6px 12px; }
    .panel { width: 320px; max-height: min(70vh, 560px); overflow: auto; box-sizing: border-box; padding: 10px 12px; border: 1px solid #c8d8ea; border-radius: 12px; background: #f6f9fd; box-shadow: 0 8px 28px rgba(0,0,0,.25); display: grid; gap: 8px; }
    .top { display: flex; justify-content: space-between; align-items: center; gap: 6px; }
    .title { font-weight: 700; color: #1d4f86; }
    .x { border: 0; background: transparent; font-size: 16px; padding: 0 4px; }
    .muted { color: #4a5a68; font-size: 12px; }
    .row { display: flex; flex-wrap: wrap; gap: 5px; }
    .tag { font-size: 12px; padding: 1px 7px; border-radius: 999px; background: #e7f4ec; color: #1f6b43; }
    .tag.no { background: #eceff3; color: #4a5a68; }
    .out { white-space: pre-wrap; background: #fff; border: 1px solid #dde3ea; border-radius: 8px; padding: 7px 9px; }
    a { color: #1d4f86; }
    @media (prefers-color-scheme: dark) {
      :host { color: #e6edf3; }
      .panel { background: #16202b; border-color: #33465a; }
      .pill { background: #1b2633; border-color: #33465a; color: #8fbef0; }
      .title { color: #8fbef0; } .muted { color: #9fb0c0; }
      button { background: #0f1720; color: #e6edf3; border-color: #33465a; }
      button.main { background: #2f6fb3; color: #fff; }
      .tag { background: #16352a; color: #7fd3a5; } .tag.no { background: #243140; color: #9fb0c0; }
      .out { background: #0f1720; border-color: #33465a; }
    }`;

  function send(message) {
    return new Promise((resolve) => {
      try {
        chrome.runtime.sendMessage(message, (response) => resolve(chrome.runtime.lastError ? null : response || null));
      } catch (error) {
        resolve(null);
      }
    });
  }

  function el(tag, attrs, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs || {})) {
      if (key === "text") node.textContent = value;
      else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
      else node.setAttribute(key, value);
    }
    node.append(...children.flat().filter(Boolean));
    return node;
  }

  function meta(name) {
    const node = document.querySelector(`meta[property='${name}'], meta[name='${name}']`);
    return node ? node.content || "" : "";
  }

  // innerText não traz o que foi digitado em campos: senha e cartão nunca entram no texto lido.
  function pageData() {
    const selection = String(window.getSelection() || "").trim();
    const heading = document.querySelector("h1");
    return {
      url: location.href.split("#")[0],
      titulo: (heading && heading.innerText.trim()) || meta("og:title") || document.title,
      empresa: meta("og:site_name"),
      texto: (selection || document.body.innerText || "").slice(0, 20000),
    };
  }

  function build() {
    const host = el("div", { "data-jobscout-assist": "1" });
    const root = host.attachShadow({ mode: "open" });
    const pill = el("button", { class: "pill", type: "button", title: "O que o JobScout sabe sobre esta página", text: "JobScout" });
    const body = el("div");
    const output = el("div", { class: "out", hidden: "" });
    const status = el("span", { class: "muted" });
    const close = el("button", { class: "x", type: "button", title: "Fechar", text: "×" });
    const panel = el("div", { class: "panel", hidden: "" }, el("div", { class: "top" }, el("span", { class: "title", text: "JobScout nesta página" }), close), body, output, status);
    root.append(el("style", { text: STYLE }), pill, panel);

    const askAI = (pedido, button) => async () => {
      button.disabled = true;
      status.textContent = "A IA está lendo a página…";
      const response = await send({ kind: "page_ai", dados: { ...pageData(), pedido } });
      button.disabled = false;
      if (!response || response.erro) {
        status.textContent = (response && response.erro) || "O JobScout não respondeu. Ele está aberto?";
        return;
      }
      status.textContent = `Escrito por ${response.modelo}. Confira antes de usar.`;
      output.hidden = false;
      output.textContent = response.texto;
    };

    const save = (como, button) => async () => {
      button.disabled = true;
      const response = await send({ kind: "page_save", dados: { ...pageData(), como } });
      if (!response || response.erro) {
        button.disabled = false;
        status.textContent = (response && response.erro) || "O JobScout não respondeu. Ele está aberto?";
        return;
      }
      status.textContent = como === "vaga" ? "Enviada para Rascunhos: aprove no JobScout." : "Salvo na aba Freela do JobScout.";
    };

    function render(info) {
      const lines = [el("div", { class: "muted", text: [LABELS[info.tipo], info.plataforma].filter(Boolean).join(" · ") })];
      if (info.vaga) lines.push(el("div", { text: `Já salva: ${info.vaga.titulo} (${info.vaga.status})` }));
      if (info.freela) lines.push(el("div", { text: `Já está no Freela: ${info.freela.title || info.freela.client}` }));
      if (info.mesma_empresa.length) lines.push(el("div", { class: "muted", text: `Você tem ${info.mesma_empresa.length} vaga(s) desta empresa.` }));
      if (info.encaixe !== null) lines.push(el("div", { text: `Encaixe: ${info.encaixe}% das skills citadas estão no seu perfil` }));
      if (info.habilidades.length) {
        lines.push(el("div", { class: "row" },
          info.tem.map((name) => el("span", { class: "tag", text: name })),
          info.faltam.map((name) => el("span", { class: "tag no", text: name }))));
      }
      if (info.valores.length) lines.push(el("div", { class: "muted", text: `Valores citados: ${info.valores.join(", ")}` }));
      const actions = el("div", { class: "row" });
      const add = (text, handler, main) => {
        const button = el("button", { type: "button", class: main ? "main" : "", text });
        button.addEventListener("click", handler(button));
        actions.append(button);
      };
      if (info.tipo === "freela" && !info.freela) add("Salvar no Freela", (button) => save("freela", button), true);
      if (info.tipo === "vaga" && !info.vaga) add("Salvar como vaga", (button) => save("vaga", button), true);
      if (info.tipo === "outra") {
        add("Salvar como vaga", (button) => save("vaga", button));
        add("Salvar no Freela", (button) => save("freela", button));
      }
      if (info.ia) {
        add("Resumir", (button) => askAI("resumo", button));
        add("Encaixe com meu perfil", (button) => askAI("encaixe", button));
        if (info.tipo !== "outra") add("Escrever proposta", (button) => askAI("proposta", button));
      } else {
        lines.push(el("div", { class: "muted", text: "Ligue a IA em Config para resumir e escrever propostas." }));
      }
      body.replaceChildren(el("div", { style: "display:grid;gap:6px" }, lines, actions));
    }

    pill.addEventListener("click", async () => {
      pill.hidden = true;
      panel.hidden = false;
      output.hidden = true;
      status.textContent = "Lendo a página…";
      const info = await send({ kind: "page_context", dados: pageData() });
      if (!info || info.erro) {
        status.textContent = (info && info.erro) || "O JobScout não respondeu. Ele está aberto?";
        return;
      }
      status.textContent = window.getSelection().toString().trim() ? "Lido só o trecho selecionado." : "";
      render(info);
    });
    close.addEventListener("click", () => {
      panel.hidden = true;
      pill.hidden = false;
    });
    document.documentElement.appendChild(host);
    return host;
  }

  let host = null;
  const toggle = (on) => {
    if (on && !host) host = build();
    if (!on && host) {
      host.remove();
      host = null;
    }
  };
  try {
    chrome.storage.local.get({ assistAny: false }, (stored) => toggle(stored.assistAny));
    chrome.storage.onChanged.addListener((changes) => {
      if (changes.assistAny) toggle(changes.assistAny.newValue);
    });
  } catch (error) {
    // Extensão recarregada: vale a partir do próximo carregamento da página.
  }
})();
