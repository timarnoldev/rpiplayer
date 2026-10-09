# rpiplayer

Raspberry Pi 3 als Lautsprecher „Wohnzimmer“: Spotify Connect (Raspotify), AirPlay (shairport-sync) und Bluetooth (BlueALSA), mit einer Läuft-gerade-Anzeige im Apple-TV-Stil auf HDMI. Das System läuft schreibgeschützt (overlayroot), der Strom kann jederzeit getrennt werden.

- `nowplaying/` – die Anzeige (Python + pygame)
- `deploy/` – Dienst, Raspotify-Hook und tmpfiles für die Anzeige
- `pi/` – alle geänderten Konfigurationsdateien vom Pi, Pfade wie im Dateisystem. Gerätespezifische Werte sind Platzhalter: `<partuuid>` (`blkid`), `<imager-id>` (vom Raspberry Pi Imager), `<adapter-mac>` (`bluetoothctl list`).
- `CLAUDE.md` – vollständige Dokumentation des Setups: Bootkette, Einrichtung, Schreibschutz, bekannte Probleme

## Anzeige lokal ausprobieren

```bash
python3 -m venv .venv && .venv/bin/pip install pygame==2.6.1 pytest
.venv/bin/python -m nowplaying --demo --windowed --size 1600x900
```

Tasten im Demo-Modus: `1`–`6` Szene wählen, `A` automatisch durchschalten, `Q` beenden. Die Demo braucht Beispiel-Cover in `assets/demo/` (`brothers.jpg`, `toto-iv.jpg`, `hotel.jpg`, `cross.jpg`), die nicht eingecheckt sind; ohne sie erscheinen Platzhalter.

```bash
.venv/bin/python -m nowplaying --screenshot shots/   # alle Szenen als PNG in 1920x1080
.venv/bin/python -m pytest -q tests                   # Datenquellen mit simulierten Ereignissen
```

## Auf dem Pi

Die Anzeige liegt unter `/opt/nowplaying` und läuft als `nowplaying.service`. Sie zeichnet direkt in `/dev/fb0` (32 Bit über `video=HDMI-A-1:1920x1080-32@60` in `cmdline.txt`) und übernimmt tty1.

Aktualisieren bei aktivem Schreibschutz:

```bash
rsync -a --exclude .venv --exclude .git --exclude tests ./ spotify@spotify-connect-1.local:/tmp/nowplaying/
ssh spotify@spotify-connect-1.local '
  sudo mount -o remount,rw /media/root-ro
  sudo rsync -a --delete --inplace --chown=root:root /tmp/nowplaying/ /media/root-ro/opt/nowplaying/
  sync; echo 2 | sudo tee /proc/sys/vm/drop_caches; sudo mount -o remount,ro /media/root-ro
  sudo rsync -a --delete --chown=root:root /tmp/nowplaying/ /opt/nowplaying/
  sudo systemctl restart nowplaying'
```

Bildschirmfoto vom echten HDMI-Bild: `sudo systemctl kill -s USR1 nowplaying`, dann `/run/nowplaying/screen.png`.

## Datenquellen

| Quelle | Woher | Was |
| --- | --- | --- |
| Spotify | `deploy/librespot-event` als `LIBRESPOT_ONEVENT`, JSON-Zeilen in `/run/nowplaying/librespot.jsonl` | Titel, Interpreten, Album, Cover, Dauer, Position, Titelnummer, Explicit, Podcast, Lautstärke, Zufall/Wiederholen. Keinen Gerätenamen (librespot 0.8 meldet ihn leer). |
| AirPlay | Metadaten-Pipe von shairport-sync, letzter Stand in `/run/nowplaying/airplay-state.json` | Titel, Interpret, Album, Jahr, Genre, Cover, Fortschritt, Lautstärke, sendendes Gerät |
| Bluetooth | BlueZ über D-Bus (`python3-dbus`) | Titel, Interpret, Album, Dauer, Position, Gerätename, Codec |

Fehlt ein Cover (Bluetooth, manche AirPlay-Apps), sucht die Anzeige es über die öffentliche iTunes-Suche anhand von Interpret und Album; abschaltbar mit `--no-cover-lookup`.

## Nicht im Repo

Netzadressen, Bluetooth-Kopplungsschlüssel (`/var/lib/bluetooth`), SSH-Schlüssel, Spotify-Zugangsdaten, Passwörter und Album-Cover.

Schriften: Inter (SIL OFL, `assets/fonts/OFL.txt`). Icons: Lucide (ISC, `assets/icons/LICENSE.txt`).
