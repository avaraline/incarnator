#!/bin/bash

# Set up cache size and nameserver subs
# Nameservers are taken from /etc/resolv.conf - if the IP contains ":", it's IPv6 and must be enclosed in [] for nginx
CACHE_SIZE="${TAKAHE_NGINX_CACHE_SIZE:-1g}"
NAMESERVER=`cat /etc/resolv.conf | grep "nameserver" | awk '{print ($2 ~ ":") ? "["$2"]" : $2}' | tr '\n' ' '`
if [ -z "$NAMESERVER" ]; then
    NAMESERVER="9.9.9.9 149.112.112.112"
fi
sed "s/__CACHESIZE__/${CACHE_SIZE}/g" /etc/nginx/conf.d/default.conf.tpl | sed "s/__NAMESERVER__/${NAMESERVER}/g" > /etc/nginx/conf.d/default.conf

# Resolve the optional streaming service at request time so the web container
# also starts when the Compose streaming profile is disabled.
case "${TAKAHE_STREAMING_ENABLED:-false}" in
    true|True|TRUE|1|yes|Yes|YES)
        STREAMING_PROXY='resolver __NAMESERVER__ valid=10s; set $streaming_backend "__UPSTREAM__"; proxy_pass http://$streaming_backend;'
        STREAMING_PROXY="${STREAMING_PROXY//__NAMESERVER__/$NAMESERVER}"
        STREAMING_PROXY="${STREAMING_PROXY//__UPSTREAM__/${TAKAHE_STREAMING_UPSTREAM:-127.0.0.1:8002}}"
        ;;
    *) STREAMING_PROXY='return 404;' ;;
esac
sed -i "s|__STREAMINGPROXY__|${STREAMING_PROXY}|g" /etc/nginx/conf.d/default.conf

# Run nginx and gunicorn
nginx &

gunicorn takahe.wsgi:application -b 0.0.0.0:8001 $GUNICORN_EXTRA_CMD_ARGS &

# Wait for any process to exit
wait -n

# Exit with status of process that exited first
exit $?
