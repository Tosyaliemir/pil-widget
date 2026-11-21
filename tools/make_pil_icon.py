r"""assets/pil.ico dosyasını üretir (bir kerelik): koyu zeminde açık pil gövdesi, bakır dolgu.
Kullanım: .venv\Scripts\python tools\make_pil_icon.py"""
from pathlib import Path

from PIL import Image, ImageDraw

SIZE = 256
BG, LIGHT, COPPER = (22, 22, 22, 255), (236, 232, 226, 255), (201, 128, 76, 255)


def draw() -> Image.Image:
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, SIZE - 1, SIZE - 1), radius=56, fill=BG)
    k = SIZE / 64
    d.rounded_rectangle((6 * k, 18 * k, 52 * k, 46 * k), radius=7 * k, outline=LIGHT, width=round(5 * k))
    d.rounded_rectangle((54 * k, 26 * k, 60 * k, 38 * k), radius=2 * k, fill=LIGHT)
    d.rounded_rectangle((13 * k, 25 * k, 36 * k, 39 * k), radius=3 * k, fill=COPPER)
    return img


if __name__ == "__main__":
    out = Path(__file__).resolve().parent.parent / "assets" / "pil.ico"
    draw().save(out, sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (256, 256)])
    print("Yazıldı:", out)
