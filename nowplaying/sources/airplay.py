import base64
import hashlib
import json
import logging
import os
import re
import threading
import time
from dataclasses import replace

from .. import covers
from ..state import Playback, Store, Track

log = logging.getLogger(__name__)

SOURCE = "airplay"
SAMPLE_RATE = 44100
COVER_WAIT_SECONDS = 3
STALE_AFTER_END_MS = 10_000

ITEM_RE = re.compile(
    rb"<item><type>([0-9a-f]{8})</type><code>([0-9a-f]{8})</code><length>(\d+)</length>"
    rb"(?:\s*<data encoding=\"base64\">\s*(.*?)</data>)?\s*</item>",
    re.S,
)


def _fourcc(hex_text: bytes) -> str:
    return bytes.fromhex(hex_text.decode()).decode("latin-1")


def _int(data: bytes) -> int:
    return int.from_bytes(data, "big") if data else 0


class AirPlaySource:
    """Reads shairport-sync's metadata pipe (metadata.enabled, include_cover_art)."""

    def __init__(self, store: Store, pipe_path: str):
        self.store = store
        self.pipe_path = pipe_path
        self.playback: Playback | None = None
        self.pending: dict[str, object] = {}
        self.controller = ""
        state_dir = os.path.dirname(pipe_path) or "."
        self.state_path = os.path.join(state_dir, "airplay-state.json")
        self.cover_path = os.path.join(state_dir, "airplay-cover")

    def start(self) -> None:
        self._restore()
        threading.Thread(target=self._read_loop, name="airplay", daemon=True).start()

    def _restore(self) -> None:
        """shairport-sync sends metadata only on track change, so a restarted display would stay blank."""
        try:
            with open(self.state_path, encoding="utf-8") as fh:
                saved = json.load(fh)
        except (OSError, ValueError):
            return
        cover = None
        if saved["track"].get("cover_key"):
            try:
                with open(self.cover_path, "rb") as fh:
                    cover = fh.read()
            except OSError:
                saved["track"]["cover_key"] = ""
        track = Track(**{**saved["track"], "artists": tuple(saved["track"]["artists"]), "cover": cover})
        now = time.monotonic()
        pb = Playback(
            source=SOURCE, track=track, playing=saved["playing"], position_ms=saved["position_ms"],
            position_at=now - max(time.time() - saved["saved_at"], 0) if saved["playing"] else now,
            controller=saved["controller"],
        )
        elapsed_ms = (time.time() - saved["saved_at"]) * 1000
        if saved["playing"] and track.duration_ms and saved["position_ms"] + elapsed_ms > track.duration_ms + STALE_AFTER_END_MS:
            return
        self.controller = pb.controller
        self.playback = pb
        self.store.set(SOURCE, pb)

    def _save(self, pb: Playback | None) -> None:
        try:
            if pb is None:
                for path in (self.state_path, self.cover_path):
                    if os.path.exists(path):
                        os.remove(path)
                return
            t = pb.track
            state = {
                "track": {"title": t.title, "artists": list(t.artists), "album": t.album, "year": t.year,
                          "genre": t.genre, "duration_ms": t.duration_ms, "number": t.number, "cover_key": t.cover_key},
                "playing": pb.playing,
                "position_ms": pb.position_now(time.monotonic()),
                "saved_at": time.time(),
                "controller": pb.controller,
            }
            if t.cover and t.cover_key != getattr(self, "_saved_cover_key", None):
                with open(self.cover_path + ".tmp", "wb") as fh:
                    fh.write(t.cover)
                os.replace(self.cover_path + ".tmp", self.cover_path)
                self._saved_cover_key = t.cover_key
            with open(self.state_path + ".tmp", "w", encoding="utf-8") as fh:
                json.dump(state, fh, ensure_ascii=False)
            os.replace(self.state_path + ".tmp", self.state_path)
        except OSError as exc:
            log.debug("AirPlay-Stand nicht gespeichert: %s", exc)

    def _read_loop(self) -> None:
        while True:
            if not os.path.exists(self.pipe_path):
                time.sleep(2)
                continue
            try:
                with open(self.pipe_path, "rb", buffering=0) as fh:
                    buf = b""
                    while chunk := fh.read(65536):
                        buf += chunk
                        last_end = 0
                        for m in ITEM_RE.finditer(buf):
                            last_end = m.end()
                            data = base64.b64decode(m.group(4)) if m.group(4) else b""
                            try:
                                self.handle(_fourcc(m.group(1)), _fourcc(m.group(2)), data)
                            except Exception:
                                log.exception("AirPlay-Metadaten nicht verarbeitet")
                        buf = buf[last_end:]
                        if len(buf) > 8 * 1024 * 1024:
                            buf = b""
            except OSError as exc:
                log.warning("AirPlay-Pipe: %s", exc)
                time.sleep(2)

    def handle(self, kind: str, code: str, data: bytes) -> None:
        pb = self.playback
        if kind == "core":
            self._core(code, data)
            return
        if kind != "ssnc":
            return
        now = time.monotonic()
        if code == "snam":
            self.controller = data.decode("utf-8", "replace")
            if pb:
                self._publish(pb.with_changes(controller=self.controller))
        elif code == "mdst":
            self.pending = {}
        elif code == "mden":
            self._apply_pending()
        elif code == "PICT":
            self._set_cover(data, from_source=True)
        elif code == "prgr":
            start, current, end = (int(x) for x in data.decode().split("/"))
            base = pb or self._empty()
            track = replace(base.track, duration_ms=int((end - start) / SAMPLE_RATE * 1000))
            self._publish(base.with_changes(
                track=track,
                position_ms=int((current - start) / SAMPLE_RATE * 1000),
                position_at=now,
                playing=True,
            ))
        elif code in ("pbeg", "prsm"):
            base = pb or self._empty()
            self._publish(base.with_changes(playing=True, position_ms=base.position_now(now), position_at=now))
        elif code == "pfls" and pb:
            self._publish(pb.with_changes(playing=False, position_ms=pb.position_now(now), position_at=now))
        elif code == "pend":
            self._publish(None)
        elif code == "pvol":
            airplay_volume = float(data.decode().split(",")[0])
            volume = 0.0 if airplay_volume <= -30 else (airplay_volume + 30) / 30
            if pb:
                self._publish(pb.with_changes(volume=volume, volume_at=now))

    def _core(self, code: str, data: bytes) -> None:
        text = lambda: data.decode("utf-8", "replace")  # noqa: E731
        if code == "minm":
            self.pending["title"] = text()
        elif code == "asar":
            self.pending["artists"] = (text(),)
        elif code == "asal":
            self.pending["album"] = text()
        elif code == "asgn":
            self.pending["genre"] = text()
        elif code == "asyr":
            self.pending["year"] = str(_int(data)) if _int(data) else ""
        elif code == "astm":
            self.pending["duration_ms"] = _int(data)
        elif code == "astn":
            self.pending["number"] = _int(data)

    def _apply_pending(self) -> None:
        if not self.pending:
            return
        base = self.playback or self._empty()
        fields = dict(self.pending)
        same_track = (fields.get("title"), fields.get("album")) == (base.track.title, base.track.album)
        track = replace(base.track if same_track else Track(), **fields)
        if not track.duration_ms and base.track.duration_ms and same_track:
            track = replace(track, duration_ms=base.track.duration_ms)
        self.pending = {}
        self._publish(base.with_changes(track=track))
        if not same_track:
            log.info("AirPlay: %s / %s / %s", track.artist_line, track.album, track.title)
            threading.Thread(target=self._fallback_cover, args=(track.identity,), daemon=True).start()

    def _fallback_cover(self, identity: tuple) -> None:
        time.sleep(COVER_WAIT_SECONDS)
        pb = self.playback
        if not pb or pb.track.identity != identity or pb.track.cover:
            return
        data = covers.lookup(pb.track.artist_line, pb.track.album, pb.track.title)
        pb = self.playback
        if data and pb and pb.track.identity == identity and not pb.track.cover:
            self._set_cover(data)

    def _set_cover(self, data: bytes, from_source: bool = False) -> None:
        if from_source:
            log.info("AirPlay-Cover von der Quelle: %d Bytes", len(data))
            if not data:
                return
        base = self.playback or self._empty()
        key = hashlib.sha1(data).hexdigest() if data else ""
        self._publish(base.with_changes(track=replace(base.track, cover=data or None, cover_key=key)))

    def _empty(self) -> Playback:
        return Playback(source=SOURCE, track=Track(), controller=self.controller)

    def _publish(self, playback: Playback | None) -> None:
        self.playback = playback
        self.store.set(SOURCE, playback)
        self._save(playback)
