import io
import logging
from collections import OrderedDict

import pygame

from ..state import Playback, Store
from .kit import Kit, opaque
from .scenes import IdleView, NowPlayingView

log = logging.getLogger(__name__)

CROSSFADE_SECONDS = 0.6
PAUSE_ANIM_SECONDS = 0.35


class Renderer:
    def __init__(self, kit: Kit, store: Store, animate: bool = True, blank_after: float = 20 * 60):
        self.kit = kit
        self.store = store
        self.animate = animate
        self.blank_after = blank_after
        self.idle = IdleView(kit)
        self.view: NowPlayingView | None = None
        self.view_key = None
        self.covers: OrderedDict[str, pygame.Surface | None] = OrderedDict()
        self.fade_from: pygame.Surface | None = None
        self.fade_start = 0.0
        self.paused_amount = 0.0
        self.last_now: float | None = None
        self.idle_since: float | None = None

    def _cover(self, pb: Playback) -> pygame.Surface | None:
        key = pb.track.cover_key
        if not key or not pb.track.cover:
            return None
        if key not in self.covers:
            try:
                self.covers[key] = opaque(pygame.image.load(io.BytesIO(pb.track.cover)))
            except pygame.error as exc:
                log.warning("Cover nicht lesbar: %s", exc)
                self.covers[key] = None
            while len(self.covers) > 8:
                self.covers.popitem(last=False)
        return self.covers[key]

    def frame(self, screen: pygame.Surface, now: float, wall: float) -> bool:
        """Draws one frame; returns True while an animation wants a high frame rate."""
        dt = 0.0 if self.last_now is None else now - self.last_now
        self.last_now = now
        pb = self.store.active(now)

        has_cover = bool(pb and pb.track.cover)
        key = (pb.source, pb.track.identity, has_cover) if pb else None
        if key != self.view_key:
            if self.animate:
                self.fade_from = screen.copy()
                self.fade_start = now
            self.view = NowPlayingView(self.kit, pb, self._cover(pb)) if pb else None
            self.view_key = key
            self.paused_amount = 0.0 if (pb and pb.playing) or not self.animate else 1.0

        target = 0.0 if (pb is None or pb.playing) else 1.0
        if not self.animate:
            self.paused_amount = target
        elif self.paused_amount != target:
            step = dt / PAUSE_ANIM_SECONDS
            self.paused_amount = min(target, self.paused_amount + step) if target > self.paused_amount \
                else max(target, self.paused_amount - step)

        if pb is None:
            self.idle_since = self.idle_since or now
            if self.blank_after and now - self.idle_since > self.blank_after:
                screen.fill((0, 0, 0))
                return False
            self.idle.draw(screen, now, wall)
        else:
            self.idle_since = None
            self.view.draw(screen, pb, now, wall, self.paused_amount)

        animating = False
        if self.fade_from is not None:
            t = (now - self.fade_start) / CROSSFADE_SECONDS
            if t >= 1:
                self.fade_from = None
            else:
                eased = 1 - (1 - t) ** 3
                self.fade_from.set_alpha(int(255 * (1 - eased)))
                screen.blit(self.fade_from, (0, 0))
                animating = True
        volume_visible = bool(pb and pb.volume_at and now - pb.volume_at < 3)
        return animating or self.paused_amount not in (0.0, 1.0) or volume_visible
