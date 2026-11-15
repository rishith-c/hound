#!/bin/sh
# deploy.sh — push the Pi-side code to the Pi over the LAN.
#   pi/deploy.sh                 rsync pi/rover/ → ~/rover/ on the Pi
#   pi/deploy.sh --setup         also run setup_pi.sh there (first time; installs libs + arduino-cli)
#   pi/deploy.sh --demo [arg]    then run demo.py on the Pi
# Host: $PI_HOST or the default below.
set -e
PI="${PI_HOST:-rishithc@rishithc.local}"
DIR="$(cd "$(dirname "$0")" && pwd)"

command rsync -az --delete --exclude venv --exclude '__pycache__' --exclude web.key --exclude pan_trim --exclude tunnel_url.sh --exclude radars.json --exclude stations.jsonl --exclude 'MobileNetSSD*' "$DIR/rover/" "$PI:rover/"
command rsync -az "$DIR/setup_pi.sh" "$PI:rover/setup_pi.sh"

case "$1" in
  --setup) command ssh "$PI" 'sh rover/setup_pi.sh' ;;
  --demo)  shift; command ssh -t "$PI" "cd rover && venv/bin/python demo.py $*" ;;
  *)       command ssh "$PI" 'echo deployed to $(hostname): && ls rover' ;;
esac
