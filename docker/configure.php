<?php
declare(strict_types=1);
require __DIR__ . '/configuration.php';

try {
    if (!file_exists('/data/config.php')) {
        fwrite(STDOUT, "No configuration yet. Complete setup on a trusted network before opening the public port.\n");
        exit(0);
    }
    $config = readConfiguration('/data/config.php');
    if (($config['podcastgen_version'] ?? '') !== trim(file_get_contents('/opt/podcastgen-version'))) {
        throw new RuntimeException('Configuration requires migration. Back up your data, then run: docker compose run --rm app migrate');
    }
    validateLayout($config);
    $updated = applyRuntimeSettings($config);
    if ($updated !== $config) {
        writeConfiguration('/data/config.php', $updated);
        fwrite(STDOUT, "Updated container path / explicitly configured public URL.\n");
    }
} catch (Throwable $error) {
    fwrite(STDERR, "podcastgen: " . $error->getMessage() . "\n");
    exit(1);
}
