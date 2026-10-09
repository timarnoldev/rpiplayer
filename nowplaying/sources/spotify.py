import hashlib
import json
import logging
import os
import threading
import time
import urllib.request
from dataclasses import replace

from ..state import Playback, Store, Track

log = logging.getLogger(__name__)

SOURCE = "spotify"
VOLUME_MAX = 65535


def fetch_cover(urls: list[str]) -> bytes | None:
    """librespot reports several sizes in no guaranteed order; keep the biggest download."""
    best = None
    for url in urls:
        try:
            with urllib.request.urlopen(url, timeout=8) as resp:
                data = resp.read()
        except OSError as exc:
            log.warning("Cover %s nicht geladen: %s", url, exc)
            continue
        if best is None or len(data) > len(best):
            best = data
    return best


class SpotifySource:
    """Follows the JSON lines written by deploy/librespot-event for every librespot event."""

    def __init__(self, store: Store, events_path: str):
        self.store = store
        self.events_path = events_path
        self.playback: Playback | None = None
        self.controller = ""
        self.cover_urls: list[str] = []
        self.replaying = True

    def start(self) -> None:
        threading.Thread(target=self._follow, name="spotify", daemon=True).start()

    def _follow(self) -> None:
        while True:
            try:
                with open(self.events_path, encoding="utf-8") as fh:
                    inode = os.fstat(fh.fileno()).st_ino
                    while True:
                        line = fh.readline()
                        if line:
                            self._handle_line(line)
                            continue
                        if self.replaying:
                            self._finish_replay()
                        time.sleep(0.2)
                        try:
                            if os.stat(self.events_path).st_ino != inode:
                                break
                        except FileNotFoundError:
                            break
            except OSError as exc:
                if not isinstance(exc, FileNotFoundError):
                    log.warning("Spotify-Ereignisse nicht lesbar: %s", exc)
                time.sleep(2)

    def _finish_replay(self) -> None:
        # Old events from before the display started: fetch only the cover that is still current.
        self.replaying = False
        pb = self.playback
        if pb and self.cover_urls and pb.track.cover is None:
            threading.Thread(target=self._load_cover, args=(pb.track, self.cover_urls), daemon=True).start()

    def _handle_line(self, line: str) -> None:
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            return
        try:
            self.handle(record["env"], record.get("t", time.time()))
        except Exception:
            log.exception("Spotify-Ereignis nicht verarbeitet: %s", line[:200])

    def handle(self, env: dict, wall_time: float) -> None:
        event = env.get("PLAYER_EVENT", "")
        monotonic_at = time.monotonic() - max(time.time() - wall_time, 0)
        pb = self.playback

        if event == "session_client_changed":
            self.controller = env.get("CLIENT_NAME", "")
            if pb:
                self._publish(pb.with_changes(controller=self.controller))
        elif event == "track_changed":
            self._track_changed(env, pb)
        elif event in ("playing", "paused", "seeked", "position_correction"):
            base = pb or Playback(source=SOURCE, track=Track(), controller=self.controller)
            playing = base.playing if event in ("seeked", "position_correction") else event == "playing"
            self._publish(base.with_changes(
                playing=playing,
                position_ms=int(env.get("POSITION_MS", "0") or 0),
                position_at=monotonic_at,
            ))
        elif event == "volume_changed" and pb:
            volume = int(env.get("VOLUME", "0") or 0) / VOLUME_MAX
            self._publish(pb.with_changes(volume=volume, volume_at=time.monotonic()))
        elif event == "shuffle_changed" and pb:
            self._publish(pb.with_changes(shuffle=env.get("SHUFFLE") == "true"))
        elif event == "repeat_changed" and pb:
            repeat = "track" if env.get("REPEAT_TRACK") == "true" else "context" if env.get("REPEAT") == "true" else ""
            self._publish(pb.with_changes(repeat=repeat))
        elif event in ("stopped", "session_disconnected"):
            self._publish(None)

    def _track_changed(self, env: dict, pb: Playback | None) -> None:
        is_episode = env.get("ITEM_TYPE") == "Episode"
        artists = tuple(a for a in env.get("ARTISTS", "").split("\n") if a)
        year = ""
        if is_episode and env.get("PUBLISH_TIME", "").isdigit():
            year = time.strftime("%d.%m.%Y", time.localtime(int(env["PUBLISH_TIME"])))
        cover_urls = [u for u in env.get("COVERS", "").split("\n") if u]
        track = Track(
            title=env.get("NAME", ""),
            artists=artists,
            album=env.get("ALBUM", ""),
            year=year,
            duration_ms=int(env.get("DURATION_MS", "0") or 0),
            number=int(env.get("NUMBER", "0") or 0),
            explicit=env.get("IS_EXPLICIT") == "true",
            is_episode=is_episode,
            show=env.get("SHOW_NAME", ""),
            cover_key=hashlib.sha1("\n".join(cover_urls).encode()).hexdigest() if cover_urls else "",
        )
        base = pb or Playback(source=SOURCE, track=track, controller=self.controller)
        self._publish(base.with_changes(track=track, position_ms=0, position_at=time.monotonic()))
        self.cover_urls = cover_urls
        if cover_urls and not self.replaying:
            threading.Thread(target=self._load_cover, args=(track, cover_urls), daemon=True).start()

    def _load_cover(self, track: Track, urls: list[str]) -> None:
        data = fetch_cover(urls)
        pb = self.playback
        if data and pb and pb.track.cover_key == track.cover_key:
            self._publish(pb.with_changes(track=replace(pb.track, cover=data)))

    def _publish(self, playback: Playback | None) -> None:
        self.playback = playback
        self.store.set(SOURCE, playback)
