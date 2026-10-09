import argparse
import fcntl
import logging
import mmap
import os
import signal
import time
from pathlib import Path

FAST_FPS = 30
SLOW_FPS = 2


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="nowplaying", description="Läuft-gerade-Anzeige für den Wohnzimmer-Lautsprecher")
    p.add_argument("--demo", action="store_true", help="Beispieldaten statt echter Quellen (Tasten 1-6, A = automatisch)")
    p.add_argument("--screenshot", metavar="DIR", help="alle Demo-Szenen als PNG speichern und beenden")
    p.add_argument("--size", default="", help="Fenstergröße, z. B. 1280x720 (Standard: Vollbild)")
    p.add_argument("--windowed", action="store_true", help="im Fenster statt Vollbild")
    p.add_argument("--librespot-events", default="/run/nowplaying/librespot.jsonl")
    p.add_argument("--airplay-pipe", default="/run/nowplaying/airplay-metadata")
    p.add_argument("--no-bluetooth", action="store_true")
    p.add_argument("--no-cover-lookup", action="store_true", help="keine Cover-Suche bei Apple, wenn die Quelle keins liefert")
    p.add_argument("--fbdev", default="", help="direkt in einen Linux-Framebuffer zeichnen, z. B. /dev/fb0")
    p.add_argument("--snapshot", default="/run/nowplaying/screen.png", help="Ziel für SIGUSR1-Bildschirmfoto")
    p.add_argument("--blank-after", type=float, default=20, help="Minuten Leerlauf bis schwarzer Bildschirm (0 = nie)")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args()


KDSETMODE = 0x4B3A
KD_TEXT, KD_GRAPHICS = 0, 1


class FramebufferOutput:
    """Writes frames straight into /dev/fbN; on the Pi this works where SDL's KMS/EGL path stays black."""

    def __init__(self, path: str):
        from .ui.kit import canvas

        sysfs = Path("/sys/class/graphics") / Path(path).name
        self.bpp = int((sysfs / "bits_per_pixel").read_text())
        w, h = (int(v) for v in (sysfs / "virtual_size").read_text().split(","))
        self.stride = int((sysfs / "stride").read_text())
        self.fd = os.open(path, os.O_RDWR)
        self.mem = mmap.mmap(self.fd, self.stride * h)
        self.canvas = canvas((w, h))
        self._grab_console(True)
        logging.info("Framebuffer %s: %dx%d, %d bit", path, w, h, self.bpp)

    def _grab_console(self, graphics: bool) -> None:
        # Stops fbcon from drawing the cursor and console text over the picture; needs tty1 as stdin.
        try:
            fcntl.ioctl(0, KDSETMODE, KD_GRAPHICS if graphics else KD_TEXT)
        except OSError as exc:
            logging.warning("Konsole nicht in Grafikmodus: %s", exc)

    def present(self) -> None:
        import pygame
        w, h = self.canvas.get_size()
        if self.bpp == 32:
            data = pygame.image.tobytes(self.canvas, "BGRA")
            row = w * 4
        else:
            rgb565 = pygame.Surface((w, h), 0, 16, (0xF800, 0x07E0, 0x001F, 0))
            rgb565.blit(self.canvas, (0, 0))
            data = rgb565.get_buffer().raw
            row = rgb565.get_pitch()
        if row == self.stride:
            self.mem[:len(data)] = data
        else:
            for y in range(h):
                self.mem[y * self.stride:y * self.stride + row] = data[y * row:(y + 1) * row]

    def close(self) -> None:
        self._grab_console(False)


class Output:
    """Renders into an opaque 24-bit canvas; the window/screen format (ARGB on macOS) never touches blending."""

    def __init__(self, args: argparse.Namespace):
        import pygame
        from .ui.kit import canvas

        size = tuple(int(v) for v in args.size.lower().split("x")) if args.size else None
        self.window = None
        if args.windowed and not args.screenshot:
            from pygame._sdl2 import video
            self.window = video.Window("Wohnzimmer", size or (1600, 900), allow_highdpi=True)
            self.renderer = video.Renderer(self.window)
            self.video = video
            self.canvas = canvas(self.renderer.get_viewport().size)
            return
        if args.screenshot:
            self.screen = pygame.display.set_mode(size or (1920, 1080))
        else:
            pygame.mouse.set_visible(False)
            info = pygame.display.Info()
            self.screen = pygame.display.set_mode(size or (info.current_w, info.current_h), pygame.FULLSCREEN)
        self.canvas = canvas(self.screen.get_size())

    def present(self) -> None:
        import pygame
        if self.window is not None:
            texture = self.video.Texture.from_surface(self.renderer, self.canvas)
            self.renderer.blit(texture)
            self.renderer.present()
        else:
            self.screen.blit(self.canvas, (0, 0))
            pygame.display.flip()

    def close(self) -> None:
        pass


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if args.screenshot or args.fbdev:
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

    import pygame

    from . import demo
    from .state import Store
    from .ui.kit import Kit
    from .ui.renderer import Renderer

    # Display and fonts only: pygame.init() would also open the sound card the players need.
    pygame.display.init()
    pygame.font.init()
    out = FramebufferOutput(args.fbdev) if args.fbdev else Output(args)
    store = Store()
    kit = Kit(*out.canvas.get_size())
    logging.info("Zeichenfläche %dx%d", *out.canvas.get_size())
    screen = out.canvas

    if args.screenshot:
        target = Path(args.screenshot)
        target.mkdir(parents=True, exist_ok=True)
        renderer = Renderer(kit, store, animate=False, blank_after=0)
        wall = time.mktime((2026, 10, 9, 20, 15, 0, 0, 0, -1))
        for name in demo.scenarios(0):
            now = time.monotonic()
            demo.apply(store, name, now)
            renderer.frame(screen, now + 0.5, wall)
            pygame.image.save(screen, str(target / f"{name}.png"))
            print(target / f"{name}.png")
        return

    if args.demo:
        names = list(demo.scenarios(0))
        current, auto, switched = 1, True, time.monotonic()
        demo.apply(store, names[current])
    else:
        from . import covers
        covers.enabled = not args.no_cover_lookup
        from .sources.airplay import AirPlaySource
        from .sources.bluetooth import BluetoothSource
        from .sources.spotify import SpotifySource
        SpotifySource(store, args.librespot_events).start()
        AirPlaySource(store, args.airplay_pipe).start()
        if not args.no_bluetooth:
            BluetoothSource(store).start()

    renderer = Renderer(kit, store, blank_after=args.blank_after * 60)
    snapshot_requested = []
    signal.signal(signal.SIGUSR1, lambda *_: snapshot_requested.append(True))
    signal.signal(signal.SIGTERM, lambda *_: (out.close(), os._exit(0)))
    clock = pygame.time.Clock()
    last_version, fast = -1, True
    next_slow = 0.0
    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT or (event.type == pygame.KEYDOWN and event.key in (pygame.K_ESCAPE, pygame.K_q)):
                return
            if args.demo and event.type == pygame.KEYDOWN:
                if event.key == pygame.K_a:
                    auto = not auto
                elif pygame.K_1 <= event.key <= pygame.K_9 and event.key - pygame.K_1 < len(names):
                    current, auto = event.key - pygame.K_1, False
                    demo.apply(store, names[current])
        now = time.monotonic()
        if args.demo and auto and now - switched > 8:
            current, switched = (current + 1) % len(names), now
            demo.apply(store, names[current])

        changed = store.version != last_version
        if fast or changed or now >= next_slow:
            last_version = store.version
            fast = renderer.frame(screen, now, time.time())
            out.present()
            next_slow = now + 1 / SLOW_FPS
            if snapshot_requested:
                snapshot_requested.clear()
                pygame.image.save(screen, args.snapshot)
                logging.info("Bildschirmfoto: %s", args.snapshot)
        clock.tick(FAST_FPS if fast else 10)


if __name__ == "__main__":
    main()
