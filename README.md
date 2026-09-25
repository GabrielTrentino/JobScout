# JobScout

Executável que busca vagas recentes a partir do seu currículo e guarda se você visitou, se candidatou e o link de cada vaga.

A especificação está em [docs/ESPECIFICACAO.md](docs/ESPECIFICACAO.md): comandos, exemplos de saída, modo local e modo com IA, fontes e o que fica no `.env`.

O `.env` fica na raiz e está listado no `.gitignore`. O modelo versionado é o `.env.example`.

## Tela inicial

```text
py -m venv .venv
.\.venv\Scripts\python -m pip install -e .
.\.venv\Scripts\python -m jobscout
```

A tela abre no navegador, recebe um PDF ou DOCX e lista as atividades do currículo. A leitura é local.
