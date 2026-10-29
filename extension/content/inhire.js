// Adaptador da InHire: páginas de carreira em <empresa>.inhire.app.
// A estrutura exata ainda está em levantamento; por isso tenta JSON-LD antes do DOM.
(function () {
  "use strict";

  const core = globalThis.JobScoutCore;
  const page = globalThis.JobScoutPage;

  const TITLE = ["[data-testid='job-title']", "main h1", "h1"];
  const COMPANY = ["[data-testid='company-name']", "header img[alt]"];
  const LOCATION = ["[data-testid='job-location']", "[class*='location' i]"];
  const DESCRIPTION = ["[data-testid='job-description']", "[class*='description' i]", "main article", "main"];

  function isJobPage() {
    return /\/vagas?\/[^/]+/i.test(location.pathname) || /\/jobs?\/[^/]+/i.test(location.pathname);
  }

  function companyFromHost() {
    const sub = location.hostname.split(".")[0];
    return sub && sub !== "www" && sub !== "inhire" ? sub.replace(/[-_]/g, " ") : "";
  }

  function currentJob() {
    if (!isJobPage()) return null;
    const url = location.origin + location.pathname.replace(/\/(candidatar|aplicar|apply|inscricao)\/?$/i, "");
    const fromLd = page.jsonLdJob();
    if (fromLd && fromLd.title) return { url, ...fromLd, company: fromLd.company || companyFromHost() };
    const logo = document.querySelector(COMPANY[1]);
    const ogSite = document.querySelector("meta[property='og:site_name']");
    return {
      url,
      title: page.text(page.pick(TITLE)),
      company:
        page.text(page.pick([COMPANY[0]])) ||
        (ogSite && ogSite.content) ||
        (logo && logo.getAttribute("alt")) ||
        companyFromHost(),
      location: page.text(page.pick(LOCATION)).slice(0, 200),
      description: page.text(page.pick(DESCRIPTION)).slice(0, 20000),
    };
  }

  function formRoot() {
    const forms = [...document.querySelectorAll("form")].filter((form) => form.querySelector("input, textarea"));
    return forms.find((form) => form.querySelectorAll("input, textarea").length >= 2) || null;
  }

  function isSubmit(button) {
    const textValue = page.text(button) || button.value || "";
    return core.isSubmitText(textValue) || (/^candidatar-se$/i.test(textValue.trim()) && Boolean(button.closest("form")));
  }

  page.start({
    site: "inhire",
    currentJob,
    formRoot,
    isSubmit,
    fieldGroup: "fieldset, [class*='field' i], [class*='question' i]",
  });
})();
