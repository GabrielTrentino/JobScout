# JobScout

JobScout é um executável de linha de comando que lê o seu perfil profissional, busca vagas recentes nos principais sites e guarda o que você fez com cada uma: visitou, candidatou, arquivou, anotou ou guardou o link.

Os dados ficam na sua máquina. A análise do currículo funciona sem inteligência artificial. A IA é opcional e só entra se você ligar uma chave no `.env`.

## Decisões de produto

### Analisador de currículo

Sim. A busca fica genérica se as palavras-chave forem digitadas à mão. O analisador transforma o currículo em um perfil reutilizável: cargo-alvo, senioridade, habilidades, idiomas, localização e modalidade (remoto, híbrido ou presencial).

Você confirma o perfil antes da primeira busca. O programa não inventa skill que não esteja no texto, e no modo local não infere senioridade que o currículo não declare.

### Uso sem IA

Sim. Esse é o modo padrão.

| | Modo local (padrão) | Modo com IA (opcional) |
|---|---|---|
| Rede | Não chama nenhum modelo | Chama o provedor configurado no `.env` |
| Chave | Não precisa | `JOBSCOUT_AI_API_KEY` |
| Entrada | PDF ou DOCX | O mesmo arquivo |
| Extração | Texto + seções + lista de tecnologias conhecidas | O modelo devolve o mesmo formato, com sinônimos e cargo-alvo sugerido |
| Saída | Perfil editável | Perfil editável, com o mesmo esquema |
| Quando falha | Mensagem clara e perfil parcial | Cai para o modo local e avisa |

Os dois modos gravam o mesmo perfil. A busca, a lista e o acompanhamento não dependem de IA.

### Vagas recentes e chaves principais

Cada busca devolve só vagas dentro da janela pedida (padrão: 14 dias) e mostra as chaves que bateram com o perfil. Uma vaga sem nenhuma chave principal não entra na lista, a menos que você passe `--all`.

Chaves principais são as que você marcou no perfil (por exemplo `Python`, `FastAPI`, `PostgreSQL`). Chaves secundárias aumentam a pontuação, mas não são obrigatórias.

### Acompanhamento

Cada vaga salva tem link, fonte, data de publicação, chaves encontradas e um estado seu:

| Estado | Significado |
|---|---|
| `nova` | Entrou na lista e ainda não foi aberta |
| `vista` | Você abriu ou marcou como visitada |
| `candidatada` | Você se candidatou |
| `entrevista` | Há processo em andamento |
| `oferta` | Recebeu proposta |
| `recusada` | A empresa recusou ou você desistiu |
| `arquivada` | Fora do fluxo, mantida no histórico |

Também dá para guardar nota livre, data da candidatura e o link original. Nada disso é enviado para fora.

## Forma de distribuição

Um único executável:

```text
jobscout.exe
```

No desenvolvimento o mesmo programa roda com `python -m jobscout`. O empacotamento (PyInstaller) gera o `.exe` para Windows. Configuração e banco não ficam dentro do executável:

```text
%USERPROFILE%\.jobscout\
  jobscout.db      banco local (vagas, perfil, notas)
  profile.json     cópia legível do perfil confirmado
```

O `.env` fica na pasta do projeto durante o desenvolvimento e ao lado do `.exe` quando você usar o executável. Os dois lugares são lidos; a variável de ambiente do sistema ganha se existir.

## Fontes

A busca usa fontes com API pública ou listagem aberta. Sites que proíbem coleta automatizada ou exigem login não são raspados.

| Fonte | Acesso previsto | Observação |
|---|---|---|
| Remotive | API pública | Vagas remotas |
| Remote OK | API pública | Vagas remotas |
| Arbeitnow | API pública | Vagas, muitas na Europa |
| The Muse | API pública | Vagas com descrição |
| Adzuna | API com chave | Brasil e outros países; chave no `.env` |
| Jooble | API com chave | Agregador; chave no `.env` |
| USAJOBS | API com chave | Setor público dos EUA, opcional |

LinkedIn, Indeed, Catho, Glassdoor e Gupy ficam de fora da coleta automática. O JobScout aceita colar um link desses sites (`jobscout add <url>`) para acompanhar a vaga do mesmo jeito que as buscadas. Incluir um site novo exige uma fonte com termos de uso compatíveis com consulta automatizada.

A ordem padrão é: Remotive, Remote OK, Arbeitnow, The Muse. Adzuna e Jooble entram quando a chave correspondente existe.

## Fluxo

1. `jobscout analyze currículo.pdf` monta o perfil no modo local.
2. Você ajusta chaves principais e cidade, se quiser.
3. `jobscout search` consulta as fontes, descarta duplicata (mesmo link ou mesmo título + empresa) e grava as vagas novas.
4. `jobscout jobs` lista o que está salvo.
5. `jobscout open`, `visit`, `apply` e `note` atualizam o acompanhamento.

Rodar `search` de novo não apaga estado. Se a vaga já existia, só a data de "vista por último na fonte" muda.

## Comandos e respostas de saída

A saída padrão é texto para o terminal. `--json` devolve o mesmo conteúdo em JSON, uma estrutura por comando, para script. Erro vai para a saída de erro e o processo termina com código diferente de zero.

### Analisar currículo (modo local)

```text
jobscout analyze curriculo.pdf
```

```text
Modo: local
Arquivo: curriculo.pdf

Cargo-alvo: Desenvolvedor backend
Senioridade: pleno
Localização: São Paulo, Brasil
Modalidade: remoto ou híbrido
Idiomas: português, inglês

Chaves principais:
  Python, FastAPI, PostgreSQL, Docker

Chaves secundárias:
  Redis, AWS, Git, testes automatizados

Perfil salvo em %USERPROFILE%\.jobscout\profile.json
Confirme ou edite com: jobscout profile edit
```

### Analisar com IA

```text
jobscout analyze curriculo.pdf --ai
```

```text
Modo: ia (openai)
Arquivo: curriculo.pdf

Cargo-alvo sugerido: Engenheiro de software backend
Senioridade sugerida: pleno
Chaves principais sugeridas:
  Python, FastAPI, PostgreSQL, Docker, APIs REST

Aviso: sugestão da IA. Nada foi buscado ainda.
Perfil salvo. Revise com: jobscout profile show
```

Sem chave, o comando não chama a rede:

```text
jobscout: modo ia indisponível (JOBSCOUT_AI_API_KEY ausente).
Use o modo local: jobscout analyze curriculo.pdf
```

### Ver perfil

```text
jobscout profile show
```

```text
Perfil ativo
  Cargo: Desenvolvedor backend
  Senioridade: pleno
  Onde: São Paulo | remoto, híbrido
  Principais: Python, FastAPI, PostgreSQL, Docker
  Secundárias: Redis, AWS, Git
  Atualizado: 2026-09-25 18:10
```

### Buscar vagas recentes

```text
jobscout search --since 7d
```

```text
Busca: últimos 7 dias
Perfil: Desenvolvedor backend
Fontes: remotive, remoteok, arbeitnow, themuse

  4 vagas novas, 1 já acompanhada, 12 ignoradas (sem chave principal)

#   Pontos  Quando     Fonte      Vaga
1   86      há 1 dia   Remotive   Backend Engineer — Northwind
        Chaves: Python, FastAPI, PostgreSQL
        https://remotive.com/remote-jobs/example-1
2   74      há 3 dias  Remote OK  Python API Developer — Lumen
        Chaves: Python, Docker
        https://remoteok.com/remote-jobs/example-2
3   61      há 5 dias  The Muse   Software Engineer — Campo
        Chaves: Python, PostgreSQL
        https://www.themuse.com/jobs/example-3
4   55      há 6 dias  Arbeitnow  Backend Developer — Kite
        Chaves: Docker, PostgreSQL
        https://www.arbeitnow.com/jobs/example-4

Já acompanhada (estado mantido):
  #18  vista   Backend Python — Acme   candidatada em 2026-09-20

Próximo passo: jobscout jobs   ou   jobscout open 1
```

A coluna `Pontos` vai de 0 a 100: chaves principais pesam mais, chaves secundárias e modalidade compatível somam, vaga mais antiga dentro da janela perde ponto.

### Listar o que está salvo

```text
jobscout jobs --status nova,vista
```

```text
Filtro: nova, vista    2 vagas

ID   Estado  Pontos  Fonte      Vaga
104  nova    86      Remotive   Backend Engineer — Northwind
        Chaves: Python, FastAPI, PostgreSQL
        Link: https://remotive.com/remote-jobs/example-1
        Publicada: 2026-09-24    Encontrada: 2026-09-25
105  vista   74      Remote OK  Python API Developer — Lumen
        Chaves: Python, Docker
        Link: https://remoteok.com/remote-jobs/example-2
        Visitada: 2026-09-25 14:02
```

### Abrir, marcar visita e candidatura

```text
jobscout open 104
```

Abre o link no navegador e grava `vista` se o estado ainda era `nova`.

```text
Aberta no navegador.
#104  vista   Backend Engineer — Northwind
Link: https://remotive.com/remote-jobs/example-1
```

```text
jobscout apply 104 --note "Enviei pelo site da empresa"
```

```text
#104  candidatada   Backend Engineer — Northwind
Candidatura: 2026-09-25 18:40
Nota: Enviei pelo site da empresa
Link: https://remotive.com/remote-jobs/example-1
```

```text
jobscout note 104 "Pediram pretensão até sexta"
```

```text
#104  nota adicionada
  2026-09-25 18:40  Enviei pelo site da empresa
  2026-09-25 19:05  Pediram pretensão até sexta
```

```text
jobscout status 104 entrevista
```

```text
#104  entrevista   Backend Engineer — Northwind
```

### Incluir um link manual

```text
jobscout add "https://www.linkedin.com/jobs/view/123" --title "Backend Python" --company "Acme"
```

```text
#110  nova   Backend Python — Acme
Fonte: manual
Link: https://www.linkedin.com/jobs/view/123
```

### Exportar

```text
jobscout export candidaturas.csv
```

```text
12 vagas escritas em candidaturas.csv
```

Colunas: `id`, `estado`, `titulo`, `empresa`, `fonte`, `link`, `publicada_em`, `encontrada_em`, `visitada_em`, `candidatada_em`, `pontos`, `chaves`, `notas`.

### JSON

```text
jobscout jobs --status nova --json
```

```json
{
  "filtro": ["nova"],
  "total": 1,
  "vagas": [
    {
      "id": 104,
      "estado": "nova",
      "pontos": 86,
      "titulo": "Backend Engineer",
      "empresa": "Northwind",
      "fonte": "remotive",
      "link": "https://remotive.com/remote-jobs/example-1",
      "publicada_em": "2026-09-24",
      "encontrada_em": "2026-09-25T18:12:00-03:00",
      "visitada_em": null,
      "candidatada_em": null,
      "chaves": ["Python", "FastAPI", "PostgreSQL"],
      "notas": []
    }
  ]
}
```

### Erros previstos

| Situação | Código | Mensagem |
|---|---|---|
| Currículo ilegível ou vazio | 2 | `jobscout: não consegui ler texto de curriculo.pdf` |
| Perfil ainda não existe | 2 | `jobscout: nenhum perfil. Rode jobscout analyze <arquivo>` |
| Id inexistente | 2 | `jobscout: vaga 999 não encontrada` |
| Fonte sem rede | 0, com aviso | `Aviso: arbeitnow indisponível (tempo esgotado). As outras fontes seguiram.` |
| IA pedida sem chave | 2 | `jobscout: modo ia indisponível (JOBSCOUT_AI_API_KEY ausente).` |
| Nenhuma vaga na janela | 0 | `0 vagas novas nos últimos 14 dias com as chaves principais.` |

## O que cada vaga guarda

| Campo | Origem |
|---|---|
| `id` | Local, numérico, estável |
| `titulo`, `empresa`, `local` | Fonte ou o que você informou em `add` |
| `fonte` | Nome da fonte ou `manual` |
| `link` | URL original |
| `descricao` | Texto da vaga, quando a fonte envia |
| `publicada_em` | Data na fonte |
| `encontrada_em` | Primeira vez que o JobScout viu |
| `chaves` | Interseção com o perfil |
| `pontos` | Pontuação da última busca |
| `estado` | O seu, default `nova` |
| `visitada_em` | Preenchido por `open` ou `visit` |
| `candidatada_em` | Preenchido por `apply` |
| `notas` | Lista de texto com data |

## Ambiente e segredos

O arquivo `.env` existe na raiz do projeto e está no `.gitignore`. O Git não versiona chave, e o exemplo versionado é o `.env.example`.

```text
JOBSCOUT_AI_MODE=off
JOBSCOUT_AI_PROVIDER=
JOBSCOUT_AI_API_KEY=
JOBSCOUT_AI_MODEL=

JOBSCOUT_ADZUNA_APP_ID=
JOBSCOUT_ADZUNA_APP_KEY=
JOBSCOUT_JOOBLE_API_KEY=

JOBSCOUT_COUNTRY=br
JOBSCOUT_SINCE_DAYS=14
JOBSCOUT_DATA_DIR=
```

`JOBSCOUT_AI_MODE=off` força o modo local mesmo se alguém passar `--ai`. `JOBSCOUT_DATA_DIR` vazio usa `%USERPROFILE%\.jobscout`.

## Fora deste documento

Ainda não há código, banco nem executável. A implementação segue esta ordem:

1. Projeto Python, comando `analyze` no modo local e `profile show`.
2. Banco local e comandos `jobs`, `open`, `visit`, `apply`, `note`, `status`, `add`, `export`.
3. Conectores das fontes públicas e o comando `search`.
4. Modo `--ai` opcional, com o mesmo formato de perfil.
5. Empacotamento `jobscout.exe`.
