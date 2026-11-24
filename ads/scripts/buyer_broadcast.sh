#!/bin/bash
# Broadcast to all HermesVPN buyers through the sales bot (runs on the Oracle server).
# ALWAYS run with --dry-run first and show Owner the preview; send only on his explicit order.
args=""; for a in "$@"; do args="$args $(printf '%q' "$a")"; done
exec ssh -o BatchMode=yes oracle-vpn "sudo /usr/local/bin/hermesvpn-buyer-broadcast.py $args"
