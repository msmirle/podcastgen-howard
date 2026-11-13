#!/bin/sh
set -eu
umask 0027

fail() {
    echo "podcastgen: $*" >&2
    exit 1
}

for value in "${PUID:-33}" "${PGID:-33}"; do
    case "$value" in
        ''|*[!0-9]*|0) fail "PUID and PGID must be positive, non-root numeric IDs." ;;
    esac
done

groupmod -o -g "${PGID:-33}" www-data
usermod -o -u "${PUID:-33}" -g "${PGID:-33}" www-data

mkdir -p /data/images /data/media
chown www-data:www-data /data /data/images /data/media
chmod u+rwx /data /data/images /data/media

# Application code is disposable; only these paths belong to the installation.
chown www-data:www-data /var/www/html
for directory in images media; do
    for seed in /opt/podcastgen/"$directory"/*; do
        [ -f "$seed" ] || continue
        target="/data/$directory/$(basename "$seed")"
        if [ ! -e "$target" ]; then
            cp "$seed" "$target"
            chown www-data:www-data "$target"
            chmod 0644 "$target"
        fi
    done
done

for file in config.php feed.xml categories.xml buttons.xml customtags.xml freebox-content.txt; do
    ln -sfn "/data/$file" "/var/www/html/$file"
    if [ -f "/data/$file" ]; then
        chown www-data:www-data "/data/$file"
        chmod 0640 "/data/$file"
    fi
done
case "${1:-}" in
    migrate)
        shift
        exec php /usr/local/lib/podcastgen/migrate.php "$@"
        ;;
    fix-permissions)
        echo "Repairing ownership of settings, artwork, episodes, and sidecar XML."
        chown -R www-data:www-data /data/images /data/media
        find /data/images /data/media -type d -exec chmod u+rwx {} +
        find /data/images /data/media -type f -exec chmod u+rw {} +
        exit 0
        ;;
esac

php /usr/local/lib/podcastgen/configure.php
exec docker-php-entrypoint "$@"
