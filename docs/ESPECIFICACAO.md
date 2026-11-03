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
| bolha | 72 × 72 px recortada no círculo do boneco (300 px com pop-ups); canto inferior direito ou onde foi solta | Boneco animado (sentado, pensando, arremesso), contador de pendentes, pop-ups das novidades. Arrastável; gruda na borda direita a menos de 48 px e volta ao canto a menos de 140 px |
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

## Currículo e backlog de melhoria

- No overlay (painel na borda direita), abrir os pontos de melhoria alarga a janela para a esquerda em 400 px; o painel ocupa essa faixa e o currículo mantém a largura. Fechar ou sair do Currículo volta ao tamanho normal.

A tela Currículo junta o texto do currículo (antes no Perfil) e o que sai dele ([jobscout/resume_tools.py](../jobscout/resume_tools.py)):

- **O que o JobScout entendeu:** cargos com período e anos por skill, calculados como nas sugestões. Cada skill tem um campo "tempo real" (`skills_extras` no perfil). Ele vale quando passa do que os cargos mostram, e a sugestão diz "Informado por você".
- **Pontos de melhoria:** toda sugestão no formulário, de regra ou de IA, tem o botão "Ponto de melhoria". Ele grava a pergunta, as opções, o tipo, o que foi sugerido e a vaga na tabela `improvements`; a mesma pergunta em aberto não duplica. "Reprocessar" responde de novo com o currículo atual (regras e, se não houver regra, IA) e guarda o resultado em `latest`, marcando se mudou. Estados: aberto, resolvido, descartado. Na aba Currículo, os pontos ficam num painel lateral à esquerda, com as abas Pendentes (em aberto) e Resolvidas (resolvidos e descartados), que abre e fecha pelo botão "Pontos de melhoria" (aberto por padrão quando há pontos em aberto; depois vale a última escolha). Ele fica ao lado de qualquer subaba e vira gaveta por cima da página em telas estreitas. "Editar no currículo" leva ao campo do currículo completo ou ao trecho do texto que cita a skill da pergunta. "Salvar e reprocessar todos" salva o editor que estiver com mudanças e reprocessa os pontos em aberto.
- **Revisão:** checagens por regras (cargo sem período, cargo sem ferramenta, skill fora de cargo com data, poucas atividades com números, LinkedIn ou GitHub faltando). "Pedir revisão da IA" traz lacunas com uma pergunta para a pessoa. Pontos de "faltam datas" são descartados quando todos os cargos têm período, porque o modelo pequeno às vezes inventa isso. Qualquer ponto pode ir para o backlog.
- **Na internet:** GitHub pela API pública (linguagens por repositório próprio, do primeiro ao último push; Jupyter conta como Python, HCL como Terraform). LinkedIn pelo `og:title`/`og:description` do perfil público; com login exigido, orienta a importar o PDF "Salvar em PDF". Site pessoal: título, descrição e skills citadas. "Usar como tempo real" só preenche a tabela de tempos; a pessoa confere e salva.
- `PUT /api/perfil` passou a gravar só os campos enviados. Assim, Perfil e Currículo editam partes diferentes sem apagar uma à outra.

## Currículo completo, versões por vaga e PDF

- Cada experiência tem habilidades destacadas (`habilidades`) e, em consultoria, as empresas onde a pessoa esteve (`clientes`: nome, período, o que fez). Os dois vão para o PDF e para o texto que as sugestões leem.
- Formação separada em Graduação e Pós-graduação (`tipo`; deduzido do nome do curso quando não informado: pós, especialização, MBA, mestrado, doutorado).
- "✨ Melhorar" em cada item pede à IA (tarefa "curriculo") uma reescrita em primeira pessoa, só com o assunto e os fatos do item. Número ou ferramenta que não está no item descarta a sugestão. A pessoa clica em Usar.
- "Conferir habilidades" (`POST /api/curriculo/conferir`) compara o que está na tela: habilidades das experiências fora do perfil (botão "+ Perfil") e habilidades do perfil em nenhuma experiência ("Citar em…").
- Modelos padrão são versões sem vaga, com nome próprio (`POST /api/curriculo/versoes` com `modelo`). Em `cv.resume_kind` contam como Padrão.
- Versões por vaga são nomeadas `cargo_empresa` (`cv.custom_label`), e o PDF também. O currículo enviado é classificado (`cv.resume_kind`) em Customizado (bate com uma versão) ou Padrão (nome do arquivo); no detalhe da vaga dá para marcar à mão. Resultados mostra o tipo e compara por tipo.

- O editor completo ([jobscout/cv.py](../jobscout/cv.py)) guarda a estrutura em `profile["cv"]`: título, resumo, principais habilidades (★), experiências (cargo, empresa, local, início/fim em mês, atual, itens), formação, idiomas, certificações e projetos. Ao salvar, gera o texto em `curriculo` no formato que o leitor de cargos entende ("Cargo | Empresa", "01/2021 - atual", "- item"). Assim anos por skill, sugestões e IA seguem iguais.
- "Montar a partir do texto" lê o texto atual (cargos pelo leitor de atividades; formação, idiomas, habilidades, resumo, certificações e projetos pelas seções) para a pessoa revisar.
- **Versão por vaga** (`resume_versions`): habilidades pedidas na vaga vão primeiro, e os itens de cada experiência são ordenados pelo que combina (skills da vaga valem mais que palavras da descrição). O resto fica oculto (`mostrar`, `mostrar_itens`), sem ser apagado. `alvo` registra o que combina e o que a vaga pede e falta. Com a tarefa "curriculo" ligada, a IA reescreve só o resumo, com fatos do currículo. Vaga em inglês gera seções em inglês.
- **PDF:** a página A4 (`render_html`) é impressa pelo Edge (ou Chrome) sem janela (`--headless --print-to-pdf`) em `Exportações\Currículos\CV <nome> - <empresa>.pdf`. Esse é o nome que aparece depois em "currículo enviado".

## Mensagens a recrutador

- **Estilo de e-mail** (`EMAIL_STYLE_GUIDE`): separado do chat, com saudação, 2 a 3 parágrafos, assunto e despedida; editado na mesma caixa, aba "E-mail" (`mensagens_estilo_email`). As respostas de e-mail usam ele.
- **Estilo de comunicação** (`STYLE_GUIDE` em [jobscout/replies.py](../jobscout/replies.py)): instruções de tom, cumprimento e seis cenários, editáveis na aba Mensagens (`GET`/`PUT /api/mensagens/estilo`, `POST /api/mensagens/estilo/restaurar`; fica em `preferencias.json`, `mensagens_estilo`, vazio = padrão). `{nome}` vira o primeiro nome do Perfil. Para a IA local não ficar lenta, vão as regras gerais e só o cenário da intenção escolhida, mais as regras do JobScout (fatos, formato JSON).
- **Abertura pelo histórico** (sem IA, `history()` e `opening()`): a extensão manda o dia de cada mensagem (`dia`: hoje/antes, do divisor do LinkedIn ou da data do WhatsApp).
  - Ainda não respondi hoje: "Olá {nome}, tudo bem?"; se perguntaram como estou, "Olá {nome}, tudo bem e contigo?".
  - Já respondi hoje: sem cumprimento ("Tudo bem, e contigo?" se perguntaram). Sem datas na página, conta como hoje se eu cumprimentei nas últimas mensagens.
  - Já agradeci antes: o agradecimento do começo sai. Número de telefone não é usado como nome.
  - O cumprimento que a IA escrever é trocado pela abertura decidida. Resposta da IA com número que não está no Perfil, na vaga nem na conversa (ex.: salário inventado) é descartada e o texto pronto é usado, com aviso.
- **Biblioteca de intenções** ([jobscout/replies.py](../jobscout/replies.py)). Já vem com: tenho interesse, quero mais informações, cobrar retorno do processo (com elogio à empresa), podemos agendar uma conversa, não posso agendar agora, agradecer pela entrevista, falar de salário, pedir feedback da entrevista, vou aguardar (outros processos), não faz sentido no momento e outro. Os textos prontos seguem os exemplos do estilo e não trazem cumprimento.
  - Cada intenção tem nome, instrução para a IA e texto pronto em português e inglês.
  - Nos textos, `{recrutador}`, `{vaga}`, `{empresa}`, `{candidatura}`, `{pretensao}`, `{nome}` e `{extra}` são trocados pelos dados. Um `[trecho]` só aparece se todos os campos dele existirem.
  - A pessoa edita, desliga ou cria intenções na aba Mensagens; isso fica em `preferencias.json` (`mensagens_modelos`). "Restaurar padrão" volta ao original; uma intenção criada pela pessoa é removida.
- **Canal pela página:** a barra da extensão usa o canal de onde está.
  - LinkedIn mensagens e WhatsApp Web: texto curto, sem assinatura.
  - Gmail: e-mail com saudação e assinatura. O assunto só é preenchido numa mensagem nova, com o campo vazio.
  - Na aba Mensagens do app, o canal é escolhido à mão.
- **Barra do chat** ([extension/content/chat.js](../extension/content/chat.js), com adaptadores em `linkedin.js`, `whatsapp.js` e `gmail.js`):
  - Começa como o botão "JobScout · responder". Ao abrir, lê as últimas mensagens (quem falou e o quê) e pede o contexto (`POST /api/extensao/chat`): quem é a pessoa, as vagas dela e a vaga mais provável. A empresa citada na conversa vale mais que o vínculo.
  - Cada intenção é uma etiqueta. A resposta (`POST /api/mensagens/responder`, com `conversa`) continua a conversa no idioma da recrutadora.
  - Escolher uma vaga na barra vincula a pessoa a ela (`POST /api/extensao/chat/vincular`).
  - "Inserir na conversa" escreve no campo linha a linha, com quebra de linha, porque Enter enviaria. Nunca envia.
  - No WhatsApp a barra é flutuante: fica no `<body>`, presa logo acima da caixa de mensagem e abrindo para cima, porque o WhatsApp cobre o que é inserido no meio da página. O contexto é relido a cada abertura (a mesma caixa serve a várias conversas).
- Sem IA, usa o texto pronto. Com a tarefa "mensagem" (privada), a IA parte do texto pronto e da instrução da intenção e responde à última mensagem. Em WhatsApp e LinkedIn, o app corta a despedida formal.

## Recrutadores

- `contacts` ganhou LinkedIn e notas. `job_contacts` liga pessoas e vagas em muitos para muitos: uma recrutadora cuida de várias vagas, e uma vaga pode ter várias pessoas.
- Quem escreve por e-mail sobre uma vaga é vinculado ao aprovar a mensagem.
- No detalhe da vaga, "Recrutador(a)" vincula alguém já cadastrado ou cadastra uma pessoa nova.
- A aba Mensagens lista os recrutadores, com as vagas de cada um, para vincular, desvincular e editar.
- No chat, a pessoa é reconhecida pelo e-mail, pelo LinkedIn, pelo telefone ou, por último, pelo nome completo.

## Abordagem de recrutador no chat

- A barra do chat (LinkedIn e WhatsApp) manda a conversa aberta para `POST /api/extensao/chat/abordagem` quando ela muda (outra pessoa ou mensagem nova).
- [jobscout/approach.py](../jobscout/approach.py) procura, só no que o recrutador escreveu, a empresa e o título ("vaga de X na Y", "role at Y", "recrutadora da Y"), o modelo de trabalho e um link de vaga (LinkedIn, Gupy, InHire). O que faltar a IA local (tarefa privada "classificar") completa, e só vale o que estiver escrito na conversa.
- "Inserir na conversa" guarda a resposta na vaga (`POST /api/extensao/chat/registrar`), e mensagem do recrutador na conversa conta como retorno nos indicadores.
- Vaga nova vira rascunho "Nova vaga" com a origem do canal, um trecho da conversa na descrição e a pessoa que abordou. Ao aprovar, ela fica vinculada como recrutadora. Sem link da vaga, o endereço é `https://jobscout.local/abordagem/<canal>/<pessoa-empresa>` (só identifica; o painel não mostra como link).
- O botão da barra passa a dizer "oportunidade nova". Vaga já salva ou rascunho já aberto não se repetem; descartado não volta.

## Etapas do processo e quadro por empresa

- [jobscout/pipeline.py](../jobscout/pipeline.py): quadro padrão Visualizada → Currículo enviado → Triagem com RH → Teste técnico → Entrevista técnica → Entrevista com gestor → Visita presencial → Proposta. Cada etapa tem um tipo (visualizada, candidatado, em análise, entrevista, proposta) que diz em que coluna do quadro geral a vaga fica.
- A empresa pode ter o próprio quadro (`companies.pipeline`, vazio = padrão). Ele é desenhado no Kanban ("Quadro" > empresa > "Editar etapas da empresa") ou a partir das etapas de uma vaga ("Usar como quadro da empresa"). "Aplicar às vagas" refaz as etapas das vagas dela mantendo estado, data e notas das etapas de mesmo nome.
- Cada vaga guarda as próprias etapas (`job_stages`), criadas na primeira vez a partir do quadro da empresa e do status atual. No detalhe da vaga dá para mover (clique na etapa), editar, marcar como pulada e pôr data.
- Mover de etapa muda o status geral para o tipo dela; mudar o status no quadro geral leva a etapa atual para a próxima do mesmo tipo. Recusada e fria não mexem nas etapas.
- O Kanban da empresa mostra uma coluna por etapa; arrastar a vaga move a etapa.

## Lembretes e Google Agenda

- [jobscout/reminders.py](../jobscout/reminders.py): lembretes com data, repetição (a cada N dias, M vezes) e intenção de mensagem. Modelos prontos: cobrar retorno (em 7 dias, a cada 7, 3 vezes), pedir feedback, agradecer pela entrevista, responder a proposta, outro.
- A cada minuto o JobScout avisa uma vez cada lembrete vencido (atividade e bolha). "Escrever mensagem" abre a aba Mensagens com a vaga e a intenção escolhidas; "Feito" passa para a próxima ocorrência (sem acumular as atrasadas), "Adiar" empurra 1 dia, "Parar" encerra.
- Vaga em recusada, fria ou proposta para os lembretes dela sozinha.
- Sem API: cada lembrete tem o botão Agenda (link `calendar.google.com/calendar/render?action=TEMPLATE`, com a repetição) e o arquivo `.ics` (`GET /api/lembretes/{id}/agenda.ics`). Etapa com data futura vira lembrete; mudar a data troca o lembrete. Adiar refaz o evento quando há agenda ligada por API.
- Com o Google conectado com a permissão `calendar.events`, cada lembrete vira evento no Google Agenda principal (30 minutos, aviso na hora, com a mesma regra de repetição `RRULE`). Parar apaga o evento. Fuso em `JOBSCOUT_FUSO` (padrão `America/Sao_Paulo`). Sem a permissão, tudo funciona no JobScout.

## Busca automática de vagas

- [jobscout/jobsearch.py](../jobscout/jobsearch.py), configurada na aba Busca (`preferencias.json`, `busca`): títulos, empresas, palavras desejadas, palavras que excluem, local, modelo de trabalho, fontes, empresas da InHire e o intervalo (2 a 168 horas).
- Fontes:
  - **Himalayas:** `himalayas.app/jobs/api/search`, vagas remotas abertas ao país do Perfil, até 3 títulos por rodada.
  - **Greenhouse, Lever e Ashby:** API pública do quadro de cada empresa listada (`ats_empresas`: `ashby:truelogic` ou o link do quadro), até 20.
  - **Gupy:** a página pública de busca do portal (`portal.gupy.io/job-search/term=...`) traz as vagas no `__NEXT_DATA__`. Uma requisição por título (até 8), com 2 s entre elas.
  - **InHire:** `api.inhire.app/job-posts/public/pages` com o cabeçalho `X-Tenant: <empresa>`, a mesma chamada da página de carreiras. Uma por empresa (até 20).
  - **LinkedIn:** o LinkedIn não tem API de busca de vagas para uso pessoal (a de vagas é para parceiros) e a busca sem login vai contra os termos de uso e bloqueia com 429. Por isso o JobScout lê os e-mails de alerta de vagas que o LinkedIn manda (`jobalerts-noreply@linkedin.com`) pelo Gmail; esses alertas não viram rascunho de recrutador.
- Pontuação de 0 a 100: título procurado (50) ou parecido (30, aceita gênero e plural), empresa (40), palavras desejadas (10 cada, até 30), modelo de trabalho (+15, ou −30 se for outro), local (+10). Palavra excluída zera. Abaixo de 30, não entra.
- Títulos similares (`similar_titles`): tabela de equivalentes em português e inglês (Engenheiro de Dados → Data Engineer, Analytics Engineer...) e tradução palavra a palavra para o resto. Vale título similar (45).
- Modelos: remoto, híbrido, presencial na cidade atual e presencial mudando de cidade; sem nada marcado, vale o Perfil.
- Presets (`busca_presets`): buscas com nome, no painel lateral da aba Busca de vagas. Os marcados "Buscar sozinho" rodam junto com a busca automática; "Buscar agora" roda só o formulário.
- Os resultados ficam em `search_results`; vaga já salva não entra, e o que já apareceu (mesmo descartado) não volta. "Salvar vaga" cria a vaga como Visualizada.

## Freela e assistente da página

Módulo `jobscout/freela.py`. Tabelas `freelas`, `freela_estimates`, `freela_events` e `freela_payments`, com remoção em cascata.

- Situações: prospecção, estimativa enviada, negociação, contrato fechado, em andamento, concluído e perdido.
- Tipos: projeto fechado, por hora e mensal. Moedas: BRL, USD e EUR, somadas sempre em separado.
- O total da estimativa é calculado das linhas no servidor; nunca vem digitado.
- A tarefa de IA `freela` só recebe o escopo escrito pela pessoa, por isso não é privada. Ela devolve etapas e horas, nunca dinheiro.

O assistente (`extension/content/assist.js`) só existe com `assistAny` ligado no popup, que pede a permissão de todos os sites. O script é registrado junto com o de formulários, e `generic.js` só começa com a opção de formulário ligada: um não liga o outro. Nada sai da página antes do clique. Depois dele, a extensão manda endereço, título e texto visível (até 20 mil caracteres) para o JobScout local. Resumo, encaixe e proposta usam a tarefa privada `chat`, que fica no modelo local. Salvar como vaga passa por Rascunhos; salvar como freela grava direto, porque não publica nada.

## Busca (chat) e encaixe

- A aba Busca é um chat com histórico (`chat_threads`, `chat_messages`). Cada pergunta procura nos registros (`assistant.search`) e, com a tarefa privada "chat", a IA responde só com esses trechos; sem IA, lista o que achou. Cada resposta mostra as fontes.
- Encaixe: `assistant.rule_fit` dá o % das skills da vaga que o perfil tem (cartão do Kanban, detalhe e resultados da busca). `POST /api/vagas/{id}/encaixe` pede à IA nota, o que combina e o que falta, e guarda em `jobs.fit_ai`.

## Aparência

- Tema: JSON com `nome`, `claro` e `escuro`, usando as cores de `appearance.TOKENS`; só entram nomes conhecidos e valores de cor (`#rrggbb`, `rgb()`, `hsl()`). Fica em `preferencias.json` (`tema`).
- Personagem: imagens PNG, GIF, WebP ou SVG por pose (`idle` obrigatória, `think`, `throw`), até 600 KB cada, em `boneco.json`, mostradas em `<img>`.

## Segundo plano

- [jobscout/tray.py](../jobscout/tray.py): ícone nos ícones ocultos, em Win32 puro. Clique alterna a janela; o botão direito mostra Abrir, Painel e Sair.
- O × do overlay esconde (`Bridge.ocultar`): o servidor, a verificação de e-mail, os lembretes e a busca continuam. Com a janela escondida, o aviso vira notificação do Windows. Quem encerra é o Sair.
- Abrir o JobScout de novo só mostra a janela que já está rodando (`POST /api/janela/mostrar`).
- Config > Segundo plano: abrir escondido (`iniciar_oculto`) e iniciar com o Windows (chave `Run` do usuário, com `pythonw`).

## Modelos por tarefa

- Config > Modelos por tarefa escolhe, para cada tarefa, entre "Padrão" (o modelo do cartão de IA), "Desligada", qualquer modelo baixado no Ollama e, com chave, os do Gemini (só nas tarefas não privadas). Fica em `preferencias.json` (`ia_tarefas`). A variável própria da tarefa no `.env` ainda ganha.
- "Baixar" chama `POST /api/pull` do Ollama em segundo plano, com o andamento na atividade. A chave do Gemini fica em `preferencias.json` e nunca volta ao painel.

## Resultados e o que foi enviado

- No clique em Enviar, a extensão manda junto o arquivo enviado (`documentos`): o escolhido num `input[type=file]` ou o cartão selecionado entre os currículos já salvos no site, reconhecido pelo nome terminado em .pdf/.docx. Ao aprovar, ele vai para `applications.documents`. A resposta de pretensão salarial vai para `applications.salary_informed`.
- As respostas do formulário ficam sempre no histórico da vaga. Desmarcar "Reusar estas respostas" grava com `origin = 'registro'`, e essas respostas ficam fora do preenchimento, das sugestões e dos exemplos da IA.
- `GET /api/resultados` devolve uma linha por candidatura, com as etapas por que a vaga passou (movimentos de status, além do status atual):
  - **retorno:** qualquer resposta da empresa (em análise, entrevista, proposta ou recusada);
  - **entrevista e proposta:** contam se a vaga passou por elas, mesmo que depois tenha sido recusada.
- A tela Resultados filtra por período, fonte, currículo enviado, senioridade e modelo. Ela mostra quatro números de destaque e compara retorno, entrevista e proposta por currículo, faixa de salário informado, fonte e senioridade. Grupos com menos de 5 candidaturas são marcados como "poucos dados".
- `GET /api/saude` diz o que está operando (extensão com contato nos últimos 3 minutos, IA e modelo do Ollama, Gmail). A bolinha do painel fica verde, amarela se algo ligado falha, ou vermelha sem ligação com o JobScout; o detalhe fica na dica do mouse.

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
| `job_stages` | id, job_id, position, name, kind, state (pendente/atual/feita/pulada), scheduled_at, notes, done_at |
| `reminders` | id, job_id, intent, title, notes, next_at, every_days, remaining, state (ativo/concluido/parado), notified_at, calendar_id |
| `search_results` | id, url (única), source, title, company, location, work_mode, description, published_at, score, reasons, state (novo/salvo/descartado), job_id |
| `notes`, `insertions`, `capture_failures`, `gmail_seen` | apoio |

Status: visualizada → candidatado → em análise → entrevista → proposta / recusada / fria (esquecida). As etapas de cada empresa ficam por cima do status (ver Etapas do processo).

Perfil em `profile.json`: dados pessoais, links, pretensão, disponibilidade, texto do currículo e histórias. O leitor local de currículo (PDF/DOCX) transforma as atividades em histórias editáveis.

## Extensão

- Content scripts em todo o `linkedin.com` (o LinkedIn troca de página sem recarregar, então quem entra pelo feed também é atendido), `*.inhire.app` e `*.inhire.com.br`. Um adaptador por site isola os seletores; a InHire tenta JSON-LD `JobPosting` antes do DOM.
- LinkedIn: se os seletores não acharem título e empresa, a extensão manda só o link e o backend lê a página pública da vaga (`jobs-guest/jobs/api/jobPosting/<id>`, sem login, classes estáveis) em [jobscout/linkedin_public.py](../jobscout/linkedin_public.py). Uma busca por vaga; o que veio da página logada tem prioridade. Sem resposta, vira falha em Config.
- Com o JobScout fechado, os eventos ficam numa fila na extensão (até 200) e são enviados quando ele volta, em até 1 minuto.
- Eventos: `job_viewed`, `form_detected`, `application_submitted`, `selector_failed` (aparece em Config).
- Campos padrão (nome, e-mail, telefone, cidade, estado, país, localização, links, pretensão) por dicionário de rótulos, sem LLM. País e localização ("Cidade, Estado, País") saem no idioma do rótulo: "Brazil" numa pergunta em inglês, "Brasil" em português e espanhol ([jobscout/places.py](../jobscout/places.py)). Rótulos sobre outra pessoa ou coisa (“Nome da empresa”, “Telefone de emergência”) são ignorados. Dá para desligar no popup.
- Perguntas abertas viram rascunho de resposta. Sugestão vem do histórico (pergunta parecida já respondida) ou da LLM, se configurada. Aprovada, a extensão insere o texto no campo.
- Campos ainda vazios (texto curto, número, lista, rádio) vão em lote para `POST /api/extensao/sugestoes` com rótulo e opções. As regras ficam em [jobscout/suggest.py](../jobscout/suggest.py): respostas rápidas do Perfil, anos de experiência por skill a partir dos períodos do currículo (cargos sobrepostos contam uma vez; formação fica de fora) e, por último, o histórico. A resposta sempre é uma das opções do campo; sem opção compatível, não há sugestão. Skill que o currículo não cita vira 0 anos, com "Não consta no currículo" na explicação. Campo numérico (tipo number, `inputmode` numérico ou `numeric` no id, como no LinkedIn) só recebe número, e nenhum valor passa do `maxlength`. A mesma checagem vale para regras, histórico e IA, e a extensão não mostra nem preenche o que o campo recusaria. Perguntas sensíveis (gênero, raça, deficiência, idade, estado civil...) nunca recebem sugestão. A extensão mostra a sugestão num Shadow DOM ao lado do campo e só preenche no clique em Usar; campo com sugestão não vira rascunho de pergunta aberta.
- **Formulários em qualquer site** ([extension/content/generic.js](../extension/content/generic.js)): no popup, "Formulários de candidatura" tem duas flags.
  - **Neste site:** pede ao Chrome a permissão só daquele endereço (ex.: `https://jobs.ashbyhq.com`, que vale para todas as empresas na Ashby) e liga o preenchimento em qualquer formulário dele.
  - **Em todos os sites de vagas:** pede a permissão de todos os sites, mas só age em página que parece candidatura (`core.looksLikeApplication`): JSON-LD `JobPosting`, endereço de sistema de candidatura conhecido (Ashby, Greenhouse, Lever, Workable, Gupy, SmartRecruiters, Recruitee, BambooHR, Workday, Teamtailor, Breezy, Sólides) ou endereço/título de vaga com campos de currículo, LinkedIn, experiência ou pretensão. Login, compra e contato ficam de fora.
  - O service worker registra o script (`chrome.scripting.registerContentScripts`) para os endereços com permissão e injeta na aba aberta na hora. LinkedIn, InHire, WhatsApp e Gmail continuam com o adaptador próprio.
  - O formulário é a `<form>` com mais campos ou, sem `<form>` (Ashby), o menor bloco com todos os campos. Captcha, busca e newsletter são ignorados.
  - Perguntas respondidas com botões (Sim/Não da Ashby) viram pergunta de opção: sugestão ao lado e "Usar" clica no botão.
  - Em sites de terceiros, toda pergunta sem resposta recebe sugestão ao lado do campo: regras primeiro, depois a IA em lotes de 6, inclusive texto longo (até 1.500 caracteres). O que nem a IA responde mostra "Sem sugestão"; texto longo sem sugestão ainda vira rascunho. O script roda também em iframes (formulário embutido) de endereços com permissão.
  - Perguntas de consentimento (SMS, WhatsApp, termos, privacidade) nunca recebem sugestão.
  - Currículo: ao lado do campo de arquivo aparece a escolha da versão; "Anexar" gera o PDF (`POST /api/extensao/curriculo-pdf`) e coloca no campo. Só no clique.
  - Grupo de caixas vira uma pergunta: lista de ferramentas é marcada pelo currículo; o resto vai para a IA, que pode escolher várias.
  - Lista com busca (combobox): depois de digitar, o script escolhe a opção mais parecida.
  - A IA tem uma segunda tentativa, campo a campo, para o que pulou no lote. Resposta aberta com número ou ferramenta fora do Perfil é descartada.
  - A vaga sai do JSON-LD ou do título da página; a empresa, do endereço do sistema de candidatura. Vira rascunho "Nova vaga" com origem "Outro site" (`web`), sem a etapa `/application` e sem `utm_`.
- Pretensão salarial em duas moedas (`pretensao_salarial`, em real, e `pretensao_usd`, em dólar). A moeda dita na pergunta ou nas opções manda; sem moeda, inglês usa dólar e o resto usa real, e a sugestão mostra o outro valor. Não há conversão automática: pergunta que pede uma moeda sem valor no Perfil fica sem sugestão de pretensão; no Perfil, um botão completa a outra moeda pela cotação do dia (`GET /api/cotacao`), e a pessoa confere e salva. Campo numérico recebe só o número.
- "Você mora/está em X?" (América Latina, LATAM, América do Sul, Europa, América do Norte ou um país) é respondida pelo país do Perfil (`places.in_region`) e nunca vai para a IA.
- Nunca clica em Enviar.

## E-mail

- Login do Google (OAuth) no próprio computador, com o cliente salvo em Config ou no `.env`; o Gmail não precisa ficar aberto (PKCE, escopos `gmail.readonly` e `calendar.events`), verificação a cada `JOBSCOUT_GMAIL_INTERVALO_MIN` minutos. Quem conectou antes só com o Gmail precisa desconectar e conectar de novo para liberar a agenda.
- Sem projeto no Google Cloud: [jobscout/imap_mail.py](../jobscout/imap_mail.py) lê por IMAP com senha de app (verificação em duas etapas na conta). Caixa em modo leitura, `BODY.PEEK` não marca como lido, mesma consulta do Gmail por `X-GM-RAW`. A senha fica cifrada com DPAPI em `preferencias.json`. Com ela conectada, tem prioridade sobre o OAuth.
- Sem Gmail configurado, a aba Rascunhos importa arquivos `.eml`.
- Pré-filtro por regras: domínio de empresa já acompanhada ou palavras como “processo seletivo”, “entrevista”.
- Avaliação de recrutamento e seleção (`mail.relevance`): regras decidem os casos claros (empresa acompanhada, plataforma de recrutamento, "processo seletivo", "entrevista"; newsletter, curso e lista de envio com descadastro ficam de fora). Os duvidosos vão para a IA local (tarefa privada "classificar"), que responde se o e-mail envolve a pessoa num processo e por quê. Sem IA, na dúvida vira rascunho. O motivo aparece na atividade e no rascunho (`relevancia`).
- Alertas de vaga do LinkedIn não viram rascunho: vão para a busca automática.
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

O modelo escolhido em Config > IA (guardado em `preferencias.json`, chave `ia`) vale para toda tarefa que o `.env` não fixar com a variável própria. O padrão sugerido é `ollama:gemma3:4b`, que roda inteiro numa GPU de 6 GB.

Nos formulários, a IA entra depois das regras ([jobscout/ai_suggest.py](../jobscout/ai_suggest.py)):

- A extensão manda de uma vez os campos curtos que as regras não responderam (`POST /api/extensao/sugestoes-ia`) e mostra "IA pensando…" ao lado deles.
- O pedido leva o perfil, a vaga e até 12 respostas anteriores: as mais parecidas com cada pergunta e as mais recentes. Assim a IA responde do jeito que a pessoa já respondeu.
- Sai como JSON. Só vale resposta que cabe no campo (uma das opções, ou um número) e que diz de onde veio. Resposta sem fonte é descartada, para a IA não dizer "não" a uma skill que o currículo só não cita.
- Perguntas que só o Perfil responde nunca vão para a IA: autorização, visto, mudança, pretensão, disponibilidade, idioma, localização e as sensíveis.
- A sugestão aparece como "Sugestão da IA" e só preenche no clique em Usar. Pergunta curta que nem a IA respondeu vira rascunho, como as abertas.
- As respostas abertas (rascunho) também recebem as respostas parecidas anteriores e o idioma da pergunta.

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
| POST | `/api/extensao/sugestoes` | Sugestões para os campos de um formulário aberto |
| GET/PUT | `/api/preferencias` | Nome do assistente e pasta do JobScout (PUT prepara a pasta) |
| POST | `/api/pasta/preparar`, `/api/pasta/abrir` | Recriar a pasta; abrir pasta, extensão, exportações ou um arquivo dentro dela no Explorer |
| GET/POST | `/api/melhorias` | Backlog de melhoria do currículo (a extensão também cria) |
| PATCH/POST | `/api/melhorias/{id}`, `/api/melhorias/{id}/reprocessar` | Estado e nota; responder de novo com o currículo atual |
| GET | `/api/curriculo/analise` | Cargos, anos por skill e checagens por regras |
| POST | `/api/curriculo/revisar-ia`, `/api/curriculo/online` | Revisão pela IA; GitHub, LinkedIn e site |
| GET | `/api/resultados`, `/api/saude` | Candidaturas para os indicadores; estado das ferramentas |
| GET/PUT | `/api/curriculo/completo`; POST `/api/curriculo/completo/do-texto` | Currículo completo; montar a partir do texto |
| POST/GET/PUT | `/api/curriculo/versoes`, `/api/curriculo/versoes/{id}`, `/remover` | Versões por vaga |
| GET/POST | `/api/curriculo/previa?versao=`, `/api/curriculo/pdf` | Prévia HTML; PDF na pasta do JobScout |
| POST | `/api/mensagens/responder` | Resposta a recrutador |
| POST | `/api/ia/baixar` | Baixar modelo no Ollama |
| GET/POST/PUT | `/api/mensagens/modelos`, `/api/mensagens/modelos/{chave}`, `/restaurar` | Intenções de mensagem (padrões e criadas) |
| GET/POST/PATCH | `/api/recrutadores`, `/api/recrutadores/{id}` | Recrutadores com as vagas vinculadas |
| POST | `/api/vagas/{id}/recrutadores`, `/api/vagas/{id}/recrutadores/{cid}/remover` | Vincular e desvincular |
| POST | `/api/extensao/chat`, `/api/extensao/chat/vincular` | Contexto da barra do chat; vincular a conversa a uma vaga |
| POST | `/api/extensao/chat/abordagem` | Abordagem de recrutador no chat vira rascunho de vaga |
| GET/PUT/POST | `/api/mensagens/estilo?canal=chat` ou `email`, `/restaurar` | Estilo de comunicação do chat e do e-mail |
| GET/PUT/POST | `/api/vagas/{id}/etapas`, `/api/vagas/{id}/etapas/mover` | Etapas da vaga; mover para uma etapa |
| GET | `/api/quadros` | Empresas com vaga, para escolher o quadro |
| GET/PUT | `/api/empresas/{id}/quadro` | Quadro (etapas) da empresa, com as vagas; salvar e aplicar |
| GET/POST | `/api/lembretes?vaga=&estado=`, `/api/lembretes/{id}/feito`, `/adiar`, `/parar` | Lembretes, modelos e estado da agenda |
| GET/PUT/POST | `/api/busca/config`, `/api/busca/rodar` | Busca automática: configuração e rodar agora |
| GET/POST | `/api/busca/resultados?estado=`, `/api/busca/resultados/{id}/salvar`, `/descartar` | Vagas encontradas |
| POST | `/api/exportar` | Planilha `.xlsx` com as abas e status escolhidos, gravada em `Exportações\` |
| POST | `/api/eventos` | Entrada da extensão |
| GET/POST | `/api/extensao/insercoes` | Respostas aprovadas para inserir |
| GET/PUT | `/api/perfil`, GET `/api/perfil/campos` | Perfil e campos padrão |
| POST | `/api/analisar`, `/api/emails/importar` | Currículo e `.eml` |
| GET/POST | `/api/gmail/conectar`, `/retorno`, `/verificar`, `/desconectar` | Google (Gmail e Agenda) |

Requisições com `Origin` de outro site são recusadas (403); só o próprio painel e `chrome-extension://` passam. Preferências, pasta e exportação aceitam só o painel.

Freela: `GET|POST /api/freelas`, `GET|PATCH /api/freelas/{id}`, `POST /api/freelas/{id}/remover`, `POST /api/freelas/estimar`, `POST /api/freelas/{id}/estimativas`, `PUT /api/freelas/estimativas/{id}`, `POST /api/freelas/estimativas/{id}/remover`, `POST /api/freelas/{id}/eventos`, `POST /api/freelas/eventos/{id}/remover`, `POST /api/freelas/{id}/pagamentos`, `PATCH /api/freelas/pagamentos/{id}`, `POST /api/freelas/pagamentos/{id}/remover`.

Assistente da página, só para a extensão: `POST /api/extensao/pagina`, `POST /api/extensao/pagina/salvar`, `POST /api/extensao/pagina/ia`.

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
