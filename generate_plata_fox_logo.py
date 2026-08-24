"""Create the PLATA fox logo from the supplied reference image."""

from pathlib import Path
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parent
REFERENCE = Path(r"C:/Users/mercb/Downloads/photo_2026-08-14_15-04-10.jpg")
SIZE = 1024
ORANGE = (255, 132, 0, 255)
BLACK = (9, 11, 14, 255)
WHITE = (248, 248, 246, 255)


def get_font(size: int):
    for path in (Path("C:/Windows/Fonts/arialbd.ttf"), Path("C:/Windows/Fonts/segoeuib.ttf")):
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


source = Image.open(REFERENCE).convert("RGBA")
source.thumbnail((700, 700), Image.Resampling.LANCZOS)

# The reference has a white background and orange fox line art. Preserve the
# orange pixels, turn the white interior into black, and remove JPEG noise.
fox = Image.new("RGBA", source.size, BLACK)
pixels = source.load()
target = fox.load()
for y in range(source.height):
    for x in range(source.width):
        r, g, b, a = pixels[x, y]
        orange_strength = r - min(g, b)
        if r > 180 and g > 70 and g < 210 and b < 130 and orange_strength > 35:
            target[x, y] = (*ORANGE[:3], 255)
        else:
            target[x, y] = BLACK

canvas = Image.new("RGBA", (SIZE, SIZE), BLACK)
fox_x = (SIZE - fox.width) // 2
fox_y = 145
canvas.alpha_composite(fox, (fox_x, fox_y))

draw = ImageDraw.Draw(canvas)
label_font = get_font(112)
label = "PLATA"
bbox = draw.textbbox((0, 0), label, font=label_font)
label_x = (SIZE - (bbox[2] - bbox[0])) // 2
label_y = fox_y + fox.height - 5
draw.text((label_x + 4, label_y + 5), label, font=label_font, fill=(100, 45, 0, 255))
draw.text((label_x, label_y), label, font=label_font, fill=ORANGE)

png_path = ROOT / "PLATA-fox.png"
ico_path = ROOT / "PLATA.ico"
canvas.save(png_path)
canvas.save(ico_path, format="ICO", sizes=[(16, 16), (24, 24), (32, 32), (48, 48),
                                             (64, 64), (128, 128), (256, 256)])
print(png_path)
print(ico_path)
