-- =====================================================================
-- PHASE 2 VALIDATION SCRIPT
-- One test per objective. Run PART 1-3 as root/admin; run
-- PART 4 in separate sessions as the demo login accounts.
-- =====================================================================
USE gigavolt_erp;


-- =====================================================================
-- TEST 1: Stored procedure executes and produces well-formatted output
-- Success = a summary row (counts + char-length stats) is returned and
-- rag_payloads is populated with a readable embedding-ready block.
-- =====================================================================
CALL sp_Prepare_RAG_Payloads(FALSE);   -- returns summary result set

-- Show one full, well-formatted service-event payload (equipment +
-- customer + warranty context) and its provenance metadata
SELECT source_id, equipment_model, warranty_status, char_length, payload_text, metadata
FROM rag_payloads
WHERE payload_type = 'service_event'
ORDER BY char_length DESC
LIMIT 1;

-- Show one warranty-claim payload that has no dispatch link
SELECT source_id, equipment_id, payload_text
FROM rag_payloads
WHERE payload_type = 'warranty_claim'
LIMIT 1;

-- Provenance check: metadata is queryable JSON
SELECT JSON_VALUE(metadata, '$.source_table') AS src, COUNT(*) AS n
FROM rag_payloads
GROUP BY src;


-- =====================================================================
-- TEST 2: Triggers fire correctly on the specified DML operations
-- Success = one INSERT then one UPDATE on service_logs produces TWO
-- Audit_Logs rows: an 'INSERT' row and an 'UPDATE' row.
-- equipment_id/customer_id left NULL to avoid FK issues (both are
-- nullable in the schema).
-- =====================================================================
INSERT INTO service_logs
  (dispatch_id, equipment_id, customer_id, dispatch_date,
   technician, service_type, hours_spent, labor_cost,
   resolution_summary, status)
VALUES
  ('DISP-VALID01', NULL, NULL, '2026-01-15',
   'Demo Tech', 'Diagnostic', 2.0, 150.00,
   'Initial diagnostic for validation test.', 'Completed');   -- fires AFTER INSERT

UPDATE service_logs
SET status = 'Cancelled', labor_cost = 275.50
WHERE dispatch_id = 'DISP-VALID01';                            -- fires BEFORE UPDATE

-- Expect exactly two rows: one INSERT, one UPDATE
SELECT operation_type, record_id, changed_by, change_desc
FROM Audit_Logs
WHERE record_id = 'DISP-VALID01'
ORDER BY audit_id;


-- =====================================================================
-- TEST 3: Audit logs capture COMPLETE change history
-- Success = the UPDATE row's JSON shows both the pre-change (old) and
-- post-change (new) values for the fields that changed, extractable
-- with JSON_VALUE()[14].
-- =====================================================================
SELECT
  record_id,
  JSON_VALUE(old_values, '$.status')     AS old_status,
  JSON_VALUE(new_values, '$.status')     AS new_status,
  JSON_VALUE(old_values, '$.labor_cost') AS old_labor_cost,
  JSON_VALUE(new_values, '$.labor_cost') AS new_labor_cost
FROM Audit_Logs
WHERE record_id = 'DISP-VALID01'
  AND operation_type = 'UPDATE';
-- Expected: old_status='Completed' -> new_status='Cancelled',
--           old_labor_cost=150.00  -> new_labor_cost=275.50


-- =====================================================================
-- TEST 4: Security policies prevent unauthorized data access
-- Run these in a SEPARATE terminal, logged in as the demo accounts
-- (NOT root, since root bypasses the view restriction).
-- Success = support sees masked PII and is DENIED the base table;
-- manager sees full PII and is DENIED the base table.
-- =====================================================================
-- ---- Terminal A:  mariadb -u demo_support -p gigavolt_erp ----
-- SELECT * FROM v_customers_masked LIMIT 3;   -- WORKS (PII masked)
-- SELECT * FROM customers          LIMIT 3;   -- ERROR: access denied
-- SELECT * FROM v_customers_full   LIMIT 3;   -- ERROR: access denied

-- ---- Terminal B:  mariadb -u demo_manager -p gigavolt_erp ----
-- SELECT * FROM v_customers_full LIMIT 3;     -- WORKS (full PII)
-- SELECT * FROM customers        LIMIT 3;     -- ERROR: access denied