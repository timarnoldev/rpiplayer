import logging
import threading
import time
from dataclasses import replace

from .. import covers
from ..state import Playback, Store, Track

log = logging.getLogger(__name__)

SOURCE = "bluetooth"
POLL_SECONDS = 1.0
A2DP_CODECS = {0x00: "SBC", 0x01: "MP3", 0x02: "AAC", 0x04: "ATRAC", 0xFF: "aptX/LDAC"}


class BluetoothSource:
    """Polls BlueZ over D-Bus: A2DP transport (streaming, codec) and AVRCP player (track, status)."""

    def __init__(self, store: Store):
        self.store = store
        self.last: tuple | None = None
        self.cover_key: tuple | None = None
        self.cover: bytes | None = None

    def start(self) -> bool:
        try:
            import dbus  # noqa: F401  (python3-dbus, only on the Pi)
        except ImportError:
            log.info("python3-dbus fehlt, Bluetooth-Anzeige aus")
            return False
        threading.Thread(target=self._loop, name="bluetooth", daemon=True).start()
        return True

    def _loop(self) -> None:
        import dbus
        bus = None
        while True:
            try:
                bus = bus or dbus.SystemBus()
                manager = dbus.Interface(bus.get_object("org.bluez", "/"), "org.freedesktop.DBus.ObjectManager")
                self._update(manager.GetManagedObjects())
            except Exception as exc:
                log.debug("BlueZ nicht erreichbar: %s", exc)
                bus = None
                self._publish(None)
            time.sleep(POLL_SECONDS)

    def _update(self, objects: dict) -> None:
        transport = next(
            ((path, ifaces["org.bluez.MediaTransport1"]) for path, ifaces in objects.items()
             if "org.bluez.MediaTransport1" in ifaces),
            None,
        )
        if transport is None:
            self._publish(None)
            return
        t_path, t_props = transport
        device_path = str(t_props.get("Device", ""))
        device = objects.get(device_path, {}).get("org.bluez.Device1", {})
        player = next(
            (ifaces["org.bluez.MediaPlayer1"] for path, ifaces in objects.items()
             if str(path).startswith(device_path + "/") and "org.bluez.MediaPlayer1" in ifaces),
            {},
        )
        raw_track = player.get("Track", {})
        status = str(player.get("Status", ""))
        streaming = str(t_props.get("State", "")) == "active"
        playing = status == "playing" if status else streaming
        if not streaming and status not in ("playing", "paused"):
            self._publish(None)
            return

        title = str(raw_track.get("Title", ""))
        artist = str(raw_track.get("Artist", ""))
        track = Track(
            title=title,
            artists=(artist,) if artist else (),
            album=str(raw_track.get("Album", "")),
            genre=str(raw_track.get("Genre", "")),
            duration_ms=int(raw_track.get("Duration", 0) or 0),
            number=int(raw_track.get("TrackNumber", 0) or 0),
        )
        lookup_key = (track.artist_line, track.album, track.title)
        if lookup_key != self.cover_key:
            self.cover_key, self.cover = lookup_key, None
            threading.Thread(target=self._fetch_cover, args=(lookup_key,), daemon=True).start()
        if self.cover:
            track = replace(track, cover=self.cover, cover_key=f"bt:{hash(lookup_key)}")
        volume = t_props.get("Volume")
        key = (track, playing, int(player.get("Position", 0) or 0) // 2000, volume)
        if key == self.last:
            return
        self.last = key

        now = time.monotonic()
        previous = self.store.get(SOURCE)
        volume_value = int(volume) / 127 if volume is not None else None
        volume_changed = previous is not None and volume_value is not None and previous.volume != volume_value
        codec = int(t_props.get("Codec", -1)) if "Codec" in t_props else -1
        self._publish(Playback(
            source=SOURCE,
            track=track,
            playing=playing,
            position_ms=int(player.get("Position", 0) or 0),
            position_at=now,
            controller=str(device.get("Alias", device.get("Name", ""))),
            codec=A2DP_CODECS.get(codec, ""),
            volume=volume_value,
            volume_at=now if volume_changed else (previous.volume_at if previous else 0.0),
        ))

    def _fetch_cover(self, key: tuple) -> None:
        data = covers.lookup(*key)
        if data and key == self.cover_key:
            self.cover = data
            self.last = None

    def _publish(self, playback: Playback | None) -> None:
        if playback is None:
            self.last = None
            if self.store.get(SOURCE) is None:
                return
        self.store.set(SOURCE, playback)
