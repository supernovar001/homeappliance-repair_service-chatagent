#!/bin/sh
# root로 시작했으면 쓰기 폴더의 소유자를 appuser로 맞춘 뒤 appuser 권한으로 명령을 실행합니다.
set -e
if [ "$(id -u)" = "0" ]; then
  if [ -n "$QDRANT_PATH" ] && [ "$QDRANT_PATH" != ":memory:" ]; then
    mkdir -p "$QDRANT_PATH"
    chown -R appuser "$QDRANT_PATH"
  fi
  chown appuser /data
  exec setpriv --reuid=appuser --regid=appuser --init-groups "$@"
fi
exec "$@"
