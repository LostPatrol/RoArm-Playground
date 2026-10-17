#!/bin/sh
# Publish a static tutorial release while preserving existing Nginx routes.
set -eu

# Fixed deployment paths keep releases separate from other applications.
BASE=/var/www/roarm-tutorial
LOCATION=/etc/nginx/roarm-tutorial-location.conf
CONFIG=/etc/nginx/nginx.conf
RELEASE=${1:?Usage: install_server.sh RELEASE ARCHIVE}
ARCHIVE=${2:?Usage: install_server.sh RELEASE ARCHIVE}

case "$RELEASE" in *[!0-9-]*|'') echo 'Invalid release name' >&2; exit 1;; esac
test -f "$ARCHIVE"
command -v nginx >/dev/null
mkdir -p "$BASE/releases" "$BASE/backups"
test ! -e "$BASE/releases/$RELEASE"
mkdir "$BASE/releases/$RELEASE"
tar -xzf "$ARCHIVE" -C "$BASE/releases/$RELEASE"
test -s "$BASE/releases/$RELEASE/index.html"
chmod -R a+rX "$BASE/releases/$RELEASE"

# Record the previous state before adding the dedicated tutorial route.
cp -p "$CONFIG" "$BASE/backups/nginx-$RELEASE.conf"
if test -f "$LOCATION"; then
    cp -p "$LOCATION" "$BASE/backups/location-$RELEASE.conf"
fi
readlink "$BASE/current" > "$BASE/backups/previous-$RELEASE.txt" || true
cat > "$LOCATION" <<'NGINX'
# Standalone static teaching site; no Python service or model runtime required.
location = /tutorial { return 302 /tutorial/; }
location ^~ /tutorial/ {
    alias /var/www/roarm-tutorial/current/;
    index index.html;
    include /etc/nginx/mime.types;
    default_type application/octet-stream;
    try_files $uri $uri/ =404;
    gzip on;
    gzip_types text/css application/javascript application/json image/svg+xml;
}
NGINX
python3 - "$CONFIG" "$LOCATION" <<'PY'
"""Add the route include to the existing IP-based HTTP virtual host once."""
import pathlib
import sys

config = pathlib.Path(sys.argv[1])
include = 'include ' + sys.argv[2] + ';'
text = config.read_text()
if include not in text:
    anchor = 'server_name 47.93.249.150;'
    if text.count(anchor) != 1:
        raise SystemExit('Cannot identify the HTTP host; configuration left unchanged')
    config.write_text(text.replace(anchor, anchor + '\n        ' + include, 1))
PY
ln -sfn "$BASE/releases/$RELEASE" "$BASE/current"
if ! nginx -t; then
    cp -p "$BASE/backups/nginx-$RELEASE.conf" "$CONFIG"
    if test -f "$BASE/backups/location-$RELEASE.conf"; then
        cp -p "$BASE/backups/location-$RELEASE.conf" "$LOCATION"
    else
        rm -f "$LOCATION"
    fi
    previous=$(cat "$BASE/backups/previous-$RELEASE.txt")
    if test -n "$previous"; then
        ln -sfn "$previous" "$BASE/current"
    else
        rm -f "$BASE/current"
    fi
    echo 'Nginx validation failed; previous configuration and site restored' >&2
    exit 1
fi
if systemctl is-active --quiet nginx; then
    systemctl reload nginx
else
    systemctl start nginx
fi
systemctl enable nginx
echo "Published $RELEASE: http://47.93.249.150/tutorial/"
