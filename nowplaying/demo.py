"""Sample playback states for designing the screens on a laptop."""
import time
from pathlib import Path

from .state import Playback, Store, Track

DEMO = Path(__file__).resolve().parents[1] / "assets" / "demo"


def _cover(name: str) -> tuple[bytes | None, str]:
    path = DEMO / f"{name}.jpg"
    return (path.read_bytes(), name) if path.exists() else (None, "")


def _track(cover: str, **fields) -> Track:
    data, key = _cover(cover)
    return Track(cover=data, cover_key=key, **fields)


def scenarios(now: float) -> dict[str, Playback | None]:
    return {
        "leerlauf": None,
        "spotify": Playback(
            source="spotify",
            track=_track("brothers", title="Money for Nothing", artists=("Dire Straits",), album="Brothers in Arms",
                         year="1985", duration_ms=506_000, number=2),
            playing=True, position_ms=192_000, position_at=now, shuffle=True,
        ),
        "airplay-pause": Playback(
            source="airplay",
            track=_track("toto-iv", title="Africa", artists=("Toto",), album="Toto IV", year="1982",
                         genre="Rock", duration_ms=295_000),
            playing=False, position_ms=121_000, position_at=now, controller="iPad",
        ),
        "bluetooth-ohne-cover": Playback(
            source="bluetooth",
            track=Track(title="Hotel California", artists=("Eagles",), album="Hotel California",
                        duration_ms=391_000),
            playing=True, position_ms=45_000, position_at=now, controller="Pixel 8", codec="AAC",
        ),
        "langer-titel": Playback(
            source="spotify",
            track=_track("cross", title="Ride Like the Wind (2019 Remaster)", artists=("Christopher Cross",),
                         album="Christopher Cross (2019 Remaster)", year="1979", duration_ms=271_000),
            playing=True, position_ms=30_000, position_at=now, repeat="context",
        ),
        "lautstaerke": Playback(
            source="airplay",
            track=_track("hotel", title="Hotel California", artists=("Eagles",), album="Hotel California",
                         year="1976", duration_ms=391_000),
            playing=True, position_ms=200_000, position_at=now, controller="MacBook",
            volume=0.62, volume_at=now,
        ),
    }


def apply(store: Store, name: str, now: float | None = None) -> None:
    now = time.monotonic() if now is None else now
    for source in ("spotify", "airplay", "bluetooth"):
        store.set(source, None)
    pb = scenarios(now)[name]
    if pb is not None:
        store.set(pb.source, pb)
