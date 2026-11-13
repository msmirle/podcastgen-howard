<?php
declare(strict_types=1);
require 'core/include.php';

header('Content-Type: text/html; charset=utf-8');
header('Cache-Control: no-store');
header('Referrer-Policy: no-referrer');

$status = 200;
$message = null;
$indexed = null;
$episodeCount = null;
$key = $_GET['key'] ?? null;
$expectedKey = $config['installationKey'] ?? '';

if (!is_string($key) || !is_string($expectedKey) || $expectedKey === '' || !hash_equals($expectedKey, $key)) {
    $status = 403;
    $message = 'Invalid or missing cron key. No changes were made.';
    error_log('podcastgen cron: rejected a request with an invalid or missing key.');
} elseif (($config['cronAutoIndex'] ?? null) != '1') {
    $status = 409;
    $message = 'Cron indexing is disabled. No changes were made.';
    error_log('podcastgen cron: indexing is disabled or not configured.');
} else {
    set_error_handler(static function (int $severity, string $message, string $file, int $line): bool {
        if (!(error_reporting() & $severity)) {
            return false;
        }
        throw new ErrorException($message, 0, $severity, $file, $line);
    });
    try {
        $indexed = indexEpisodes($config);
        if (generateRSS() === false) {
            throw new RuntimeException('Cannot write the RSS feed.');
        }
        $feed = simplexml_load_file($config['absoluteurl'] . $config['feed_dir'] . 'feed.xml');
        if ($feed === false) {
            throw new RuntimeException('The regenerated RSS feed is not valid XML.');
        }
        $episodeCount = count($feed->channel->item);
    } catch (Throwable $error) {
        $status = 500;
        $message = 'Regeneration did not complete. Check the container logs before retrying; indexing may have partially completed.';
        error_log('podcastgen cron: ' . str_replace($expectedKey, '[redacted]', $error->getMessage()));
    } finally {
        restore_error_handler();
    }
}

http_response_code($status);
$success = $status === 200;
?>
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta name="robots" content="noindex, nofollow">
    <title>RSS regeneration result</title>
    <style>
        body { margin: 0; padding: 2rem 1rem; background: #f3f5f7; color: #202b36; font: 1rem/1.6 system-ui, sans-serif; }
        main { max-width: 38rem; margin: auto; padding: 2rem; background: #fff; border-radius: .75rem; border-top: .35rem solid #21834a; }
        main.error { border-top-color: #b42318; }
        h1 { margin-top: 0; font-size: 1.65rem; line-height: 1.3; }
        dl { display: grid; grid-template-columns: 1fr auto; gap: .75rem 1rem; padding: 1rem 0; border-top: 1px solid #dce2e7; border-bottom: 1px solid #dce2e7; }
        dd { margin: 0; font-weight: bold; }
        a { color: #185bb0; }
    </style>
</head>
<body>
    <main<?= $success ? '' : ' class="error"' ?>>
        <h1><?= $success ? 'RSS feed regenerated' : 'RSS regeneration failed' ?></h1>
        <?php if ($success) { ?>
            <p>The RSS feed was regenerated successfully.</p>
            <dl>
                <dt>New episodes indexed</dt>
                <dd id="new-episodes"><?= $indexed ?></dd>
                <dt>Total episodes in feed</dt>
                <dd id="feed-total"><?= $episodeCount ?></dd>
            </dl>
            <?php if ($indexed === 0) { ?>
                <p>No new episodes were found.</p>
            <?php } ?>
            <p><a href="<?= htmlspecialchars($config['url'] . $config['feed_dir'] . 'feed.xml', ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8') ?>">View RSS feed</a></p>
        <?php } else { ?>
            <p><?= htmlspecialchars($message, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8') ?></p>
        <?php } ?>
    </main>
</body>
</html>
