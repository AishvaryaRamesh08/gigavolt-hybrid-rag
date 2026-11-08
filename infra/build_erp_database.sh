#!/bin/bash
# Builds the ERP side of the Phase 5 pipeline, in order. Run on EC2 as ubuntu:
#   bash build_erp_database.sh [sql_dir]        (default /opt/gigavolt/sql)
# CSVs must already be in /opt/data (02_load_staging.sql reads /opt/data/*.csv).
set -euo pipefail
D="${1:-/opt/gigavolt/sql}"
run() { echo ">>> $1"; sudo mariadb --local-infile=1 < "$D/$1"; }

run 01_staging_tables.sql        # Bronze: import_* tables (DROPs + recreates gigavolt_erp)
run 02_load_staging.sql        # Bronze: LOAD DATA from /opt/data/*.csv
run 03_silver_tables.sql         # Silver: 3NF tables
run 04_cleanse_to_silver.sql         # Silver: cleanse + dedupe + load
run 06_rag_payloads_table.sql   # rag_payloads table
run 07_sp_prepare_rag_payloads.sql                 # sp_Prepare_RAG_Payloads()

echo ">>> CALL sp_Prepare_RAG_Payloads(FALSE)"
sudo mariadb gigavolt_erp -e "CALL sp_Prepare_RAG_Payloads(FALSE);"
echo ">>> row counts"
sudo mariadb gigavolt_erp -e "
SELECT 'customers' t, COUNT(*) n FROM customers UNION ALL
SELECT 'equipment_units', COUNT(*) FROM equipment_units UNION ALL
SELECT 'service_logs', COUNT(*) FROM service_logs UNION ALL
SELECT 'warranty_claims', COUNT(*) FROM warranty_claims UNION ALL
SELECT 'parts_inventory', COUNT(*) FROM parts_inventory UNION ALL
SELECT 'rag_payloads', COUNT(*) FROM rag_payloads;"
