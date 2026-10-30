// WhatsApp Web: a conversa aberta ganha a barra de resposta (curta, sem assinatura). Só lê e insere no campo.
(function () {
  "use strict";

  const chat = globalThis.JobScoutChat;
  const COMPOSER = "#main footer div[contenteditable='true'][role='textbox'], #main footer div[contenteditable='true']";
  // "[10:31, 29/10/2026] Carla RH: " vem no atributo de cada mensagem.
  const META = /^\[[^\]]*\]\s*([^:]+):\s*$/;

  function read() {
    const main = document.getElementById("main") || document;
    const header = main.querySelector("header");
    const titled = header && header.querySelector("span[dir='auto'][title], span[title]");
    const name = (titled && titled.getAttribute("title")) || chat.text(header && header.querySelector("span[dir='auto']")) || "";
    const phone = /^\+?[\d\s()-]{8,}$/.test(name) ? name : "";
    const turns = [];
    for (const row of main.querySelectorAll("div.message-in, div.message-out")) {
      const box = row.querySelector(".copyable-text[data-pre-plain-text]");
      const meta = box ? box.getAttribute("data-pre-plain-text") || "" : "";
      const match = meta.match(META);
      const body = chat.text(row.querySelector("span.selectable-text, .copyable-text span[dir]"));
      if (!body) continue;
      const mine = row.classList.contains("message-out");
      const when = meta.match(/\[([^\]]*)\]/);
      turns.push({ autor: mine ? "" : (match ? match[1].trim() : name), texto: body, minha: mine, dia: when ? chat.dayOf(when[1].split(",").pop()) : "" });
    }
    return { nome: phone ? "" : name, telefone: phone, email: "", linkedin: "", turnos: turns.slice(-12) };
  }

  if (chat) {
    chat.start({
      canal: "whatsapp",
      composers: () => [...document.querySelectorAll(COMPOSER)].slice(0, 1),
      anchor: (composer) => composer.closest("footer") || composer,
      floating: true,
      read,
    });
  }
})();
