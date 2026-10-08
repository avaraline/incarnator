map $http_upgrade $connection_upgrade {
    default upgrade;
    '' close;
}

proxy_cache_path /cache/nginx levels=1:2 keys_zone=takahe:20m inactive=14d max_size=__CACHESIZE__;

upstream takahe {
    server "127.0.0.1:8001";
}

# access_log /dev/stdout;

server {
    listen 8000;
    listen [::]:8000;
    server_name _;

    root /takahe/static;
    index index.html;

    ignore_invalid_headers on;
    proxy_connect_timeout 900;

    client_max_body_size 100M;
    client_body_buffer_size 128k;
    charset utf-8;

    proxy_set_header Host $http_host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_http_version 1.1;

    # The user header is available for logging, but not returned to the client
    proxy_hide_header X-Takahe-User;
    proxy_hide_header X-Takahe-Identity;

    # Serves static files from the collected dir
    location /static/ {
        # Files in static have cache-busting hashes in the name, thus can be cached forever
        add_header Cache-Control "public, max-age=604800, immutable";

        alias /takahe/static-collected/;
        try_files $uri /static//static-real$uri;
    }

    # Static fallback for dev mode
    location /static-real/ {
        internal;
        proxy_pass http://takahe/;
    }

    # Proxies media and remote media with caching
    location ~* ^/(media|proxy) {
        # Cache media and proxied resources
        proxy_cache takahe;
        proxy_cache_key $host$uri;
        proxy_cache_valid 200 304 4h;
        proxy_cache_valid 301 307 4h;
        proxy_cache_valid 500 502 503 504 0s;
        proxy_cache_valid any 1h;
        add_header X-Cache $upstream_cache_status;
        add_header X-Content-Type-Options nosniff always;
        add_header Content-Security-Policy "default-src 'none'; style-src 'unsafe-inline'; sandbox" always;
        proxy_hide_header X-Content-Type-Options;
        proxy_hide_header Content-Security-Policy;
        proxy_force_ranges on;

        # Signal to Takahē that we support full URI accel proxying
        proxy_set_header X-Takahe-Accel true;

        proxy_pass http://takahe;
    }

    # Internal target for X-Accel redirects that stashes the URI in a var
    location /__takahe_accel__/ {
        internal;
        set $takahe_realuri $upstream_http_x_takahe_realuri;
        rewrite ^/(.+) /__takahe_accel__/real/;
    }

    # Real internal-only target for X-Accel redirects
    location /__takahe_accel__/real/ {
        # Only allow internal redirects
        internal;

        # Reconstruct the remote URL
        resolver __NAMESERVER__ valid=10s;

        # Unset Authorization and Cookie for security reasons.
        proxy_set_header Authorization '';
        proxy_set_header Cookie '';
        proxy_set_header User-Agent 'takahe/nginx';
        proxy_set_header Host $proxy_host;
        proxy_set_header X-Forwarded-For '';
        proxy_set_header X-Forwarded-Host '';
        proxy_set_header X-Forwarded-Server '';
        proxy_set_header X-Real-Ip '';

        # Stops the local disk from being written to (just forwards data through)
        proxy_max_temp_file_size 0;

        # Proxy the remote file through to the client
        proxy_pass $takahe_realuri;
        proxy_ssl_server_name on;
        # Fail fast on arbitrary remote hosts so proxy_cache_use_stale
        # can kick in
        proxy_connect_timeout 15s;
        add_header X-Takahe-Accel "HIT";

        # Remote origins may reply with Cache-Control: private, Vary or
        # Set-Cookie, which would prevent nginx from storing the response;
        # ignore them so proxy_cache_valid below applies, and hide them so
        # browsers/CDNs can cache the proxied copy. X-Accel-* headers from
        # untrusted remote servers must not be honored either.
        proxy_ignore_headers Cache-Control Expires Set-Cookie Vary X-Accel-Redirect X-Accel-Expires X-Accel-Limit-Rate X-Accel-Buffering X-Accel-Charset;
        proxy_hide_header Cache-Control;
        proxy_hide_header Expires;
        proxy_hide_header Set-Cookie;
        proxy_hide_header Vary;
        # add_header deliberately skips 4xx/5xx, so error passthroughs are
        # never marked cacheable to browsers
        add_header Cache-Control "public, max-age=1209600";

        # Cache these responses too
        proxy_cache takahe;
        # Cache after a single request
        proxy_cache_min_uses 1;
        proxy_cache_key $takahe_realuri;
        proxy_cache_valid 200 304 720h;
        proxy_cache_valid 301 307 12h;
        proxy_cache_valid 500 501 502 503 504 505 507 508 0s;
        proxy_cache_valid any 72h;
        # Serve a stale copy instead of the error when the remote is down,
        # and refresh expired entries in the background instead of blocking
        proxy_cache_use_stale error timeout updating http_500 http_502 http_503 http_504;
        proxy_cache_background_update on;
        add_header X-Cache $upstream_cache_status;
        add_header X-Content-Type-Options nosniff always;
        add_header Content-Security-Policy "default-src 'none'; style-src 'unsafe-inline'; sandbox" always;
        proxy_hide_header X-Content-Type-Options;
        proxy_hide_header Content-Security-Policy;
        proxy_force_ranges on;
    }

    # Streaming is served by a separate ASGI process; keep long-lived
    # connections out of the WSGI worker pool. Do not log bearer query strings.
    location ~ ^/api/v1/streaming(?:/|$) {
        access_log off;
        __STREAMINGPROXY__
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_set_header Host $http_host;
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }

    # Default config for all other pages
    location / {
        proxy_redirect off;
        proxy_buffering off;
        proxy_pass http://takahe;
    }
}
