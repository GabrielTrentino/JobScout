# Pose "sentado": handoff de animação

É a pose que a bolha do JobScout mostra quase o tempo todo, quando nada está sendo processado: o boneco sentado na maleta, esperando. Hoje ela é um desenho feito à mão com uma respiração simples. Este pedido é para refazê-la na mesma ferramenta e no mesmo estilo do arremesso ([stickman-arremesso-quadros.svg](stickman-arremesso-quadros.svg)).

**Ponto de partida:** [stickman-sentado-guia.svg](stickman-sentado-guia.svg) é o quadro 0 já no tamanho, no traço e nas cores certas. Importe e anime a partir dele.

## O que a animação mostra

Um loop calmo de quem está sentado esperando. Ele fica na tela o dia inteiro, numa bolha de 54 px, então o movimento precisa ser sutil: deve parecer vivo sem chamar atenção.

| Momento | Movimento |
|---|---|
| Todo o loop | Respiração: tronco e cabeça sobem uns 4 a 6 unidades e voltam |
| Metade do loop | Balança as pernas, um pé de cada vez, como quem está sentado na beira da maleta |
| Uma vez por loop | Cabeça inclina de leve para um lado e volta (olhando em volta) |

O que evitar: levantar, trocar de lugar, mexer a maleta, movimento rápido. Qualquer coisa brusca vira distração no canto da tela.

## Especificação técnica

| Item | Valor |
|---|---|
| Área | 528 × 456, igual ao arremesso |
| Quadros | 80, a 25 quadros por segundo (3,2 s) |
| Loop | Contínuo. O último quadro precisa emendar no primeiro sem pulo |
| Quadro 0 | Igual ao guia. A pose pensando parte desse mesmo quadro, e o app troca de uma para a outra a qualquer momento |
| Exportação | **Animated SVG (CSS)**, como foi feito com o arremesso |
| Nome do arquivo | `stickman-sentado-quadros.svg`, nesta pasta |

## Desenho

- **Traço do boneco:** `rgb(22,32,42)`, espessura 20,4, pontas e cantos arredondados, sem preenchimento. Cabeça com raio 36.
- **Maleta:** preenchimento `rgb(201,138,43)`, contorno e faixa `rgb(111,76,24)` com espessura 10. Sentado, ela mede 144 × 84, com cantos de raio 15 e a faixa no meio.
- **Sombra:** elipse `rgb(22,32,42)` com opacidade 0,12, no chão (y = 416).
- **Chão:** y = 412, o mesmo do arremesso. A maleta fica apoiada nele.
- **Área visível:** tudo que importa fica dentro do quadrado tracejado do guia (x 24–408, y 60–444). O círculo é o fundo da bolha.

## Regras para o app conseguir usar

- **Use exatamente essas três cores.** Na conversão, a cor do traço vira a cor do tema, para o boneco ficar claro no modo escuro. Outro tom de preto não seria convertido.
- **Todos os traços do boneco com 20,4.** O app aplica essa espessura a todos de uma vez.
- **Sem texto, imagem embutida, degradê ou filtro.**
- **Apague a camada "guias"** (retângulo, círculo e linha do chão tracejados) antes de exportar.

## Como entregar

Salve o arquivo exportado nesta pasta (`assets/stickman/`) e avise. Do lado do app: converter as cores, encaixar a fita na pose `idle` e configurar o loop de 80 quadros.
