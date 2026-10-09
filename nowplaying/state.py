import threading
import time
from dataclasses import dataclass, field, replace

PAUSED_VISIBLE_SECONDS = 15 * 60


@dataclass(frozen=True)
class Track:
    title: str = ""
    artists: tuple[str, ...] = ()
    album: str = ""
    year: str = ""
    genre: str = ""
    duration_ms: int = 0
    number: int = 0
    explicit: bool = False
    is_episode: bool = False
    show: str = ""
    cover: bytes | None = field(default=None, repr=False)
    cover_key: str = ""

    @property
    def artist_line(self) -> str:
        return ", ".join(a for a in self.artists if a)

    @property
    def identity(self) -> tuple:
        return (self.title, self.artists, self.album, self.cover_key)


@dataclass(frozen=True)
class Playback:
    source: str
    track: Track
    playing: bool = False
    position_ms: int = 0
    position_at: float = 0.0
    controller: str = ""
    codec: str = ""
    volume: float | None = None
    volume_at: float = 0.0
    shuffle: bool = False
    repeat: str = ""
    updated_at: float = field(default_factory=time.monotonic)

    def position_now(self, now: float) -> int:
        pos = self.position_ms
        if self.playing and self.position_at:
            pos += int((now - self.position_at) * 1000)
        if self.track.duration_ms:
            pos = min(pos, self.track.duration_ms)
        return max(pos, 0)

    def with_changes(self, **changes) -> "Playback":
        return replace(self, updated_at=time.monotonic(), **changes)


class Store:
    """Latest playback per source; the renderer shows whichever is active."""

    def __init__(self):
        self._lock = threading.Lock()
        self._by_source: dict[str, Playback] = {}
        self.version = 0

    def set(self, source: str, playback: Playback | None) -> None:
        with self._lock:
            if playback is None:
                self._by_source.pop(source, None)
            else:
                self._by_source[source] = playback
            self.version += 1

    def get(self, source: str) -> Playback | None:
        with self._lock:
            return self._by_source.get(source)

    def active(self, now: float) -> Playback | None:
        with self._lock:
            candidates = list(self._by_source.values())
        playing = [p for p in candidates if p.playing]
        if playing:
            return max(playing, key=lambda p: p.updated_at)
        recent = [p for p in candidates if now - p.updated_at < PAUSED_VISIBLE_SECONDS]
        return max(recent, key=lambda p: p.updated_at) if recent else None
