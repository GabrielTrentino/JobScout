"""Respostas a recrutador: curtas para WhatsApp e LinkedIn, mais formais por e-mail.

Cada intenção (tenho interesse, cobrar retorno...) tem um texto pronto em português e inglês e uma
instrução para a IA. Os padrões vêm daqui; a pessoa edita, desliga ou cria outras na aba Mensagens.
Nos textos, [trecho com {campo}] só aparece quando o campo existe: "Agradeço[, {recrutador}]!".
Com a conversa do chat, a IA responde à última mensagem. Nada é enviado: é para revisar e inserir.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from jobscout import llm, places
from jobscout.activities import clean_space, fold

CHANNELS = {"whatsapp": "WhatsApp", "linkedin": "LinkedIn", "email": "E-mail"}
FIELDS = ("recrutador", "vaga", "empresa", "pretensao", "nome", "extra", "candidatura")
MAX_INTENTS = 30
MAX_TURNS = 12

# Os textos não trazem cumprimento: "Olá {nome}, tudo bem?" entra (ou não) conforme a conversa, ver opening().
DEFAULT_INTENTS: tuple[dict[str, str], ...] = (
    {
        "chave": "interesse", "nome": "Tenho interesse",
        "instrucao": "Demonstre interesse em conhecer melhor a oportunidade. Agradeça pelo contato e mostre abertura para entender mais sobre a posição, o projeto e os desafios. Sem entusiasmo exagerado e sem confirmar participação no processo antes de conhecer os detalhes.",
        "pt": "Obrigado pelo contato! Tenho interesse em conhecer melhor a oportunidade[ de {vaga}][ na {empresa}]. [{extra} ]Poderia compartilhar mais detalhes sobre a posição e os desafios do projeto?",
        "en": "Thanks for reaching out! I'm interested in learning more about the [{vaga} ]opportunity[ at {empresa}]. [{extra} ]Could you share more details about the role and the project's challenges?",
    },
    {
        "chave": "mais_info", "nome": "Quero mais informações",
        "instrucao": "Demonstre curiosidade e peça mais informações, sem necessariamente confirmar interesse em participar do processo. Priorize o que ainda não foi apresentado na conversa: stack tecnológica, responsabilidades, modelo de trabalho, tipo de contratação, localização e faixa salarial (quando pertinente). Não pergunte o que já foi dito.",
        "pt": "Obrigado por compartilhar a oportunidade! Você poderia me passar mais algumas informações sobre a posição[ de {vaga}], principalmente em relação à stack tecnológica, modelo de trabalho e tipo de contratação? [{extra}]",
        "en": "Thanks for sharing the opportunity! Could you send me a bit more information about the [{vaga} ]role, especially the tech stack, work model and contract type? [{extra}]",
    },
    {
        "chave": "cobrar_retorno", "nome": "Cobrar retorno do processo",
        "instrucao": "Pergunte com educação se há novidades sobre o processo seletivo. Diga que gostou do que conheceu da empresa (sem inventar fatos específicos sobre ela) e que segue com interesse. Sem pressionar e sem reclamar da demora.",
        "pt": "Passando para saber se há novidades sobre o processo[ da vaga de {vaga}][ na {empresa}][, para a qual me candidatei {candidatura}]. Gostei muito do que conheci da empresa e sigo com interesse na oportunidade. [{extra} ]Agradeço desde já.",
        "en": "I wanted to check if there are any updates on the [{vaga} ]process[ at {empresa}][, which I applied to {candidatura}]. I really liked what I learned about the company and I'm still interested in the opportunity. [{extra} ]Thanks in advance.",
    },
    {
        "chave": "agendar", "nome": "Podemos agendar uma conversa",
        "instrucao": "Confirme a conversa de maneira simples e natural. Se a pessoa sugeriu horários, responda a eles; se não, pergunte quais horários ela tem disponíveis. Não invente horários.",
        "pt": "Podemos agendar uma conversa sim! Tenho disponibilidade para conhecer melhor a oportunidade e entender os detalhes da posição. [{extra} ]Quais horários funcionam melhor para você?",
        "en": "Sure, we can schedule a call! I'm available to learn more about the opportunity and the details of the role. [{extra} ]What times work best for you?",
    },
    {
        "chave": "nao_agendar", "nome": "Não posso agendar agora",
        "instrucao": "Responda com educação que não vai agendar a conversa agora, sem confirmar nenhum compromisso. Se houver um motivo em “algo mais”, explique brevemente. Agradeça pelo contato.",
        "pt": "Agradeço pelo convite! No momento não vou conseguir seguir com uma conversa sobre essa oportunidade. [{extra} ]De qualquer forma, obrigado pelo contato.",
        "en": "Thanks for the invitation! At the moment I won't be able to move forward with a call about this opportunity. [{extra} ]Thanks for reaching out anyway.",
    },
    {
        "chave": "agradecer_entrevista", "nome": "Agradecer pela entrevista",
        "instrucao": "Agradeça pela conversa ou entrevista, diga que gostou de conhecer mais sobre a vaga e a empresa e que segue com interesse nos próximos passos. Curto.",
        "pt": "Obrigado pela conversa! Gostei de conhecer mais sobre a vaga[ de {vaga}][ e a {empresa}] e sigo com interesse na oportunidade. [{extra} ]Fico à disposição para os próximos passos.",
        "en": "Thank you for the conversation! I enjoyed learning more about the [{vaga} ]role[ and {empresa}] and I'm still interested. [{extra} ]Looking forward to the next steps.",
    },
    {
        "chave": "salario", "nome": "Falar de salário",
        "instrucao": "Informe a pretensão salarial do perfil (só ela, sem inventar) e pergunte a faixa prevista para a vaga.",
        "pt": "Para avaliar a vaga[ de {vaga}], minha pretensão é {pretensao}. [{extra} ]Você consegue me dizer a faixa prevista para a posição?",
        "en": "To evaluate the [{vaga} ]role, my expectation is {pretensao}. [{extra} ]Could you share the expected range for the position?",
    },
    {
        "chave": "pedir_feedback", "nome": "Pedir feedback da entrevista",
        "instrucao": "Peça um retorno sobre a entrevista ou o processo: como foi a avaliação e se há atualização sobre as próximas etapas. Se já houver uma previsão de retorno combinada na conversa, considere essa informação.",
        "pt": "Gostaria de saber se você já tem algum retorno sobre nossa conversa e se existe alguma atualização em relação ao processo seletivo[ da {empresa}]. Caso tenha algum feedback sobre a entrevista, também gostaria de saber. [{extra}]",
        "en": "I'd like to know if you have any feedback on our conversation and if there's any update on the [{empresa} ]hiring process. If you have any feedback on the interview, I'd also like to hear it. [{extra}]",
    },
    {
        "chave": "outro_processo", "nome": "Vou aguardar (outros processos)",
        "instrucao": "Diga que estou participando de outros processos seletivos e que gostaria de aguardar um pouco antes de decidir ou avançar. Transparente e cordial, sem pressionar nem usar os outros processos como negociação. Não invente propostas, aprovações ou prazos.",
        "pt": "Tenho interesse na oportunidade, mas atualmente estou participando de outros processos seletivos e gostaria de aguardar um pouco para entender como essas conversas vão evoluir. [{extra} ]De qualquer forma, agradeço pelo contato e pela oportunidade.",
        "en": "I'm interested in the opportunity, but I'm currently in other hiring processes and would like to wait a bit to see how those conversations evolve. [{extra} ]Either way, thank you for reaching out and for the opportunity.",
    },
    {
        "chave": "sem_interesse", "nome": "Não faz sentido no momento",
        "instrucao": "Recuse com educação, agradecendo pela consideração. Sem justificativa longa; se houver um motivo em “algo mais” (localização, modelo de trabalho, idioma, escopo), explique brevemente. Deixe a porta aberta para oportunidades futuras.",
        "pt": "Agradeço pelo contato e por considerar meu perfil para a oportunidade! No momento, acredito que a posição não esteja tão alinhada aos meus objetivos profissionais. [{extra} ]De qualquer forma, agradeço pela lembrança e espero que possamos conversar em outras oportunidades.",
        "en": "Thank you for reaching out and for considering my profile! At the moment, I don't think the role is quite aligned with my professional goals, so I'm not interested in moving forward. [{extra} ]Thanks for thinking of me, and I hope we can talk about other opportunities in the future.",
    },
    {
        "chave": "outro", "nome": "Outro (eu explico)",
        "instrucao": "Diga exatamente o que a pessoa escreveu em “algo mais”, com educação e no tom da conversa.",
        "pt": "{extra}",
        "en": "{extra}",
    },
)
DEFAULT_KEYS = {intent["chave"] for intent in DEFAULT_INTENTS}

EMAIL = {
    "pt": {"assunto": "Re: [{vaga}][ — {empresa}]", "abre": "Olá[ {recrutador}],", "fecha": "Atenciosamente,\n{nome}[\n{contato}]", "padrao": "Re: oportunidade"},
    "en": {"assunto": "Re: [{vaga}][ — {empresa}]", "abre": "Hi[ {recrutador}],", "fecha": "Best regards,\n{nome}[\n{contato}]", "padrao": "Re: opportunity"},
}
# Cumprimento no começo do texto ("Olá, Carla! Tudo bem?"), para trocar pela abertura que a conversa pede.
GREETING = re.compile(
    r"^(?:(?:ol[aá]|oi|hi|hello|hey)\b[^.!?\n]*[.!?,]\s*)?"
    r"(?:(?:e\s+)?(?:tudo bem|tudo bom|como vai)[^.!?\n]*\?\s*|(?:i'm good|i am good|how are you|hope you're)[^.!?\n]*[.!?]\s*)*",
    re.I,
)
THANKS = re.compile(r"^(obrigad[oa]|agrade[cç]o|muito obrigad[oa]|thanks|thank you)\b[^.!?]*[.!?]\s*", re.I)
CLOSINGS = re.compile(r"^(atenciosamente|abraços?|att\.?|cordialmente|saudações|best regards|regards|kind regards|best|cheers|saludos|un saludo)[,.!]?$", re.I)
ASKED_HOW = re.compile(r"tudo bem\s*\?|tudo bom\s*\?|como vai|como você está|como vc está|how are you|how's it going|how have you been", re.I)
THANKED = re.compile(r"\b(obrigad[oa]|agrade[cç]|thanks|thank you)", re.I)
INTERESTED = re.compile(r"\b(tenho interesse|interess|interested)", re.I)

# Abertura das mensagens curtas, conforme a conversa (as regras de cumprimento do estilo).
OPENINGS = {
    "pt": {"novo": "Olá[ {recrutador}], tudo bem?", "responde": "Olá[ {recrutador}], tudo bem e contigo?", "segue_responde": "Tudo bem, e contigo?"},
    "en": {"novo": "Hi[ {recrutador}], how are you?", "responde": "Hi[ {recrutador}], I'm good, thanks. How about you?", "segue_responde": "I'm good, thanks. How about you?"},
}

# Estilo de comunicação padrão (editável na aba Mensagens). {nome} vira o primeiro nome do Perfil.
STYLE_GUIDE = """# INSTRUÇÕES DE COMUNICAÇÃO — RESPOSTAS A RECRUTADORES

Você deve escrever mensagens como se fosse eu, {nome}, respondendo a recrutadores pelo LinkedIn ou WhatsApp.

O objetivo é manter uma comunicação cordial, profissional e natural, sem parecer excessivamente formal ou utilizar textos padronizados de inteligência artificial.

## 1. Meu estilo de comunicação

- Seja cordial, educado e profissional.
- Utilize uma linguagem natural, simples e espontânea.
- Seja objetivo, sem parecer frio ou indiferente.
- Demonstre interesse quando apropriado, sem entusiasmo exagerado.
- Prefira frases curtas e diretas.
- Evite formalidade excessiva, expressões rebuscadas e linguagem corporativa.
- Não utilize emojis.
- Evite exclamações em excesso.
- Prefira mensagens de 1 a 3 parágrafos.
- Não apresente justificativas longas quando uma explicação simples for suficiente.

A mensagem deve parecer escrita naturalmente por mim, e não produzida por uma IA.

## 2. Regras de cumprimento e abertura

Analise o histórico da conversa antes de iniciar a resposta.

- Se não houve contato ou troca de mensagens naquele dia, comece com: "Olá [nome], tudo bem?"
- Se a pessoa já perguntou se está tudo bem, responda: "Olá [nome], tudo bem e contigo?"
- Se já houve uma troca de mensagens no mesmo dia, não repita o cumprimento. Continue diretamente a conversa.
- Se a conversa já estiver em andamento, mantenha a continuidade natural, sem reiniciar o assunto.
- Utilize o nome da pessoa quando estiver disponível. Nunca invente nomes.

## 3. Cenários de resposta

### CENÁRIO 1 — Tenho interesse em saber mais sobre a vaga

Demonstre interesse em conhecer melhor a oportunidade. Agradeça pelo contato e manifeste abertura para entender mais sobre a posição, o projeto e os desafios.

Exemplo de abordagem:

"Olá [nome], tudo bem?

Obrigado pelo contato! Tenho interesse em conhecer melhor a oportunidade. Poderia compartilhar mais detalhes sobre a posição e os desafios do projeto?"

Não demonstre entusiasmo exagerado nem confirme participação em processos antes de conhecer os detalhes.

### CENÁRIO 2 — Gostaria de mais informações

Demonstre curiosidade e solicite informações adicionais sobre a oportunidade, sem necessariamente confirmar interesse em participar do processo.

Priorize informações que ainda não foram apresentadas, como:
- Stack tecnológica.
- Responsabilidades da posição.
- Modelo de trabalho.
- Tipo de contratação.
- Localização.
- Faixa salarial, quando pertinente.

Exemplo de abordagem:

"Olá [nome], tudo bem?

Obrigado por compartilhar a oportunidade! Você poderia me passar mais algumas informações sobre a posição, principalmente em relação à stack tecnológica, modelo de trabalho e tipo de contratação?"

Não faça perguntas repetidas sobre informações que já foram compartilhadas.

### CENÁRIO 3 — Podemos agendar uma conversa (sim ou não)

Quando houver interesse, confirme de maneira simples e natural.

Exemplo positivo:

"Olá [nome], tudo bem e contigo?

Podemos agendar uma conversa sim! Tenho disponibilidade para conhecer melhor a oportunidade e entender os detalhes da posição."

Quando não houver interesse ou disponibilidade, responda educadamente, sem confirmar compromissos.

Não invente horários. Se necessário, pergunte quais horários a pessoa tem disponíveis.

### CENÁRIO 4 — Pedir feedback da entrevista

Elabore uma mensagem solicitando um retorno sobre a entrevista ou processo seletivo.

Demonstre interesse em saber como foi minha avaliação e se existe alguma atualização sobre as próximas etapas.

Exemplo de abordagem:

"Olá [nome], tudo bem?

Gostaria de saber se você já tem algum retorno sobre nossa conversa e se existe alguma atualização em relação ao processo seletivo. Caso tenha algum feedback sobre a entrevista, também gostaria de saber."

Se já houver uma previsão de retorno combinada, considere essa informação na mensagem.

### CENÁRIO 5 — Mencionar que vou esperar um pouco pois estou em outros processos

Comunique que estou participando de outros processos seletivos e que gostaria de aguardar um pouco antes de tomar uma decisão ou avançar.

Mantenha transparência e cordialidade, sem parecer que estou pressionando o recrutador ou utilizando outras oportunidades como instrumento de negociação.

Exemplo de abordagem:

"Olá [nome], tudo bem?

Tenho interesse na oportunidade, mas atualmente estou participando de outros processos seletivos e gostaria de aguardar um pouco para entender como essas conversas vão evoluir. De qualquer forma, agradeço pelo contato e pela oportunidade."

Adapte a mensagem conforme o estágio dos outros processos. Não invente propostas, aprovações ou prazos.

### CENÁRIO 6 — A oportunidade não faz sentido para mim no momento

Recuse a oportunidade de maneira educada e cordial, agradecendo pela consideração.

Não é necessário apresentar justificativas longas. Quando houver um motivo específico, como localização, modelo de trabalho, idioma ou escopo da posição, explique brevemente.

Exemplo de abordagem:

"Olá [nome], tudo bem?

Agradeço pelo contato e por considerar meu perfil para a oportunidade! No momento, acredito que a posição não esteja tão alinhada aos meus objetivos profissionais. De qualquer forma, agradeço pela lembrança e espero que possamos conversar em outras oportunidades."

Preserve sempre o relacionamento profissional e demonstre abertura para oportunidades futuras que façam sentido.

## 4. Regras gerais de comportamento

Antes de gerar qualquer resposta, verifique o histórico da conversa para identificar:

- Se já houve cumprimento no mesmo dia.
- Se o recrutador perguntou como estou.
- Se já existe uma conversa em andamento.
- Se já agradeci pelo contato anteriormente.
- Se já demonstrei interesse na oportunidade.
- Se já foram discutidos horários, salário ou outros detalhes.

Não repita cumprimentos, agradecimentos ou informações desnecessariamente.

Adapte a mensagem ao grau de proximidade e informalidade da conversa.

Não invente informações, disponibilidade, propostas ou compromissos.

Não altere minhas intenções. Se eu selecionar uma opção de recusa, não tente transformar a resposta em demonstração de interesse. Se selecionar interesse, não transmita desinteresse.

## 5. Formato de saída

- Entregue somente a mensagem pronta para copiar e enviar.
- Não apresente explicações sobre a resposta.
- Não utilize títulos ou introduções.
- Não apresente múltiplas versões, a menos que seja solicitado.
- Preserve a naturalidade da conversa.
- Priorize sempre uma comunicação cordial, profissional e espontânea.

**REGRA PRINCIPAL: escreva como uma pessoa conversando com outra pessoa. A mensagem deve transmitir educação, clareza e profissionalismo, sem parecer artificial, excessivamente formal ou padronizada.**"""
MAX_STYLE = 12000

# Estilo padrão do e-mail: o mesmo jeito de escrever, no formato de e-mail (saudação, parágrafos, assinatura).
EMAIL_STYLE_GUIDE = """# INSTRUÇÕES DE COMUNICAÇÃO — E-MAILS A RECRUTADORES

Você deve escrever e-mails como se fosse eu, {nome}, respondendo a recrutadores e empresas.

O objetivo é uma comunicação cordial, profissional e clara, um pouco mais estruturada que no chat, mas sem formalidade excessiva ou textos padronizados de inteligência artificial.

## 1. Meu estilo no e-mail

- Seja cordial, educado e profissional.
- Use linguagem natural e direta; evite expressões rebuscadas ("venho por meio deste", "outrossim", "cordialmente venho").
- Prefira 2 a 3 parágrafos curtos, uma ideia por parágrafo.
- Demonstre interesse quando apropriado, sem entusiasmo exagerado.
- Não utilize emojis nem exclamações em excesso.
- Não repita o que a pessoa já sabe; responda ao que ela perguntou.

## 2. Estrutura

- Saudação: "Olá [nome]," (com o nome, quando disponível; nunca invente nomes).
- Primeiro parágrafo: agradecimento ou contexto em uma frase, só se ainda não agradeci nesta troca de e-mails.
- Corpo: o que eu quero dizer (interesse, pedido de informação, disponibilidade, retorno).
- Fechamento curto: "Fico à disposição." ou "Aguardo seu retorno." quando fizer sentido.
- Despedida: "Abraço," ou "Atenciosamente," seguido do meu nome e do contato do perfil.

## 3. Assunto

- Em resposta, mantenha "Re:" com o assunto original.
- Em e-mail novo, assunto curto e claro: "[vaga] — [empresa]" ou o objetivo ("Retorno sobre o processo de [vaga]").

## 4. Regras gerais

- Não invente informações, disponibilidade, horários, propostas ou compromissos.
- Se pedirem horários e eu não informei, peça as opções da pessoa.
- Não altere minhas intenções: recusa continua recusa; interesse continua interesse.
- Entregue só o e-mail pronto, sem explicações nem versões alternativas."""

# Regras do JobScout que valem por cima do estilo: formato, fatos e a abertura já decidida pela conversa.
RULES = (
    "# REGRAS DO JOBSCOUT (valem junto com o estilo acima)\n"
    "- Siga a intenção escolhida e a instrução dela exatamente.\n"
    "- Use só os fatos do perfil, da vaga e da conversa; não invente salário, data, nome, horário ou experiência.\n"
    "- Se houver conversa, responda à última mensagem do recrutador, sem repetir o que já foi dito.\n"
    "- Parta do rascunho base: ele já tem a intenção e a abertura certas. Adapte ao tom e ao conteúdo da conversa, sem mudar o que a pessoa quer dizer.\n"
    "- A abertura (cumprimento) foi decidida pelo histórico: use exatamente a indicada em “Abertura”; se ela disser “sem cumprimento”, comece direto no assunto.\n"
    "- Não acrescente dados do perfil que ninguém pediu (links, idiomas, experiência).\n"
    "- O que a pessoa pediu para dizer entra com o mesmo sentido (ex.: “posso começar em 30 dias” é data de início, não de conversa).\n"
    "- Mantenha as palavras de gênero como estão no estilo e no rascunho (ex.: “Obrigado”); não troque.\n"
    "- WhatsApp e LinkedIn: sem assunto e sem assinatura; a abertura fica num parágrafo e o resto em 1 a 2 parágrafos curtos.\n"
    "- E-mail: siga o estilo de e-mail acima, com a saudação e a despedida do rascunho base.\n"
    "- Escreva no idioma pedido. Responda só com o JSON pedido no fim da mensagem."
)
JSON_SHAPE = {
    "email": "Responda só com JSON: {\"assunto\": \"assunto do e-mail\", \"texto\": \"o e-mail pronto\"}",
    "curto": "Responda só com JSON: {\"texto\": \"a mensagem pronta para enviar\"}",
}


def default_style(channel: str) -> str:
    return EMAIL_STYLE_GUIDE if channel == "email" else STYLE_GUIDE


def style_text(custom: str, profile: dict[str, Any], channel: str = "chat") -> str:
    name = first_name(str(profile.get("nome") or ""))
    text = (custom or "").strip() or default_style(channel)
    return text.replace("{nome}", name or "a pessoa candidata")[:MAX_STYLE]


SCENARIO = re.compile(r"^### .*?(?=^### |^## |\Z)", re.M | re.S)
SCENARIO_OF = {"interesse": 1, "mais_info": 2, "agendar": 3, "nao_agendar": 3, "pedir_feedback": 4, "outro_processo": 5, "sem_interesse": 6}


def for_intent(style: str, intent: dict[str, Any]) -> str:
    """Só o cenário da intenção escolhida vai para a IA: os outros cinco só deixam o modelo local lento.

    O cenário é achado pelas palavras do nome da intenção ("Pedir feedback da entrevista" → CENÁRIO 4);
    sem cenário parecido, vão só as regras gerais, e a instrução da intenção cobre o resto.
    """
    words = {word for word in re.findall(r"\w{4,}", fold(intent.get("nome") or ""))}
    number = SCENARIO_OF.get(intent.get("chave") or "")
    best, score = "", 1  # pelas palavras, só com 2 ou mais em comum
    for match in SCENARIO.finditer(style):
        title = fold(match.group(0).split("\n", 1)[0])
        if number and re.search(rf"\bcenario {number}\b", title):
            best = match.group(0)
            break
        hits = sum(1 for word in words if re.search(rf"\b{re.escape(word)}\b", title))
        if hits > score:
            best, score = match.group(0), hits
    trimmed = SCENARIO.sub(lambda match: match.group(0) if match.group(0) == best else "", style)
    return re.sub(r"\n{3,}", "\n\n", trimmed).strip()


def system_prompt(custom: str, profile: dict[str, Any], intent: dict[str, Any] | None = None, channel: str = "chat") -> str:
    style = style_text(custom, profile, channel)
    return f"{for_intent(style, intent) if intent else style}\n\n{RULES}"


# Biblioteca de intenções: padrões + o que a pessoa editou ou criou

def _clean_intent(raw: dict[str, Any], key: str) -> dict[str, Any]:
    return {
        "chave": key,
        "nome": clean_space(str(raw.get("nome") or ""))[:60] or key,
        "instrucao": clean_space(str(raw.get("instrucao") or ""))[:800],
        "pt": str(raw.get("pt") or "").strip()[:1500],
        "en": str(raw.get("en") or "").strip()[:1500],
        "ativo": raw.get("ativo", True) is not False,
    }


def library(overrides: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Intenções na ordem: as padrão (com a edição da pessoa por cima) e depois as criadas por ela."""
    overrides = overrides if isinstance(overrides, dict) else {}
    result = []
    for default in DEFAULT_INTENTS:
        edited = overrides.get(default["chave"]) if isinstance(overrides.get(default["chave"]), dict) else {}
        merged = _clean_intent({**default, **edited}, default["chave"])
        merged["padrao"] = True
        merged["editado"] = bool(edited)
        result.append(merged)
    for key, raw in overrides.items():
        if key in DEFAULT_KEYS or not isinstance(raw, dict):
            continue
        custom = _clean_intent(raw, key)
        custom["padrao"] = False
        custom["editado"] = True
        result.append(custom)
    return result[:MAX_INTENTS]


def custom_key(name: str, existing: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "_", fold(name)).strip("_")[:30] or "modelo"
    key, counter = base, 2
    while key in existing or key in DEFAULT_KEYS:
        key = f"{base}_{counter}"
        counter += 1
    return key


def fill(text: str, values: dict[str, str]) -> str:
    """Troca {campo}; [trecho] some se algum campo dele estiver vazio. Espaços sobrando saem, quebras ficam."""
    def optional(match: re.Match[str]) -> str:
        segment = match.group(1)
        names = re.findall(r"\{(\w+)\}", segment)
        if any(not values.get(name) for name in names):
            return ""
        return segment

    text = re.sub(r"\[([^\[\]]*)\]", optional, text)
    text = re.sub(r"\{(\w+)\}", lambda match: values.get(match.group(1), ""), text)
    lines = [" ".join(line.split()).replace(" .", ".").replace(" ,", ",").replace(" !", "!").replace(" ?", "?") for line in text.split("\n")]
    return "\n".join(lines).strip()


# Valores dos campos

def first_name(name: str) -> str:
    # No WhatsApp, contato sem nome salvo aparece como o número: não é nome para cumprimentar.
    parts = [part for part in clean_space(name).split() if re.search(r"[^\W\d_]", part)]
    return parts[0] if parts else ""


def _applied(job: dict[str, Any] | None, lang: str) -> str:
    raw = (job or {}).get("applied_at") or ""
    try:
        when = datetime.fromisoformat(raw)
    except (TypeError, ValueError):
        return ""
    return f"em {when:%d/%m}" if lang == "pt" else f"on {when:%b %d}"


def values_for(lang: str, profile: dict[str, Any], job: dict[str, Any] | None, recruiter: str, extra: str) -> dict[str, str]:
    contact = " · ".join(item for item in (profile.get("telefone"), profile.get("linkedin")) if item)
    return {
        "recrutador": first_name(recruiter),
        "vaga": (job or {}).get("title") or "",
        "empresa": (job or {}).get("company") or "",
        # Em inglês, o valor em dólar; em português, o valor em real.
        "pretensao": ((profile.get("pretensao_usd") or profile.get("pretensao_salarial")) if lang == "en"
                      else (profile.get("pretensao_salarial") or profile.get("pretensao_usd")))
                     or ("[sua pretensão]" if lang == "pt" else "[your expectation]"),
        "nome": profile.get("nome") or "",
        "extra": (extra.rstrip(".") + ".") if extra else "",
        "candidatura": _applied(job, lang),
        "contato": contact,
    }


def short_message(text: str) -> str:
    """WhatsApp e LinkedIn: sem despedida formal nem assinatura (o modelo às vezes escreve como e-mail)."""
    lines = [line.rstrip() for line in text.strip().splitlines()]
    for index, line in enumerate(lines):
        if CLOSINGS.match(line.strip()):
            lines = lines[:index]
            break
    return "\n".join(lines).strip()


def history(turns: list[dict[str, Any]]) -> dict[str, Any]:
    """O que o histórico diz para a abertura: já conversamos hoje, perguntaram como estou, já agradeci."""
    dated = [turn for turn in turns if turn.get("dia")]
    if dated:
        # Troca no dia = eu já respondi hoje; só a mensagem dela de hoje ainda pede cumprimento.
        today = any(turn["minha"] and turn["dia"] == "hoje" for turn in dated)
    else:
        # Sem data na página: conta como "hoje" se eu já cumprimentei nas últimas mensagens.
        today = any(turn["minha"] and GREETING.match(turn["texto"]).group(0) for turn in turns[-4:])
    mine = [index for index, turn in enumerate(turns) if turn["minha"]]
    since_mine = turns[mine[-1] + 1:] if mine else turns
    return {
        "hoje": today,
        "sabe_dia": bool(dated),
        "perguntou": any(not turn["minha"] and ASKED_HOW.search(turn["texto"]) for turn in since_mine),
        "agradeci": any(turn["minha"] and THANKED.search(turn["texto"]) for turn in turns),
        "interesse": any(turn["minha"] and INTERESTED.search(turn["texto"]) for turn in turns),
        "em_andamento": bool(mine),
    }


def opening(facts: dict[str, Any] | None, lang: str, values: dict[str, str]) -> str:
    facts = facts or {}
    parts = OPENINGS["en" if lang == "en" else "pt"]
    if not facts.get("hoje"):
        key = "responde" if facts.get("perguntou") else "novo"
    else:
        key = "segue_responde" if facts.get("perguntou") else ""
    return fill(parts[key], values) if key else ""


def with_opening(body: str, facts: dict[str, Any] | None, lang: str, values: dict[str, str]) -> str:
    """Troca o cumprimento do texto pela abertura que a conversa pede; sem repetir o agradecimento."""
    body = GREETING.sub("", body.strip(), count=1).strip()
    if facts and facts.get("agradeci"):
        body = THANKS.sub("", body, count=1).strip() or body
    if body:
        body = body[0].upper() + body[1:]
    start = opening(facts, lang, values)
    return f"{start}\n\n{body}".strip() if start else body


def template(intent: dict[str, Any], channel: str, lang: str, values: dict[str, str],
             facts: dict[str, Any] | None = None) -> dict[str, str]:
    lang = "en" if lang == "en" else "pt"
    text = intent.get(lang) or intent.get("pt") or ""
    if channel != "email":
        return {"assunto": "", "texto": with_opening(fill(text, values), facts, lang, values)}
    # No e-mail o nome vai na saudação; a frase de saudação do corpo sai para não repetir.
    body = GREETING.sub("", fill(text, {**values, "recrutador": ""}), count=1)
    parts = EMAIL[lang]
    subject = fill(parts["assunto"], values)
    return {
        "assunto": subject if subject != "Re:" else parts["padrao"],
        "texto": f"{fill(parts['abre'], values)}\n\n{body}\n\n{fill(parts['fecha'], values)}".strip(),
    }


# Conversa do chat (lida pela extensão)

def conversation(raw: Any) -> list[dict[str, Any]]:
    turns = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        text = clean_space(str(item.get("texto") or ""))[:1500]
        if text:
            day = item.get("dia") if item.get("dia") in {"hoje", "antes"} else ""
            turns.append({"autor": clean_space(str(item.get("autor") or ""))[:80], "texto": text, "minha": bool(item.get("minha")), "dia": day})
    return turns[-MAX_TURNS:]


def transcript(turns: list[dict[str, Any]], recruiter: str) -> str:
    lines = []
    for turn in turns:
        who = "Eu" if turn["minha"] else (turn["autor"] or recruiter or "Recrutadora")
        lines.append(f"{who}: {turn['texto']}")
    return "\n".join(lines)


def language(text: str, choice: str) -> str:
    if choice in {"pt", "en", "es"}:
        return choice
    return places.language(text) if text.strip() else "pt"


def invented_numbers(text: str, sources: list[str]) -> list[str]:
    """Números da resposta (salário, prazo, horário) que não aparecem em nenhuma fonte: o modelo inventou."""
    known = set()
    for source in sources:
        known.update(re.sub(r"\D", "", number) for number in re.findall(r"\d[\d.,]*", source or ""))
    found = []
    for number in re.findall(r"\d[\d.,]*\d|\d", text):
        digits = re.sub(r"\D", "", number)
        if len(digits) >= 2 and digits not in known and number not in found:
            found.append(number)
    return found


def facts_text(facts: dict[str, Any], start: str, channel: str) -> str:
    yes = lambda value: "sim" if value else "não"  # noqa: E731
    today = yes(facts["hoje"]) if facts["sabe_dia"] else f"{yes(facts['hoje'])} (deduzido; a página não mostra datas)"
    lines = [
        f"- Já houve troca de mensagens hoje: {today}",
        f"- O recrutador perguntou como estou: {yes(facts['perguntou'])}",
        f"- Conversa já em andamento: {yes(facts['em_andamento'])}",
        f"- Já agradeci pelo contato antes: {yes(facts['agradeci'])}",
        f"- Já demonstrei interesse antes: {yes(facts['interesse'])}",
    ]
    if channel != "email":
        lines.append(f"Abertura: {start}" if start else "Abertura: sem cumprimento (já conversamos hoje); comece direto no assunto.")
    return "Histórico:\n" + "\n".join(lines)


def write(data: dict[str, Any], profile: dict[str, Any], profile_text: str, job: dict[str, Any] | None,
          intents: list[dict[str, Any]] | None = None, style: str = "") -> dict[str, Any]:
    """Escreve a resposta: IA se houver modelo para "mensagem", senão o texto pronto da intenção."""
    intents = intents or library()
    by_key = {intent["chave"]: intent for intent in intents}
    intent = by_key.get(str(data.get("intencao") or "interesse"))
    channel = str(data.get("canal") or "whatsapp")
    if intent is None or channel not in CHANNELS:
        raise ValueError("Intenção ou canal inválido.")
    turns = conversation(data.get("conversa"))
    message = clean_space(str(data.get("mensagem") or ""))[:6000]
    extra = clean_space(str(data.get("detalhe") or ""))[:800]
    recruiter = clean_space(str(data.get("recrutador") or ""))[:80]
    if not recruiter:
        others = [turn["autor"] for turn in turns if not turn["minha"] and turn["autor"]]
        recruiter = others[-1] if others else ""
    theirs = " ".join(turn["texto"] for turn in turns if not turn["minha"]) or message
    lang = language(theirs, str(data.get("idioma") or "auto"))
    if "{extra}" in (intent.get("pt") or "") and "[{extra}" not in (intent.get("pt") or "") and not extra:
        raise ValueError("Nesta intenção, escreva em “Algo mais” o que você quer dizer.")
    values = values_for(lang, profile, job, recruiter, extra)
    # Mensagem colada (aba Mensagens) conta como a última fala do recrutador, sem data.
    facts = history(turns or ([{"autor": recruiter, "texto": message, "minha": False, "dia": ""}] if message else []))
    start = opening(facts, lang, values)
    fallback = template(intent, channel, lang, values, facts)
    base = {"idioma": lang, "recrutador": values["recrutador"], "vaga": f"{values['vaga']} — {values['empresa']}".strip(" —")}
    if not llm.available("mensagem"):
        return {**fallback, **base, "origem": "modelo"}
    names = {"pt": "português", "en": "inglês", "es": "espanhol"}
    prompt = (
        f"Perfil da pessoa:\n{profile_text[:3000]}\n\n"
        + (f"Vaga: {job.get('title') or ''} — {job.get('company') or ''}"
           + (f" (candidatura {values['candidatura']})" if values["candidatura"] else "")
           + f"\n{str(job.get('description') or '')[:1500]}\n\n" if job else "")
        + (f"Conversa até agora (responda à última mensagem do recrutador):\n{transcript(turns, recruiter)}\n\n" if turns else "")
        + (f"Mensagem do recrutador ({recruiter}):\n{message}\n\n" if message and not turns else "")
        + f"{facts_text(facts, start, channel)}\n\n"
        + "Pretensão salarial no Perfil: "
        + (f"{values['pretensao']}\n" if profile.get("pretensao_salarial") or profile.get("pretensao_usd") else "não informada (não invente valor; se precisar, escreva exatamente “[sua pretensão]”)\n")
        + f"Canal: {CHANNELS[channel]}\nIntenção da pessoa: {intent['nome']}\n"
        + (f"Instrução: {intent['instrucao']}\n" if intent.get("instrucao") else "")
        + f"Rascunho base (mantenha a intenção e os pedidos dele):\n{fallback['texto']}\n"
        + (f"O que ela quer dizer também: {extra}\n" if extra else "")
        + f"Idioma: {names.get(lang, 'português')}\n"
        + JSON_SHAPE["email" if channel == "email" else "curto"]
    )
    try:
        raw = llm.ask_llm("mensagem", prompt, system=system_prompt(style, profile, intent, channel), as_json=True, timeout=150)
        reply = json.loads(raw)
        text = str(reply.get("texto") or "").strip()
        if not text and channel != "email":
            # Modelo pequeno às vezes escreve a mensagem no "assunto".
            text = str(reply.get("assunto") or "").strip()
    except (llm.LLMUnavailable, json.JSONDecodeError, AttributeError) as exc:
        return {**fallback, **base, "origem": "modelo", "aviso": f"IA indisponível, usei o texto pronto. {exc}"[:200]}
    # Às vezes o modelo repete a pergunta do recrutador antes de responder.
    theirs_lines = {fold(turn["texto"]) for turn in turns if not turn["minha"]} | ({fold(message)} if message else set())
    lines = text.split("\n")
    while lines and (not lines[0].strip() or fold(lines[0].strip()) in theirs_lines):
        lines.pop(0)
    text = "\n".join(lines).strip()
    if not text:
        return {**fallback, **base, "origem": "modelo", "aviso": "A IA não devolveu texto; usei o texto pronto."}
    invented = invented_numbers(text, [profile_text, json.dumps(profile, ensure_ascii=False), prompt])
    if invented:
        return {**fallback, **base, "origem": "modelo",
                "aviso": f"A IA citou {', '.join(invented[:3])}, que não está no Perfil, na vaga nem na conversa; usei o texto pronto."}
    if channel != "email":
        # A abertura segue o histórico mesmo se o modelo cumprimentar por conta própria.
        text = with_opening(short_message(text), facts, lang, values)
    return {
        **base,
        "assunto": clean_space(str(reply.get("assunto") or ""))[:200] if channel == "email" else "",
        "texto": text[:4000],
        "origem": "ia",
        "modelo": llm.model_name("mensagem"),
    }


def match_job(texts: list[str], jobs: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Vaga salva cuja empresa aparece na conversa (ou no título do chat); a candidatura mais recente vence."""
    haystack = fold(" ".join(texts))
    found = []
    for job in jobs:
        company = fold(job.get("company") or "")
        if len(company) >= 3 and re.search(rf"\b{re.escape(company)}\b", haystack):
            found.append(job)
    found.sort(key=lambda job: (job.get("status") != "visualizada", job.get("applied_at") or "", job.get("status_at") or ""), reverse=True)
    return found[0] if found else None
