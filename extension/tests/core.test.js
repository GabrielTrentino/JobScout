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
