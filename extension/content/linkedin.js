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
  const APPLY_STEP = /(avan[cç]ar|pr[oó]xim|next|continu|revisar|review|enviar candidatura|submit application|candidatura)/i;
  const MODAL = [".jobs-easy-apply-modal", ".jobs-easy-apply-content", "[data-test-modal-id='easy-apply-modal']"];

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
    for (const selector of MODAL) {
      const node = document.querySelector(selector);
      if (node) return node;
    }
    // Layout novo: a candidatura simplificada abre num diálogo com campos e botões de etapa.
    // Mensagens e busca também abrem diálogos; sem botão de candidatura, não é formulário.
    for (const dialog of document.querySelectorAll("[role='dialog']")) {
      if (!dialog.querySelector("input:not([type='hidden']), textarea, select")) continue;
      const buttons = [...dialog.querySelectorAll("button")];
      if (buttons.some((button) => APPLY_STEP.test(button.getAttribute("aria-label") || "") || APPLY_STEP.test(page.text(button)))) {
        return dialog;
      }
    }
    return null;
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
    isSubmit,
    fieldGroup: ".jobs-easy-apply-form-element, .fb-dash-form-element, [data-test-form-element], fieldset",
  });
})();
