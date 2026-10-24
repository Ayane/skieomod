# Existing server deployment

New stable source versions on `main` are published automatically after the
`Checks` workflow succeeds. Increase the matching versions in `pyproject.toml`
and `tools/skieo_loader.py`, add release notes to `CHANGELOG.md`, test the mod in
the game, then push. A change without a version increase does not redeploy.

The `Publish release` workflow checks the exact commit again, prepares the mod,
CLI and featured maps, builds the website, then creates `vX.Y.Z` and a GitHub
release. Assets are uploaded to a draft before the release becomes public.
Published versions and existing tags cannot be overwritten. An interrupted
draft upload can be retried with `gh workflow run release.yml --ref main`;
the same checks run before publication. UE4SS is fetched from the existing
public download and checked against its pinned SHA-256. When a new pinned build
has not reached that mirror, the workflow fetches its exact official GitHub
asset and verifies the same digest before packaging it.

The server polls the public GitHub Releases API every five minutes (up to 15
seconds of jitter), without a GitHub token or an inbound webhook. It verifies
GitHub's bundle size and SHA-256, rejects unsafe archive entries, prepares a
separate Python environment and merges the existing immutable downloads into
the candidate release using hard links. The normal publisher validates the
artifacts and retains earlier featured mapmod versions. The candidate downloads,
website and API become active together by an atomic `current` symlink switch.
The map database, account configuration and user publications remain in
`/srv/custom-map-data` and `/etc/custom-map.env`.

If the service, Nginx, website or HTTPS update feed check fails, the previous
code, downloads, service unit and Nginx configuration are restored. Failed
attempts are retried on the next timer tick. Successful releases are retained
under `/opt/custom-map/releases/github-VERSION-ASSETID` and the deployment
receipt is `/var/lib/skieomod-autopublish/last-success.json`. No Discord
announcement is sent by this workflow.

Install or update the poller once on the existing server:

```sh
sudo bash deployment/install_autopublish.sh
systemctl status skieomod-autopublish.timer
journalctl -u skieomod-autopublish.service -n 50
# Check now without deploying:
sudo python3 /opt/skieomod-autopublish/github_autopublish.py --check
# Publish an available release immediately:
sudo systemctl start skieomod-autopublish.service
# Stop automatic publication:
sudo systemctl disable --now skieomod-autopublish.timer
```

The poller is installed separately in `/opt/skieomod-autopublish`; updating its
code requires rerunning the installation command. Each deployed application has
its own `.venv` so rolling back also restores its Python dependencies.

For a new server or a manual bootstrap, use the existing Nginx + Gunicorn
installation under `/opt/custom-map`:

1. Build `repository/web` with `npm ci && npm run build`.
2. Prepare a release directory with the source, built site, `docs/` and
   existing versioned `downloads/`. Preserve `/srv/custom-map-data` and
   `/etc/custom-map.env`; they contain publications and private configuration.
3. Point both `skieomod.emillon.fr` and `skieomap.emillon.fr` DNS records at
   the server. Install Certbot's Nginx TLS options and DH parameters if this
   is a fresh server.
4. Upload the release to `/opt/custom-map/releases/RELEASE`, then run
   `sudo bash deployment/install.sh /opt/custom-map/releases/RELEASE` on the server.

`install.sh` keeps the old HTTPS virtual host active while initially obtaining
the new SAN certificate through a separate HTTP challenge host. It then migrates the
old `CUSTOM_MAP_URL` value while preserving other settings, restarts Gunicorn,
validates Nginx and checks the API. Nginx redirects HTTP and the old HTTPS
hostname's web pages to `https://skieomod.emillon.fr` with 308, preserving paths,
query strings and request methods. HTTPS `/downloads/` links on the old hostname
remain directly available because installed native helpers reject redirects.
The old hostname must remain in DNS and in the certificate renewal configuration.

Creating a DNS record alone does not activate HTTPS for a new hostname: Nginx
must serve a certificate covering that name. The certificate's saved deploy
hook validates and reloads Nginx after each successful automatic renewal.

The landing page replaces the old browser catalogue. `/publish` points to
its publishing instructions and old `/packages/…` links point to the in-game
catalogue explanation. `/account`, `/auth/`, `/api/`, `/downloads/`, `/docs/`
and `/tutorials/` remain available. CLI publication uses bearer tokens from
`/account`; the game only reads the public registry and downloads.

For local development, the API defaults to `http://localhost:8091`:

```sh
python3 repository/server/app.py
# In a second terminal:
cd repository/web
npm start
```

Set `CUSTOM_MAP_URL=https://skieomod.emillon.fr` in production. Configure
`CUSTOM_MAP_ADMIN_STEAM_IDS` explicitly; no administrator is granted by default.
