"""Generate the official PLATA Windows icon."""

from pathlib import Path
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parent
SIZE = 1024
BG = (15, 18, 23, 255)
ORANGE = (255, 132, 0, 255)
ORANGE_DARK = (193, 79, 0, 255)
WHITE = (250, 250, 248, 255)


def font(size: int):
    candidates = [
        Path("C:/Windows/Fonts/arialbd.ttf"),
        Path("C:/Windows/Fonts/segoeuib.ttf"),
    ]
    for path in candidates:
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


image = Image.new("RGBA", (SIZE, SIZE), BG)
draw = ImageDraw.Draw(image)

draw.rounded_rectangle((48, 48, 976, 976), radius=190, fill=BG, outline=ORANGE, width=38)
draw.rounded_rectangle((105, 105, 919, 919), radius=150, outline=ORANGE_DARK, width=12)

letter_font = font(610)
bbox = draw.textbbox((0, 0), "P", font=letter_font)
x = (SIZE - (bbox[2] - bbox[0])) // 2 - bbox[0]
y = (SIZE - (bbox[3] - bbox[1])) // 2 - bbox[1] - 12
draw.text((x, y), "P", font=letter_font, fill=ORANGE)

draw.rounded_rectangle((690, 735, 862, 803), radius=34, fill=WHITE)
draw.rounded_rectangle((690, 825, 862, 893), radius=34, fill=ORANGE)

png_path = ROOT / "PLATA.png"
ico_path = ROOT / "PLATA.ico"
image.save(png_path)
image.save(ico_path, format="ICO", sizes=[(16, 16), (24, 24), (32, 32), (48, 48),
                                           (64, 64), (128, 128), (256, 256)])
print(png_path)
print(ico_path)
