import json
import logging
import threading
import urllib.parse
import urllib.request

log = logging.getLogger(__name__)

enabled = True
_lock = threading.Lock()
_cache: dict[tuple[str, str, str], bytes | None] = {}
_NETWORK_ERROR = object()


def _lookup(artist: str, album: str, title: str) -> bytes | None:
    entity = "album" if album else "song"
    term = f"{artist} {album or title}".strip()
    query = urllib.parse.urlencode({"term": term, "entity": entity, "limit": 1, "country": "DE"})
    try:
        with urllib.request.urlopen(f"https://itunes.apple.com/search?{query}", timeout=6) as resp:
            results = json.load(resp).get("results", [])
        if not results:
            log.info("Kein Cover gefunden für %s", term)
            return None
        art = results[0].get("artworkUrl100", "").replace("100x100bb", "600x600bb")
        with urllib.request.urlopen(art, timeout=8) as resp:
            return resp.read()
    except (OSError, ValueError) as exc:
        log.warning("Cover-Suche für %s fehlgeschlagen: %s", term, exc)
        return _NETWORK_ERROR


def lookup(artist: str, album: str, title: str) -> bytes | None:
    """Fallback cover from the public iTunes Search API when a source sends none (Bluetooth, many AirPlay apps)."""
    if not enabled or not artist or not (album or title):
        return None
    key = (artist.strip(), album.strip(), title.strip())
    with _lock:
        if key not in _cache:
            result = _lookup(*key)
            if result is _NETWORK_ERROR:
                return None
            _cache[key] = result
            while len(_cache) > 128:
                _cache.pop(next(iter(_cache)))
        return _cache[key]
