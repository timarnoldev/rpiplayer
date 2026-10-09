import base64
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from nowplaying.sources.airplay import ITEM_RE, AirPlaySource, _fourcc
from nowplaying.sources.spotify import SpotifySource
from nowplaying.state import Store

ROOT = Path(__file__).resolve().parents[1]


def item(kind: str, code: str, data: bytes = b"") -> bytes:
    head = f"<item><type>{kind.encode().hex()}</type><code>{code.encode().hex()}</code><length>{len(data)}</length>"
    if data:
        return (head + '\n<data encoding="base64">\n' + base64.b64encode(data).decode() + "</data></item>\n").encode()
    return (head + "</item>\n").encode()


def test_airplay_metadata_stream():
    store = Store()
    src = AirPlaySource(store, "/nonexistent")
    stream = b"".join([
        item("ssnc", "snam", "iPhone".encode()),
        item("ssnc", "pbeg"),
        item("ssnc", "mdst"),
        item("core", "minm", "Africa".encode()),
        item("core", "asar", "Toto".encode()),
        item("core", "asal", "Toto IV".encode()),
        item("core", "asyr", (1982).to_bytes(2, "big")),
        item("ssnc", "mden"),
        item("ssnc", "PICT", b"\xff\xd8fakejpeg"),
        item("ssnc", "prgr", b"1000/442000/13010500"),
        item("ssnc", "pvol", b"-15.00,-24.0,-96.0,0.0"),
    ])
    for m in ITEM_RE.finditer(stream):
        data = base64.b64decode(m.group(4)) if m.group(4) else b""
        src.handle(_fourcc(m.group(1)), _fourcc(m.group(2)), data)
    pb = store.get("airplay")
    assert pb.track.title == "Africa" and pb.track.artists == ("Toto",) and pb.track.year == "1982"
    assert pb.controller == "iPhone" and pb.playing and pb.track.cover == b"\xff\xd8fakejpeg"
    assert abs(pb.position_ms - 10_000) < 50 and abs(pb.track.duration_ms - 295_000) < 50
    assert abs(pb.volume - 0.5) < 0.01
    src.handle("ssnc", "pfls", b"")
    assert not store.get("airplay").playing
    src.handle("ssnc", "pend", b"")
    assert store.get("airplay") is None


def test_spotify_hook_and_source():
    with tempfile.TemporaryDirectory() as tmp:
        events = os.path.join(tmp, "librespot.jsonl")
        hook = ROOT / "deploy" / "librespot-event"
        def fire(**env):
            subprocess.run([sys.executable, str(hook)], env={"NOWPLAYING_EVENTS": events, **env}, check=True)
        fire(PLAYER_EVENT="session_client_changed", CLIENT_NAME="iPhone")
        fire(PLAYER_EVENT="track_changed", ITEM_TYPE="Track", NAME="Money for Nothing", ARTISTS="Dire Straits",
             ALBUM="Brothers in Arms", DURATION_MS="506000", NUMBER="2", IS_EXPLICIT="false", COVERS="")
        fire(PLAYER_EVENT="playing", TRACK_ID="x", POSITION_MS="192000")
        fire(PLAYER_EVENT="volume_changed", VOLUME="32768")
        fire(PLAYER_EVENT="shuffle_changed", SHUFFLE="true")

        store = Store()
        src = SpotifySource(store, events)
        with open(events) as fh:
            for line in fh:
                src._handle_line(line)
        pb = store.get("spotify")
        assert pb.track.title == "Money for Nothing" and pb.track.number == 2
        assert pb.controller == "iPhone" and pb.playing and pb.shuffle
        assert pb.position_now(time.monotonic()) >= 192_000
        assert abs(pb.volume - 0.5) < 0.01
        src.handle({"PLAYER_EVENT": "paused", "POSITION_MS": "200000"}, time.time())
        assert not store.get("spotify").playing
        src.handle({"PLAYER_EVENT": "stopped"}, time.time())
        assert store.get("spotify") is None


def test_store_prefers_playing_source():
    from nowplaying.state import Playback, Track
    store = Store()
    store.set("spotify", Playback(source="spotify", track=Track(title="a"), playing=False))
    store.set("airplay", Playback(source="airplay", track=Track(title="b"), playing=True))
    assert store.active(time.monotonic()).source == "airplay"


def test_airplay_falls_back_to_cover_lookup(monkeypatch):
    from nowplaying.sources import airplay
    monkeypatch.setattr(airplay, "COVER_WAIT_SECONDS", 0)
    monkeypatch.setattr(airplay.covers, "lookup", lambda artist, album, title: b"jpeg:" + artist.encode())
    store = Store()
    src = AirPlaySource(store, "/nonexistent")
    for kind, code, data in [("ssnc", "mdst", b""), ("core", "minm", b"Africa"), ("core", "asar", b"Toto"),
                             ("core", "asal", b"Toto IV"), ("ssnc", "mden", b"")]:
        src.handle(kind, code, data)
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and not store.get("airplay").track.cover:
        time.sleep(0.01)
    assert store.get("airplay").track.cover == b"jpeg:Toto"


def test_airplay_state_survives_display_restart(tmp_path):
    pipe = str(tmp_path / "airplay-metadata")
    store = Store()
    src = AirPlaySource(store, pipe)
    for kind, code, data in [("ssnc", "snam", b"iPhone"), ("ssnc", "mdst", b""), ("core", "minm", b"Africa"),
                             ("core", "asar", b"Toto"), ("ssnc", "mden", b""), ("ssnc", "PICT", b"jpegdata"),
                             ("ssnc", "prgr", b"0/441000/13230000")]:
        src.handle(kind, code, data)

    restarted = Store()
    AirPlaySource(restarted, pipe)._restore()
    pb = restarted.get("airplay")
    assert pb.track.title == "Africa" and pb.track.cover == b"jpegdata" and pb.controller == "iPhone"
    assert pb.playing and pb.position_ms >= 10_000

    src.handle("ssnc", "pend", b"")
    gone = Store()
    AirPlaySource(gone, pipe)._restore()
    assert gone.get("airplay") is None
