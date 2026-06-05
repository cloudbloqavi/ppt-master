"""edge-tts backend for narration audio generation."""

from __future__ import annotations

import re
from pathlib import Path


COMMON_VOICES = [
    ("zh-CN", "zh-CN-XiaoxiaoNeural", "Female voice, Mandarin, clear and natural, default recommendation"),
    ("zh-CN", "zh-CN-XiaoyiNeural", "Female voice, Mandarin, bright"),
    ("zh-CN", "zh-CN-YunjianNeural", "Male voice, Mandarin, steady"),
    ("zh-CN", "zh-CN-YunxiNeural", "Male voice, Mandarin, young"),
    ("zh-CN", "zh-CN-YunxiaNeural", "Male voice, Mandarin, youthful"),
    ("zh-CN", "zh-CN-YunyangNeural", "Male voice, Mandarin, announcing"),
    ("zh-HK", "zh-HK-HiuGaaiNeural", "Female voice, Cantonese"),
    ("zh-HK", "zh-HK-WanLungNeural", "Male voice, Cantonese"),
    ("zh-TW", "zh-TW-HsiaoChenNeural", "Female voice, Taiwanese Mandarin"),
    ("zh-TW", "zh-TW-YunJheNeural", "Male voice, Taiwanese Mandarin"),
    ("en-US", "en-US-JennyNeural", "Female voice, American English"),
    ("en-US", "en-US-GuyNeural", "Male voice, American English"),
    ("en-GB", "en-GB-SoniaNeural", "Female voice, British English"),
    ("en-GB", "en-GB-RyanNeural", "Male voice, British English"),
]


def edge_output_extension() -> str:
    return ".mp3"


def normalize_rate(rate: str) -> str:
    """Normalize a user-provided rate into edge-tts format."""
    value = rate.strip()
    if not value:
        return "+0%"
    if value.endswith("%"):
        if value[0] not in "+-":
            return f"+{value}"
        return value
    if re.fullmatch(r"[+-]?\d+", value):
        number = int(value)
        return f"{number:+d}%"
    return value


async def generate(text: str, output_path: Path, *, voice: str, rate: str) -> None:
    try:
        import edge_tts
    except ImportError as exc:
        raise RuntimeError(
            "Missing dependency `edge-tts`. Install it with: "
            "python3 -m pip install edge-tts"
        ) from exc

    communicate = edge_tts.Communicate(text, voice=voice, rate=normalize_rate(rate))
    await communicate.save(str(output_path))


def print_common_voices() -> None:
    print("Common edge-tts voices:")
    print("Locale   Voice                         Notes")
    print("------   ----------------------------  ----------------")
    for locale, voice, notes in COMMON_VOICES:
        print(f"{locale:<8} {voice:<29} {notes}")


async def print_voices(locale: str | None = None) -> None:
    try:
        import edge_tts
    except ImportError as exc:
        raise RuntimeError(
            "Missing dependency `edge-tts`. Install it with: "
            "python3 -m pip install edge-tts"
        ) from exc

    manager = await edge_tts.VoicesManager.create()
    voices = manager.voices
    if locale:
        voices = [voice for voice in voices if voice.get("Locale") == locale]
    for voice in sorted(voices, key=lambda item: (item.get("Locale", ""), item.get("ShortName", ""))):
        short_name = voice.get("ShortName", "")
        voice_locale = voice.get("Locale", "")
        gender = voice.get("Gender", "")
        friendly = voice.get("FriendlyName", "")
        print(f"{voice_locale:<8} {short_name:<34} {gender:<8} {friendly}")