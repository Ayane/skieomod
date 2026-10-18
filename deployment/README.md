# Existing server deployment

The public source repository does not deploy the production server on push.
The existing Nginx + Gunicorn installation remains under `/opt/custom-map`;
release preparation is separate from deployment.

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
