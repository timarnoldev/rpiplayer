import io
from functools import lru_cache
from pathlib import Path

import pygame

ASSETS = Path(__file__).resolve().parents[2] / "assets"
BASE_W, BASE_H = 1920, 1080
WEIGHTS = {"light": "Light", "regular": "Regular", "medium": "Medium", "semibold": "SemiBold", "bold": "Bold"}


class Kit:
    """Drawing helpers in 1920x1080 design units, scaled to the real screen."""

    def __init__(self, width: int, height: int):
        self.w, self.h = width, height
        self.s = min(width / BASE_W, height / BASE_H)
        self.ox = (width - BASE_W * self.s) / 2
        self.oy = (height - BASE_H * self.s) / 2
        self._fonts: dict[tuple, pygame.font.Font] = {}
        self._icons: dict[tuple, pygame.Surface] = {}

    def px(self, v: float) -> int:
        return max(1, round(v * self.s))

    def x(self, v: float) -> int:
        return round(self.ox + v * self.s)

    def y(self, v: float) -> int:
        return round(self.oy + v * self.s)

    def font(self, weight: str, size: float) -> pygame.font.Font:
        key = (weight, self.px(size))
        if key not in self._fonts:
            self._fonts[key] = pygame.font.Font(str(ASSETS / "fonts" / f"Inter-{WEIGHTS[weight]}.ttf"), key[1])
        return self._fonts[key]

    def text(self, text: str, weight: str, size: float, alpha: int = 255) -> pygame.Surface:
        surf = self.font(weight, size).render(text, True, (255, 255, 255))
        if alpha < 255:
            surf.set_alpha(alpha)
        return surf

    def ellipsize(self, text: str, weight: str, size: float, max_w: float) -> str:
        font, limit = self.font(weight, size), self.px(max_w)
        if font.size(text)[0] <= limit:
            return text
        lo, hi = 0, len(text)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if font.size(text[:mid].rstrip() + "…")[0] <= limit:
                lo = mid
            else:
                hi = mid - 1
        return text[:lo].rstrip() + "…"

    def wrap(self, text: str, weight: str, size: float, max_w: float, max_lines: int) -> list[str]:
        font, limit = self.font(weight, size), self.px(max_w)
        lines: list[str] = []
        current = ""
        words = text.split()
        for i, word in enumerate(words):
            candidate = f"{current} {word}".strip()
            if font.size(candidate)[0] <= limit or not current:
                current = candidate
                continue
            lines.append(current)
            current = word
            if len(lines) == max_lines - 1:
                current = " ".join(words[i:])
                break
        if current:
            lines.append(current)
        if len(lines) > max_lines:
            lines = lines[:max_lines]
        lines[-1] = self.ellipsize(lines[-1], weight, size, max_w)
        return lines

    def tabular(self, text: str, weight: str, size: float, alpha: int = 255) -> pygame.Surface:
        """Inter's digits are proportional; fixed cells keep running times from jittering."""
        font = self.font(weight, size)
        cell = max(font.size(d)[0] for d in "0123456789")
        widths = [cell if ch.isdigit() else font.size(ch)[0] for ch in text]
        surf = pygame.Surface((sum(widths), font.get_height()), pygame.SRCALPHA)
        x = 0
        for ch, w in zip(text, widths):
            glyph = font.render(ch, True, (255, 255, 255))
            surf.blit(glyph, (x + (w - glyph.get_width()) // 2, 0))
            x += w
        if alpha < 255:
            surf.set_alpha(alpha)
        return surf

    def icon(self, name: str, size: float, alpha: int = 255, stroke: float = 2.0) -> pygame.Surface:
        key = (name, self.px(size), alpha, stroke)
        if key not in self._icons:
            svg = (ASSETS / "icons" / f"{name}.svg").read_text()
            n = self.px(size)
            svg = (svg.replace('width="24"', f'width="{n}"').replace('height="24"', f'height="{n}"')
                   .replace("currentColor", "#ffffff").replace('stroke-width="2"', f'stroke-width="{stroke}"'))
            surf = pygame.image.load(io.BytesIO(svg.encode()), "icon.svg")
            if alpha < 255:
                surf.set_alpha(alpha)
            self._icons[key] = surf
        return self._icons[key]


_OPAQUE = None


def opaque(surface: pygame.Surface) -> pygame.Surface:
    """24-bit without alpha; never the display's format, which is ARGB on macOS and breaks blending."""
    global _OPAQUE
    if _OPAQUE is None:
        _OPAQUE = pygame.Surface((1, 1), 0, 24)
    return surface.convert(_OPAQUE)


def canvas(size: tuple[int, int]) -> pygame.Surface:
    return pygame.Surface(size, 0, 24)


def rounded_mask(size: tuple[int, int], radius: int) -> pygame.Surface:
    """Antialiased rounded-rect alpha mask (pygame's own border_radius is aliased)."""
    factor = 4
    big = pygame.Surface((size[0] * factor, size[1] * factor), pygame.SRCALPHA)
    pygame.draw.rect(big, (255, 255, 255, 255), big.get_rect(), border_radius=radius * factor)
    return pygame.transform.smoothscale(big, size)


def rounded(image: pygame.Surface, size: int, radius: int) -> pygame.Surface:
    img = pygame.Surface((size, size), pygame.SRCALPHA)
    img.blit(pygame.transform.smoothscale(image, (size, size)), (0, 0))
    img.blit(rounded_mask((size, size), radius), (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    return img


def blur(surface: pygame.Surface, factor: int) -> pygame.Surface:
    w, h = surface.get_size()
    small = pygame.transform.smoothscale(surface, (max(1, w // factor), max(1, h // factor)))
    return pygame.transform.smoothscale(small, (w, h))


def shadow(size: tuple[int, int], radius: int, spread: int, alpha: int) -> pygame.Surface:
    w, h = size[0] + spread * 2, size[1] + spread * 2
    surf = pygame.Surface((w, h), pygame.SRCALPHA)
    pygame.draw.rect(surf, (0, 0, 0, alpha), (spread, spread, *size), border_radius=radius)
    return blur(blur(surf, max(2, spread // 3)), max(2, spread // 4))


def panel(size: tuple[int, int], radius: int, rgba: tuple[int, int, int, int]) -> pygame.Surface:
    surf = pygame.Surface(size, pygame.SRCALPHA)
    surf.fill(rgba)
    surf.blit(rounded_mask(size, radius), (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    return surf


@lru_cache(maxsize=4)
def vignette(width: int, height: int, strength: int) -> pygame.Surface:
    small = pygame.Surface((64, 36), pygame.SRCALPHA)
    for y in range(36):
        for x in range(64):
            dx, dy = (x - 31.5) / 32, (y - 17.5) / 18
            d = min(1.0, (dx * dx + dy * dy) ** 0.5 / 1.25)
            small.set_at((x, y), (0, 0, 0, int(strength * d * d)))
    return pygame.transform.smoothscale(small, (width, height))


def vertical_gradient(width: int, height: int, top: tuple[int, int, int, int], bottom: tuple[int, int, int, int]) -> pygame.Surface:
    small = pygame.Surface((1, 64), pygame.SRCALPHA)
    for y in range(64):
        t = y / 63
        small.set_at((0, y), tuple(round(a + (b - a) * t) for a, b in zip(top, bottom)))
    return pygame.transform.smoothscale(small, (width, height))
