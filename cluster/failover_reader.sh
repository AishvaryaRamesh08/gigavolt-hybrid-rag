#!/bin/bash
# =============================================================================
# failover_reader.sh - once a second, show what THIS node sees: cluster size, state,
# and how many heartbeat rows it can read.
#
#   ./failover_reader.sh            (run on another surviving node, e.g. Node C)
#   ./failover_reader.sh 20         (optional: stop after 20 reads)
#
# Watch cluster_size drop from 3 to 2 when the node dies and return to 3 after it
# rejoins, while the row count keeps growing: reads never stop.
# =============================================================================
MAX="${1:-0}"
n=0
printf "%-9s %-12s %-10s %-10s %-10s %s\n" "time" "cluster_size" "status" "state" "rows" "max_id"
while :; do
  n=$((n + 1))
  out=$(timeout 10 mariadb -N -B -e "
    SELECT VARIABLE_VALUE FROM information_schema.GLOBAL_STATUS WHERE VARIABLE_NAME='WSREP_CLUSTER_SIZE';
    SELECT VARIABLE_VALUE FROM information_schema.GLOBAL_STATUS WHERE VARIABLE_NAME='WSREP_CLUSTER_STATUS';
    SELECT VARIABLE_VALUE FROM information_schema.GLOBAL_STATUS WHERE VARIABLE_NAME='WSREP_LOCAL_STATE_COMMENT';
    SELECT COUNT(*), COALESCE(MAX(id),0) FROM failover_test.heartbeat;" 2>&1)
  if echo "$out" | grep -q "ERROR" || [ -z "$out" ]; then
    printf "%-9s %s\n" "$(date +%H:%M:%S)" "READ FAILED: $(echo "$out" | head -1)"
  else
    size=$(echo "$out" | sed -n 1p); st=$(echo "$out" | sed -n 2p); state=$(echo "$out" | sed -n 3p)
    read -r rows maxid <<< "$(echo "$out" | sed -n 4p)"
    printf "%-9s %-12s %-10s %-10s %-10s %s\n" "$(date +%H:%M:%S)" "$size" "$st" "$state" "$rows" "$maxid"
  fi
  [ "$MAX" -gt 0 ] && [ "$n" -ge "$MAX" ] && exit 0
  sleep 1
done
