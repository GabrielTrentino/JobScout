# Boneco do JobScout: handoff

O mascote do JobScout é um boneco de palitinho com uma maleta. Ele vive na bolha do overlay, no canto inferior direito da tela, e muda de pose conforme o que o app está fazendo. As três poses do app são animações exportadas da ferramenta de animação, no mesmo formato.

## Arquivos

| Arquivo | Pose | Para quê |
|---|---|---|
| [stickman-sentado-quadros.svg](stickman-sentado-quadros.svg) | `idle` | **Usado pelo app.** 60 quadros em 3,2 s, em loop |
| [stickman-pensando-quadros.svg](stickman-pensando-quadros.svg) | `think` | **Usado pelo app.** 58 quadros em 2,4 s, em loop |
| [stickman-arremesso-quadros.svg](stickman-arremesso-quadros.svg) | `throw` | **Usado pelo app.** 60 quadros em 2,4 s, tocados 1,65 vez |
| [encaixar.py](encaixar.py) | — | Converte uma exportação e a coloca na pose certa do `index.html` |
| [stickman-arremesso-estatico.svg](stickman-arremesso-estatico.svg) | — | Quadro parado do arremesso, sem CSS. Base dos ícones |
| [stickman-arremesso.svg](stickman-arremesso.svg) | — | Primeira versão do arremesso, feita à mão. Não é mais usada |

As exportações são fitas: os quadros de 528 × 456 ficam lado a lado, e o CSS desliza a fita um quadro por vez. A área é 6× o viewBox `-12 -10 88 76` do boneco, com o chão em y = 412.

## Trocar uma pose por uma nova exportação

1. Exporte como **Animated SVG (CSS)**, com 528 × 456 e as cores dos handoffs.
2. Salve nesta pasta com o nome da pose (tabela acima).
3. Rode, na raiz do projeto:

   ```
   .venv\Scripts\python.exe assets\stickman\encaixar.py idle assets\stickman\stickman-sentado-quadros.svg
   ```

   Troque `idle` por `think` ou `throw` conforme a pose.

O conversor:

- troca a cor do traço `rgb(22,32,42)` pela cor do tema, para o boneco ficar claro no modo escuro;
- substitui os atributos repetidos por classes do `app.css` (`i`, `f`, `shadow`);
- grava o número de quadros e a duração na própria fita, então não é preciso mexer no CSS.

Se a exportação trouxer a cor do traço com outros atributos, ele para e avisa.

Um cuidado no arremesso: ele toca 1,65 vez (`POSES` no `encaixar.py`), ou seja, uma volta inteira e a segunda até as mãos vazias. Se a duração ou essa conta mudar, ajuste também `THROW_MS` no `app.js` (hoje 3960 ms = 2,4 s × 1,65). É esse tempo que segura a pose antes de voltar a sentar.

## Poses e quando aparecem

| Pose | `data-pose` | Movimento | Quando o app mostra |
|---|---|---|---|
| Parado | `idle` | Sentado na maleta, respirando e balançando as pernas | Nada sendo processado |
| Lendo a vaga | `think` | Sentado, mão no queixo, três pontos acendendo em sequência | Atividade com nível `trabalhando`: leitura de vaga ou formulário, verificação do Gmail |
| Arremesso | `throw` | Duas vezes seguidas: a primeira inteira e a segunda até ficar de mãos vazias (3,96 s), e volta a sentar | Atividade com `acao: "envio"`, emitida quando a extensão detecta o clique em Enviar candidatura |

Cada troca de pose recomeça a fita do primeiro quadro. Se o sistema pedir menos movimento, cada pose fica parada num quadro: o primeiro no sentado e no pensando, e o 24 (maleta no ar) no arremesso.

## Primeira versão (feita à mão)

As seções abaixo descrevem o boneco desenhado à mão, que serviu de base para as poses exportadas e para os ícones.

### Desenho

- **Área de desenho:** `viewBox="0 0 64 64"`. Na bolha ele aparece com 54 px. O arquivo animado usa `-12 -10 88 76` para caber o balanço e o voo da maleta.
- **Traço:** 3,4 unidades, pontas e cantos arredondados, sem preenchimento. A cabeça é um círculo com raio 6.
- **Maleta:** retângulo 13 × 9 com cantos de raio 2 e alça de 4 × 2. Na pose sentada ela é maior: 24 × 14, com uma faixa no meio.

### Cores

| Elemento | Tema claro | Tema escuro |
|---|---|---|
| Traço do boneco | `#16202a` | `#e6edf3` |
| Maleta (preenchimento) | `#c98a2b` | `#c98a2b` |
| Contorno e alça da maleta | `#6f4c18` | `#6f4c18` |
| Fundo da bolha | `#e9edf2` | `#10151c` |

No app, o traço usa `currentColor` e herda a cor do texto. O contorno da maleta é a cor dela misturada com 45% de preto.

### Anatomia do arremesso

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

### Para quem for editar

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

- Abra qualquer `*-quadros.svg` no Chrome: a animação roda em loop.
- Para ver dentro do app sem candidatar de verdade: com o JobScout rodando, abra `http://127.0.0.1:8765/?overlay=1` no Chrome (mostra a bolha no navegador), abra o console (F12) e rode uma das linhas:

  ```js
  // pensando, por 4 s
  onActivity({ id: Date.now(), em: new Date().toISOString(), texto: "teste", nivel: "trabalhando" })
  // arremesso, duas vezes
  onActivity({ id: Date.now(), em: new Date().toISOString(), texto: "teste", nivel: "ok", acao: "envio" })
  ```

- As três poses foram conferidas na bolha, nos temas claro e escuro: a fita avança, cada pose recomeça ao entrar e o boneco volta a sentar ao fim do trabalho e do arremesso.
