#!/usr/bin/env bash
set -euo pipefail

result_root="${FIG3_RESULT_ROOT:-$HOME/BioZero_remote/results/fig3_full_20261028}"
cache_root="${FIG3_CACHE_ROOT:-$HOME/BioZero_remote/cache-fig3-full-20261028}"
latency_pid="$(cat "$result_root/logs/latency.pid")"
child_log="$result_root/logs/zokrates-child-resources.tsv"
host_log="$result_root/logs/host-load-frequency.log"
clock_ticks="$(getconf CLK_TCK)"
if [ ! -s "$child_log" ]; then
  printf 'pid\tobserved_start_epoch\tobserved_wall_s\tuser_s\tsystem_s\tmax_rss_kib\trayon_num_threads\tcwd\tcommand\n' >"$child_log"
fi
if [ ! -s "$host_log" ]; then
  lscpu >"$host_log"
else
  printf '\n[%s] resource monitor restarted\n' "$(date -Is)" >>"$host_log"
fi

monitor_child() {
  local pid="$1"
  local start now elapsed user_ticks system_ticks max_rss rayon cwd command
  start="$(date +%s.%N)"
  user_ticks=0
  system_ticks=0
  max_rss=0
  cwd="$(readlink -f "/proc/$pid/cwd" 2>/dev/null || true)"
  command="$(tr '\0' ' ' <"/proc/$pid/cmdline" 2>/dev/null || true)"
  rayon="$(tr '\0' '\n' <"/proc/$pid/environ" 2>/dev/null | awk -F= '$1 == "RAYON_NUM_THREADS" {print $2}' || true)"
  if [ -z "$rayon" ]; then rayon="unset"; fi
  while [ -r "/proc/$pid/stat" ]; do
    stat_values="$(awk '{print $14, $15}' "/proc/$pid/stat" 2>/dev/null || true)"
    if [ -n "$stat_values" ]; then read -r user_ticks system_ticks <<<"$stat_values"; fi
    current_rss="$(awk '/^VmHWM:/ {print $2}' "/proc/$pid/status" 2>/dev/null || true)"
    if [ -n "$current_rss" ] && [ "$current_rss" -gt "$max_rss" ]; then max_rss="$current_rss"; fi
    sleep 0.1
  done
  now="$(date +%s.%N)"
  elapsed="$(awk -v a="$start" -v b="$now" 'BEGIN {printf "%.6f", b-a}')"
  user_s="$(awk -v ticks="$user_ticks" -v hz="$clock_ticks" 'BEGIN {printf "%.6f", ticks/hz}')"
  system_s="$(awk -v ticks="$system_ticks" -v hz="$clock_ticks" 'BEGIN {printf "%.6f", ticks/hz}')"
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$pid" "$start" "$elapsed" "$user_s" "$system_s" "$max_rss" "$rayon" "$cwd" "$command" >>"$child_log"
}

last_host_snapshot=0
while kill -0 "$latency_pid" 2>/dev/null; do
  now_seconds="$(date +%s)"
  if [ $((now_seconds - last_host_snapshot)) -ge 60 ]; then
    {
      printf '\n[%s]\n' "$(date -Is)"
      uptime
      free -h
      if compgen -G '/sys/devices/system/cpu/cpu*/cpufreq/scaling_cur_freq' >/dev/null; then
        awk '{sum+=$1; count+=1} END {if (count) printf "mean_scaling_cur_freq_khz=%.0f cpus=%d\n", sum/count, count}' \
          /sys/devices/system/cpu/cpu*/cpufreq/scaling_cur_freq
      fi
      ps -eo user,pid,ppid,etime,%cpu,%mem,rss,cmd --sort=-%cpu | head -12
    } >>"$host_log"
    last_host_snapshot="$now_seconds"
  fi

  child=""
  for candidate in $(pgrep -u "$USER" -f '/zokrates (generate-proof|compute-witness|verify)' || true); do
    candidate_cwd="$(readlink -f "/proc/$candidate/cwd" 2>/dev/null || true)"
    if [[ "$candidate_cwd" == "$cache_root"/* ]]; then child="$candidate"; break; fi
  done
  if [ -n "$child" ]; then monitor_child "$child"
  else sleep 0.1
  fi
done
