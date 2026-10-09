# spotify-connect-1: Spotify-Connect-Lautsprecher „Wohnzimmer“

Raspberry Pi 3 Model B (V1.2) als Lautsprecher „Wohnzimmer“: Spotify Connect (Raspotify), AirPlay (shairport-sync) und Bluetooth (BlueALSA), mit Läuft-gerade-Anzeige auf HDMI. Das System ist schreibgeschützt (overlayroot), damit man den Strom jederzeit ohne Schaden trennen kann.

Eingerichtet am 2026-10-09.

## Überblick

| Was | Wert |
| --- | --- |
| Hardware | Raspberry Pi 3 Model B V1.2, 1 GB RAM |
| System | Raspberry Pi OS Lite 64-bit (Debian 13 „trixie“), Image `2026-10-06-raspios-trixie-arm64-lite` |
| Hostname | `spotify-connect-1` (`spotify-connect-1.local`) |
| Benutzer | `spotify` (sudo ohne Passwort; Passwort steht bewusst nicht hier) |
| Netz | LAN, DHCP |
| Spotify-Name | `Wohnzimmer` |
| Audio | 3,5-mm-Klinke (`plughw:CARD=Headphones,DEV=0`), 320 kbit/s |
| Root-Dateisystem | USB-Stick 15,7 GB, `/dev/sda2` (ext4), Boot `/dev/sda1` (FAT) |

## Bootkette (wichtig)

Der Pi 3 B kann ab Werk nicht von USB booten (OTP-Bit nicht gesetzt). Deshalb:

1. **microSD-Karte (2 GB) bleibt dauerhaft im Pi.** Sie hat nur eine 32-MB-FAT16-Partition `PIBOOT` mit genau einer Datei: `bootcode.bin` (aktuelle Version aus `raspberrypi/firmware`, `boot/bootcode.bin`).
2. Diese `bootcode.bin` findet auf der Karte kein `start.elf` und lädt alles Weitere vom **USB-Stick**.
3. Auf dem Stick: Firmware → Kernel + `initramfs8` → overlayroot → System.

Ohne SD-Karte blinkt die grüne LED gleichmäßig im Sekundentakt und nichts passiert. Keine weiteren Dateien (`start.elf`, `config.txt`) auf die Karte legen, sonst bootet sie nicht mehr an den Stick weiter.

## Raspotify

- Installiert per `curl -sSL https://dtcooper.github.io/raspotify/install.sh | sh` (APT-Repo `dtcooper.github.io/raspotify`, Paket `raspotify`, librespot 0.8.0).
- Konfiguration: `/etc/raspotify/conf`, Original unter `/etc/raspotify/conf.orig`. Geändert wurden nur:
  ```
  LIBRESPOT_NAME="Wohnzimmer"
  LIBRESPOT_DEVICE=plughw:CARD=Headphones,DEV=0
  LIBRESPOT_BITRATE=320
  LIBRESPOT_INITIAL_VOLUME=100
  LIBRESPOT_VOLUME_RANGE=30
  LIBRESPOT_ENABLE_VOLUME_NORMALISATION=
  LIBRESPOT_NORMALISATION_METHOD=dynamic
  LIBRESPOT_NORMALISATION_PREGAIN=9        # Maximum, war mit 6 noch zu leise
  LIBRESPOT_NORMALISATION_THRESHOLD=-4.0   # Limiter früher, weil ALSA +4 dB draufgibt
  ```
- Hardware-Pegel Klinke: ALSA `PCM` auf +4 dB (Maximum), gespeichert in `/var/lib/alsa/asound.state` (wird beim Boot von alsa-restore geladen). Zusammen mit Limiter -4 dBFS landen Spitzen bei 0 dBFS. Lauter geht nur mit USB-DAC oder Verstärker.
- Dienst: `systemctl status raspotify`, Logs: `journalctl -u raspotify -b`.
- Braucht Spotify Premium auf dem steuernden Konto.

## AirPlay (shairport-sync)

- Paket `shairport-sync` 4.3.7 aus Debian: **AirPlay 1** (kein AirPlay 2, kein Multiroom, nicht in der Home-App). Für iPhone/iPad/Mac → ein Lautsprecher reicht das.
- Konfiguration `/etc/shairport-sync.conf` (Original: `.orig`): Name `Wohnzimmer`, Ausgabe `boost`.
- `boost` ist ein ALSA-Gerät aus `/etc/asound.conf`: LADSPA `fastLookaheadLimiter` (Paket `swh-plugins`) mit +9 dB Eingangsverstärkung, Limit −4 dBFS, Release 0,05 s, dann `plughw:CARD=Headphones,DEV=0`. Entspricht dem Boost in Raspotify. Bluetooth läuft (noch) ohne Boost.
- Funktioniert mit jedem Spotify-Konto (die offizielle App spielt, der Pi empfängt nur). Das Handy bleibt Zuspieler.

## Bluetooth (BlueALSA)

- Pakete `bluez-alsa-utils`, `bluez-tools`. Der Pi ist A2DP-Empfänger („Bluetooth-Box“).
- `bluealsa` per Override nur `-p a2dp-sink`, `bluealsa-aplay` gibt auf `plughw:CARD=Headphones,DEV=0` aus (`/etc/systemd/system/bluealsa*.service.d/override.conf`).
- `/etc/bluetooth/main.conf` (Original: `.orig`): `Name = Wohnzimmer`, `Class = 0x200414`, dauerhaft sichtbar und koppelbar (`DiscoverableTimeout = 0`, `PairableTimeout = 0`, `AlwaysPairable = true`, `JustWorksRepairing = always`). Alias zusätzlich per `bluetoothctl system-alias Wohnzimmer`, sonst nimmt BlueZ den Hostnamen.
- `bt-agent.service` (eigene Unit): `bt-agent -c NoInputNoOutput`, koppelt **ohne PIN**. Jeder in Funkreichweite kann koppeln und abspielen.
- Kopplungen überleben das Overlay: `bt-persist.path` beobachtet `/var/lib/bluetooth/<Adapter-MAC>` (MAC per `bluetoothctl list`, in der Unit eintragen), bei neuer Kopplung schreibt `/usr/local/sbin/bt-persist` das Verzeichnis (ohne `cache`) per rsync auf `/media/root-ro` (kurz rw, dann drop_caches und wieder ro).
- Alle drei Dienste (Raspotify, AirPlay, Bluetooth) greifen gleichzeitig auf die Klinke zu; der bcm2835 hat 8 Hardware-Subdevices, das geht ohne dmix.

## Anzeige auf HDMI (nowplaying)

- Eigene Läuft-gerade-Anzeige im Apple-TV-Stil (Python + pygame), Quellcode und alle Konfigurationen im Repo `github.com/timarnoldev/rpiplayer`, auf dem Pi unter `/opt/nowplaying`. Schrift Inter, Icons Lucide.
- Leerlauf: Uhr, Datum, Anleitungen für Spotify/AirPlay/Bluetooth; nach 20 min Leerlauf schwarz. Beim Abspielen: Cover, unscharfer Cover-Hintergrund, Titel, Interpret, Album, Fortschritt, Quelle, Lautstärke-Einblendung.
- Dienst `nowplaying.service` (User `spotify`), zeichnet **direkt in `/dev/fb0`** (`--fbdev /dev/fb0`). Der SDL-KMS/EGL-Weg blieb auf dem Pi 3 schwarz. Der Dienst übernimmt tty1 und schaltet es in den Grafikmodus (`KDSETMODE`), `getty@tty1` ist deaktiviert.
- `cmdline.txt` hat `video=HDMI-A-1:1920x1080-32@60 vt.global_cursor_default=0` (Original: `cmdline.txt.orig`), sonst läuft fb0 mit 16 Bit und Verläufe bekommen Stufen.
- Daten: `/run/nowplaying/` (tmpfs, `/etc/tmpfiles.d/nowplaying.conf`, 1777).
  - Spotify: `LIBRESPOT_ONEVENT=/usr/local/bin/librespot-event` schreibt JSON-Zeilen nach `librespot.jsonl` (chmod 644, weil raspotify mit UMask 0077 als root läuft). Drop-in `raspotify.service.d/nowplaying.conf`: `ReadWritePaths=/run/nowplaying`.
  - AirPlay: `metadata`-Block in `/etc/shairport-sync.conf`, Pipe `airplay-metadata`.
  - Bluetooth: BlueZ über D-Bus (`python3-dbus`).
- Cover: Spotify liefert Cover-Links. AirPlay schickt je nach App ein Bild (`PICT`, im Log `AirPlay-Cover von der Quelle`) oder keins, Bluetooth nie. Fehlt es, sucht die Anzeige nach 3 s per öffentlicher iTunes-Suche (Interpret + Album bzw. Titel, ohne Anmeldung); abschaltbar mit `--no-cover-lookup`.
- Gerätename: Kommt bei AirPlay (`snam`) und Bluetooth (Alias). librespot 0.8 meldet bei Spotify keinen (`session_client_changed` mit leerem `CLIENT_NAME`, `set_client_name` wird nie aufgerufen).
- Bildschirmfoto vom echten Bild: `sudo systemctl kill -s USR1 nowplaying` → `/run/nowplaying/screen.png`.
- Pakete: `python3-pygame python3-dbus libegl1 libegl-mesa0 libgles2 libgl1-mesa-dri` (EGL wird beim fbdev-Weg nicht gebraucht, stört aber nicht).
- Last: Leerlauf ca. 150 MB RAM, CPU gering (Neuzeichnen 2x pro Sekunde, Animationen 30 fps).

## Schutz vor Stromtrennung

- `raspi-config nonint do_overlayfs 0` aktiviert:
  - `overlayroot=tmpfs` in `/boot/firmware/cmdline.txt`: `/` ist ein Overlay, der Stick liegt read-only unter `/media/root-ro`, alle Änderungen landen im RAM (`/media/root-rw`) und sind nach einem Neustart weg.
  - `/boot/firmware` ist in `/etc/fstab` mit `ro` gemountet.
- Swap ist `zram` (im RAM), schreibt also nicht auf den Stick.
- Prüfen: `findmnt /` zeigt `overlayroot overlay`, `findmnt /media/root-ro` zeigt `/dev/sda2 ro`.

## Änderungen dauerhaft machen

Variante A, für Updates und größere Änderungen:
```bash
sudo raspi-config nonint do_overlayfs 1   # Overlay aus
sudo reboot
# ändern, z. B. sudo apt update && sudo apt full-upgrade
sudo raspi-config nonint do_overlayfs 0   # Overlay wieder an (setzt auch /boot wieder ro)
sudo reboot
```

Variante B, für einzelne Dateien ohne Neustart (so wurde diese Datei angelegt):
```bash
sudo mount -o remount,rw /media/root-ro
sudo nano /media/root-ro/etc/raspotify/conf   # Pfad unter /media/root-ro!
sync && sudo mount -o remount,ro /media/root-ro
sudo systemctl restart raspotify             # oder reboot, damit das Overlay die Datei sicher sieht
```

## Hinweise

- Der USB-Stick ist beim Schreiben sehr langsam (Paket-Installationen dauern Minuten). Im Betrieb egal, weil nicht geschrieben wird.
- Der Stick ist ein No-Name-Stick (`lsusb`: `ffff:5678 USB Disk 2.0`) und ist am 2026-10-09 zweimal im Betrieb weggebrochen (danach fehlten `ls`/`sudo`, SSH brach mit `Connection reset by peer` ab). Einmal davon mitten in `apt-get install` mit Overlay aus: `libconfig11` war danach kaputt (`dpkg --audit`), repariert per `dpkg --configure -a` und `apt-get --reinstall install libconfig11`. Unterspannung war nach dem Neustart nicht nachweisbar (`vcgencmd get_throttled` = `0x0`). Bei Wiederholung: Stick gegen microSD-Karte (ab 8 GB) tauschen. Installationen nur mit Overlay aus und mit `--no-install-recommends`.
- Grüne LED blinkt 4-mal im Takt: `bootcode.bin` von der SD-Karte läuft, kann aber `start.elf` vom Stick nicht laden (Stick nicht erkannt). Die Boot-Dateien waren dabei unbeschädigt; Stick neu einstecken bzw. anderer USB-Port half.
- WLAN wäre möglich, der Pi 3 B kann aber nur 2,4 GHz.
- Grüne LED: unregelmäßiges Flackern = bootet / liest. Gleichmäßiges Blinken im Sekundentakt = findet nichts Bootbares (SD-Karte fehlt oder Stick nicht erkannt; anderen USB-Port probieren).
- Zugang per SSH-Schlüssel in `/home/spotify/.ssh/authorized_keys` (bei Overlay aus oder per Variante B eintragen).
- SSH sperrt nach mehreren abgebrochenen/fehlgeschlagenen Verbindungen die Absender-IP für bis zu 10 Minuten (`Connection reset by peer` direkt nach dem Verbindungsaufbau). Abhilfe: warten oder Strom kurz trennen.
- Neuere Spotify-Konten bekommen von librespot teils keinen Audio-Schlüssel (`error audio key 0 1`, alle Titel werden übersprungen), siehe librespot-Issue #1649. Mit einem älteren Konto funktioniert es.
- Das im Imager gesetzte Passwort von `spotify` bei Bedarf ändern (bei Overlay aus oder per Variante B mit `chroot`).
