# Boneco do JobScout: handoff

O mascote do JobScout é um boneco de palitinho com uma maleta. Ele vive na bolha do overlay, no canto inferior direito da tela, e muda de pose conforme o que o app está fazendo. Este documento entrega o boneco arremessando a maleta em SVG, para refinar o desenho e gerar os ícones.

## Arquivos

| Arquivo | Para quê |
|---|---|
| [stickman-arremesso-quadros.svg](stickman-arremesso-quadros.svg) | **Arremesso que o app usa.** Exportado da ferramenta de animação: 60 quadros de 528 × 456 lado a lado, deslizados em 2,4 s. Escala 6× do viewBox `-12 -10 88 76`. |
| [HANDOFF-sentado.md](HANDOFF-sentado.md) + [guia](stickman-sentado-guia.svg) | Pedido da pose sentado (parado) no mesmo formato do arremesso |
| [HANDOFF-pensando.md](HANDOFF-pensando.md) + [guia](stickman-pensando-guia.svg) | Pedido da pose sentado pensando (lendo a vaga) no mesmo formato |
| [stickman-arremesso.svg](stickman-arremesso.svg) | Primeira versão do arremesso, feita à mão; substituída pela de cima. Arremesso animado e autônomo. CSS dentro do próprio arquivo, ciclo de 2,4 s, abre direto no navegador ou num `<img>`. Muda a cor do traço no tema escuro e fica parado se o sistema pedir menos movimento. |
| [stickman-arremesso-estatico.svg](stickman-arremesso-estatico.svg) | Quadro-chave do arremesso, sem CSS e sem animação, com as transformações fixas em atributos. Abre em Figma, Illustrator e Inkscape. É a base dos ícones. |

A versão que roda no app tem as três poses no mesmo `<svg>`, que fica dentro de [jobscout/web/index.html](../../jobscout/web/index.html) (`#stickman`). As animações estão em [jobscout/web/app.css](../../jobscout/web/app.css), na seção "Boneco da bolha". O app não lê os arquivos desta pasta. Se você mudar o desenho aqui, leve a mudança para lá também.

### Trocar o arremesso por uma nova exportação

Exporte como **Animated SVG (CSS)** com o mesmo tamanho (528 × 456) e 60 quadros. Na conversão para o app:

- a cor do traço `rgb(22,32,42)` sai e vira `currentColor` pelo CSS, para seguir o tema escuro;
- a sombra vira `class="shadow"`;
- as cores da maleta ficam como vieram;
- a fita entra em `.pose-throw > svg.sprite > g.strip` no `index.html`, e o CSS (`sm-strip`) a desliza uma vez.

Se mudar o número de quadros ou a duração, ajuste `sm-strip` e `steps()` no `app.css` e o tempo de `throwUntil` no `app.js` (hoje 2400 ms).

## Poses e quando aparecem

| Pose | `data-pose` | Movimento | Quando o app mostra |
|---|---|---|---|
| Parado | `idle` | Sentado na maleta, respirando (3,2 s, em loop) | Nada sendo processado |
| Lendo a vaga | `think` | Em pé, mão no queixo, balança de leve; três pontos piscam em sequência (1,2 s) | Atividade com nível `trabalhando`: leitura de vaga ou formulário, verificação do Gmail |
| Arremesso | `throw` | Uma vez, 2,4 s: lança a maleta, ela some, ele pega outra e volta a sentar | Atividade com `acao: "envio"`, emitida quando a extensão detecta o clique em Enviar candidatura |

## Desenho

- **Área de desenho:** `viewBox="0 0 64 64"`. Na bolha ele aparece com 54 px. O arquivo animado usa `-12 -10 88 76` para caber o balanço e o voo da maleta.
- **Traço:** 3,4 unidades, pontas e cantos arredondados, sem preenchimento. A cabeça é um círculo com raio 6.
- **Maleta:** retângulo 13 × 9 com cantos de raio 2 e alça de 4 × 2. Na pose sentada ela é maior: 24 × 14, com uma faixa no meio.

## Cores

| Elemento | Tema claro | Tema escuro |
|---|---|---|
| Traço do boneco | `#16202a` | `#e6edf3` |
| Maleta (preenchimento) | `#c98a2b` | `#c98a2b` |
| Contorno e alça da maleta | `#6f4c18` | `#6f4c18` |
| Fundo da bolha | `#e9edf2` | `#10151c` |

No app, o traço usa `currentColor` e herda a cor do texto. O contorno da maleta é a cor dela misturada com 45% de preto.

## Anatomia do arremesso (primeira versão)

Esta seção descreve o `stickman-arremesso.svg` feito à mão. A versão em quadros já vem com tudo desenhado e não usa pontos de giro.

Os pontos de giro são os pontos da articulação. Se você mexer na geometria, eles precisam continuar batendo.

| Grupo | Ponto de giro | O que faz |
|---|---|---|
| `.lean` (corpo inteiro) | quadril, (24, 42) | Inclina −4° → −12° (tomando impulso) → 10° (soltando) → 4° |
| `.arm` (braço com a maleta) | ombro, (22, 28) | Gira −160° → −215° (para trás) → −25° (solta) → 15° |
| `.held` (maleta na mão) | — | Some no instante em que a maleta é solta (57% do arremesso) |
| `.flying` (maleta no ar) | centro da própria maleta | Aparece na mão, sobe para a direita girando até 160°, desce e some girando até 320° |

Tempo, dentro do 1,4 s do arremesso:

| Momento | O que acontece |
|---|---|
| 0–38% | Puxa o braço para trás e inclina o corpo |
| 38–58% | Gira o braço para a frente e solta a maleta |
| 58–100% | A maleta voa e some; o corpo assenta |

## Para quem for editar

- **Mantenha as classes** (`pose`, `pose-idle`, `pose-think`, `pose-throw`, `body`, `breathe`, `sway`, `lean`, `arm`, `case`, `held`, `flying`, `dots`, `head`). O CSS do app depende delas.
- Os editores visuais costumam achatar grupos e converter `<circle>` em `<path>`. Se isso acontecer, refaça a estrutura antes de levar para o app, ou peça a um dev para religar.
- Exporte SVG simples: sem `<image>` embutida, sem fontes e sem filtros. O traço precisa continuar sendo traço, não contorno convertido em forma, para trocar de cor no tema escuro.

## Ícones a gerar a partir do quadro estático

| Destino | Tamanhos | Observação |
|---|---|---|
| Extensão do Chrome (`icons` e `action.default_icon` no manifest) | PNG 16, 32, 48 e 128 | 48 e 128 podem usar o quadro como está, sobre um círculo de fundo |
| Janela do overlay e futuro `jobscout.exe` | `.ico` com 16, 24, 32, 48 e 256 | A barra de tarefas usa 24 ou 32 |
| Aba do navegador | `favicon.svg` + `favicon.ico` com 16 e 32 | — |

Em 16 px o boneco vira poucos pixels e quase não se reconhece. Para 16 e 32 px, faça uma versão simplificada. Duas opções:

- só a maleta voando com dois riscos de movimento;
- o boneco com traço de 5 a 6 unidades, sem os riscos.

Sempre sobre um fundo sólido (círculo ou quadrado arredondado), para funcionar na barra clara e na escura do Chrome.

## Como testar

- Abra `stickman-arremesso.svg` no Chrome: o arremesso roda em loop.
- Para ver dentro do app sem candidatar de verdade: com o JobScout rodando, abra `http://127.0.0.1:8765/?overlay=1` no Chrome (mostra a bolha no navegador), abra o console (F12) e rode:

  ```js
  onActivity({ id: Date.now(), em: new Date().toISOString(), texto: "teste", nivel: "trabalhando", acao: "envio" })
  ```

- O quadro estático foi conferido em 160, 128, 48, 32 e 16 px. Os quadros do animado foram conferidos em 0,2 s, 0,6 s, 0,85 s, 1,0 s, 1,2 s e 2,0 s.
