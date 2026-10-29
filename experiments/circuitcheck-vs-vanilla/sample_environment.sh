#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: sample_environment.sh OUTPUT_LOG STOP_FILE" >&2
  exit 2
fi

output_log="$1"
stop_file="$2"
mkdir -p "$(dirname "$output_log")"

printf 'timestamp\tloadavg\tcpu0_khz\tcpu20_khz\tcpu0_stat\tcpu20_stat\tcpu20_tasks\n' >"$output_log"
while [[ ! -e "$stop_file" ]]; do
  timestamp="$(date -Ins)"
  loadavg="$(tr ' ' ',' </proc/loadavg)"
  cpu0_khz="$(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq 2>/dev/null || printf 'NA')"
  cpu20_khz="$(cat /sys/devices/system/cpu/cpu20/cpufreq/scaling_cur_freq 2>/dev/null || printf 'NA')"
  cpu0_stat="$(awk '$1 == "cpu0" {$1=""; sub(/^ /, ""); gsub(/ /, ","); print}' /proc/stat)"
  cpu20_stat="$(awk '$1 == "cpu20" {$1=""; sub(/^ /, ""); gsub(/ /, ","); print}' /proc/stat)"
  cpu20_tasks="$(ps -eLo pid=,tid=,psr=,pcpu=,comm= 2>/dev/null | awk '$3 == 20 {gsub(/^ +| +$/, ""); gsub(/ +/, ":"); printf "%s;", $0}' || true)"
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$timestamp" "$loadavg" "$cpu0_khz" "$cpu20_khz" \
    "$cpu0_stat" "$cpu20_stat" "$cpu20_tasks" >>"$output_log"
  sleep 1
done

