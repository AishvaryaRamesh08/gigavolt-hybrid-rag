-- ===================================================================
-- VERIFICATION QUERIES
-- ===================================================================
USE gigavolt_erp;

-- 1. CHECK FOR RECORDS THAT DIDN'T MIGRATE FROM BRONZE TO SILVER
-- ===================================================================

-- Customers not migrated
SELECT 'Customers Not Migrated' AS check_type, COUNT(*) AS record_count
FROM import_customers ic
WHERE NULLIF(TRIM(REGEXP_REPLACE(customer_id, '<[^>]+>', '')), '') IS NOT NULL
AND NOT EXISTS (
    SELECT 1 FROM customers c 
    WHERE c.customer_id = NULLIF(TRIM(REGEXP_REPLACE(ic.customer_id, '<[^>]+>', '')), '')
);

-- Equipment not migrated
SELECT 'Equipment Not Migrated' AS check_type, COUNT(*) AS record_count
FROM import_equipment ie
WHERE NULLIF(TRIM(REGEXP_REPLACE(equipment_id, '<[^>]+>', '')), '') IS NOT NULL
AND NOT EXISTS (
    SELECT 1 FROM equipment_units e 
    WHERE e.equipment_id = NULLIF(TRIM(REGEXP_REPLACE(ie.equipment_id, '<[^>]+>', '')), '')
);

-- Parts not migrated
SELECT 'Parts Not Migrated' AS check_type, COUNT(*) AS record_count
FROM import_parts ip
WHERE NULLIF(TRIM(REGEXP_REPLACE(part_id, '<[^>]+>', '')), '') IS NOT NULL
AND NOT EXISTS (
    SELECT 1 FROM parts_inventory p 
    WHERE p.part_id = NULLIF(TRIM(REGEXP_REPLACE(ip.part_id, '<[^>]+>', '')), '')
);

-- Dispatches not migrated
SELECT 'Dispatches Not Migrated' AS check_type, COUNT(*) AS record_count
FROM import_dispatches id
WHERE NULLIF(TRIM(REGEXP_REPLACE(dispatch_id, '<[^>]+>', '')), '') IS NOT NULL
AND NOT EXISTS (
    SELECT 1 FROM service_logs d 
    WHERE d.dispatch_id = NULLIF(TRIM(REGEXP_REPLACE(id.dispatch_id, '<[^>]+>', '')), '')
);

-- Warranty Claims not migrated
SELECT 'Warranty Claims Not Migrated' AS check_type, COUNT(*) AS record_count
FROM import_warranty_claims iwc
WHERE NULLIF(TRIM(REGEXP_REPLACE(claim_id, '<[^>]+>', '')), '') IS NOT NULL
AND NOT EXISTS (
    SELECT 1 FROM warranty_claims wc 
    WHERE wc.claim_id = NULLIF(TRIM(REGEXP_REPLACE(iwc.claim_id, '<[^>]+>', '')), '')
);

-- 2. DETECT CONFLICTS IN BRONZE LAYER (Duplicates)
-- ===================================================================

-- Duplicate customer IDs in staging
SELECT 'Duplicate Customer IDs' AS conflict_type, 
       TRIM(REGEXP_REPLACE(customer_id, '<[^>]+>', '')) AS id_value, 
       COUNT(*) AS duplicate_count
FROM import_customers
WHERE TRIM(customer_id) != '' AND customer_id IS NOT NULL
GROUP BY TRIM(REGEXP_REPLACE(customer_id, '<[^>]+>', ''))
HAVING COUNT(*) > 1;

-- Duplicate equipment IDs in staging
SELECT 'Duplicate Equipment IDs' AS conflict_type, 
       TRIM(REGEXP_REPLACE(equipment_id, '<[^>]+>', '')) AS id_value, 
       COUNT(*) AS duplicate_count
FROM import_equipment
WHERE TRIM(equipment_id) != '' AND equipment_id IS NOT NULL
GROUP BY TRIM(REGEXP_REPLACE(equipment_id, '<[^>]+>', ''))
HAVING COUNT(*) > 1;

-- Duplicate part IDs in staging
SELECT 'Duplicate Part IDs' AS conflict_type, 
       TRIM(REGEXP_REPLACE(part_id, '<[^>]+>', '')) AS id_value, 
       COUNT(*) AS duplicate_count
FROM import_parts
WHERE TRIM(part_id) != '' AND part_id IS NOT NULL
GROUP BY TRIM(REGEXP_REPLACE(part_id, '<[^>]+>', ''))
HAVING COUNT(*) > 1;

-- Duplicate dispatch IDs in staging
SELECT 'Duplicate Dispatch IDs' AS conflict_type, 
       TRIM(REGEXP_REPLACE(dispatch_id, '<[^>]+>', '')) AS id_value, 
       COUNT(*) AS duplicate_count
FROM import_dispatches
WHERE TRIM(dispatch_id) != '' AND dispatch_id IS NOT NULL
GROUP BY TRIM(REGEXP_REPLACE(dispatch_id, '<[^>]+>', ''))
HAVING COUNT(*) > 1;

-- Duplicate claim IDs in staging
SELECT 'Duplicate Claim IDs' AS conflict_type, 
       TRIM(REGEXP_REPLACE(claim_id, '<[^>]+>', '')) AS id_value, 
       COUNT(*) AS duplicate_count
FROM import_warranty_claims
WHERE TRIM(claim_id) != '' AND claim_id IS NOT NULL
GROUP BY TRIM(REGEXP_REPLACE(claim_id, '<[^>]+>', ''))
HAVING COUNT(*) > 1;

-- 3. DATA QUALITY ISSUES IN BRONZE LAYER
-- ===================================================================

-- Records with NULL/empty primary keys
SELECT 'Customers with NULL IDs' AS issue_type, COUNT(*) AS issue_count
FROM import_customers
WHERE customer_id IS NULL OR TRIM(customer_id) = '';

SELECT 'Equipment with NULL IDs' AS issue_type, COUNT(*) AS issue_count
FROM import_equipment
WHERE equipment_id IS NULL OR TRIM(equipment_id) = '';

-- Foreign key violations (orphaned records)
SELECT 'Equipment with Invalid Customer FK' AS issue_type, COUNT(*) AS issue_count
FROM import_equipment ie
WHERE NULLIF(TRIM(REGEXP_REPLACE(customer_id, '<[^>]+>', '')), '') IS NOT NULL
AND NOT EXISTS (
    SELECT 1 FROM customers c 
    WHERE c.customer_id = NULLIF(TRIM(REGEXP_REPLACE(ie.customer_id, '<[^>]+>', '')), '')
);

-- 4. RECORD COUNT COMPARISON
-- ===================================================================

SELECT 'Bronze vs Silver Record Counts' AS summary;

SELECT 'Customers' AS table_name,
       COUNT(*) AS bronze_count,
       (SELECT COUNT(*) FROM customers) AS silver_count,
       COUNT(*) - (SELECT COUNT(*) FROM customers) AS difference
FROM import_customers
WHERE TRIM(customer_id) != '' AND customer_id IS NOT NULL

UNION ALL

SELECT 'Equipment' AS table_name,
       COUNT(*) AS bronze_count,
       (SELECT COUNT(*) FROM equipment_units) AS silver_count,
       COUNT(*) - (SELECT COUNT(*) FROM equipment_units) AS difference
FROM import_equipment
WHERE TRIM(equipment_id) != '' AND equipment_id IS NOT NULL

UNION ALL

SELECT 'Parts' AS table_name,
       COUNT(*) AS bronze_count,
       (SELECT COUNT(*) FROM parts_inventory) AS silver_count,
       COUNT(*) - (SELECT COUNT(*) FROM parts_inventory) AS difference
FROM import_parts
WHERE TRIM(part_id) != '' AND part_id IS NOT NULL

UNION ALL

SELECT 'Dispatches' AS table_name,
       COUNT(*) AS bronze_count,
       (SELECT COUNT(*) FROM service_logs) AS silver_count,
       COUNT(*) - (SELECT COUNT(*) FROM service_logs) AS difference
FROM import_dispatches
WHERE TRIM(dispatch_id) != '' AND dispatch_id IS NOT NULL

UNION ALL

SELECT 'Warranty Claims' AS table_name,
       COUNT(*) AS bronze_count,
       (SELECT COUNT(*) FROM warranty_claims) AS silver_count,
       COUNT(*) - (SELECT COUNT(*) FROM warranty_claims) AS difference
FROM import_warranty_claims
WHERE TRIM(claim_id) != '' AND claim_id IS NOT NULL;
