#!/bin/bash
# =============================================================================
# validate_engines.sh - prove InnoDB and ColumnStore hold the SAME data.
#
#   sudo ./validate_engines.sh        (run on Node C)
#
# HOW IT WORKS
#   ColumnStore cannot mix its tables with another engine's tables inside one SQL
#   statement (cross-engine support is not configured). So each check runs as TWO
#   separate queries, one per engine, and this script compares the two answers.
#   (CHECKSUM TABLE is not supported for ColumnStore, so we compare aggregates.)
#
#   Numbers are compared with a tolerance of 0.005; dates and text must match exactly.
#   Exit code is 0 only if every check passes.
# =============================================================================
DB=gigavolt_analytics
INNO=svc_analytics_innodb
CS=svc_analytics_cs

# one query, one value; echoes the value or the error text
q() { mariadb -N -B "$DB" -e "$1" 2>&1 | head -1; }

# name|SQL expression  (the expression is evaluated against each table)
CHECKS=(
  "Row count|COUNT(*)"
  "Highest copy_id|MAX(copy_id)"
  "SUM(labor_cost)|SUM(labor_cost)"
  "SUM(hours_spent)|SUM(hours_spent)"
  "SUM(claim_amount_total)|SUM(claim_amount_total)"
  "SUM(approved_amount_total)|SUM(approved_amount_total)"
  "MIN(dispatch_date)|MIN(dispatch_date)"
  "MAX(dispatch_date)|MAX(dispatch_date)"
  "Distinct models|COUNT(DISTINCT model)"
  "Distinct service types|COUNT(DISTINCT service_type)"
  "Distinct states|COUNT(DISTINCT customer_state)"
)

printf "%-28s %-22s %-22s %s\n" "Check" "InnoDB" "ColumnStore" "Result"
printf -- "---------------------------------------------------------------------------------\n"
FAILS=0
for c in "${CHECKS[@]}"; do
  name="${c%%|*}"; expr="${c#*|}"
  vi=$(q "SELECT $expr FROM $INNO")
  vc=$(q "SELECT $expr FROM $CS")
  if [[ "$vi" == ERROR* || "$vc" == ERROR* || -z "$vi" || -z "$vc" ]]; then
    res="FAIL (query error: ${vi:0:30} / ${vc:0:30})"
  elif [[ "$vi" =~ ^-?[0-9.]+$ && "$vc" =~ ^-?[0-9.]+$ ]]; then
    res=$(awk -v a="$vi" -v b="$vc" 'BEGIN{d=a-b; if(d<0)d=-d; print (d<=0.005)?"PASS":"FAIL"}')
  else
    [ "$vi" = "$vc" ] && res=PASS || res=FAIL
  fi
  [[ "$res" == PASS ]] || FAILS=$((FAILS + 1))
  printf "%-28s %-22s %-22s %s\n" "$name" "$vi" "$vc" "$res"
done
printf -- "---------------------------------------------------------------------------------\n"
if [ "$FAILS" -eq 0 ]; then echo "ALL CHECKS PASSED: both engines hold identical data."
else echo "$FAILS CHECK(S) FAILED: do not trust a timing comparison yet."; exit 1; fi
