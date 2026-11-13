"""Container-level tests. Uses only Python's standard library and Docker."""

import http.cookiejar
import json
import pathlib
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import xml.etree.ElementTree as ET


IMAGE = sys.argv[1] if len(sys.argv) > 1 else "podcastgen:test"
PREFIX = "podcastgen-test-" + uuid.uuid4().hex[:12]
PASSWORD = "Synthetic-test-password-42"
PUBLIC_URL = "http://podcast.example.test:6766/"
VOLUMES = [PREFIX + "-data", PREFIX + "-media"]
CONTAINERS = []


def docker(*args, input=None, check=True):
    result = subprocess.run(
        ["docker", *args], input=input, text=True, capture_output=True, check=False
    )
    if check and result.returncode:
        raise AssertionError(f"docker {' '.join(args)}\n{result.stdout}\n{result.stderr}")
    return result


def mounts():
    return [
        "--mount", f"type=volume,source={VOLUMES[0]},target=/data",
        "--mount", f"type=volume,source={VOLUMES[1]},target=/data/media",
        "-e", f"PUBLIC_URL={PUBLIC_URL}",
        "-e", "PUID=1001", "-e", "PGID=1001",
    ]


def php(container, source):
    return docker("exec", container, "php", "-r", source).stdout


def config(container):
    return json.loads(php(
        container,
        "require '/usr/local/lib/podcastgen/configuration.php';"
        "echo json_encode(readConfiguration('/data/config.php'));",
    ))


def base_url(name):
    port = json.loads(docker("inspect", name).stdout)[0]["NetworkSettings"]["Ports"]["80/tcp"][0]["HostPort"]
    return f"http://127.0.0.1:{port}/"


def start():
    name = PREFIX + "-" + str(len(CONTAINERS))
    CONTAINERS.append(name)
    docker("run", "-d", "--name", name, "-p", "127.0.0.1::80", *mounts(), IMAGE)
    base = base_url(name)
    for _ in range(90):
        state = json.loads(docker("inspect", name).stdout)[0]["State"]
        if not state["Running"]:
            raise AssertionError(docker("logs", name).stdout + docker("logs", name).stderr)
        try:
            with urllib.request.urlopen(base + "healthz.php", timeout=2) as response:
                if response.read() == b"ok\n":
                    return name, base
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(1)
    raise AssertionError("Container did not become ready: " + docker("logs", name).stderr)


def stop(name):
    docker("rm", "-f", name)


def client():
    return urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
    )


def request(browser, base, path, values=None):
    data = urllib.parse.urlencode(values).encode() if values is not None else None
    with browser.open(base + path, data=data, timeout=30) as response:
        body = response.read()
        assert b"Fatal error" not in body, body[:1000]
        return body, response.url


def assert_status(base, path, expected):
    try:
        with urllib.request.urlopen(base + path, timeout=5) as response:
            status = response.status
    except urllib.error.HTTPError as error:
        status = error.code
    assert status == expected, (path, status, expected)


def migration(*args, password=None, check=True):
    return docker("run", "--rm", "-i", *mounts(), IMAGE, "migrate", *args, input=password, check=check)


def upload_limit(container, base):
    # The endpoint exists only in the disposable test container, never in the image.
    php(container, r"""
        file_put_contents('/var/www/html/upload-test.php',
            '<?php header("Content-Type: application/json"); echo json_encode($_FILES["file"]);');
    """)
    size = 1000 * 1024 * 1024
    with tempfile.TemporaryDirectory() as directory:
        path = pathlib.Path(directory) / "upload.bin"
        with path.open("wb") as stream:
            stream.truncate(size)
        result = subprocess.run(
            ["curl", "--fail", "--silent", "--show-error", "--max-time", "180",
             "-F", f"file=@{path}", base + "upload-test.php"],
            text=True, capture_output=True, check=True,
        )
    uploaded = json.loads(result.stdout)
    assert uploaded["error"] == 0, uploaded
    assert uploaded["size"] == size, uploaded
    php(container, "unlink('/var/www/html/upload-test.php');")
    print("PASS: actual 1000 MiB multipart upload through Apache and PHP")


def cron_summary(container, base):
    key = config(container)["installationKey"]
    path = "pg-cron.php?" + urllib.parse.urlencode({"key": key})
    filename = "2020-01-01_cron-sample.mp3"
    with tempfile.TemporaryDirectory() as directory:
        audio = pathlib.Path(directory) / filename
        # MPEG-1 Layer III frames at 128 kbps and 44.1 kHz.
        audio.write_bytes((b"\xff\xfb\x90\x00" + b"\0" * 413) * 40)
        docker("cp", str(audio), f"{container}:/data/media/{filename}")

    body, _ = request(client(), base, path)
    assert b"RSS feed regenerated" in body
    assert b'<dd id="new-episodes">1</dd>' in body
    assert b'<dd id="feed-total">1</dd>' in body
    assert key.encode() not in body
    feed = ET.fromstring(request(client(), base, "feed.xml")[0])
    assert feed.find("channel/item/enclosure").attrib["url"] == PUBLIC_URL + "media/" + filename

    body, _ = request(client(), base, path)
    assert b'<dd id="new-episodes">0</dd>' in body
    assert b'<dd id="feed-total">1</dd>' in body
    assert b"No new episodes were found." in body

    before = php(container, "echo hash_file('sha256', '/data/feed.xml');")
    assert_status(base, "pg-cron.php?key=invalid", 403)
    php(container, r"""
        require 'core/misc/configsystem.php';
        updateConfig('config.php', 'cronAutoIndex', '0');
    """)
    assert_status(base, path, 409)
    assert php(container, "echo hash_file('sha256', '/data/feed.xml');") == before
    php(container, r"""
        require 'core/misc/configsystem.php';
        updateConfig('config.php', 'cronAutoIndex', '1');
        chmod('/data/feed.xml', 0444);
    """)
    try:
        try:
            request(client(), base, path)
            raise AssertionError("Cron should report an unwritable feed as a failure")
        except urllib.error.HTTPError as error:
            assert error.code == 500
            body = error.read()
            assert b"RSS regeneration failed" in body
            assert b"Check the container logs" in body
            assert b"regenerated successfully" not in body
            assert key.encode() not in body
    finally:
        php(container, "chmod('/data/feed.xml', 0640);")
    php(container, r"""
        unlink('/data/media/2020-01-01_cron-sample.mp3');
        unlink('/data/media/2020-01-01_cron-sample.xml');
        require 'core/include.php';
        if (generateRSS() === false) {
            throw new RuntimeException('Cannot restore the test feed');
        }
    """)
    print("PASS: cron summaries for new/no episodes, denied/disabled requests, and write failures")


def main():
    for volume in VOLUMES:
        docker("volume", "create", volume)
    container, base = start()
    browser = client()
    request(browser, base, "setup/step1.php?done=1", {"lang": "en_US"})
    request(browser, base, "setup/step3.php?create=1", {
        "username": "testadmin", "password": PASSWORD, "password2": PASSWORD,
    })
    original = config(container)
    assert original["podcastgen_version"] == "3.2.9"
    ET.fromstring(request(browser, base, "feed.xml")[0])
    cron_summary(container, base)
    php(container, r"""
        file_put_contents('/data/images/persistence.txt', 'artwork-marker');
        file_put_contents('/data/media/persistence.txt', 'episode-marker');
        file_put_contents('/data/media/blocked.php', '<?php echo "should-not-run";');
    """)
    assert_status(base, "config.php", 403)
    assert_status(base, "media/blocked.php", 403)
    assert_status(base, "vendor/autoload.php", 403)
    print("PASS: fresh web setup, feed creation, and blocked private/script paths")
    upload_limit(container, base)

    docker("restart", container)
    base = base_url(container)
    for _ in range(60):
        try:
            request(browser, base, "healthz.php")
            break
        except OSError:
            time.sleep(1)
    else:
        logs = docker("logs", container)
        raise AssertionError("Restart failed:\n" + logs.stdout + logs.stderr)
    assert config(container)["url"] == PUBLIC_URL
    stop(container)
    container, base = start()
    browser = client()
    assert config(container)["users_json"] == original["users_json"]
    assert request(browser, base, "images/persistence.txt")[0] == b"artwork-marker"
    assert request(browser, base, "media/persistence.txt")[0] == b"episode-marker"
    _, location = request(browser, base, "admin/login.php?login=1", {
        "username": "testadmin", "password": PASSWORD,
    })
    assert location.endswith("/admin/index.php"), location
    assert php(container, "echo fileowner('/data/config.php');").strip() == "1001"
    print("PASS: same-container restart, replacement-container persistence, custom UID, and admin login")

    # Match the old installation's theme, computed permalink, and MD5 credentials.
    php(container, r"""
        require '/usr/local/lib/podcastgen/configuration.php';
        $c = readConfiguration('/data/config.php');
        $c['podcastgen_version'] = '2.7';
        $c['username'] = 'testadmin';
        $c['userpassword'] = md5('old-test-password');
        $c['max_upload_form_size'] = '1000000000';
        $c['theme_path'] = 'themes/flatly/';
        $c['scriptlang'] = 'en_EN';
        $c['link'] = '?name=';
        $c['websub_server'] = '';
        $c['podcast_title'] = "A host's podcast";
        unset($c['users_json']);
        writeConfiguration('/data/config.php', $c);
        file_put_contents('/data/config.php',
            '$link = $url . "?name=";' . "\n"
            . '$enablesocialnetworks = array("facebook" => "yes", "twitter" => "no");' . "\n",
            FILE_APPEND);
        file_put_contents('/data/feed.xml', 'original-feed-marker');
        unlink('/data/buttons.xml');
        unlink('/data/customtags.xml');
        file_put_contents('/data/freebox-content.txt', 'preserved-freebox');
        file_put_contents('/data/media/sample.mp3', 'ID3' . str_repeat("\0", 128));
        file_put_contents('/data/media/sample.xml', '<PodcastGenerator><episode>
            <titlePG>Migration sample</titlePG><shortdescPG>Test episode</shortdescPG>
            <longdescPG>Test episode</longdescPG><keywordsPG></keywordsPG>
            <explicitPG>no</explicitPG><fileInfoPG><duration>00:01</duration></fileInfoPG>
            <guid>urn:uuid:synthetic-stable-guid</guid>
            </episode></PodcastGenerator>');
    """)
    legacy = php(container, "echo hash_file('sha256', '/data/config.php');")
    stop(container)
    blocked = docker("run", "--rm", *mounts(), IMAGE, check=False)
    assert blocked.returncode != 0 and "requires migration" in blocked.stderr, blocked.stderr
    assert migration("--password-stdin", password="short\n", check=False).returncode != 0
    result = migration("--password-stdin", password=PASSWORD + "\n")
    assert "2.7 -> 3.0.1" in result.stdout and "3.0.x -> 3.1.5" in result.stdout
    container, base = start()
    migrated = config(container)
    assert migrated["podcastgen_version"] == "3.2.9"
    assert migrated["theme_path"] == "themes/default/"
    assert migrated["img_dir"] == "images/" and migrated["upload_dir"] == "media/"
    assert migrated["link"] == "?name=" and migrated["url"] == PUBLIC_URL
    assert migrated["podcast_title"] == "A host's podcast"
    assert migrated["scriptlang"] == "en_US"
    assert "enablesocialnetworks" not in migrated
    assert php(container, r"""
        $backups = glob('/data/backups/migration-*');
        echo hash_file('sha256', $backups[0] . '/original.php');
    """) == legacy
    assert request(client(), base, "feed.xml")[0] == b"original-feed-marker"
    assert request(client(), base, "images/persistence.txt")[0] == b"artwork-marker"
    buttons = ET.fromstring(request(client(), base, "buttons.xml")[0])
    assert buttons.findtext("button/href") == "feed.xml"
    ET.fromstring(request(client(), base, "customtags.xml")[0])
    assert request(client(), base, "freebox-content.txt")[0] == b"preserved-freebox"
    browser = client()
    _, location = request(browser, base, "admin/login.php?login=1", {
        "username": "testadmin", "password": PASSWORD,
    })
    assert location.endswith("/admin/index.php"), location
    request(browser, base, "admin/episodes_regenerate.php")
    feed = ET.fromstring(request(browser, base, "feed.php")[0])
    enclosure = feed.find("channel/item/enclosure")
    assert enclosure is not None
    assert enclosure.attrib["url"] == PUBLIC_URL + "media/sample.mp3"
    assert feed.findtext("channel/item/guid") == "urn:uuid:synthetic-stable-guid"
    assert request(browser, base, "media/sample.mp3")[0].startswith(b"ID3")
    assert "Already at 3.2.9" in migration().stdout
    print("PASS: guarded 2.7 startup, rejected weak password, staged backups, migrated login, RSS URLs, and GUIDs")

    # Both intermediate backup formats can be restored independently.
    for version in ("3.0.1", "3.1.5"):
        php(container, f"""
            $dirs = glob('/data/backups/migration-*');
            copy($dirs[0] . '/{version}.php', '/data/config.php');
        """)
        stop(container)
        args = ["--password-stdin"] if version == "3.0.1" else []
        migration(*args, password=PASSWORD + "\n" if args else None)
        container, base = start()
        assert config(container)["podcastgen_version"] == "3.2.9"
    print("PASS: independent 3.0.1 and 3.1.5 backup restores")

    php(container, r"""
        require '/usr/local/lib/podcastgen/configuration.php';
        $c = readConfiguration('/data/config.php');
        $c['podcastgen_version'] = '1.0';
        writeConfiguration('/data/config.php', $c);
    """)
    before = php(container, "echo hash_file('sha256', '/data/config.php');")
    stop(container)
    assert migration(check=False).returncode != 0
    result = docker(
        "run", "--rm", *mounts(), "--entrypoint", "php", IMAGE, "-r",
        "echo hash_file('sha256', '/data/config.php');",
    )
    assert result.stdout == before
    print("PASS: unsupported migrations leave configuration unchanged")


try:
    main()
finally:
    for name in CONTAINERS:
        if sys.exc_info()[0] is not None:
            logs = docker("logs", name, check=False)
            print(logs.stdout + logs.stderr, file=sys.stderr)
        docker("rm", "-f", name, check=False)
    for volume in reversed(VOLUMES):
        docker("volume", "rm", volume, check=False)
