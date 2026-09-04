#!/usr/bin/env bash
# Genereert een geldige EarnApp device-UUID (sdk-node- + 32 hex chars).
# Zet de output in .env als EARNAPP_UUID en koppel het device daarna via
# https://earnapp.com/r/<uuid>
set -euo pipefail
uuid="sdk-node-$(head -c 1024 /dev/urandom | md5sum | cut -d' ' -f1)"
echo "$uuid"
echo
echo "Zet in .env:      EARNAPP_UUID=$uuid"
echo "Koppel daarna op: https://earnapp.com/r/$uuid"
