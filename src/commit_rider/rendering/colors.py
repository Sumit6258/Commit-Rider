"""Small colour helpers. Colours are ``(r, g, b)`` tuples of ints; hex strings are accepted."""

from __future__ import annotations

Color = tuple[int, int, int]


def rgb(value: str | Color) -> Color:
    if isinstance(value, tuple):
        return (int(value[0]), int(value[1]), int(value[2]))
    text = value.strip().lstrip("#")
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    if len(text) != 6:
        raise ValueError(f"bad colour {value!r}")
    return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))


def to_hex(color: Color) -> str:
    return "#{:02x}{:02x}{:02x}".format(*color)


def mix(a: str | Color, b: str | Color, t: float) -> Color:
    ca, cb = rgb(a), rgb(b)
    t = min(1.0, max(0.0, t))
    return tuple(round(ca[i] + (cb[i] - ca[i]) * t) for i in range(3))  # type: ignore[return-value]


def darken(c: str | Color, amount: float) -> Color:
    return mix(c, (0, 0, 0), amount)


def lighten(c: str | Color, amount: float) -> Color:
    return mix(c, (255, 255, 255), amount)


def luminance(c: str | Color) -> float:
    r, g, b = rgb(c)
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255.0


def with_alpha(c: str | Color, alpha: float) -> tuple[int, int, int, int]:
    r, g, b = rgb(c)
    return (r, g, b, round(255 * min(1.0, max(0.0, alpha))))
