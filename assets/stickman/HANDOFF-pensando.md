# Pose "sentado pensando": handoff de animação

É a pose que a bolha do JobScout mostra enquanto trabalha: lendo uma vaga, lendo um formulário de candidatura ou verificando o Gmail. Hoje o boneco fica em pé com a mão no queixo. A nova versão é ele **sentado na maleta, pensando**, feita na mesma ferramenta e no mesmo estilo do arremesso ([stickman-arremesso-quadros.svg](stickman-arremesso-quadros.svg)).

**Ponto de partida:** [stickman-pensando-guia.svg](stickman-pensando-guia.svg) é o quadro 0 já no tamanho, no traço e nas cores certas. Importe e anime a partir dele.

## O que a animação mostra

Um loop de quem está concentrado lendo alguma coisa. Precisa dar para perceber que o app está ocupado, então é um pouco mais vivo que a pose sentado, mas sem ser agitado.

| Momento | Movimento |
|---|---|
| Todo o loop | Mão no queixo; a cabeça inclina devagar de um lado para o outro (uns 4°) |
| Duas vezes por loop | Dedos batem no queixo: a mão afasta 6 a 8 unidades e volta |
| Em sequência | Os três pontos acima da cabeça acendem um de cada vez, do menor para o maior, e apagam juntos. Apagado = opacidade 0,15; aceso = 1 |
| Opcional | Um pé bate no chão no ritmo dos pontos |

## Especificação técnica

| Item | Valor |
|---|---|
| Área | 528 × 456, igual ao arremesso |
| Quadros | 60, a 25 quadros por segundo (2,4 s) |
| Loop | Contínuo. O último quadro precisa emendar no primeiro sem pulo |
| Quadro 0 | Igual ao guia. Maleta, tronco e pernas ficam onde estão na pose sentado, porque o app alterna entre as duas várias vezes por minuto. Só o braço direito, a cabeça e os pontos mudam |
| Exportação | **Animated SVG (CSS)**, como foi feito com o arremesso |
| Nome do arquivo | `stickman-pensando-quadros.svg`, nesta pasta |

## Desenho

- **Traço do boneco:** `rgb(22,32,42)`, espessura 20,4, pontas e cantos arredondados, sem preenchimento. Cabeça com raio 36.
- **Pontos de pensamento:** círculos preenchidos com `rgb(22,32,42)`, sem contorno, raios 9, 12 e 15. Para acender e apagar, use opacidade, não outra cor.
- **Maleta:** preenchimento `rgb(201,138,43)`, contorno e faixa `rgb(111,76,24)` com espessura 10. Mede 144 × 84, com cantos de raio 15.
- **Sombra:** elipse `rgb(22,32,42)` com opacidade 0,12, no chão (y = 416).
- **Chão:** y = 412, o mesmo do arremesso e da pose sentado.
- **Área visível:** tudo que importa fica dentro do quadrado tracejado do guia (x 24–408, y 60–444). Os pontos podem encostar no canto de cima à direita, mas não devem sair do quadrado.

## Regras para o app conseguir usar

- **Use exatamente essas três cores.** Na conversão, a cor do traço e dos pontos vira a cor do tema, para o boneco ficar claro no modo escuro. Outro tom de preto não seria convertido.
- **Todos os traços do boneco com 20,4.** O app aplica essa espessura a todos de uma vez. Os pontos são preenchidos, sem traço.
- **Sem texto, imagem embutida, degradê ou filtro.**
- **Apague a camada "guias"** (retângulo, círculo e linha do chão tracejados) antes de exportar.

## Como entregar

Salve o arquivo exportado nesta pasta (`assets/stickman/`) e avise. Do lado do app: converter as cores, encaixar a fita na pose `think` no lugar do boneco em pé e configurar o loop de 60 quadros.
