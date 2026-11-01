# JobScout

Assistente pessoal de candidaturas que roda no seu computador. Ele acompanha as vagas que você vê, ajuda a preencher formulários, procura vagas novas, responde recrutadores e organiza cada processo seletivo, do currículo enviado à proposta.

Tem três partes:

- um programa local em Python, que guarda tudo em SQLite;
- um painel com um boneco na tela, que fica nos ícones ocultos quando você não precisa dele;
- uma extensão do Chrome, que lê as páginas e preenche os campos.

**Regra central:** nada entra no seu histórico sem a sua aprovação, e o JobScout nunca envia nada por você. O que ele captura vira um rascunho para aprovar, e o que ele sugere só vai para o campo quando você clica em Usar. Candidatar-se e enviar mensagem são sempre com você.

A especificação técnica está em [docs/ESPECIFICACAO.md](docs/ESPECIFICACAO.md).

## O que ele faz

### Formulários de candidatura

- **Em qualquer site:** LinkedIn e InHire funcionam direto. Nos outros (Ashby, Greenhouse, Lever, Gupy, páginas de empresa), você liga pelo popup da extensão, por site ou em todos os sites de vagas.
- **Preenche os campos padrão:** nome, e-mail, telefone, LinkedIn, localização e país, no idioma da pergunta.
- **Sugere ao lado de cada pergunta:** usa primeiro o Perfil, o currículo e o histórico, e depois a IA, inclusive em perguntas abertas. Cada sugestão mostra de onde veio.
- **Pretensão em real e dólar:** escolhe pela moeda da pergunta ou pelo idioma.
- **Anexa o currículo:** você escolhe a versão e clica em Anexar.
- **Não sugere em temas sensíveis:** gênero, raça, deficiência, idade e consentimentos ficam com você.

### Currículo

- Editor completo com habilidades por experiência, empresas atendidas em consultoria e graduação separada de pós.
- Modelos padrão e versões `cargo_empresa` para cada vaga, com exportação em PDF.
- IA que melhora cada item e revisa o currículo, sem aceitar número ou ferramenta que não esteja no texto.
- Conferência entre as habilidades do perfil e as das experiências.
- Pontos de melhoria: a sugestão que não reflete a sua experiência vai para uma lista, e você reprocessa depois de ajustar o currículo.

### Busca de vagas

- Busca a cada X horas, ou quando você pedir, por títulos, empresas, palavras e modelo de trabalho.
- Procura também títulos similares em outros idiomas ("Engenheiro de Dados" inclui "Data Engineer").
- Fontes: Gupy, Himalayas, InHire, Greenhouse, Lever, Ashby e os alertas do LinkedIn que chegam por e-mail.
- Dá nota a cada vaga, mostra o motivo e o encaixe com o seu perfil, e guarda buscas prontas como presets.

### Acompanhamento

- Kanban geral e quadro por empresa, com etapas que você desenha (testes, entrevistas, visita) e filtros.
- Lembretes com repetição para cobrar retorno ou pedir feedback, com link para o Google Agenda e arquivo `.ics`.
- Resultados: taxa de retorno, entrevistas e propostas, comparadas por currículo enviado, salário, fonte e senioridade.
- Exportação para Excel e linha do tempo de tudo o que aconteceu.

### Recrutadores

- Barra "JobScout · responder" no LinkedIn, WhatsApp Web e Gmail: lê a conversa e escreve a resposta no formato de cada canal, com o seu estilo. Ela só insere o texto; quem envia é você.
- Modelos prontos: interesse, mais informações, cobrar retorno, agendar, feedback, recusar e outros, todos editáveis.
- Reconhece quando um recrutador oferece uma vaga e cria o rascunho da oportunidade.
- Lê o Gmail, separa o que é recrutamento de newsletter e propõe a mudança de status da vaga.

### Consulta e aparência

- Aba **Busca**: chat com histórico para perguntar sobre as suas vagas, respostas e mensagens.
- Tema importado por JSON e personagem importado no lugar do boneco.

A IA é opcional. Sem ela, tudo funciona por regras. Com o [Ollama](https://ollama.com), roda no seu computador e nada sai dele. O Gemini é a opção em nuvem e nunca é usado em e-mails, mensagens e chat, a menos que você libere em `JOBSCOUT_LLM_NUVEM_PRIVADO`.

## Como rodar

Precisa de Windows, Python 3.11 ou mais novo e Google Chrome.

```text
py -m venv .venv
.\.venv\Scripts\python -m pip install -e .
.\.venv\Scripts\python -m jobscout
```

O JobScout abre como uma bolha no canto da tela. O **×** esconde o programa nos ícones ocultos, e ele continua trabalhando. Clique no ícone para voltar; com o botão direito há Abrir, Painel e Sair.

Outras opções:

- `python -m jobscout --navegador` abre o painel no navegador, em `http://127.0.0.1:8765/`.
- `python -m jobscout --no-browser` roda só o servidor.
- Em Config > Segundo plano dá para abrir já escondido e iniciar com o Windows.

### Extensão do Chrome

1. Ao abrir, o JobScout cria a pasta `Documentos\JobScout`, com a extensão, as planilhas exportadas e um guia.
2. Em `chrome://extensions`, ligue o modo do desenvolvedor.
3. Clique em "Carregar sem compactação" e escolha a pasta `Extensão do Chrome`.
4. Quando atualizar, clique em ↻ na extensão e recarregue as abas abertas.

### IA local (opcional)

Instale o Ollama e, em Config > IA, baixe um modelo. O sugerido é `gemma3:4b`, cerca de 3 GB. O passo a passo está na própria tela.

### E-mail (opcional)

Sem projeto no Google Cloud: ligue a verificação em duas etapas na conta Google, crie uma [senha de app](https://myaccount.google.com/apppasswords) e cole em Config > Gmail. A leitura é só de consulta, e o Gmail não precisa ficar aberto.

### Onde ficam os dados

Em `%USERPROFILE%\.jobscout\`: banco, perfil e preferências. A senha de app fica cifrada para o seu usuário do Windows.

## Limitações

**Ainda não validado em uso real**

- Barra de resposta e detecção de abordagem no LinkedIn e no WhatsApp reais: só testadas em páginas de imitação. A barra no Gmail não foi testada nem assim.
- Senha de app, leitura do Gmail e alertas do LinkedIn: testados com servidor e e-mails simulados.
- Permissões e flags do popup, numa extensão instalada.
- Anexar o currículo em site real: testado só numa página de imitação, e o site pode recusar o arquivo.
- Notificação do Windows, menu do botão direito do ícone e início com o Windows.

**Limites do que existe**

- **Só Windows e Chrome:** o overlay e o ícone usam recursos do Windows.
- **Seletores frágeis:** LinkedIn, WhatsApp e Gmail mudam as páginas, e a extensão pode parar de achar os campos até um ajuste.
- **LinkedIn:** não há API de busca de vagas para uso pessoal, e a busca sem login vai contra os termos de uso. Por isso, as vagas de lá vêm só dos alertas por e-mail.
- **Quadros por empresa:** InHire, Greenhouse, Lever e Ashby só trazem as empresas que você listar.
- **Agenda:** sem projeto no Google Cloud, o lembrete abre o evento pronto, mas você precisa clicar em Salvar. A criação automática exige o login do Google com projeto próprio.
- **IA local:** pode enfeitar textos longos e fica lenta em formulários grandes. As travas pegam números e ferramentas inventados, mas não frases. Confira antes de usar.
- **Melhoria de item do currículo:** descarta sugestões com frequência, porque a trava é rígida.
- **Campos fora do padrão:** seletores muito personalizados podem não ser reconhecidos.
- **Conversão de moeda:** é um botão no Perfil com arredondamento, não automática no formulário.
- **Modo "todos os sites":** age só em páginas que parecem candidatura. Para outro tipo de formulário, ligue o site específico.
- **Segurança local:** o painel não tem login e atende só neste computador, sem proteger os dados de outros usuários da mesma conta.

## Próximos passos

1. **Validar no uso real:** conectar o Gmail e testar LinkedIn, WhatsApp e Gmail, ajustando os seletores.
2. **Instalador:** gerar um `jobscout.exe`, para instalar sem Python e sem terminal.
3. **Extensão:** empacotar e publicar, sem precisar do modo do desenvolvedor.
4. **Backup:** exportar e restaurar banco, perfil e configurações.
5. **Mais fontes de vagas:** avaliar outras fontes públicas e permitir mais de uma busca por empresa.
6. **IA mais confiável:** revisar textos longos frase a frase e avaliar a qualidade das respostas.
7. **Resultados:** comparar qual currículo e qual mensagem trazem mais retorno ao longo do tempo.
8. **Manutenção:** dividir o `app.js`, criar testes automáticos de interface e padronizar fins de linha com `.gitattributes`.
9. **Gemini Nano:** avaliar a IA do próprio Chrome como alternativa ao Ollama.

## Testes

```text
.\.venv\Scripts\python -m unittest discover -s tests
node --test extension/tests/core.test.js
```

## Requisitos de uso

O JobScout é para uso pessoal: lê as páginas que você abre, sem coleta em massa. Respeite os termos dos sites que usa, e use o material de entrevista para se preparar antes, não durante.
