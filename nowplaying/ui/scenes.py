import math
import time

import pygame

from ..state import Playback
from .kit import BASE_H, BASE_W, Kit, blur, canvas, opaque, panel, rounded, shadow, vertical_gradient, vignette

SOURCE_LABEL = {"spotify": "Spotify", "airplay": "AirPlay", "bluetooth": "Bluetooth"}
SOURCE_ICON = {"spotify": "music-2", "airplay": "airplay", "bluetooth": "bluetooth"}
SOURCE_TINT = {"spotify": (22, 78, 58), "airplay": (58, 60, 96), "bluetooth": (26, 54, 122)}

WEEKDAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
MONTHS = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September",
          "Oktober", "November", "Dezember"]

COVER = 600
COVER_X = 210
COVER_CY = 530
TEXT_X = COVER_X + COVER + 110
TEXT_W = BASE_W - TEXT_X - 190
PAUSED_COVER_SCALE = 0.9


def fmt_time(ms: int) -> str:
    seconds = max(ms, 0) // 1000
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def draw_clock(kit: Kit, screen: pygame.Surface, wall: float) -> None:
    clock = kit.tabular(time.strftime("%H:%M", time.localtime(wall)), "medium", 32, 190)
    screen.blit(clock, (kit.x(BASE_W - 90) - clock.get_width(), kit.y(64)))


class NowPlayingView:
    def __init__(self, kit: Kit, playback: Playback, cover: pygame.Surface | None):
        self.kit = kit
        self.source = playback.source
        size = kit.px(COVER)
        radius = kit.px(14)
        if cover is not None:
            self.cover = rounded(cover, size, radius)
            self.background = self._background_from(cover)
        else:
            self.cover = self._placeholder(size, radius)
            self.background = self._background_tint()
        self.cover_shadow = shadow((size, size), kit.px(14), kit.px(60), 150)
        self._scaled: tuple[float, pygame.Surface, pygame.Surface] | None = None
        self.text_key = None
        self.text_layer: pygame.Surface | None = None
        self.bar_y = 0

    def _background_from(self, cover: pygame.Surface) -> pygame.Surface:
        k = self.kit
        tiny = pygame.transform.smoothscale(opaque(cover), (24, 14))
        soft = pygame.transform.smoothscale(tiny, (192, 108))
        soft = blur(soft, 3)
        bg = pygame.transform.smoothscale(soft, (k.w, k.h))
        bg.blit(vertical_gradient(k.w, k.h, (0, 0, 0, 70), (0, 0, 0, 150)), (0, 0))
        bg.blit(vignette(k.w, k.h, 150), (0, 0))
        return opaque(bg)

    def _background_tint(self) -> pygame.Surface:
        k = self.kit
        r, g, b = SOURCE_TINT.get(self.source, (40, 40, 60))
        bg = canvas((k.w, k.h))
        bg.blit(vertical_gradient(k.w, k.h, (r, g, b, 255), (r // 4, g // 4, b // 4, 255)), (0, 0))
        bg.blit(vignette(k.w, k.h, 160), (0, 0))
        return bg

    def _placeholder(self, size: int, radius: int) -> pygame.Surface:
        r, g, b = SOURCE_TINT.get(self.source, (40, 40, 60))
        surf = vertical_gradient(size, size, (min(r * 2, 255), min(g * 2, 255), min(b * 2, 255), 255), (r, g, b, 255))
        icon = self.kit.icon(SOURCE_ICON.get(self.source, "music-2"), COVER * 0.3, 150, stroke=1.25)
        surf.blit(icon, icon.get_rect(center=(size // 2, size // 2)))
        return rounded(surf, size, radius)

    def _build_text(self, pb: Playback) -> None:
        k = self.kit
        t = pb.track
        label = SOURCE_LABEL.get(pb.source, pb.source)
        title = t.title or f"Musik über {label}"
        artist = t.artist_line if not t.is_episode else (t.show or t.artist_line)
        if t.is_episode:
            album = " · ".join(x for x in ("Podcast", t.year) if x)
        else:
            album = " · ".join(x for x in (t.album, t.year) if x)

        header = label + (f" · {pb.controller}" if pb.controller else "")
        title_lines = k.wrap(title, "semibold", 64, TEXT_W, 2)

        meta: list[tuple[str, str]] = []
        if not pb.playing:
            meta.append(("icon", "pause"))
        details = [x for x in ("Pausiert" if not pb.playing else "", t.genre,
                               f"Titel {t.number}" if t.number else "", pb.codec) if x]
        if details:
            meta.append(("text", " · ".join(details)))
        if t.explicit:
            meta.append(("badge", "E"))
        if pb.shuffle:
            meta.append(("icon", "shuffle"))
        if pb.repeat:
            meta.append(("icon", "repeat-1" if pb.repeat == "track" else "repeat"))

        has_bar = t.duration_ms > 0
        heights = [34, 26, 72 * len(title_lines), 12, 48, 6, 40]
        if has_bar:
            heights += [48, 8, 16, 32]
        if meta:
            heights += [36, 32]
        y = COVER_CY - sum(heights) / 2

        layer = pygame.Surface((k.w, k.h), pygame.SRCALPHA)
        icon = k.icon(SOURCE_ICON.get(pb.source, "music-2"), 28, 160)
        layer.blit(icon, (k.x(TEXT_X), k.y(y + 3)))
        layer.blit(k.text(k.ellipsize(header, "medium", 28, TEXT_W - 44), "medium", 28, 160), (k.x(TEXT_X + 42), k.y(y)))
        y += 34 + 26
        for line in title_lines:
            layer.blit(k.text(line, "semibold", 64), (k.x(TEXT_X - 3), k.y(y - 6)))
            y += 72
        y += 12
        if artist:
            layer.blit(k.text(k.ellipsize(artist, "medium", 40, TEXT_W), "medium", 40, 215), (k.x(TEXT_X), k.y(y)))
        y += 48 + 6
        if album:
            layer.blit(k.text(k.ellipsize(album, "regular", 32, TEXT_W), "regular", 32, 150), (k.x(TEXT_X), k.y(y)))
        y += 40
        if has_bar:
            y += 48
            self.bar_y = y
            y += 8 + 16 + 32
        else:
            self.bar_y = 0
        if meta:
            y += 36
            self._draw_meta(layer, meta, y)
        self.text_layer = layer

    def _draw_meta(self, layer: pygame.Surface, items: list[tuple[str, str]], y: float) -> None:
        k = self.kit
        x = TEXT_X
        for kind, value in items:
            if kind == "icon":
                icon = k.icon(value, 26, 160)
                layer.blit(icon, (k.x(x), k.y(y + 2)))
                x += 26 + 10
            elif kind == "badge":
                text = k.text(value, "semibold", 18, 255)
                box = panel((k.px(26), k.px(26)), k.px(5), (255, 255, 255, 150))
                box.blit(text, text.get_rect(center=box.get_rect().center), special_flags=pygame.BLEND_RGBA_SUB)
                layer.blit(box, (k.x(x), k.y(y + 2)))
                x += 26 + 14
            else:
                text = k.text(value, "regular", 26, 150)
                layer.blit(text, (k.x(x), k.y(y)))
                x += text.get_width() / k.s + 18

    def draw(self, screen: pygame.Surface, pb: Playback, now: float, wall: float, paused_amount: float) -> None:
        k = self.kit
        key = (pb.track.identity, pb.source, pb.controller, pb.codec, pb.shuffle, pb.repeat, pb.playing)
        if key != self.text_key:
            self._build_text(pb)
            self.text_key = key

        screen.blit(self.background, (0, 0))
        if paused_amount > 0:
            dim = canvas((k.w, k.h))
            dim.set_alpha(int(70 * paused_amount))
            screen.blit(dim, (0, 0))

        scale = 1 - (1 - PAUSED_COVER_SCALE) * paused_amount
        cover, cover_shadow = self._cover_at(scale)
        center = (k.x(COVER_X + COVER / 2), k.y(COVER_CY))
        screen.blit(cover_shadow, cover_shadow.get_rect(center=(center[0], center[1] + k.px(26 * scale))))
        screen.blit(cover, cover.get_rect(center=center))
        screen.blit(self.text_layer, (0, 0))

        if self.bar_y:
            self._draw_progress(screen, pb, now)
        draw_clock(k, screen, wall)
        draw_volume(k, screen, pb, now)

    def _cover_at(self, scale: float) -> tuple[pygame.Surface, pygame.Surface]:
        if scale >= 0.999:
            return self.cover, self.cover_shadow
        if self._scaled and abs(self._scaled[0] - scale) < 0.002:
            return self._scaled[1], self._scaled[2]
        size = self.cover.get_width()
        cover = pygame.transform.smoothscale(self.cover, (round(size * scale),) * 2)
        sw, sh = self.cover_shadow.get_size()
        sh_s = pygame.transform.smoothscale(self.cover_shadow, (round(sw * scale), round(sh * scale)))
        self._scaled = (scale, cover, sh_s)
        return cover, sh_s

    def _draw_progress(self, screen: pygame.Surface, pb: Playback, now: float) -> None:
        k = self.kit
        duration = pb.track.duration_ms
        pos = pb.position_now(now)
        x, y, w, h = k.x(TEXT_X), k.y(self.bar_y), k.px(TEXT_W), k.px(8)
        screen.blit(panel((w, h), h // 2, (255, 255, 255, 60)), (x, y))
        filled = int(w * min(pos / duration, 1.0)) if duration else 0
        if filled >= h:
            screen.blit(panel((filled, h), h // 2, (255, 255, 255, 235)), (x, y))
        elapsed = k.tabular(fmt_time(pos), "medium", 26, 160)
        remaining = k.tabular("-" + fmt_time(duration - pos), "medium", 26, 160)
        ty = y + h + k.px(14)
        screen.blit(elapsed, (x, ty))
        screen.blit(remaining, (x + w - remaining.get_width(), ty))


def draw_volume(kit: Kit, screen: pygame.Surface, pb: Playback, now: float) -> None:
    if pb.volume is None or not pb.volume_at:
        return
    age = now - pb.volume_at
    if age > 2.8:
        return
    alpha = 1.0 if age < 2.3 else max(0.0, 1 - (age - 2.3) / 0.5)
    k = kit
    w, h = k.px(440), k.px(72)
    pill = panel((w, h), h // 2, (0, 0, 0, 120))
    icon = k.icon("volume-x" if pb.volume <= 0.001 else "volume-2", 30, 230)
    pill.blit(icon, (k.px(28), (h - icon.get_height()) // 2))
    bx, bw, bh = k.px(80), w - k.px(80 + 32), k.px(8)
    by = (h - bh) // 2
    pill.blit(panel((bw, bh), bh // 2, (255, 255, 255, 70)), (bx, by))
    fill = int(bw * pb.volume)
    if fill >= bh:
        pill.blit(panel((fill, bh), bh // 2, (255, 255, 255, 240)), (bx, by))
    pill.set_alpha(int(255 * alpha))
    screen.blit(pill, ((k.w - w) // 2, k.y(50)))


IDLE_CARDS = [
    ("music-2", "Spotify", [
        "Spotify-App öffnen",
        "Auf das Lautsprecher-Symbol tippen",
        "„Wohnzimmer“ auswählen",
    ]),
    ("airplay", "AirPlay", [
        "Auf iPhone, iPad oder Mac auf AirPlay tippen",
        "„Wohnzimmer“ auswählen",
        "Klappt mit fast jeder App",
    ]),
    ("bluetooth", "Bluetooth", [
        "Bluetooth am Handy öffnen",
        "„Wohnzimmer“ koppeln, ohne PIN",
        "Musik in einer App starten",
    ]),
]


class IdleView:
    def __init__(self, kit: Kit):
        self.kit = kit
        self.aurora = self._aurora()
        self.cards = self._cards()
        self.clock_key = None
        self.clock_layer: pygame.Surface | None = None

    def _aurora(self) -> pygame.Surface:
        k = self.kit
        w, h = 320, 180
        base = canvas((w, h))
        base.fill((7, 9, 16))
        blobs = pygame.Surface((w, h), pygame.SRCALPHA)
        for cx, cy, r, color in [
            (60, 40, 120, (20, 70, 90, 150)),
            (250, 50, 110, (60, 40, 110, 140)),
            (180, 160, 130, (18, 60, 70, 130)),
            (40, 170, 90, (70, 30, 80, 110)),
        ]:
            pygame.draw.circle(blobs, color, (cx, cy), r)
        base.blit(blur(blur(blobs, 6), 4), (0, 0))
        big = pygame.transform.smoothscale(blur(base, 3), (int(k.w * 1.25), int(k.h * 1.25)))
        return opaque(big)

    def _cards(self) -> pygame.Surface:
        k = self.kit
        layer = pygame.Surface((k.w, k.h), pygame.SRCALPHA)
        layer.blit(k.text("Musik auf „Wohnzimmer“ abspielen", "semibold", 48), (k.x(160), k.y(500)))

        gap, left, top, height = 40, 160, 590, 360
        width = (BASE_W - 2 * left - 2 * gap) / 3
        for i, (icon_name, title, steps) in enumerate(IDLE_CARDS):
            x = left + i * (width + gap)
            layer.blit(panel((k.px(width), k.px(height)), k.px(28), (255, 255, 255, 20)), (k.x(x), k.y(top)))
            pad = 40
            circle = panel((k.px(60), k.px(60)), k.px(30), (255, 255, 255, 34))
            icon = k.icon(icon_name, 30, 240)
            circle.blit(icon, icon.get_rect(center=circle.get_rect().center))
            layer.blit(circle, (k.x(x + pad), k.y(top + pad)))
            layer.blit(k.text(title, "semibold", 34), (k.x(x + pad + 80), k.y(top + pad + 9)))
            y = top + pad + 96
            for n, step in enumerate(steps, start=1):
                badge = panel((k.px(32), k.px(32)), k.px(16), (255, 255, 255, 40))
                num = k.text(str(n), "semibold", 18, 230)
                badge.blit(num, num.get_rect(center=badge.get_rect().center))
                layer.blit(badge, (k.x(x + pad), k.y(y + 1)))
                for line in k.wrap(step, "regular", 26, width - pad * 2 - 48, 2):
                    layer.blit(k.text(line, "regular", 26, 215), (k.x(x + pad + 48), k.y(y)))
                    y += 34
                y += 16

        hint = "Spotify überspringt jeden Titel? Dann über AirPlay oder Bluetooth abspielen."
        layer.blit(k.text(hint, "regular", 24, 120), (k.x(160), k.y(1000)))
        return layer

    def _clock(self, wall: float) -> pygame.Surface:
        k = self.kit
        lt = time.localtime(wall)
        key = (lt.tm_yday, lt.tm_hour, lt.tm_min)
        if key != self.clock_key:
            layer = pygame.Surface((k.w, k.px(400)), pygame.SRCALPHA)
            layer.blit(k.tabular(time.strftime("%H:%M", lt), "light", 168), (k.x(150), k.px(70)))
            date = f"{WEEKDAYS[lt.tm_wday]}, {lt.tm_mday}. {MONTHS[lt.tm_mon - 1]}"
            layer.blit(k.text(date, "regular", 38, 180), (k.x(162), k.px(290)))
            speaker = k.icon("speaker", 32, 170)
            name = k.text("Wohnzimmer", "medium", 32, 170)
            nx = k.x(BASE_W - 160) - name.get_width()
            layer.blit(name, (nx, k.px(120)))
            layer.blit(speaker, (nx - k.px(46), k.px(122)))
            self.clock_layer, self.clock_key = layer, key
        return self.clock_layer

    def draw(self, screen: pygame.Surface, now: float, wall: float) -> None:
        k = self.kit
        span_x = self.aurora.get_width() - k.w
        span_y = self.aurora.get_height() - k.h
        phase = now / 90
        ox = int(span_x * (0.5 + 0.5 * math.sin(phase)))
        oy = int(span_y * (0.5 + 0.5 * math.cos(phase * 0.7)))
        screen.blit(self.aurora, (-ox, -oy))
        screen.blit(self._clock(wall), (0, k.oy))
        screen.blit(self.cards, (0, 0))
