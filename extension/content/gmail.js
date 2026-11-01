// Gmail: a caixa de resposta (ou de nova mensagem) ganha a barra; a resposta sai em formato de e-mail,
// com saudação e assinatura. O assunto só é preenchido numa mensagem nova, com o campo vazio.
(function () {
  "use strict";

  const chat = globalThis.JobScoutChat;
  const COMPOSER = "div[contenteditable='true'][g_editable='true'], div[contenteditable='true'][role='textbox'][aria-label]";

  function read(composer) {
    const main = document.querySelector("[role='main']") || document;
    const turns = [];
    for (const message of main.querySelectorAll("div.adn, div.gs")) {
      const sender = message.querySelector("span.gD[email], span[email].gD");
      const body = chat.text(message.querySelector("div.a3s"));
      if (!body) continue;
      const name = sender ? sender.getAttribute("name") || chat.text(sender) : "";
      turns.push({ autor: name, email: sender ? sender.getAttribute("email") : "", texto: body.slice(0, 1500), minha: /^(eu|me|mim)$/i.test(name) });
    }
    const others = turns.filter((turn) => !turn.minha);
    const last = others[others.length - 1] || {};
    return { nome: last.autor || "", email: last.email || "", telefone: "", linkedin: "", turnos: turns.slice(-8) };
  }

  function insert(composer, value, subject) {
    const form = composer.closest("form, [role='dialog'], table") || document;
    const box = form.querySelector("input[name='subjectbox']");
    if (box && subject && !box.value) {
      box.focus();
      box.value = subject;
      box.dispatchEvent(new Event("input", { bubbles: true }));
    }
    chat.insertInto(composer, value);
  }

  if (chat) {
    chat.start({
      canal: "email",
      composers: () => [...document.querySelectorAll(COMPOSER)].filter((node) => node.offsetParent !== null),
      anchor: (composer) => composer.closest("table") || composer,
      read,
      insert,
    });
  }
})();
