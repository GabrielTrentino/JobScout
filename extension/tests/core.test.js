const test = require("node:test");
const assert = require("node:assert/strict");
const core = require("../content/core.js");

const FIELDS = [
  { chave: "nome", valor: "Ana Souza", rotulos: ["nome completo", "full name", "seu nome", "nome", "name"] },
  { chave: "email", valor: "ana@email.com", rotulos: ["e-mail", "email"] },
  { chave: "telefone", valor: "11 99999-0000", rotulos: ["telefone", "celular", "phone", "mobile"] },
];

test("campos padrão batem pelo rótulo, com ou sem acento e asterisco", () => {
  assert.equal(core.matchStandard("Nome completo *", FIELDS).chave, "nome");
  assert.equal(core.matchStandard("Seu e-mail", FIELDS).chave, "email");
  assert.equal(core.matchStandard("Mobile phone number", FIELDS).chave, "telefone");
  assert.equal(core.matchStandard("Celular (obrigatório)", FIELDS).chave, "telefone");
});

test("pergunta inteira de localização bate com a cidade do perfil", () => {
  const city = [{ chave: "cidade", valor: "São Paulo, SP", rotulos: ["cidade", "city", "location", "current location", "where are you located", "cidade atual"] }];
  assert.equal(core.matchStandard("What is your current location?", city).chave, "cidade");
  assert.equal(core.matchStandard("Where are you located?", city).chave, "cidade");
  assert.equal(core.matchStandard("Qual sua cidade atual?", city).chave, "cidade");
  assert.equal(core.matchStandard("Preferred work location", city), null);
  assert.equal(core.matchStandard("Which country are you located in?", city), null);
});

test("país e localização saem no idioma do rótulo", () => {
  const fields = [
    { chave: "pais", valor: "Brasil", valores: { pt: "Brasil", en: "Brazil", es: "Brasil" }, rotulos: ["pais", "country"] },
    { chave: "estado", valor: "SP", rotulos: ["estado", "state"] },
    { chave: "localizacao", valor: "São Paulo, SP, Brasil", valores: { pt: "São Paulo, SP, Brasil", en: "São Paulo, SP, Brazil", es: "São Paulo, SP, Brasil" }, rotulos: ["location", "current location", "localizacao"] },
  ];
  const fill = (label, page) => {
    const field = core.matchStandard(label, fields);
    return field && core.standardValue(field, label, page);
  };
  assert.equal(fill("Country", "pt"), "Brazil");
  assert.equal(fill("País", "en"), "Brasil");
  assert.equal(fill("What is your current location?", "pt"), "São Paulo, SP, Brazil");
  assert.equal(fill("Localização", "en"), "São Paulo, SP, Brasil");
  assert.equal(fill("Phone country code", "en"), null);
  assert.equal(fill("Estado civil", "pt"), null);
  assert.equal(core.labelLanguage("12345", "en-US"), "en");
});

test("rótulos de outra pessoa ou de outra coisa não são preenchidos", () => {
  assert.equal(core.matchStandard("Nome da empresa atual", FIELDS), null);
  assert.equal(core.matchStandard("Company name", FIELDS), null);
  assert.equal(core.matchStandard("Telefone de emergência", FIELDS), null);
  assert.equal(core.matchStandard("Phone country code", FIELDS), null);
  assert.equal(core.matchStandard("Por que você quer trabalhar conosco?", FIELDS), null);
});

test("pergunta aberta: textarea, rótulo longo ou com interrogação", () => {
  assert.equal(core.isOpenQuestion({ tag: "textarea", type: "text", label: "Carta" }), true);
  assert.equal(core.isOpenQuestion({ tag: "input", type: "text", label: "Quantos anos de experiência com Python você tem?" }), true);
  assert.equal(core.isOpenQuestion({ tag: "input", type: "text", label: "Cidade" }), false);
  assert.equal(core.isOpenQuestion({ tag: "select", type: "text", label: "Você aceita trabalho híbrido?" }), false);
});

test("link canônico do LinkedIn sai da vaga aberta ou da busca", () => {
  assert.equal(core.linkedinJobUrl("https://www.linkedin.com/jobs/view/4012345678/?refId=abc"), "https://www.linkedin.com/jobs/view/4012345678/");
  assert.equal(
    core.linkedinJobUrl("https://www.linkedin.com/jobs/search/?currentJobId=4012345678&keywords=python"),
    "https://www.linkedin.com/jobs/view/4012345678/",
  );
  assert.equal(core.linkedinJobUrl("https://www.linkedin.com/jobs/"), null);
});

test("botões de envio reconhecidos pelo texto", () => {
  assert.equal(core.isSubmitText("Enviar candidatura"), true);
  assert.equal(core.isSubmitText("  Submit application "), true);
  assert.equal(core.isSubmitText("Avançar"), false);
  assert.equal(core.isSubmitText("Next"), false);
});

test("JobPosting em JSON-LD vira vaga", () => {
  const block = JSON.stringify({
    "@context": "https://schema.org",
    "@type": "JobPosting",
    title: "Backend Python",
    hiringOrganization: { "@type": "Organization", name: "Acme" },
    jobLocation: { address: { addressLocality: "São Paulo", addressRegion: "SP" } },
    description: "<p>APIs em <b>FastAPI</b></p><ul><li>Docker</li></ul>",
  });
  const job = core.jobFromJsonLd(["not json", block]);
  assert.equal(job.title, "Backend Python");
  assert.equal(job.company, "Acme");
  assert.equal(job.location, "São Paulo, SP");
  assert.match(job.description, /APIs em FastAPI/);
});

const HISTORY = [
  { rotulo: "Quantos anos de experiência você tem com Python?", valor: "5" },
  { rotulo: "Você aceita trabalho híbrido?", valor: "Sim" },
  { rotulo: "Cidade", valor: "São Paulo" },
];

test("histórico: mesma pergunta, com ou sem acento e asterisco", () => {
  assert.equal(core.matchHistory("Quantos anos de experiencia voce tem com Python? *", HISTORY).valor, "5");
  assert.equal(core.matchHistory("cidade", HISTORY).valor, "São Paulo");
});

test("histórico: pergunta longa quase igual vale; curta e diferente não", () => {
  assert.equal(core.matchHistory("Quantos anos de experiência você possui com Python?", HISTORY), null);
  assert.equal(core.matchHistory("Você aceita trabalho híbrido em SP?", HISTORY), null);
  assert.equal(core.matchHistory("Quantos anos de experiência você tem com Python", HISTORY).valor, "5");
  assert.equal(core.matchHistory("Estado", HISTORY), null);
});

test("opção de select ou rádio pela resposta guardada, inclusive sim/yes", () => {
  assert.equal(core.pickOption(["Selecione", "Sim", "Não"], "sim"), 1);
  assert.equal(core.pickOption(["Yes", "No"], "Sim"), 0);
  assert.equal(core.pickOption(["Yes", "No"], "Não"), 1);
  assert.equal(core.pickOption(["Júnior", "Pleno"], "Sênior"), -1);
});

test("sistemas de candidatura: empresa pelo endereço e endereço da vaga sem a etapa", () => {
  const ashby = "https://jobs.ashbyhq.com/truelogic/cc7ced8a-4d8f-4ebc-b2c5-fb02fd1419ca/application?utm_source=5M9w72G1d1";
  assert.deepEqual(core.atsFor(ashby), { ats: "Ashby", company: "Truelogic" });
  assert.equal(core.jobUrlFrom(ashby), "https://jobs.ashbyhq.com/truelogic/cc7ced8a-4d8f-4ebc-b2c5-fb02fd1419ca");
  assert.equal(core.atsFor("https://boards.greenhouse.io/nubank/jobs/123").company, "Nubank");
  assert.equal(core.atsFor("https://jobs.lever.co/acme-corp/abc/apply").company, "Acme Corp");
  assert.equal(core.atsFor("https://stone.gupy.io/job/xyz").company, "Stone");
  assert.equal(core.atsFor("https://www.google.com/search?q=x"), null);
});

test("modo todos os sites: só página que parece candidatura", () => {
  const ashby = { href: "https://jobs.ashbyhq.com/truelogic/x/application", fieldLabels: ["Name", "Email"] };
  assert.equal(core.looksLikeApplication(ashby), true);
  assert.equal(core.looksLikeApplication({ href: "https://empresa.com/carreiras/vaga-dados", fieldLabels: ["Nome", "Currículo", "LinkedIn"] }), true);
  assert.equal(core.looksLikeApplication({ href: "https://loja.com/checkout", title: "Pagamento", fieldLabels: ["Nome", "Cartão"] }), false);
  assert.equal(core.looksLikeApplication({ href: "https://empresa.com/contato", fieldLabels: ["Nome", "E-mail", "Mensagem"] }), false);
  // Fala de vaga, mas não pede nada de candidatura (newsletter de vagas): fica de fora.
  assert.equal(core.looksLikeApplication({ href: "https://site.com/jobs", fieldLabels: ["E-mail"] }), false);
  assert.equal(core.looksLikeApplication({ href: "https://x.com/a", hasJobPosting: true }), true);
  assert.equal(core.isSubmitText("Submit Application"), true);
  assert.equal(core.isSubmitText("Yes"), false);
});

test("pretensão: a moeda do rótulo manda, sem converter", () => {
  const field = { chave: "pretensao_salarial", valor: "R$ 15.000", valores: { pt: "R$ 15.000", es: "R$ 15.000", en: "US$ 4,000", brl: "R$ 15.000", usd: "US$ 4,000" } };
  assert.equal(core.standardValue(field, "Pretensão salarial", "pt"), "R$ 15.000");
  assert.equal(core.standardValue(field, "Salary expectation", "en"), "US$ 4,000");
  assert.equal(core.standardValue(field, "Pretensão salarial em dólar", "pt"), "US$ 4,000");
  assert.equal(core.standardValue(field, "Salary expectation (BRL)", "en"), "R$ 15.000");
  const onlyReal = { chave: "pretensao_salarial", valor: "R$ 15.000", valores: { pt: "R$ 15.000", es: "R$ 15.000", en: "R$ 15.000", brl: "R$ 15.000" } };
  assert.equal(core.standardValue(onlyReal, "Salary expectation in USD", "en"), "");
});
