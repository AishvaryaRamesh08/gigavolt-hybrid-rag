#!/bin/bash
# =============================================================================
# compare.sh - InnoDB (row store) vs ColumnStore (column store), one run.
#
# USAGE (on the node that holds the analytics tables, Node C):
#     sudo ./compare.sh
#
# WHAT IT DOES
#   For each of 5 aggregate queries it
#     1. prints the SQL,
#     2. shows the first 5 result rows from InnoDB and from ColumnStore
#        (so you can see both engines return the same answer),
#     3. times each engine, and
#     4. ends with one summary table: ms per engine and the speedup.
#
# HOW THE TIMING WORKS (so you can explain it in the video)
#   * Every timed run starts a fresh `mariadb` client process, so each run
#     carries a fixed start-up cost. We measure that cost once with "SELECT 1"
#     and subtract it, so the numbers reflect query time, not client start-up.
#   * Each query gets ONE untimed warm-up run first. The first execution reads
#     data from disk into the buffer pool / ColumnStore caches; including it
#     would measure disk speed, not the engines.
#   * We then take the AVERAGE of 3 timed runs to smooth out noise.
#   * Speedup = InnoDB ms / ColumnStore ms. Above 1.0x means ColumnStore won.
#
# WHY THESE QUERIES FAVOUR A COLUMN STORE
#   They scan every row but touch only a few of the 23 columns (sums, averages,
#   group-bys). A row store must read whole rows to do that; a column store
#   reads just the needed columns, compressed. That is the effect being shown.
# =============================================================================
set -u
DB=gigavolt_analytics
RUNS=3
INNO=svc_analytics_innodb
CS=svc_analytics_cs

NAMES=(); QUERIES=()
add() { NAMES+=("$1"); QUERIES+=("$2"); }

# Q1: several aggregates over 5 columns of a 23-column table (scan, few columns).
add "Q1 Fleet cost summary"       "SELECT COUNT(*) AS dispatches, SUM(labor_cost) AS total_labor, AVG(labor_cost) AS avg_labor, AVG(hours_spent) AS avg_hours, SUM(claim_amount_total) AS total_claimed, SUM(approved_amount_total) AS total_approved FROM {T}"
# Q2: ONE column out of 23 - the best case for a column store.
add "Q2 Single-column average"    "SELECT AVG(labor_cost) AS avg_labor_cost FROM {T}"
# Q3: GROUP BY a text column (7 groups): typical "break it down by category" report.
add "Q3 Cost by service type"     "SELECT service_type, COUNT(*) AS dispatches, AVG(labor_cost) AS avg_labor, AVG(hours_spent) AS avg_hours, SUM(claim_amount_total) AS total_claimed FROM {T} GROUP BY service_type ORDER BY total_claimed DESC"
# Q4: time-series rollup using date functions: the classic reporting query.
add "Q4 Monthly labor trend"      "SELECT YEAR(dispatch_date) AS yr, MONTH(dispatch_date) AS mo, COUNT(*) AS dispatches, SUM(labor_cost) AS total_labor, AVG(hours_spent) AS avg_hours FROM {T} GROUP BY yr, mo ORDER BY yr, mo"
# Q5: filter on NON-indexed columns, then group (~34 groups). InnoDB has no index
#     to help with the WHERE, so it must read every row.
add "Q5 Out-of-warranty by state" "SELECT customer_state, COUNT(*) AS dispatches, SUM(labor_cost) AS total_labor, SUM(claim_amount_total) AS total_claimed FROM {T} WHERE under_warranty = 0 AND dispatch_status = 'Completed' GROUP BY customer_state ORDER BY total_labor DESC"

# {T} in each query is replaced by the table name for each engine.
sql_for() { echo "${1//\{T\}/$2}"; }                       # fill in the table name

ms() {                                                      # one timed run, whole ms
  local s e
  s=$(date +%s%N)
  mariadb -N -B "$DB" -e "SET SESSION wsrep_on=OFF; $1" >/dev/null 2>&1 || return 1
  e=$(date +%s%N); echo $(( (e - s) / 1000000 ))
}
avg_ms() {                                                  # warm-up + RUNS timed, prints avg or ERR
  local i t sum=0
  ms "$1" >/dev/null || { echo ERR; return; }
  for ((i = 0; i < RUNS; i++)); do t=$(ms "$1") || { echo ERR; return; }; sum=$((sum + t)); done
  echo $((sum / RUNS))
}
show() {                                                    # print first 5 rows of a result
  mariadb -t "$DB" -e "SET SESSION wsrep_on=OFF; $1 LIMIT 5" 2>&1 | sed -e 's/^/    /'
}

# client start-up overhead
base=0
for ((i = 0; i < 5; i++)); do t=$(ms "SELECT 1") || { echo "Cannot connect to MariaDB (run with sudo?)"; exit 1; }; base=$((base + t)); done
base=$((base / 5))

echo "################################################################"
echo "  InnoDB (row store)  vs  ColumnStore (column store)"
echo "  Rows per table: $(mariadb -N -B "$DB" -e "SELECT COUNT(*) FROM $INNO") (InnoDB), $(mariadb -N -B "$DB" -e "SELECT COUNT(*) FROM $CS") (ColumnStore)"
echo "  Timing: avg of $RUNS runs after warm-up, client overhead (${base} ms) removed"
echo "################################################################"

RES_I=(); RES_C=()
for idx in "${!NAMES[@]}"; do
  q="${QUERIES[$idx]}"
  echo; echo "=== ${NAMES[$idx]} ==="
  echo "  SQL: $(sql_for "$q" "<table>")"
  echo "  --- InnoDB result (first 5 rows) ---";      show "$(sql_for "$q" $INNO)"
  echo "  --- ColumnStore result (first 5 rows) ---"; show "$(sql_for "$q" $CS)"
  ti=$(avg_ms "$(sql_for "$q" $INNO)"); tc=$(avg_ms "$(sql_for "$q" $CS)")
  [ "$ti" = ERR ] || { ti=$((ti - base)); [ "$ti" -lt 1 ] && ti=1; }
  [ "$tc" = ERR ] || { tc=$((tc - base)); [ "$tc" -lt 1 ] && tc=1; }
  RES_I+=("$ti"); RES_C+=("$tc")
  echo "  >> InnoDB: ${ti} ms   |   ColumnStore: ${tc} ms"
done

echo; echo "======================== SUMMARY ========================"
printf "%-28s %12s %18s %10s\n" "Query" "InnoDB (ms)" "ColumnStore (ms)" "Speedup"
printf -- "------------------------------------------------------------------------\n"
ti_tot=0; tc_tot=0
for idx in "${!NAMES[@]}"; do
  ti="${RES_I[$idx]}"; tc="${RES_C[$idx]}"
  if [ "$ti" = ERR ] || [ "$tc" = ERR ]; then
    printf "%-28s %12s %18s %10s\n" "${NAMES[$idx]}" "$ti" "$tc" "failed"; continue
  fi
  ti_tot=$((ti_tot + ti)); tc_tot=$((tc_tot + tc))
  printf "%-28s %12s %18s %9sx\n" "${NAMES[$idx]}" "$ti" "$tc" "$(awk -v a="$ti" -v b="$tc" 'BEGIN{printf "%.1f", a/b}')"
done
printf -- "------------------------------------------------------------------------\n"
[ "$tc_tot" -gt 0 ] && printf "%-28s %12s %18s %9sx\n" "TOTAL" "$ti_tot" "$tc_tot" "$(awk -v a="$ti_tot" -v b="$tc_tot" 'BEGIN{printf "%.1f", a/b}')"
echo "Speedup = InnoDB time / ColumnStore time (above 1.0x means ColumnStore was faster)."
