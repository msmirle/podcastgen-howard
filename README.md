# podcastgen-howard

Prebuilt **PodcastGenerator 3.2.9** for Linux x86-64:

```text
ghcr.io/msmirle/podcastgen-howard:3.2.9
```

The server needs Docker Engine and the Compose plugin, not Make, PHP, Git, or unzip.
Images are built and tested in GitHub Actions before publishing to GHCR. A weekly
rebuild picks up PHP/Debian fixes; pulling/recreating the container applies them.

> **Maintenance warning:** [PodcastGenerator is archived](https://github.com/PodcastGenerator/PodcastGenerator).
> Container rebuilds do not fix vulnerabilities in the application or its bundled
> dependencies. Do not treat this as a maintained or hardened internet-facing CMS.
> HTTP also sends admin credentials without encryption. Prefer HTTPS or a
> VPN/restricted management network; existing HTTP feed subscribers can retain their
> URL only while that endpoint remains reachable. Disable external access during
> setup and migration. No reverse proxy or TLS termination is included here.

## Deployment layout

The Linux server needs only:

```text
~/docker/podcastgen-howard/
    compose.yaml
    .env
    data/
```

The image is built on GitHub, not on the server. Build files, tests, and a Git
checkout are not needed in the deployment directory. The repository still
contains those files for development and CI.

The Compose project is `podcastgen-howard`, with service `app`, container
`podcastgen-howard-app-1`, and network `podcastgen-howard_default`. A separate
rehearsal can override the project name using `docker compose -p <test-name>`.
These names do not change the application's public URL or external media path.

## What survives container replacement?

| Host location | Container location | Contents |
| --- | --- | --- |
| `./data` | `/data` | Settings, artwork, generated RSS, categories, buttons, freebox, migration backups |
| `/mnt/external-8tb/howard-stern` | `/data/media` | Episodes **and their XML sidecar metadata** |

`./data` is relative to the directory containing `compose.yaml`, not the home
directory or the container. `DATA_DIR` can override it for existing installations
or rehearsals. The media path is configured separately through `MEDIA_DIR` in
`.env`: backing up `./data` alone does **not** back up episodes.
The application code comes from the image. Old PHP files in the host directory
are ignored, not served, overwritten, or deleted. Existing `custom/custom.ini` is
not loaded; the required upload settings are built into the image.

No actual configuration, credentials, artwork, or media belongs in this repository.
`.env` and common data/backup paths are excluded from Git.

## First deployment

For a **new deployment**, run on the **Linux Docker server**. These commands create
a new directory and refuse to reuse an existing one, protecting any existing
configuration. Use `curl` for the two downloads (or download the files manually):

```bash
(
  set -e
  mkdir -p "$HOME/docker"
  mkdir "$HOME/docker/podcastgen-howard"
  cd "$HOME/docker/podcastgen-howard"
  curl --fail --location https://raw.githubusercontent.com/msmirle/podcastgen-howard/main/compose.yaml --output compose.yaml
  curl --fail --location https://raw.githubusercontent.com/msmirle/podcastgen-howard/main/.env.example --output .env
  mkdir data
)
```

After both downloads succeed:

```bash
cd "$HOME/docker/podcastgen-howard"
nano .env
```

Keep `DATA_DIR=./data` for the layout above. Verify `MEDIA_DIR` points to your
existing external episode directory; episodes do not move into the project.
Check the external disk before starting:

```bash
findmnt /mnt/external-8tb
test -d /mnt/external-8tb/howard-stern
```

If you are starting fresh without an external media disk, create a media directory
where you want it and set `MEDIA_DIR` to that absolute path. Compose deliberately
refuses missing host paths instead of silently creating empty storage.

Keep `PORT=6766` and your existing DNS/router port forwarding to retain an existing
feed URL. `PUBLIC_URL` is optional: leave it blank to preserve the restored URL,
or set it explicitly to the original public base URL including a trailing slash.
It is applied to an existing configuration at container startup, including after
the initial setup's first restart. A changed base URL takes effect in newly
generated feeds; regenerate RSS in the admin UI if you intentionally change it.

For an **existing 2.7/3.0/3.1 installation, stop here and follow migration below**.
Do not run two installations against the same writable data.

For a **fresh installation**, temporarily block external access first:

```bash
docker compose pull
docker compose up -d
docker compose ps
```

Open the site at its intended public base URL from a trusted network and complete
the setup wizard. The hostname/port used for setup becomes the configured URL
unless overridden by `PUBLIC_URL`. Create a strong admin password, then:

```bash
docker compose restart app
```

Check `/feed.xml`, artwork, and an episode download before reopening public access.
The container exposes port 80 internally and port 6766 on the host by default.
The feed remains `/feed.xml`; no redirect or URL change is required.

## Migrate 2.7 or restore a legacy backup

The official upgrade sequence is **2.7 -> 3.0.1 -> 3.1.5 -> 3.2.9**. This image
implements those configuration transformations offline rather than running
obsolete web applications. It preserves artwork/media paths, feed URL, episode
files and XML, and existing GUIDs. Old 2.7 themes (including Flatly) switch to the
current default theme; custom theme migration is not included.
The obsolete 2.7 `enablesocialnetworks` flags are retired during migration and
remain available in the original configuration backup.
Missing application metadata (such as buttons and custom RSS tags) is initialized
with upstream defaults without replacing existing files.

The helper avoids known legacy converter problems with artwork paths and account
JSON. For 2.7/3.0, it asks for a **new admin password**, retaining the username;
an MD5 password cannot be converted into a modern password hash without the
password. For 3.1/3.2, existing modern account hashes are retained.

1. **Stop the old container** and take complete, independent backups of both
   host locations, including episode XML and hidden files. Keep the old image and
   deployment files for rollback. Configuration-stage snapshots below are **not**
   a substitute for this backup.
2. **Rehearse on a copy first.** Copy the application/settings/artwork and media
   directories to separate test locations. Point a test `.env` at both copies,
   choose a different `PORT`, and keep `PUBLIC_URL` at the original public URL.
   Never mount the live media directory for the rehearsal.
3. Pull and migrate (one-off Compose runs do not publish service ports):

   ```bash
   docker compose pull
   docker compose run --rm app migrate
   ```

   Enter the new password when prompted. It is not put into Compose, environment
   variables, or command-line arguments. Each configuration stage is saved under
   `DATA_DIR/backups/migration-.../`; the original is saved byte-for-byte before
   replacement. Failure leaves the original configuration unchanged.
4. Repair existing ownership **once if necessary**:

   ```bash
   docker compose run --rm app fix-permissions
   ```

   This explicitly and recursively changes ownership of artwork/media to `PUID`
   and `PGID` and grants that owner read/write access. It can take time on a large
   library and affects other host processes sharing those files. Normal startup
   only adjusts directory roots and the small set of mutable settings/feed files.
   New installations do not need `chmod 777`.
5. Start and verify:

   ```bash
   docker compose up -d
   docker compose logs --tail=100 app
   ```

   Verify admin login, title, artwork, episode count, `/feed.xml`, enclosure URLs,
   GUIDs, and an actual episode download. The existing static feed is left intact
   by migration. Regenerate RSS through the admin UI and check it again.
6. Once the copy passes, repeat the same backed-up procedure on production with
   the original host paths and `PORT=6766`. Stop/remove the old container before
   starting the replacement. Keep public access blocked until validation passes.

Configuration paths must be `media/`, `images/`, an empty `feed_dir`, and (for
3.x) `themes/default/`. Other layouts require a separately planned migration.
Malformed/unsupported configurations fail explicitly rather than starting a
broken site. Configuration strings are checked against the upstream parser before
replacement; unsupported multiline/escaped values may require manual preparation
of a backup copy. The helper does not rewrite episode XML.

For automation, `migrate --password-stdin` reads one password line from standard
input. Supply it through a secret manager, not a literal command in shell history.

## Restore a 3.2.9 backup

Stop the container, restore the settings/artwork directory and the complete media
directory, verify `.env`, then run:

```bash
docker compose run --rm app fix-permissions  # if restored ownership differs
docker compose up -d
```

The container fixes the internal application path and, only if explicitly set,
the public URL. It never replaces a restored configuration with defaults.

For rollback after a migration, stop the new container and restore **both** original
host backups, then use the old deployment/image. A newer configuration is not
backwards compatible. Never just downgrade the image against migrated data.

## Consolidate an existing deployment

Changing `DATA_DIR` does not move any files. Back up the current settings/artwork
directory, stop this project's service with `docker compose stop app`, and move
the complete current data directory into the deployment's `./data` directory.
Do not overwrite or merge an existing destination without checking it first.
Leave the external media directory untouched, set `DATA_DIR=./data` in `.env`,
and run `docker compose up -d --wait`. No application migration is needed for
this host-directory move.

Verify the container's bind mounts, admin login, artwork, feed, and an episode
download before removing any old copies. If the deployment was originally a Git
checkout, archive its source/build files and Git metadata after verifying the
new layout. Only `compose.yaml`, `.env`, and `data/` need remain at the top level;
private archives can be retained under `data/backups/`. Keep independent backups
separate from the live data directory.

## Updates and operations

```bash
docker compose pull
docker compose up -d
docker compose ps
docker compose logs --tail=100 app
docker compose down
```

Stopping/removing containers does not remove bind-mounted host data. Back up
before updating. The `3.2.9` tag receives runtime rebuilds; use a published
`build-<run-id>-<attempt>` tag or image digest when you need an immutable deployment.

Built-in PHP limits: **1000 MiB per file**, **1024 MiB POST**, **2000 MiB memory**.
The POST limit intentionally leaves room for multipart overhead. Apache's body
limit is 1100 MiB; upload/input/execution timeouts are 30 minutes. Any future
reverse proxy must also allow these sizes and timeouts. Modern PodcastGenerator
does not need the legacy `$max_upload_form_size` setting.

`PUID`/`PGID` default to Apache's `33:33`, or set them to your Linux user's numeric
`id -u` / `id -g`. The entrypoint requires root to initialize ownership; Apache
serves requests as the unprivileged user. Rootless/user-namespace-remapped Docker
and NFS root-squash may need host-side permission setup.

### Cron regeneration results

Opening the existing cron URL from **Admin > Podcast Generator Configuration**
now displays a results page instead of a blank response. The URL and key are
unchanged. A successful response shows the number of newly indexed episodes and
the total number in the regenerated feed, with an explicit message when no new
episodes were found. Zero new episodes does not mean existing episode metadata
was unchanged: the RSS feed is rebuilt on every successful run.

The endpoint still scans media using upstream's indexing behavior, which can
rename new files and create episode XML. Invalid/missing keys return HTTP 403,
disabled indexing returns 409, and processing failures return 500 with a visible
error and details in container logs. A failed run can have partially indexed
episodes; it is not rolled back automatically. Successful runs return HTTP 200.
The results page is not cached and does not display the cron key. Keep the URL
private because possession of its key allows triggering the job.

## Build, test, and publish

```bash
docker build --pull -t podcastgen-howard:test .
python3 tests/integration.py podcastgen-howard:test
```

Tests use disposable, uniquely named Docker volumes and loopback-only ports.
They exercise the real setup wizard, admin login, restart/replacement persistence,
custom UID ownership, an **actual 1000 MiB multipart upload**, blocked private and
uploaded-script paths, staged legacy backups/migrations, RSS enclosure URLs,
GUID preservation, unsupported-version rejection, and cron result/error summaries.

[The workflow](.github/workflows/container.yml) runs on pushes, pull requests,
manual dispatch, and weekly. Only successful main-branch runs publish images.
GitHub provides a short-lived `GITHUB_TOKEN`; no stored registry password is
needed. After the first publish, set the GHCR package's visibility to **Public**
in its package settings and confirm an unauthenticated pull works.

The release archive is verified against a pinned SHA-256. PHP 8.3 is used while
it remains security-supported; upstream application/dependency maintenance is
still separate. This wrapper's code is MIT-licensed. PodcastGenerator and bundled
dependencies retain their own licenses; the upstream license is included in the
image at `/usr/share/doc/podcastgenerator/LICENSE`.
