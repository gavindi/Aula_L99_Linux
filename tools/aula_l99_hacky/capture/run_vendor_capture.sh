#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
SHIM="$ROOT/tools/aula_l99_hacky/capture/wine_ioctl_shim.so"
APP="$ROOT/Windows/AULA L99/DeviceDriver.exe"
NAME="${1:-cap_default}"
LOG="$ROOT/tools/aula_l99_hacky/capture/logs/${NAME}.log"

RUNBOOK=()
case "${1:-}" in
    response_time)
        RUNBOOK=(
            "PRESET response_time -- vendor app, keyboard settings panel"
            "  step the Response Time dropdown: 1 -> 2 -> 3 -> 4 -> 5, ~2s apart"
            "  quit the app when done"
            "  expect on the wire (settings_write.md): a 0x17 session per step,"
            "  byte[8] (response-time slot) sweeping 1..5 while byte[6] holds"
            "  its last value -- levels decoded in protocol.RESPONSE_TIME_DELAYS_MS"
        )
        ;;
    sleep_timer|sleep_time)
        RUNBOOK=(
            "PRESET sleep_timer -- vendor app, keyboard settings panel"
            "  step the Sleep Time dropdown: 0 -> 1 -> 2 -> 3, ~2s apart"
            "  quit the app when done"
            "  expect on the wire (settings_write.md): a 0x17 session per step,"
            "  byte[6] (sleep-time slot) sweeping 0..3 while byte[8] holds"
            "  its last value -- 0 = no sleep, 1 = 1 min, 2 = 5 min, 3 = 30 min"
        )
        ;;
    settings)
        RUNBOOK=(
            "PRESET settings -- vendor app, keyboard settings panel, one session"
            "  step Response Time 1 -> 2 -> 3 -> 4 -> 5 (~2s apart), then"
            "  step Sleep Time 0 -> 1 -> 2 -> 3 (~2s apart)"
            "  quit the app when done"
            "  every 0x17 write carries both slots, so one capture cross-"
            "  validates the whole panel -- parse with --settings"
        )
        ;;
esac

if [[ ${#RUNBOOK[@]} -gt 0 ]]; then
    printf '%s\n' "${RUNBOOK[@]}" >&2
    echo >&2
fi

if [[ ! -f "$SHIM" ]]; then
    echo "shim not built: $SHIM" >&2
    echo "run tools/aula_l99_hacky/capture/build_shim.sh first" >&2
    exit 1
fi
if [[ ! -f "$APP" ]]; then
    echo "vendor app not found: $APP" >&2
    exit 1
fi

mkdir -p "$(dirname "$LOG")"
echo "killing wineserver (all wine processes must be dead so the shim is picked up)..." >&2
wineserver -k 2>/dev/null || true
sleep 1

export AULA_IOCTL_LOG="$LOG"
export LD_PRELOAD="$SHIM"
echo "capture -> $LOG" >&2
echo "launching vendor app; quit it when the capture is done..." >&2
cd "$ROOT"
wine "$APP"
echo "capture complete: $LOG" >&2
