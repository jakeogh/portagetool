#!/bin/bash
# https://wiki.gentoo.org/wiki/User:Sam/PORTAGE_NICENESS
set -o nounset

PID="${1}"

# Could use `ionice -c 2 -n 7 -p ${PID}` to be slightly less aggressive.
ionice -c 3 -p "${PID}"
chrt -p -i 0 "${PID}"
