FROM php:8.3-apache-bookworm

ARG PG_VERSION=3.2.9
ARG PG_SHA256=f2962195b51071ef910455f12b8aa96f30d42925b58f448d3e81cf25e5afb17a

RUN apt-get update \
    && apt-get install -y --no-install-recommends libxml2 libonig5 libxml2-dev libonig-dev locales unzip \
    && docker-php-ext-install -j"$(nproc)" gettext mbstring simplexml \
    && sed -i 's/^# en_US.UTF-8 UTF-8/en_US.UTF-8 UTF-8/' /etc/locale.gen \
    && locale-gen \
    && curl --fail --location --retry 3 \
        "https://github.com/PodcastGenerator/PodcastGenerator/releases/download/v${PG_VERSION}/PodcastGenerator-${PG_VERSION}.zip" \
        --output /tmp/podcastgen.zip \
    && echo "${PG_SHA256}  /tmp/podcastgen.zip" | sha256sum --check --strict \
    && unzip -q /tmp/podcastgen.zip -d /tmp/release \
    && mkdir -p /opt/podcastgen /usr/share/doc/podcastgenerator \
    && cp -a /tmp/release/PodcastGenerator/. /opt/podcastgen/ \
    && cp /tmp/release/LICENSE /usr/share/doc/podcastgenerator/LICENSE \
    && rm -rf /tmp/release /tmp/podcastgen.zip \
    && apt-get purge -y --auto-remove libxml2-dev libonig-dev unzip \
    && rm -rf /var/lib/apt/lists/* \
    && printf '%s\n' "${PG_VERSION}" > /opt/podcastgen-version

COPY docker/php.ini /usr/local/etc/php/conf.d/zz-podcastgen.ini
COPY docker/apache.conf /etc/apache2/conf-available/podcastgen.conf
COPY docker/ /usr/local/lib/podcastgen/
RUN a2enconf podcastgen \
    && chmod +x /usr/local/lib/podcastgen/entrypoint.sh \
    && cp -a /opt/podcastgen/. /var/www/html/ \
    && rm -r /var/www/html/images /var/www/html/media \
    && ln -s /data/images /var/www/html/images \
    && ln -s /data/media /var/www/html/media \
    && cp /usr/local/lib/podcastgen/pg-cron.php /var/www/html/pg-cron.php \
    && cp /usr/local/lib/podcastgen/healthz.php /var/www/html/healthz.php

LABEL org.opencontainers.image.title="podcastgen-howard" \
      org.opencontainers.image.description="PodcastGenerator with persistent host storage and offline migration" \
      org.opencontainers.image.source="https://github.com/msmirle/podcastgen-howard" \
      org.opencontainers.image.version="${PG_VERSION}"

WORKDIR /var/www/html
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD php -r 'exit(file_get_contents("http://127.0.0.1/healthz.php") === "ok\n" ? 0 : 1);'
ENTRYPOINT ["/usr/local/lib/podcastgen/entrypoint.sh"]
CMD ["apache2-foreground"]
