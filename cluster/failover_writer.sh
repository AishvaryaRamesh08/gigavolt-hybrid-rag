#!/bin/bash
# =============================================================================
# failover_writer.sh - write one row per second to failover_test.heartbeat.
#
#   ./failover_writer.sh            (run on a node that will SURVIVE, e.g. Node B)
#   ./failover_writer.sh 20         (optional: stop after 20 writes)
#   Press Ctrl-C to stop; a summary is printed.
#
# It keeps going through errors, so you can SEE what happens to writes while the
# cluster loses a node: a short pause while Galera detects the failure, then
# writes continue. Each line shows the insert latency in milliseconds.
# =============================================================================
MAX="${1:-0}"                       # 0 = run until Ctrl-C
HOST=$(hostname)
n=0; ok=0; bad=0

summary() { echo; echo "----- writer summary on $HOST: $ok OK, $bad FAILED, of $n attempts -----"; exit 0; }
trap summary INT TERM

while :; do
  n=$((n + 1))
  start=$(date +%s%N)
  # timeout: a write can block briefly while the cluster re-forms; do not hang forever
  out=$(timeout 30 mariadb -N -B -e \
        "INSERT INTO failover_test.heartbeat (written_by, note) VALUES ('$HOST', 'write $n'); SELECT LAST_INSERT_ID();" 2>&1)
  rc=$?
  ms=$(( ($(date +%s%N) - start) / 1000000 ))
  now=$(date +%H:%M:%S)

  if [ $rc -eq 0 ] && ! echo "$out" | grep -q "ERROR"; then
    ok=$((ok + 1)); echo "$now  OK    id=$out  (${ms} ms)"
  elif [ $rc -eq 124 ]; then
    bad=$((bad + 1)); echo "$now  TIMEOUT after 30 s"
  else
    bad=$((bad + 1)); echo "$now  FAIL  $(echo "$out" | head -1)"
  fi

  [ "$MAX" -gt 0 ] && [ "$n" -ge "$MAX" ] && summary
  sleep 1
done
