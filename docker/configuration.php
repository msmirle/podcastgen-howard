<?php
declare(strict_types=1);

function readConfiguration(string $path): array
{
    return (static function (string $file): array {
        require $file;
        $values = get_defined_vars();
        unset($values['file']);
        return $values;
    })($path);
}

function validateLayout(array $config): void
{
    foreach (['upload_dir' => 'media/', 'img_dir' => 'images/', 'feed_dir' => ''] as $key => $expected) {
        if (!array_key_exists($key, $config) || $config[$key] !== $expected) {
            throw new RuntimeException("Unsupported $key. This image requires '$expected'; adjust a backup copy first.");
        }
    }
    if (($config['theme_path'] ?? '') !== 'themes/default/') {
        throw new RuntimeException('Custom themes need a separate migration; this image uses themes/default/.');
    }
}

function applyRuntimeSettings(array $config): array
{
    $config['absoluteurl'] = '/var/www/html/';
    $url = getenv('PUBLIC_URL');
    if ($url !== false && $url !== '') {
        if (!filter_var($url, FILTER_VALIDATE_URL) || !preg_match('~^https?://~', $url)
            || parse_url($url, PHP_URL_QUERY) !== null || parse_url($url, PHP_URL_FRAGMENT) !== null
            || parse_url($url, PHP_URL_USER) !== null) {
            throw new RuntimeException('PUBLIC_URL must be an HTTP(S) URL without credentials, query, or fragment.');
        }
        $config['url'] = rtrim($url, '/') . '/';
    }
    return $config;
}

function writeConfiguration(string $path, array $config): void
{
    $output = "<?php\n";
    $expected = [];
    foreach ($config as $key => $value) {
        if (!preg_match('/^[a-zA-Z_][a-zA-Z0-9_]*$/', $key)) {
            throw new RuntimeException('Invalid configuration key.');
        }
        $items = is_array($value) ? $value : [null => $value];
        foreach ($items as $index => $item) {
            if (!is_string($item) && !is_int($item)) {
                throw new RuntimeException("Unsupported value type in configuration key $key.");
            }
            if (is_array($value) && ($key !== 'itunes_category' || !is_int($index))) {
                throw new RuntimeException("Unsupported array in configuration key $key.");
            }
            $name = is_array($value) ? "$key" . "[$index]" : $key;
            $expected[$name] = (string) $item;
            $output .= '$' . $name . ' = ' . var_export($item, true) . ";\n\n";
        }
    }

    $temporary = tempnam(dirname($path), '.config-');
    if ($temporary === false) {
        throw new RuntimeException('Cannot create a temporary configuration.');
    }
    try {
        if (file_put_contents($temporary, $output) === false) {
            throw new RuntimeException('Cannot write the configuration.');
        }
        require_once '/opt/podcastgen/core/misc/configsystem.php';
        $roundtrip = getConfig($temporary);
        foreach ($expected as $key => $value) {
            if (!isset($roundtrip[$key]) || (string) $roundtrip[$key] !== $value) {
                throw new RuntimeException("Upstream cannot safely read configuration key $key; original file was not replaced.");
            }
        }
        if (!chmod($temporary, 0640) || !chown($temporary, 'www-data') || !chgrp($temporary, 'www-data')
            || !rename($temporary, $path)) {
            throw new RuntimeException('Cannot install the configuration.');
        }
    } finally {
        if (file_exists($temporary)) {
            unlink($temporary);
        }
    }
}
