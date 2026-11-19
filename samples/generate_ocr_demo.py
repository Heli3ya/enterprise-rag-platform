"""
Generate the OCR demo assets in `samples/`.

This is a *developer-only* helper: it needs Pillow plus
`arabic-reshaper` and `python-bidi`, which shape Arabic script before
Pillow draws it (the Windows Pillow wheel has no libraqm). None of
those are runtime dependencies of the platform and none are imported
by the OCR extractor.

    ./venv/Scripts/python.exe samples/generate_ocr_demo.py
"""

from pathlib import Path

import arabic_reshaper
from bidi.algorithm import get_display
from PIL import Image, ImageDraw, ImageFont

OUTPUT = Path(__file__).resolve().parent
FONT_PATH = "C:/Windows/Fonts/tahoma.ttf"

LINES = [
    ("به نام خدا", 28, False),
    ("اداره کل فناوری اطلاعات", 26, False),
    ("شماره: ۱۴۰۲/د/۴۵", 26, False),
    ("تاریخ: ۱۴۰۲/۰۸/۱۵", 26, False),
    ("موضوع: صورتجلسه تأمین تجهیزات", 27, False),
    ("", 20, False),
    ("بدینوسیله صورتجلسه شماره ۱۲۳ مورخ ۱۴۰۲ جهت بررسی", 27, False),
    ("کد کالا: BR-777", 27, False),
    ("مراتب به دفتر فنی ارسال میگردد.", 27, False),
    ("", 20, False),
    ("امضا: مدیر بخش تدارکات", 26, False),
]


def shaped(line):
    return get_display(arabic_reshaper.reshape(line))


def main():
    image = Image.new("RGB", (1400, 900), color="white")
    draw = ImageDraw.Draw(image)

    draw.rectangle((40, 40, 1360, 860), outline="black", width=3)

    y = 90

    for text, size, bold in LINES:
        if not text:
            y += 26
            continue

        font = ImageFont.truetype(
            "C:/Windows/Fonts/tahomabd.ttf" if bold else FONT_PATH,
            size,
        )
        glyphs = shaped(text)
        left, top, right, bottom = draw.textbbox((0, 0), glyphs, font=font)
        x = 1320 - (right - left)

        draw.text((x - left, y - top), glyphs, fill="black", font=font)
        y += (bottom - top) + 34

    image.save(OUTPUT / "scanned_letter_demo.png")
    image.save(
        OUTPUT / "scanned_letter_demo.pdf",
        "PDF",
        resolution=200.0,
    )

    print("wrote scanned_letter_demo.png and scanned_letter_demo.pdf")


if __name__ == "__main__":
    main()
