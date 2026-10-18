#!/bin/bash
# Run as root on the specified Debian server after uploading a release.
set -euo pipefail
release_dir=${1:?Usage: install.sh /opt/custom-map/releases/RELEASE}
case "$release_dir" in /opt/custom-map/releases/*) ;; *) echo 'Release must be inside /opt/custom-map/releases' >&2; exit 2;; esac
if [ ! -d "$release_dir/repository/web/dist/browser" ]; then echo 'Angular build is missing' >&2; exit 2; fi
if ! id custom-map >/dev/null 2>&1; then useradd --system --home-dir /nonexistent --shell /usr/sbin/nologin custom-map; fi
mkdir -p /var/lib/custom-map /srv/custom-map-data /opt/custom-map /var/www/custom-map-acme
if [ ! -e /var/lib/custom-map/storage.img ]; then
    fallocate -l 40000000000 /var/lib/custom-map/storage.img
    chmod 0600 /var/lib/custom-map/storage.img
    mkfs.ext4 -q -m 0 /var/lib/custom-map/storage.img
fi
if ! rg -q '^/var/lib/custom-map/storage.img ' /etc/fstab 2>/dev/null && ! grep -q '^/var/lib/custom-map/storage.img ' /etc/fstab; then
    printf '\n/var/lib/custom-map/storage.img /srv/custom-map-data ext4 loop,nosuid,nodev,noexec,nofail 0 0\n' >> /etc/fstab
fi
systemctl daemon-reload
mountpoint -q /srv/custom-map-data || mount /srv/custom-map-data
chown custom-map:custom-map /srv/custom-map-data
mkdir -p /srv/custom-map-data/nginx-body /srv/custom-map-data/logs
chown www-data:custom-map /srv/custom-map-data/nginx-body /srv/custom-map-data/logs
chmod 0750 /srv/custom-map-data/nginx-body /srv/custom-map-data/logs
if [ ! -x /opt/custom-map/venv/bin/pip ]; then
    if ! python3 -m ensurepip --version >/dev/null 2>&1; then
        apt-get update -qq
        apt-get install -y --no-install-recommends python3-venv
    fi
    python3 -m venv /opt/custom-map/venv
fi
/opt/custom-map/venv/bin/pip install -r "$release_dir/repository/server/requirements.txt"
if [ ! -f /etc/custom-map.env ]; then
    cat > /etc/custom-map.env <<'ENV'
CUSTOM_MAP_URL=https://skieomod.emillon.fr
CUSTOM_MAP_DATA=/srv/custom-map-data
CUSTOM_MAP_STORAGE_BYTES=40000000000
CUSTOM_MAP_OWNER_BYTES=2147483648
CUSTOM_MAP_ADMIN_STEAM_IDS=
ENV
    chmod 0640 /etc/custom-map.env
    chown root:custom-map /etc/custom-map.env
fi
# Migrate the public origin while retaining storage, administrators and secrets.
sed -i 's|^CUSTOM_MAP_URL=https://skieomap.emillon.fr/*$|CUSTOM_MAP_URL=https://skieomod.emillon.fr|' /etc/custom-map.env
ln -sfn "$release_dir" /opt/custom-map/current
install -m 0644 "$release_dir/deployment/custom-map.service" /etc/systemd/system/custom-map.service
install -m 0644 "$release_dir/deployment/logrotate.conf" /etc/logrotate.d/custom-map
systemctl daemon-reload
systemctl enable --now custom-map.service
systemctl restart custom-map.service
if [ ! -f /etc/letsencrypt/live/skieomod.emillon.fr/fullchain.pem ]; then
    cat > /etc/nginx/sites-available/custom-map <<'HTTP'
server {
  listen 80;
  listen [::]:80;
  server_name skieomod.emillon.fr skieomap.emillon.fr;
  location /.well-known/acme-challenge/ { root /var/www/custom-map-acme; }
  location / { return 503; }
}
HTTP
    ln -sfn /etc/nginx/sites-available/custom-map /etc/nginx/sites-enabled/custom-map
    nginx -t
    systemctl reload nginx
fi
# Cover the canonical host and the redirect alias with a single SAN certificate.
certbot certonly --webroot -w /var/www/custom-map-acme --cert-name skieomod.emillon.fr -d skieomod.emillon.fr -d skieomap.emillon.fr --keep-until-expiring --expand --non-interactive --agree-tos --register-unsafely-without-email
install -m 0644 "$release_dir/deployment/nginx.conf" /etc/nginx/sites-available/custom-map
ln -sfn /etc/nginx/sites-available/custom-map /etc/nginx/sites-enabled/custom-map
nginx -t
systemctl reload nginx
curl --fail --silent --show-error --retry 3 --retry-all-errors --retry-delay 1 https://skieomod.emillon.fr/api/v1/health
