# JobScout — especificação

Assistente pessoal que acompanha a busca de emprego de ponta a ponta: registra cada vaga e candidatura, ajuda a preencher formulários e reúne os retornos de recrutadores numa linha do tempo por vaga. Uma pessoa, um computador, Chrome com LinkedIn e InHire.

Princípios:

- O assistente sugere e preenche. O envio de candidaturas e mensagens fica sempre com o usuário.
- **Tudo o que é capturado ou alterado automaticamente passa por um rascunho que o usuário aprova.**
- Dados e movimentos ficam neste computador.

WhatsApp está fora desta versão.

## Arquitetura

```text
Extensão Chrome (LinkedIn, InHire) ──┐
                                     ├──► Backend local (Python, stdlib) ──► SQLite
Gmail (somente leitura) ─────────────┘          │
Importação .eml ─────────────────────┘          └──► Painel (SSE, ao vivo)
```

| Peça | Onde | O que faz |
|---|---|---|
| Extensão MV3 | [extension/](../extension/) | Content scripts leem o DOM, emitem eventos, preenchem campos padrão e inserem respostas aprovadas |
| Backend | [jobscout/server.py](../jobscout/server.py) | API REST, Server-Sent Events para o painel, poller do Gmail |
| Rascunhos | [jobscout/assistant.py](../jobscout/assistant.py) | Transforma eventos em rascunhos; aplica a decisão do usuário |
| Banco | [jobscout/store.py](../jobscout/store.py) | SQLite em `%USERPROFILE%\.jobscout\jobscout.db` |
| E-mail | [jobscout/mail.py](../jobscout/mail.py), [jobscout/gmail.py](../jobscout/gmail.py) | Pré-filtro por regras, classificação, data citada, vínculo com a vaga |
| IA | [jobscout/llm.py](../jobscout/llm.py) | `ask_llm(task, input)` com modelo escolhido por tarefa |
| Painel | [jobscout/web/](../jobscout/web/) | Agora, Rascunhos, Linha do tempo, Kanban, Busca, Perfil, Config |
| Overlay | [jobscout/overlay.py](../jobscout/overlay.py) | Janela pywebview (WebView2) sem borda, sempre por cima, presa à direita; recolhe numa aba na borda |

## Overlay e atividade

`python -m jobscout` abre uma janela sem borda, sempre por cima, em quatro formatos (Win32 `SetWindowPos` em pixels físicos, cantos arredondados com `SetWindowRgn`):

| Formato | Tamanho | O que mostra |
|---|---|---|
| bolha | 300 px, altura do conteúdo, canto inferior direito | Círculo que gira durante o processamento, contagem de pendentes, pop-ups das novidades |
| menu | idem | Itens de navegação, chave do modo noturno, 📌, ⤢, × |
| painel | 400 px, altura da tela, borda direita | A tela escolhida no menu |
| amplo | 880 px, altura da tela | Kanban e página da empresa; ⇔ alterna com o painel |

Os pop-ups seguem o nível da atividade; em Config o usuário escolhe quais níveis aparecem (padrão: o que precisa dele e erros). `--navegador` abre o painel completo no navegador.

A aba **Agora** junta o próximo rascunho pendente (Aprovar, Descartar, Depois) e o feed de atividade. O backend narra cada passo em `Hub.activity(texto, nivel)` com níveis `trabalhando`, `aviso` (precisa de você), `ok`, `info` e `erro`. Também narra o que não virou rascunho e o motivo: vaga já salva sem mudança, já nos rascunhos, descartada antes, e-mail que não parece de recrutamento, falha de seletor, IA indisponível. As últimas 150 entradas ficam em memória (`GET /api/atividade`) e chegam ao vivo pelo SSE como `{"tipo": "atividade"}`.

Decisões tomadas a partir das questões em aberto do handoff:

| Questão | Decisão | Motivo |
|---|---|---|
| Backend | Python, só biblioteca padrão | Reaproveita o leitor de currículo; sem dependência nova |
| Tempo real | Server-Sent Events em vez de WebSocket | O painel só recebe; SSE funciona na stdlib e reconecta sozinho |
| Banco | SQLite local | Dados de movimentação ficam no computador |
| Painel | Web app próprio em `127.0.0.1:8765` | Fica aberto na segunda tela, independente da aba do LinkedIn |
| Extensão | JavaScript puro, sem build | Carrega direto em `chrome://extensions`; regras puras testadas no Node |
| WhatsApp | Fora por enquanto | Pedido do usuário |

## Rascunhos

| Tipo | Nasce quando | Aprovar faz |
|---|---|---|
| `vaga` | Vaga aberta que ainda não existe no banco | Cria `jobs` + `applications` com o status escolhido |
| `vaga_alteracao` | Vaga já salva aparece com título, empresa, local ou descrição diferente | Aplica só os campos marcados |
| `status` | Clique em Enviar numa vaga já salva | Muda o status para `candidatado` |
| `resposta` | Pergunta aberta detectada no formulário | Grava em `answers` e pede à extensão para inserir o texto no campo |
| `mensagem` | E-mail relevante (Gmail ou `.eml`) | Grava em `messages`, vincula o contato e aplica o status proposto |

Regras:

- Um rascunho pendente por assunto. Nova captura do mesmo assunto atualiza o rascunho em vez de criar outro.
- O que o usuário editou não é sobrescrito por capturas seguintes.
- Vaga descartada não volta a ser proposta só por ser vista de novo. Se houver candidatura, volta.
- Clique em Enviar antes de aprovar a vaga marca o próprio rascunho da vaga como `candidatado`.
- Resposta só é aprovada depois da vaga e com texto não vazio. Mensagem só com vaga escolhida.
- Ações feitas pelo usuário no painel (arrastar no Kanban, mudar status, nota, vaga por link) já são a decisão dele: entram direto e ficam registradas.

Onde aprovar:

- Aba **Rascunhos**: todos os pendentes, com filtros para aprovados e descartados.
- **Popup** do painel: fila de um rascunho por vez (“1 de N”), com Aprovar, Descartar e Depois. Liga e desliga no topo.
- **Kanban**: coluna Rascunho com as vagas novas.
- **Gaveta da vaga**: rascunhos daquela vaga.
- **Popup da extensão**: contagem no ícone e aprovação rápida; ajustes finos ficam no painel.

## Extração, empresas e vagas frias

- [jobscout/insights.py](../jobscout/insights.py): regras sem IA sobre título, local e descrição: skills (dicionário), inglês, modalidade, salário citado, região e senioridade. Vale para todas as fontes. O que veio da página tem prioridade; o usuário ajusta no rascunho.
- Vaga nova do LinkedIn: uma busca na página pública traz nível de experiência, contrato, setor e o link da empresa.
- Empresa: criada ao aprovar a vaga (chave = nome sem acento e minúsculo). Se houver link do LinkedIn, a página pública da empresa preenche setor, tamanho, sede, especializações e descrição, uma vez; o botão "Atualizar do LinkedIn" repete.
- Respostas do formulário: a extensão acumula rótulo e valor em cada etapa (o clique é lido antes de a página trocar de etapa) e manda no `application_submitted`. Ficam no rascunho com "guardar estas respostas"; aprovadas, entram em `answers` com `origin = formulario`. `GET /api/extensao/historico` devolve a última resposta por pergunta, usada no preenchimento automático (mesmo rótulo, ou quase igual em pergunta longa).
- Vaga fria: de hora em hora, vaga em candidatado, em análise, entrevista ou proposta sem movimento há `JOBSCOUT_DIAS_FRIA` dias vira rascunho de status para `fria`. Descartado, não volta até haver movimento novo.

## Movimentos

Toda criação, aprovação e descarte de rascunho, mudança de status, nota, resposta e mensagem gera uma linha em `movements` (data, tipo, resumo, origem, vaga, rascunho, detalhe). É a linha do tempo do painel e da gaveta da vaga. Exportação em CSV no painel (`/api/exportar.csv`).

## Modelo de dados

| Tabela | Campos principais |
|---|---|
| `jobs` | id, source, url (canônica, única), title, company, description, location, seniority, employment_type, industry, company_url, work_mode, english, salary, region, skills, captured_at |
| `applications` | id, job_id, status, applied_at, updated_at |
| `answers` | id, application_id, question, answer, suggested_by_llm |
| `contacts` | id, name, email, phone, company, role |
| `messages` | id, application_id, contact_id, channel, external_id, subject, received_at, body, summary, classification, event_at |
| `drafts` | id, kind, state (pendente/aprovado/descartado), dedupe_key, source, job_id, job_url, payload, original, edited |
| `movements` | id, at, kind, summary, source, job_id, draft_id, detail |
| `companies` | id, key, name, linkedin_url, industry, size, headquarters, specialties, description, notes, fetched_at |
| `notes`, `insertions`, `capture_failures`, `gmail_seen` | apoio |

Status: visualizada → candidatado → em análise → entrevista → proposta / recusada / fria (esquecida).

Perfil em `profile.json`: dados pessoais, links, pretensão, disponibilidade, texto do currículo e histórias. O leitor local de currículo (PDF/DOCX) transforma as atividades em histórias editáveis.

## Extensão

- Content scripts em todo o `linkedin.com` (o LinkedIn troca de página sem recarregar, então quem entra pelo feed também é atendido), `*.inhire.app` e `*.inhire.com.br`. Um adaptador por site isola os seletores; a InHire tenta JSON-LD `JobPosting` antes do DOM.
- LinkedIn: se os seletores não acharem título e empresa, a extensão manda só o link e o backend lê a página pública da vaga (`jobs-guest/jobs/api/jobPosting/<id>`, sem login, classes estáveis) em [jobscout/linkedin_public.py](../jobscout/linkedin_public.py). Uma busca por vaga; o que veio da página logada tem prioridade. Sem resposta, vira falha em Config.
- Com o JobScout fechado, os eventos ficam numa fila na extensão (até 200) e são enviados quando ele volta, em até 1 minuto.
- Eventos: `job_viewed`, `form_detected`, `application_submitted`, `selector_failed` (aparece em Config).
- Campos padrão (nome, e-mail, telefone, cidade, links, pretensão) por dicionário de rótulos, sem LLM. Rótulos sobre outra pessoa ou coisa (“Nome da empresa”, “Telefone de emergência”) são ignorados. Dá para desligar no popup.
- Perguntas abertas viram rascunho de resposta. Sugestão vem do histórico (pergunta parecida já respondida) ou da LLM, se configurada. Aprovada, a extensão insere o texto no campo.
- Nunca clica em Enviar.

## E-mail

- Gmail via OAuth no próprio computador (PKCE, escopo `gmail.readonly`), verificação a cada `JOBSCOUT_GMAIL_INTERVALO_MIN` minutos.
- Sem Gmail configurado, a aba Rascunhos importa arquivos `.eml`.
- Pré-filtro por regras: domínio de empresa já acompanhada ou palavras como “processo seletivo”, “entrevista”.
- Classificação por regras (rejeição, entrevista, documento, outro); a LLM local só entra se as regras não decidirem.
- Convite propõe status `entrevista` e a data/hora citada; rejeição propõe `recusada`.

## IA

| Tarefa | Variável | Privada |
|---|---|---|
| classificar | `JOBSCOUT_LLM_CLASSIFICAR` | sim |
| resumir | `JOBSCOUT_LLM_RESUMIR` | sim |
| responder | `JOBSCOUT_LLM_RESPONDER` | não |
| preparar | `JOBSCOUT_LLM_PREPARAR` | não |

Valor: `off`, `ollama:<modelo>` ou `gemini:<modelo>`. Tarefas privadas recusam modelo em nuvem salvo `JOBSCOUT_LLM_NUVEM_PRIVADO=sim`. Prompts usam só o perfil; toda sugestão passa por rascunho.

## API

| Método | Caminho | Uso |
|---|---|---|
| GET | `/api/estado` | Status, vagas, rascunhos pendentes, modelos, Gmail |
| GET | `/api/stream` | Eventos ao vivo (SSE) |
| GET | `/api/rascunhos?estado=` | Lista por estado |
| PATCH | `/api/rascunhos/{id}` | Editar sem decidir |
| POST | `/api/rascunhos/{id}/aprovar` | Aprovar, com `payload` opcional editado |
| POST | `/api/rascunhos/{id}/descartar` | Descartar |
| GET/POST | `/api/vagas` | Listar / adicionar por link |
| GET | `/api/vagas/{id}` | Detalhe com respostas, mensagens, notas, movimentos, rascunhos |
| PATCH | `/api/vagas/{id}/status` | Mudança manual |
| POST | `/api/vagas/{id}/notas` | Nota |
| GET | `/api/vagas/{id}/preparo` | Preparação de entrevista |
| GET | `/api/movimentos`, `/api/buscar?q=`, `/api/exportar.csv` | Linha do tempo, busca, exportação |
| GET | `/api/empresas`, `/api/empresas/{id}` | Empresas com contagens; detalhe com vagas, movimentos e rascunhos |
| PATCH/POST | `/api/empresas/{id}`, `/api/empresas/{id}/atualizar` | Notas; buscar de novo a página pública |
| POST | `/api/frias/verificar` | Procura vagas paradas agora |
| GET | `/api/extensao/historico` | Respostas já dadas, para o preenchimento |
| POST | `/api/eventos` | Entrada da extensão |
| GET/POST | `/api/extensao/insercoes` | Respostas aprovadas para inserir |
| GET/PUT | `/api/perfil`, GET `/api/perfil/campos` | Perfil e campos padrão |
| POST | `/api/analisar`, `/api/emails/importar` | Currículo e `.eml` |
| GET/POST | `/api/gmail/conectar`, `/retorno`, `/verificar`, `/desconectar` | Gmail |

Requisições com `Origin` de outro site são recusadas (403); só o próprio painel e `chrome-extension://` passam.

## Riscos e limites

- Termos do LinkedIn: só leitura e preenchimento, sem coleta em massa, envio manual.
- Seletores quebram quando o site muda: adaptadores isolados e registro de falhas em Config.
- LLM pode inventar: prompt restrito ao perfil, revisão obrigatória, respostas salvas.
- Uso ético: preparação antes da entrevista, nunca durante.

## Próximos passos

1. Validar os seletores do LinkedIn e da InHire em páginas reais e ajustar os adaptadores.
2. Gemini Nano (Prompt API) na extensão como alternativa local ao Ollama.
3. WhatsApp: encaminhamento para bot oficial ou importação `.txt`.
4. Empacotamento `jobscout.exe`.
