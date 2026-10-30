// Adaptador do LinkedIn: todos os seletores do site ficam aqui.
(function () {
  "use strict";

  const core = globalThis.JobScoutCore;
  const page = globalThis.JobScoutPage;

  const TITLE = [
    ".job-details-jobs-unified-top-card__job-title h1",
    ".job-details-jobs-unified-top-card__job-title",
    ".jobs-unified-top-card__job-title",
    "h1.top-card-layout__title",
    ".jobs-details h1",
  ];
  const COMPANY = [
    ".job-details-jobs-unified-top-card__company-name a",
    ".job-details-jobs-unified-top-card__company-name",
    ".jobs-unified-top-card__company-name",
    ".topcard__org-name-link",
    ".top-card-layout__second-subline a",
  ];
  const LOCATION = [
    ".job-details-jobs-unified-top-card__primary-description-container .tvm__text",
    ".job-details-jobs-unified-top-card__bullet",
    ".jobs-unified-top-card__bullet",
    ".topcard__flavor--bullet",
  ];
  const DESCRIPTION = [
    "#job-details",
    ".jobs-description__content",
    ".jobs-box__html-content",
    ".show-more-less-html__markup",
  ];
  const APPLY_STEP = /(avan[cç]ar|pr[oó]xim|next|continu|revisar|review|avaliar|voltar|back|anterior|enviar candidatura|submit application|candidatura)/i;
  const APPLY_TITLE = /(candidat|apply to|aplicar|easy apply)/i;
  const MODAL = [".jobs-easy-apply-modal", ".jobs-easy-apply-content", "[data-test-modal-id='easy-apply-modal']"];
  // O LinkedIn passou a abrir a candidatura simplificada dentro de um Shadow DOM (#interop-outlet).
  const SHADOW_HOSTS = "#interop-outlet, [data-testid='interop-shadowdom']";

  function scopes() {
    const list = [document];
    for (const host of document.querySelectorAll(SHADOW_HOSTS)) {
      const root = page.shadowOf(host);
      if (root) list.push(root);
    }
    return list;
  }

  function isApplyDialog(dialog) {
    if (!dialog.querySelector("input:not([type='hidden']), textarea, select")) return false;
    const heading = dialog.querySelector("h1, h2, h3, header");
    if (heading && APPLY_TITLE.test(page.text(heading))) return true;
    // Mensagens e busca também abrem diálogos; sem botão de etapa da candidatura, não é formulário.
    return [...dialog.querySelectorAll("button")].some(
      (button) => APPLY_STEP.test(button.getAttribute("aria-label") || "") || APPLY_STEP.test(page.text(button)),
    );
  }

  function currentJob() {
    const url = core.linkedinJobUrl(location.href);
    if (!url) return null;
    const scope = document.querySelector(".jobs-search__job-details, .job-view-layout, .jobs-details") || document;
    const title = page.text(page.pick(TITLE, scope));
    return {
      url,
      title,
      company: page.text(page.pick(COMPANY, scope)),
      location: page.text(page.pick(LOCATION, scope)),
      description: page.text(page.pick(DESCRIPTION, scope)).slice(0, 20000),
    };
  }

  function formRoot() {
    for (const scope of scopes()) {
      for (const selector of MODAL) {
        const node = scope.querySelector(selector);
        if (node) return node;
      }
      // Layout novo: a candidatura simplificada abre num diálogo com campos e botões de etapa.
      for (const dialog of scope.querySelectorAll("[role='dialog'], dialog")) {
        if (isApplyDialog(dialog)) return dialog;
      }
    }
    return null;
  }

  // Para Config > Falhas, quando o clique em Candidatura simplificada não abre nada reconhecível.
  function describeForm() {
    const parts = [];
    for (const scope of scopes()) {
      const where = scope === document ? "página" : "shadow DOM";
      const dialogs = [...scope.querySelectorAll("[role='dialog'], dialog")];
      parts.push(`${where}: ${dialogs.length} diálogo(s)`);
      for (const dialog of dialogs.slice(0, 3)) {
        const heading = page.text(dialog.querySelector("h1, h2, h3, header")).slice(0, 60);
        const buttons = [...dialog.querySelectorAll("button")].map((button) => page.text(button) || button.getAttribute("aria-label") || "").filter(Boolean).slice(0, 6);
        const fields = dialog.querySelectorAll("input:not([type='hidden']), textarea, select").length;
        parts.push(`“${heading}” campos=${fields} botões=[${buttons.join(", ")}]`);
      }
    }
    const host = document.querySelector(SHADOW_HOSTS);
    if (host && !page.shadowOf(host)) parts.push("interop-outlet sem acesso ao shadow DOM");
    return parts.join("; ");
  }

  function isSubmit(button) {
    const label = button.getAttribute("aria-label") || "";
    return /submit application|enviar candidatura/i.test(label) || core.isSubmitText(page.text(button));
  }

  page.start({
    site: "linkedin",
    publicFallback: true,
    currentJob,
    formRoot,
    describeForm,
    shadowHosts: SHADOW_HOSTS,
    applyButton: /^(candidatura simplificada|easy apply|candidatar-se)/i,
    isSubmit,
    fieldGroup: ".jobs-easy-apply-form-element, .fb-dash-form-element, [data-test-form-element], fieldset",
  });

  // Mensagens: a conversa aberta (aba flutuante ou página de mensagens) ganha a barra de resposta.
  const COMPOSER = ".msg-form__contenteditable[contenteditable='true'], form.msg-form [contenteditable='true'][role='textbox']";
  const CONVERSATION = ".msg-overlay-conversation-bubble, .msg-convo-wrapper, .msg-thread, .msg-s-message-list-container, .scaffold-layout__detail";
  const NAME = [".msg-overlay-bubble-header__title", ".msg-entity-lockup__entity-title", "#thread-detail-jump-target", ".msg-thread__link-to-profile", "h2"];

  function chatScope(composer) {
    let node = composer.closest(CONVERSATION);
    // A página de mensagens separa lista e formulário: sobe até achar as mensagens.
    while (node && !node.querySelector(".msg-s-message-list__event, .msg-s-event-listitem") && node.parentElement) node = node.parentElement.closest(CONVERSATION) || (node.parentElement === document.body ? null : node.parentElement);
    return node || document;
  }

  function readChat(composer) {
    const scope = chatScope(composer);
    const name = page.text(page.pick(NAME, scope)).split("\n")[0].replace(/\s+(status|online|offline).*$/i, "").trim();
    const profile = scope.querySelector("a[href*='/in/']");
    const turns = [];
    let author = "";
    let day = "";
    for (const item of scope.querySelectorAll("li.msg-s-message-list__event, .msg-s-message-list__event")) {
      // O divisor de dia ("Hoje", "Ontem", "29 de out.") vem antes do primeiro grupo daquele dia.
      const heading = item.querySelector(".msg-s-message-list__time-heading");
      if (heading) day = globalThis.JobScoutChat.dayOf(page.text(heading));
      const who = page.text(item.querySelector(".msg-s-message-group__name, .msg-s-message-group__profile-link"));
      if (who) author = who;
      const bodies = [...item.querySelectorAll(".msg-s-event-listitem__body, .msg-s-event__content")].map((node) => page.text(node)).filter(Boolean);
      for (const body of bodies) {
        const other = item.querySelector(".msg-s-event-listitem--other") !== null;
        const mine = other ? false : Boolean(author) && core.fold(author) !== core.fold(name);
        turns.push({ autor: author, texto: body, minha: mine, dia: day });
      }
    }
    return { nome: name, linkedin: profile ? profile.href : "", email: "", telefone: "", turnos: turns.slice(-12) };
  }

  if (globalThis.JobScoutChat) {
    globalThis.JobScoutChat.start({
      canal: "linkedin",
      composers: () => scopes().flatMap((scope) => [...scope.querySelectorAll(COMPOSER)]),
      anchor: (composer) => composer.closest("form.msg-form, .msg-form") || composer,
      read: readChat,
    });
  }
})();
