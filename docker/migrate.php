<?php
declare(strict_types=1);
require __DIR__ . '/configuration.php';

function newPassword(bool $fromStdin): string
{
    if (!$fromStdin && !stream_isatty(STDIN)) {
        throw new RuntimeException('Use an interactive terminal, or --password-stdin for automation.');
    }
    if (!$fromStdin) {
        fwrite(STDERR, 'New admin password (at least 12 characters): ');
        system('stty -echo', $status);
        if ($status !== 0) {
            throw new RuntimeException('Cannot disable terminal echo.');
        }
    }
    try {
        $line = fgets(STDIN);
        if ($line === false) {
            throw new RuntimeException('No password received.');
        }
        $password = rtrim($line, "\r\n");
    } finally {
        if (!$fromStdin) {
            system('stty echo');
            fwrite(STDERR, "\n");
        }
    }
    if (strlen($password) < 12) {
        throw new RuntimeException('Admin password must contain at least 12 characters.');
    }
    return password_hash($password, PASSWORD_DEFAULT);
}

try {
    $options = array_slice($argv, 1);
    if ($options !== [] && $options !== ['--password-stdin']) {
        throw new RuntimeException('Usage: migrate [--password-stdin]');
    }
    $path = '/data/config.php';
    if (!is_file($path)) {
        throw new RuntimeException('No config.php to migrate. Use the web setup wizard for a fresh installation.');
    }
    $config = readConfiguration($path);
    $version = (string) ($config['podcastgen_version'] ?? '');
    if (!preg_match('/^(2\.7|3\.0(?:\.1)?|3\.1(?:\.[0-5])?|3\.2(?:\.[0-9])?)$/', $version)) {
        throw new RuntimeException('Unsupported source version; expected 2.7, 3.0.x, 3.1.x, or 3.2.x up to 3.2.9.');
    }
    if ($version === '2.7') {
        $config['theme_path'] = 'themes/default/';
    }
    validateLayout($config);
    if ($version === '3.2.9') {
        fwrite(STDOUT, "Already at 3.2.9; no migration necessary.\n");
        exit(0);
    }
    foreach (['url', 'podcast_title', 'podcast_description', 'author_name', 'author_email', 'itunes_category'] as $key) {
        if (!array_key_exists($key, $config)) {
            throw new RuntimeException("Required configuration key $key is missing.");
        }
    }
    $hash = null;
    if (version_compare($version, '3.1', '<')) {
        if (empty($config['username'])) {
            throw new RuntimeException('Legacy admin username is missing.');
        }
        $hash = newPassword(in_array('--password-stdin', $options, true));
    }

    $backup = '/data/backups/migration-' . gmdate('Ymd-His') . '-' . bin2hex(random_bytes(3));
    if (!mkdir($backup, 0700, true) || !copy($path, "$backup/original.php") || !chmod("$backup/original.php", 0600)) {
        throw new RuntimeException('Cannot back up the original configuration.');
    }
    fwrite(STDOUT, "Configuration backups: $backup\n");
    if ($version === '2.7') {
        // Legacy PHP configurations can build this value from $url.
        if (str_starts_with((string) $config['link'], (string) $config['url'])) {
            $config['link'] = substr($config['link'], strlen($config['url']));
        }
        $config['podcastgen_version'] = '3.0.1';
        $config['userpassword'] = $hash;
        writeConfiguration("$backup/3.0.1.php", $config);
        fwrite(STDOUT, "Prepared 2.7 -> 3.0.1 (kept artwork/episode paths; selected the current default theme).\n");
        $version = '3.0.1';
    }
    if (version_compare($version, '3.1', '<')) {
        $config['users_json'] = json_encode([(string) $config['username'] => $hash], JSON_THROW_ON_ERROR | JSON_UNESCAPED_SLASHES);
        unset($config['username'], $config['userpassword'], $config['max_upload_form_size']);
        $config['indexfile'] = 'index.php';
        $config['podcastPassword'] = '';
        $config['podcastgen_version'] = '3.1.5';
        writeConfiguration("$backup/3.1.5.php", $config);
        fwrite(STDOUT, "Prepared 3.0.x -> 3.1.5 (converted admin account).\n");
    }
    $users = json_decode((string) ($config['users_json'] ?? ''), true, 512, JSON_THROW_ON_ERROR);
    if (!is_array($users) || $users === []) {
        throw new RuntimeException('Admin accounts are missing or invalid.');
    }
    $config += [
        'customtagsenabled' => 'no', 'timezone' => '', 'podcast_guid' => '',
        'podcast_cover' => 'itunes_image.jpg', 'feed_locked' => '', 'websub_server' => '',
        'pi_api_key' => '', 'pi_api_secret' => '', 'pi_podcast_id' => 0,
        'feed_sort' => 'timestamp', 'webmaster' => $config['author_email'],
    ];
    $languages = simplexml_load_file('/opt/podcastgen/components/supported_languages/podcast_languages.xml');
    if ($languages === false) {
        throw new RuntimeException('Cannot read supported feed languages.');
    }
    $language = 'en';
    foreach ($languages as $entry) {
        if ((string) $entry->code === ($config['feed_language'] ?? '')) {
            $language = isset($entry->alias) ? (string) $entry->alias : (string) $entry->code;
            break;
        }
    }
    $config['feed_language'] = $language;
    if ($config['scriptlang'] === 'en_EN') {
        $config['scriptlang'] = 'en_US';
    }
    $config['podcastgen_version'] = '3.2.9';
    $config = applyRuntimeSettings($config);
    writeConfiguration("$backup/3.2.9.php", $config);
    writeConfiguration($path, $config);
    fwrite(STDOUT, "Migrated to 3.2.9. Artwork, media, episode XML, and the existing feed were not modified.\n");
} catch (Throwable $error) {
    fwrite(STDERR, "podcastgen migration: " . $error->getMessage() . "\n");
    exit(1);
}
