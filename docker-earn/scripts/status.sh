#!/usr/bin/env bash
# Overzicht van de draaiende earn-containers: status, uptime en het verkeer
# dat elke container sinds de start door zijn netwerkinterface heeft geduwd.
# Dat verkeer is waar je voor betaald wordt, dus het is de eerlijkste
# voortgangsindicator die je lokaal hebt.
set -euo pipefail

if ! docker info >/dev/null 2>&1; then
  echo "Kan de Docker-daemon niet bereiken. Draait Docker, en heb je rechten op de socket?" >&2
  exit 1
fi

names=$(docker ps -a --filter "name=^earn-" --format '{{.Names}}' | sort)
if [ -z "$names" ]; then
  echo "Geen earn-* containers gevonden. Draait de stack al? (docker compose up -d)"
  exit 0
fi

printf '%-22s %-10s %-22s %-12s %-12s\n' CONTAINER STATUS SINDS RX TX
printf '%.0s-' {1..82}; echo

human() {
  awk -v b="$1" 'BEGIN{
    split("B KB MB GB TB",u," "); i=1
    while (b>=1024 && i<5){ b/=1024; i++ }
    printf "%.2f %s", b, u[i]
  }'
}

for n in $names; do
  state=$(docker inspect -f '{{.State.Status}}' "$n")
  since=$(docker inspect -f '{{.State.StartedAt}}' "$n" | cut -c1-19 | tr 'T' ' ')
  rx=0; tx=0
  if [ "$state" = "running" ]; then
    read -r rx tx < <(docker exec "$n" sh -c \
      "awk 'NR>2 && \$1 !~ /lo:/ {gsub(/:/,\" \"); r+=\$2; t+=\$10} END{print r, t}' /proc/net/dev" 2>/dev/null || echo "0 0")
  fi
  printf '%-22s %-10s %-22s %-12s %-12s\n' \
    "$n" "$state" "$since" "$(human "${rx:-0}")" "$(human "${tx:-0}")"
done

echo
echo "Tip: ./scripts/honeygain-balance.py toont je werkelijke Honeygain-saldo."
