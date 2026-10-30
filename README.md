# JobScout

Assistente pessoal de candidaturas. Uma extensão do Chrome acompanha o LinkedIn e a InHire, um backend local guarda tudo em SQLite e um painel aberto na segunda tela mostra a linha do tempo, o Kanban e a fila de **rascunhos**.

Regra central: nada capturado ou alterado automaticamente entra no histórico sem a sua aprovação. Cada vaga vista, candidatura detectada, resposta de formulário e e-mail de recrutador vira um rascunho. Você revisa, ajusta e aprova (ou descarta) na aba Rascunhos, no popup do painel, na coluna Rascunho do Kanban, na gaveta da vaga ou no popup da extensão.

A especificação está em [docs/ESPECIFICACAO.md](docs/ESPECIFICACAO.md).

## Rodar

```text
py -m venv .venv
.\.venv\Scripts\python -m pip install -e .
.\.venv\Scripts\python -m jobscout
```

O JobScout abre como **overlay**: uma bolha no canto inferior direito, sempre por cima dos outros programas (navegador, jogos em janela ou tela cheia sem borda).

- **Bolha:** só o boneco e uma bolinha vermelha com o número de rascunhos pendentes. O boneco fica sentado quando está tudo parado, pensa enquanto lê uma vaga e arremessa a maleta quando você envia uma candidatura; passe o mouse para ver o status. Arraste para mover: perto da borda direita ela gruda, e perto do canto volta para o lugar padrão. Cada novidade vira um pop-up pequeno em cima da bolha. Em Config você escolhe quais tipos de aviso viram pop-up.
- **Menu:** clique na bolha para abrir o menu, com o nome do assistente no topo (troque em Config > Nome e pasta) e os itens Agora, Rascunhos, Linha do tempo, Kanban, Empresas, Busca, Perfil e Config, mais a chave do modo noturno, 📌 (sempre por cima), ⤢ (abrir no navegador) e × (fechar).
- **Painel:** cada item do menu abre um painel na borda direita. ⇔ expande para cobrir mais tela (Kanban e a página da empresa já abrem expandidos). ▾ ou Esc voltam para a bolha.

A aba **Agora** mostra o próximo rascunho para aprovar e um feed ao vivo do que está sendo processado, inclusive o que foi ignorado e por quê.

`python -m jobscout --navegador` abre o painel no navegador, como antes. O painel completo continua em `http://127.0.0.1:8765/`. Os dados ficam em `%USERPROFILE%\.jobscout\` (`jobscout.db`, `profile.json`).

Jogos em tela cheia exclusiva desenham por cima de qualquer janela; nesse caso use o modo janela ou "tela cheia sem borda".

## Pasta do JobScout

Ao abrir, o JobScout prepara uma pasta fácil de achar (padrão `%USERPROFILE%\Documents\JobScout`; troque em Config > Nome e pasta, com o botão "Escolher pasta…"):

- `Extensão do Chrome\`: cópia da extensão, atualizada sempre que o JobScout abre. É essa pasta que você carrega no Chrome.
- `Exportações\`: as planilhas do Excel.
- `Como usar o JobScout.txt`: o passo a passo para deixar tudo funcionando.

O banco e o perfil continuam na pasta de dados (`%USERPROFILE%\.jobscout\`).

## Exportar para Excel

Config > Exportar para Excel: escolha as abas (vagas e candidaturas, empresas, perguntas e respostas dos formulários, linha do tempo) e, se quiser, só alguns status de vaga. O `.xlsx` cai em `Exportações\` com cabeçalho fixo e filtro em cada coluna; os botões abrem a planilha ou a pasta.

## Extensão

1. Abra `chrome://extensions` (ou Edge/Brave) e ative o modo do desenvolvedor.
2. "Carregar sem compactação" → pasta `Extensão do Chrome` dentro da pasta do JobScout (Config > Abrir pasta da extensão).
3. Com o JobScout rodando, abra uma vaga no LinkedIn: um rascunho aparece no painel em menos de 2 segundos.

A extensão só lê a página e preenche campos. O botão Enviar é sempre seu.

## O que o JobScout tira de cada vaga

Sem IA, só com regras, e tudo passa pelo rascunho:

- Senioridade, contrato e setor (página pública do LinkedIn), modalidade (remoto/híbrido/presencial), inglês (obrigatório, diferencial ou vaga em inglês), salário quando a vaga cita, região (Brasil, LATAM ou internacional).
- Skills pedidas na vaga, marcando as que aparecem no seu currículo do Perfil.
- **Empresa:** cadastrada ao aprovar a vaga, com setor, tamanho, sede e descrição da página pública dela no LinkedIn. A página da empresa mostra as vagas (com link), o Kanban só daquela empresa, notas e a linha do tempo.
- **Questionário:** no clique em Enviar, a extensão lê o que você preencheu em todas as etapas do formulário e manda junto. As respostas entram no rascunho e são guardadas ao aprovar. Na próxima vez que a mesma pergunta aparecer (texto curto, número, lista ou sim/não), a extensão já preenche e marca o campo com contorno verde. Perguntas abertas continuam virando rascunho de resposta, com a sugestão do histórico.
- **Sugestões de resposta:** para perguntas curtas e de opção, a extensão mostra uma sugestão ao lado do campo, com a origem, e só preenche quando você clica em Usar. Vem das respostas rápidas do Perfil (nível de inglês e espanhol, autorização de trabalho, visto, mudança de cidade, modelos de trabalho, pretensão, disponibilidade), do currículo ("Quantos anos com Python?" soma os períodos dos cargos que citam Python, sem contar formação; "Tem experiência com Airflow?" só diz sim se o currículo mostrar) e do histórico. Faixas como "3 a 5 anos" e níveis como "Fluente" são casados com as opções do campo. Perguntas sobre gênero, raça, deficiência, idade e afins nunca recebem sugestão. Dá para desligar no popup da extensão.
- **Vaga fria:** vaga em aberto sem movimento há `JOBSCOUT_DIAS_FRIA` dias (14 por padrão) vira um rascunho "Marcar como fria". Aprovado, ela vai para a coluna Fria do Kanban.

Se o layout do LinkedIn mudar e a extensão não achar título e empresa, o JobScout busca os dados na página pública da vaga. Vagas vistas com o JobScout fechado ficam guardadas na extensão e chegam quando ele abrir. Depois de atualizar os arquivos da extensão, clique em ↻ no card dela em `chrome://extensions` e recarregue as abas do LinkedIn.

## Testes

```text
.\.venv\Scripts\python -m unittest discover -s tests
node --test extension/tests/core.test.js
```
