// Adaptador genérico: formulários de candidatura em qualquer site (Ashby, Greenhouse, Lever, Gupy, sites próprios...).
// Só roda onde a pessoa ligou no popup ("neste site" ou "em todos os sites de vagas").
// No modo "todos os sites", só age em página que parece candidatura; login, compra e contato ficam de fora.
(function () {
  "use strict";

  if (globalThis.__jobscoutGeneric) return;
  globalThis.__jobscoutGeneric = true;

  const core = globalThis.JobScoutCore;
  const page = globalThis.JobScoutPage;
  const FIELDS = "input:not([type='hidden']):not([type='submit']):not([type='button']), textarea, select";
  // Captcha, busca do site e newsletter não são perguntas da candidatura.
  const IGNORE = /recaptcha|captcha|hcaptcha|g-recaptcha|search|newsletter|cookie/i;
  let explicit = false;

  function visibleFields(scope) {
    return [...scope.querySelectorAll(FIELDS)].filter((node) => {
      const name = `${node.name || ""} ${node.id || ""} ${node.className || ""}`;
      return !IGNORE.test(name) && (node.offsetParent !== null || node.type === "file" || node.type === "radio" || node.type === "checkbox");
    });
  }

  function commonAncestor(nodes) {
    let ancestor = nodes[0];
    while (ancestor && !nodes.every((node) => ancestor.contains(node))) ancestor = ancestor.parentElement;
    return ancestor || document.body;
  }

  // O formulário: a <form> com mais campos; sem <form> (Ashby), o menor bloco que contém todos os campos.
  function formRoot() {
    const forms = [...document.querySelectorAll("form")]
      .map((form) => ({ form, count: visibleFields(form).length }))
      .filter((item) => item.count >= 2)
      .sort((a, b) => b.count - a.count);
    let root = forms.length ? forms[0].form : null;
    if (!root) {
      const fields = visibleFields(document);
      if (fields.length < 2) return null;
      root = commonAncestor(fields);
    }
    if (!explicit && !looksLikeApplication(root)) return null;
    return root;
  }

  function jsonLd() {
    return page.jsonLdJob();
  }

  function looksLikeApplication(root) {
    const labels = root ? visibleFields(root).slice(0, 40).map((node) => node.labels && node.labels[0] ? page.text(node.labels[0]) : node.getAttribute("aria-label") || node.name || "") : [];
    return core.looksLikeApplication({
      href: location.href,
      title: document.title,
      heading: page.text(document.querySelector("h1")),
      hasJobPosting: Boolean(jsonLd()),
      fieldLabels: labels,
    });
  }

  function meta(name) {
    const node = document.querySelector(`meta[property='${name}'], meta[name='${name}']`);
    return node ? node.content || "" : "";
  }

  // Título "Senior Data Engineer @ Truelogic" / "Vaga X | Empresa": separa quando a página não tem JSON-LD.
  function splitTitle(text) {
    const parts = String(text || "").split(/\s+(?:@|at|\||–|—|-)\s+/i);
    return parts.length > 1 ? { title: parts[0].trim(), company: parts[parts.length - 1].trim() } : { title: String(text || "").trim(), company: "" };
  }

  function currentJob() {
    const ld = jsonLd();
    const ats = core.atsFor(location.href);
    const root = formRoot();
    // Página sem vaga nem formulário de candidatura não vira vaga.
    if (!ld && !ats && !root) return null;
    const url = core.jobUrlFrom(location.href);
    if (ld && ld.title) return { url, ...ld, company: ld.company || (ats && ats.company) || meta("og:site_name") };
    const fromTitle = splitTitle(meta("og:title") || document.title);
    return {
      url,
      title: page.text(document.querySelector("h1")) || fromTitle.title,
      company: (ats && ats.company) || meta("og:site_name") || fromTitle.company || location.hostname.replace(/^(www|jobs|careers|carreiras|vagas)\./, "").split(".")[0],
      location: "",
      description: (meta("og:description") || meta("description")).slice(0, 4000),
    };
  }

  function isSubmit(button) {
    const label = button.getAttribute("aria-label") || "";
    return core.isSubmitText(page.text(button)) || core.isSubmitText(button.value || "") || core.isSubmitText(label);
  }

  function begin() {
    page.start({
      site: "web",
      currentJob,
      formRoot,
      isSubmit,
      // Ashby, Greenhouse e Lever agrupam rótulo e campo num bloco "field"/"question"/"application-question".
      fieldGroup: "fieldset, [class*='fieldEntry' i], [class*='field-entry' i], [class*='application-question' i], [class*='question' i], [class*='form-group' i], [class*='field' i]",
      choiceButtons: true,
      // Sugestão ao lado de toda pergunta, também nas de texto longo.
      suggestAll: true,
    });
  }

  // "Neste site" (lista do popup) libera qualquer formulário; "todos os sites" só candidaturas.
  try {
    chrome.storage.local.get({ formSites: [] }, (stored) => {
      explicit = (stored.formSites || []).includes(location.origin);
      begin();
    });
  } catch (error) {
    begin();
  }
})();
