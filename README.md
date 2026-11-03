# Miday

*Midday: lunchtime.* A small web app for deciding with your team where to eat:

- **Shared restaurant list.** Paste a Google Maps link and the name, rating, number of reviews, address, cuisine, phone, website, hours and photo fill themselves in. Everything can be edited.
- **Voting sessions.** Pick a few restaurants and get one link to share, on WhatsApp for example. Anyone who opens it can 👍 or 👎 each place, leave an optional comment, and add another restaurant to the vote, either from the list or as a new place via its Google Maps link. Results update live, and whoever started the vote can close it to show the winner.
- **No login.** Each browser gets an anonymous cookie, which is what "one vote per person" means. Names are optional.
- Anyone can add, edit or remove restaurants. Removing is soft: there is an **Undo** button and a "Recently removed" list.

Built with Django 5.2 LTS and SQLite. The pages are server-rendered with a little vanilla JavaScript. The look is pixel art, inspired by farming games: parchment panels in wooden frames on a grass field by day, and under a starry sky by night. It follows the device's light or dark setting, and the navbar has a Day/Night switch.

## Run it

Two ways to host it: on a machine on your network with `./run.sh` (below), or for free on [PythonAnywhere](#deploy-on-pythonanywhere-free).

```bash
./run.sh
```

On first run this:
- creates `.venv` with Python 3.10 or newer (the newest it finds) and installs `requirements.txt`;
- creates `.env` with a fresh secret key;
- migrates the database and collects static files;
- starts gunicorn on port 8000.

It prints the address colleagues should open, for example `http://192.168.1.20:8000`.

- Share links use `PUBLIC_BASE_URL`. If that's blank, `run.sh` uses this machine's LAN IP. Set it in `.env` if the IP changes or you use a host name.
- If you open the app as `localhost`, the voting page warns you and links to the shared address. Cookies are per address, so votes and the Close button only carry over on the shared one.
- If other machines can't connect, check that the firewall lets port 8000 in: `sudo nft list ruleset`.
- If this machine needs a proxy for the internet, add `HTTPS_PROXY=http://proxy:port` to `.env`. Google lookups use it.

### Keep it running

- Simplest: `tmux new -s picker ./run.sh`, then detach with Ctrl-b d.
- Or as a systemd user service that restarts on failure and starts at boot:

  ```bash
  mkdir -p ~/.config/systemd/user
  cp deploy/miday.service ~/.config/systemd/user/
  systemctl --user daemon-reload
  systemctl --user enable --now miday
  sudo loginctl enable-linger "$USER"     # run without being logged in
  journalctl --user -u miday -f
  ```

  The unit expects the project at `~/miday`; edit the paths in it if yours is elsewhere.

After changing code or `.env`, restart `run.sh` or the service. Static files are re-collected on each start.

## Using it

1. **Add restaurants.** Go to *Add restaurant*, then in Google Maps tap **Share → Copy link** and paste it. The whole share text works too. The form fills itself; check it, add team notes, and press **Save**.
   - On an existing restaurant, **Refresh from Google** updates rating, reviews, price and hours. It keeps your name and notes, and fills other details only where they are blank. Nothing is saved until you press Save.
2. **Start a vote.** Go to *Start a vote*, tick at least two restaurants, and optionally set a deadline (15 minutes to 4 hours).
3. **Share the link** with Copy or WhatsApp. Keep the **manage link**: it gives Close and Reopen on another device.
4. **Vote.** Tap 👍 or 👎, and tap again to undo. You can comment on any place, with or without a vote. A name is optional and shows next to your comments.
   - **Add a place to the vote** with *Add another restaurant to this vote*, below the cards. Pick one from the list, or paste a Google Maps link for a new place; the new place also joins the restaurant list. Everyone's page shows it within a few seconds, marked with who added it. A vote holds at most 30 restaurants, and nothing can be added once voting has closed.
5. **Close voting**, or let the deadline pass. The page shows 🏆 the winner, or a tie.
   - Ranking: 👍 minus 👎, then more 👍, then Google rating.

## Deploy on PythonAnywhere (free)

PythonAnywhere's free plan runs the app at `https://<username>.pythonanywhere.com` with HTTPS. No credit card is needed.

1. Sign up at [www.pythonanywhere.com](https://www.pythonanywhere.com/), the US site. Avoid `eu.pythonanywhere.com`: from EU servers Google answers with a cookie-consent page, which breaks the keyless lookup.
2. On PythonAnywhere, open a **Bash console** and run:

   ```bash
   git clone https://github.com/D3ShOoM/miday.git ~/miday
   cd ~/miday && bash deploy/pythonanywhere_setup.sh
   ```

   The script:
   - creates a virtualenv and installs the requirements;
   - writes `.env` with the public HTTPS address, a secret key, `DEBUG` off and WAL off;
   - sets up the database and static files;
   - prints the exact settings to enter on the Web tab.
3. On the **Web** tab, follow the printed steps:
   - add a web app with *Manual configuration*;
   - set the source code folder and the virtualenv;
   - replace the WSGI file with the printed one;
   - add the `/static/` mapping;
   - turn on *Force HTTPS*, then press **Reload**.

**Updating later:** in a Bash console run `cd ~/miday && git pull && bash deploy/pythonanywhere_setup.sh`, then press **Reload** on the Web tab. Your `.env` and database are kept.

**Without git:** `.venv/bin/python deploy/make_bundle.py` builds `dist/miday.zip` without `.env` or the database. Upload it on the **Files** tab, then run `unzip -o -q miday.zip -d ~/miday` before the setup script.

**Free-plan limits to know:**
- **Monthly renewal.** The web app stops after a month unless you press *Run until 1 month from today* on the Web tab. Old voting links keep working once it's renewed.
- **Short links.** Free accounts can only reach an allowlist of sites. Google and its APIs are on it, but the short-link hosts (`maps.app.goo.gl`, `share.google`) are not.
  - With a `GOOGLE_MAPS_API_KEY`, the app hands short links to Google's API, so they work.
  - Without a key, people get a message asking them to open the link and paste the full `google.com/maps/…` address instead.
  - You can also ask PythonAnywhere to add those hosts to the allowlist.
- **Keyless lookup.** The unofficial lookup may be blocked from PythonAnywhere's servers. If adding by link fails there, add a Google API key.
- **One web worker.** Requests are handled one at a time. That's fine for a team, but a Google lookup briefly delays everyone else's refresh. To lighten the load, raise `LIVE_REFRESH_SECONDS` in `.env`.
- **Database.** New free accounts have no MySQL or Postgres, so the app uses SQLite on PythonAnywhere's network disk.
  - WAL is turned off there (`SQLITE_WAL=0`).
  - Occasional "database is locked" errors are still possible.
  - Back up with `dumpdata` (see below) and download the file from the Files tab.

## Restaurant details from Google Maps

Supported links:
- `maps.app.goo.gl/…` (the phone app's Share button)
- `share.google/…`
- `goo.gl/maps/…`
- full `google.com/maps/place/…` links on any country domain
- `?cid=…`, `?q=place_id:…` and `query_place_id=…`
- shared text that has the link somewhere inside it

Only Google hosts are ever contacted.

Details come from the first of these that works:

1. **Official Google Places API**, if `GOOGLE_MAPS_API_KEY` is set. This is reliable.
2. **Unofficial keyless lookup**, on by default (`GMAPS_KEYLESS=1`). It reads the same data the Google Maps website loads. ⚠️ It isn't an official API: Google's terms don't allow it, and it can break whenever Google changes its site. Turn it off with `GMAPS_KEYLESS=0`.
3. **The link itself**, which gives the name and map position. You type the rest.

### Adding a Google API key (recommended)

1. In the [Google Cloud console](https://console.cloud.google.com/), create a project and attach a billing account. Google requires billing even for free usage.
2. Enable **Places API (New)**. Also enable **Maps Grounding Lite**, which turns links into places for free; without it, the app falls back to a free Text Search.
3. Create an API key under *APIs & Services → Credentials*. Restrict it to those two APIs, and to this machine's public IP if you can.
4. Under *Quotas*, cap **Place Details** requests per day, for example at 50.
5. Put `GOOGLE_MAPS_API_KEY=…` in `.env` and restart.

**Cost:**
- Finding the place from a link is free.
- Each **Fetch** or **Refresh** makes one Place Details (Enterprise) call: 1,000 free per month, then about $20 per 1,000.
- Repeat lookups of the same link are cached for 24 hours.
- `GMAPS_DAILY_DETAILS_CAP` (default 50) is a second safety limit inside the app.

Google's terms allow storing only place IDs long term. This app saves the fetched details as editable team data, which is common for small internal tools but isn't what the terms intend. Keep that in mind before running it as a public service.

To see exactly what a link produces:

```bash
.venv/bin/python manage.py gmaps_lookup "https://maps.app.goo.gl/…"            # what the app would do
.venv/bin/python manage.py gmaps_lookup --keyless "https://maps.app.goo.gl/…"  # ignore the API key
```

## Settings (`.env`)

| Name | Default | Meaning |
|---|---|---|
| `PUBLIC_BASE_URL` | LAN IP from `run.sh` | Address used in share links, e.g. `http://192.168.1.20:8000` |
| `PORT` | `8000` | Port gunicorn listens on (all interfaces) |
| `GOOGLE_MAPS_API_KEY` | empty | Enables the official Places API |
| `GMAPS_DAILY_DETAILS_CAP` | `50` | Max billable Place Details calls per day |
| `GMAPS_KEYLESS` | `1` | Unofficial keyless fallback on/off |
| `GMAPS_LANGUAGE` / `GMAPS_REGION` | `en` / `SA` | Language and region for Google results |
| `DJANGO_SECRET_KEY` | generated | Created on first run; keep it private |
| `DJANGO_ALLOWED_HOSTS` | `*` | Comma-separated host names, if you want to restrict them |
| `DATABASE_PATH` | `db.sqlite3` | SQLite file location |
| `SQLITE_WAL` | `1` | SQLite WAL mode; use `0` on network disks such as PythonAnywhere's |
| `LIVE_REFRESH_SECONDS` | `4` | How often an open voting page checks for changes |
| `TIME_ZONE` | `Asia/Riyadh` | Time zone for times shown on pages, e.g. `Europe/London` |
| `DJANGO_DEBUG` | `true` without `.env` | `run.sh` and the PythonAnywhere script turn it off; leave it off on a server |

`config/settings.py` reads `.env` itself, so `manage.py`, `run.sh` and PythonAnywhere's WSGI file all use the same settings. Variables already set in the environment take precedence. Anything else can go in `config/local_settings.py`, which is imported last and ignored by git. For example, `DATABASES` for PostgreSQL.

## Admin, backups

- `.venv/bin/python manage.py createsuperuser`, then open `/admin/`. It's for fixing data and deleting old or test votes. Only the admin site needs a password; the app itself never does.
- Back up with `.venv/bin/python manage.py dumpdata picker --indent 2 > backup-$(date +%F).json`. Restore with `loaddata`. Don't copy `db.sqlite3` while the app runs: with WAL mode on, the copy can be incomplete.

## Development

```bash
.venv/bin/python manage.py runserver 0.0.0.0:8000    # auto-reload, DEBUG on
.venv/bin/python manage.py test picker               # all tests; no network access
```

```
config/                 settings (env vars + optional local_settings.py), urls
picker/models.py        Restaurant, Voter, Poll ("voting session"), PollOption, Vote
picker/voting.py        voting rules: idempotent votes, comments, adding options, close/reopen, ranking
picker/catalog.py       turns a looked-up place into a list entry (reuse, restore or create)
picker/gmaps/           Google Maps: links.py (parse, SSRF allowlist), resolve.py (short links),
                        places_api.py (official), maps_page.py (unofficial), service.py (merge, cache)
picker/views/           restaurants.py, polls.py
picker/templates/       Django templates; the voting page refreshes [data-live] regions
static/js/picker.js     live updates (polls every 4 s, 204 when unchanged), copy, filters
static/css/miday.css    the pixel look, day and night, on top of Bootstrap 5.3
static/css/icons.css    icons and background tiles (generated, see below)
static/img/             the bear logo, favicon and home-screen icon (generated)
tools/pixel_art.py      draws icons.css and static/img/ from text grids; the bear is in tools/art/
deploy/                 systemd unit, PythonAnywhere setup script + WSGI file, bundle builder
```

### Pixel art

Every icon, the background tiles and the bear logo are text grids with one character per pixel: the icons are in `tools/pixel_art.py` and the two bears (day and night) in `tools/art/`. Edit a grid, then rebuild the files with:

```bash
python tools/pixel_art.py
```

The font is [Pixelify Sans](https://fonts.google.com/specimen/Pixelify+Sans) (SIL Open Font License), loaded from Google Fonts. Text in other scripts, such as Arabic names, uses the device's own font.

## Limits of "no login"

- Someone can vote twice by using a second browser or a private window. That's fine among colleagues; it isn't for anything that matters.
- Anyone with access can edit or remove restaurants. Removal is undoable, and `/admin/` shows everything.
- Anyone with a voting link can add restaurants to that vote, and through it to the list.
- With `run.sh` the app serves plain HTTP on the LAN; put it behind HTTPS if it leaves the internal network. PythonAnywhere provides HTTPS.

## License

[MIT](LICENSE)
