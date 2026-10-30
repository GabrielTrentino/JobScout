"""Encaixa uma animação exportada (Animated SVG com CSS, fita de quadros 528 x 456) numa pose do boneco da bolha.

Uso: python assets/stickman/encaixar.py <idle|think|throw> <arquivo exportado>

Troca o conteúdo de <g class="pose pose-...">, em jobscout/web/index.html, pela fita convertida:
a cor do traço vira currentColor (segue o tema) e os atributos repetidos viram classes do app.css.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

INDEX = Path(__file__).resolve().parents[2] / "jobscout" / "web" / "index.html"
INK = "rgb(22,32,42)"
FRAME = 528
POSES = {
    # pose: (repetições, quadro mostrado quando o sistema pede menos movimento)
    "idle": ("infinite", 0),
    "think": ("infinite", 0),
    "throw": ("1.65", 24),  # uma volta e a segunda até as mãos vazias (THROW_MS no app.js)
}
CLASSES = {
    f' fill="none" stroke="{INK}" stroke-opacity="1" stroke-width="20.4" stroke-linecap="round" stroke-linejoin="round"': ' class="i"',
    f' fill="{INK}" fill-opacity="1"': ' class="f"',
    f' fill="{INK}" fill-opacity="0.12"': ' class="shadow"',
}


def convert(src: str, pose: str) -> str:
    frames = int(re.search(r"steps\((\d+)", src).group(1))
    duration = re.search(r"animation:\S+ ([\d.]+s)", src).group(1)
    inner = src.split('will-change:transform">', 1)[1].rsplit("</g></g>", 1)[0]
    for attrs, cls in CLASSES.items():
        inner = inner.replace(attrs, cls)
    inner = inner.replace(' fill-opacity="1"', "").replace(' stroke-opacity="1"', "")
    if INK in inner:
        raise SystemExit(f"A cor {INK} aparece com atributos que o conversor não conhece; confira a exportação.")
    inner = re.sub(r">\s+<", "><", inner).strip()
    while True:
        shorter = re.sub(r"<g(?: [^>]*)?></g>", "", inner)
        if shorter == inner:
            break
        inner = shorter
    inner = re.sub(r'<g transform="translate\((\d+) 0\)">', r'<g transform="translate(\1)">', inner)
    found = len(re.findall(r'<g transform="translate\(\d+\)">', inner))
    if found != frames:
        raise SystemExit(f"Esperava {frames} quadros e achei {found}.")
    repeat, still = POSES[pose]
    style = f"--frames:{frames};--dur:{duration};--end:-{(frames - 1) * FRAME}px;--repeat:{repeat};--still:-{still * FRAME}px"
    return (
        f'          <svg class="sprite" x="-4" y="-10" width="88" height="76" viewBox="0 0 {FRAME} 456">'
        f'<g class="strip" style="{style}">{inner}</g></svg>\n'
    )


def main() -> None:
    if len(sys.argv) != 3 or sys.argv[1] not in POSES:
        raise SystemExit(__doc__)
    pose, path = sys.argv[1], Path(sys.argv[2])
    sprite = convert(path.read_text(encoding="utf-8"), pose)
    html = INDEX.read_text(encoding="utf-8")
    opening = f'<g class="pose pose-{pose}">\n'
    start = html.index(opening) + len(opening)
    # A pose fecha no primeiro </g> com o mesmo recuo da abertura (8 espaços).
    end = html.index("\n        </g>\n", start - 1) + 1
    INDEX.write_text(html[:start] + sprite + html[end:], encoding="utf-8", newline="")
    print(f"pose {pose}: {len(sprite) // 1024} KB, origem {path.name}")


if __name__ == "__main__":
    main()
