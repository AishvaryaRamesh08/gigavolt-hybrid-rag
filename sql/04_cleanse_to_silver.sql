use gigavolt_erp;

-- ------------------------------------------------------------------
-- Step 1: locations — cleaned zip/city/state/country, deduped
--   HTML tags are stripped from every column here, not just the ones
--   profiling showed had tags, as a defensive measure (matches the
--   sample script's blanket-stripping approach).
-- ------------------------------------------------------------------
INSERT IGNORE INTO locations (zip, city, state, country)
SELECT DISTINCT
    LPAD(TRIM(REGEXP_REPLACE(zip, '<[^>]+>', '')), 5, '0') AS zip,
    TRIM(REGEXP_REPLACE(city, '<[^>]+>', '')) AS city,
    UPPER(TRIM(REGEXP_REPLACE(state, '<[^>]+>', ''))) AS state,
    CASE
        WHEN UPPER(TRIM(REGEXP_REPLACE(country, '<[^>]+>', ''))) IN ('US', 'USA', 'UNITED STATES') THEN 'USA'
        ELSE NULLIF(TRIM(REGEXP_REPLACE(country, '<[^>]+>', '')), '')
    END AS country
FROM import_customers
WHERE zip IS NOT NULL AND TRIM(zip) != '';

-- Backfill country where it was blank/NULL in the source but state is a
-- valid US state code — every distinct state value in this dataset is a
-- real USPS code (no Canadian provinces or other countries present), so
-- state alone already identifies these as US locations. This is filling
-- in an omission, not inferring unknown data.
UPDATE locations
SET country = 'USA'
WHERE country IS NULL
  AND state IN (
    'AL','AK','AZ','AR','CA','CO','CT','DE','FL','GA','HI','ID','IL','IN',
    'IA','KS','KY','LA','ME','MD','MA','MI','MN','MS','MO','MT','NE','NV',
    'NH','NJ','NM','NY','NC','ND','OH','OK','OR','PA','RI','SC','SD','TN',
    'TX','UT','VT','VA','WA','WV','WI','WY','DC'
  );

-- ------------------------------------------------------------------
-- Step 2: customers — cleanse, dedupe, and load in one pass
-- ------------------------------------------------------------------
INSERT INTO customers
WITH parsed AS (
    SELECT
        TRIM(REGEXP_REPLACE(customer_id, '<[^>]+>', '')) AS customer_id,
        REGEXP_REPLACE(company_name, '<[^>]+>', '') AS company_name,
        REGEXP_REPLACE(contact_name, '<[^>]+>', '') AS contact_name,
        REGEXP_REPLACE(phone, '<[^>]+>', '') AS phone,
        REGEXP_REPLACE(email, '<[^>]+>', '') AS email,
        REGEXP_REPLACE(address, '<[^>]+>', '') AS address,
        REGEXP_REPLACE(zip, '<[^>]+>', '') AS zip,
        REGEXP_REPLACE(status, '<[^>]+>', '') AS status,
        CASE
            WHEN REGEXP_REPLACE(created_date, '<[^>]+>', '') REGEXP '^[0-9]{4}-[0-9]{2}-[0-9]{2}T'
                THEN STR_TO_DATE(LEFT(REGEXP_REPLACE(created_date, '<[^>]+>', ''), 10), '%Y-%m-%d')
            WHEN REGEXP_REPLACE(created_date, '<[^>]+>', '') REGEXP '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
                THEN STR_TO_DATE(REGEXP_REPLACE(created_date, '<[^>]+>', ''), '%Y-%m-%d')
            WHEN REGEXP_REPLACE(created_date, '<[^>]+>', '') REGEXP '^[0-9]{4}/[0-9]{2}/[0-9]{2}$'
                THEN STR_TO_DATE(REGEXP_REPLACE(created_date, '<[^>]+>', ''), '%Y/%m/%d')
            WHEN REGEXP_REPLACE(created_date, '<[^>]+>', '') REGEXP '^[0-9]{2}/[0-9]{2}/[0-9]{4}$'
                THEN STR_TO_DATE(REGEXP_REPLACE(created_date, '<[^>]+>', ''), '%m/%d/%Y')
            WHEN REGEXP_REPLACE(created_date, '<[^>]+>', '') REGEXP '^[0-9]{2}-[0-9]{2}-[0-9]{4}$'
                THEN STR_TO_DATE(REGEXP_REPLACE(created_date, '<[^>]+>', ''), '%m-%d-%Y')
            ELSE NULL
        END AS created_date_parsed
    FROM import_customers
),
ranked AS (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY customer_id
            ORDER BY created_date_parsed DESC
        ) AS rn
    FROM parsed
)
SELECT
    customer_id,
    TRIM(REGEXP_REPLACE(company_name, '\\s+', ' ')) AS company_name,
    TRIM(REGEXP_REPLACE(contact_name, '\\s+', ' ')) AS contact_name,

    -- keep only digits, format as (XXX) XXX-XXXX, drop leading US "1"
    CASE
        WHEN LENGTH(REGEXP_REPLACE(phone, '[^0-9]', '')) = 10
            THEN CONCAT(
                '(', SUBSTRING(REGEXP_REPLACE(phone, '[^0-9]', ''), 1, 3), ') ',
                SUBSTRING(REGEXP_REPLACE(phone, '[^0-9]', ''), 4, 3), '-',
                SUBSTRING(REGEXP_REPLACE(phone, '[^0-9]', ''), 7, 4)
            )
        WHEN LENGTH(REGEXP_REPLACE(phone, '[^0-9]', '')) = 11
             AND LEFT(REGEXP_REPLACE(phone, '[^0-9]', ''), 1) = '1'
            THEN CONCAT(
                '(', SUBSTRING(REGEXP_REPLACE(phone, '[^0-9]', ''), 2, 3), ') ',
                SUBSTRING(REGEXP_REPLACE(phone, '[^0-9]', ''), 5, 3), '-',
                SUBSTRING(REGEXP_REPLACE(phone, '[^0-9]', ''), 8, 4)
            )
        ELSE NULL
    END AS phone,

    LOWER(TRIM(email)) AS email,
    TRIM(REGEXP_REPLACE(address, '\\s+', ' ')) AS address,

    -- must match Step 1's zip cleaning exactly, or the FK breaks
    LPAD(TRIM(zip), 5, '0') AS zip,

    created_date_parsed AS created_date,

    CASE LOWER(TRIM(status))
        WHEN 'active'   THEN 'Active'
        WHEN 'inactive' THEN 'Inactive'
        WHEN 'pending'  THEN 'Pending'
        ELSE NULL
    END AS status

FROM ranked
WHERE rn = 1;

-- ------------------------------------------------------------------
-- Step 1: equipment_models — cleaned, deduped model -> capacity/voltage
-- ------------------------------------------------------------------
INSERT IGNORE INTO equipment_models (model, capacity_kw, voltage)
SELECT DISTINCT
    TRIM(REGEXP_REPLACE(model, '<[^>]+>', '')) AS model,
    CAST(TRIM(REGEXP_REPLACE(capacity_kw, '<[^>]+>', '')) AS UNSIGNED) AS capacity_kw,
    CAST(REPLACE(UPPER(TRIM(REGEXP_REPLACE(voltage, '<[^>]+>', ''))), 'V', '') AS UNSIGNED) AS voltage
FROM import_equipment
WHERE model IS NOT NULL AND TRIM(model) != '';

-- ------------------------------------------------------------------
-- Step 2: equipment_units — cleanse, dedupe, and load in one pass
--   Dedup rule (no timestamp column exists to determine recency):
--     - "Decommissioned" wins if present in a duplicate group
--     - otherwise last-occurring row in file wins (temp table used
--       only to sequence this transformation, never touches the
--       staging table's schema)
-- ------------------------------------------------------------------
DROP TEMPORARY TABLE IF EXISTS tmp_equipment_ordered;

CREATE TEMPORARY TABLE tmp_equipment_ordered (
    row_id INT AUTO_INCREMENT PRIMARY KEY,
    equipment_id TEXT,
    customer_id TEXT,
    model TEXT,
    serial_number TEXT,
    install_date TEXT,
    warranty_expiration TEXT,
    status TEXT,
    location_notes TEXT
);

INSERT INTO tmp_equipment_ordered
    (equipment_id, customer_id, model, serial_number,
     install_date, warranty_expiration, status, location_notes)
SELECT
    equipment_id, customer_id, model, serial_number,
    install_date, warranty_expiration, status, location_notes
FROM import_equipment;

INSERT INTO equipment_units
WITH parsed AS (
    SELECT
        row_id,
        TRIM(REGEXP_REPLACE(equipment_id, '<[^>]+>', '')) AS equipment_id,
        TRIM(REGEXP_REPLACE(customer_id, '<[^>]+>', '')) AS customer_id,
        TRIM(REGEXP_REPLACE(model, '<[^>]+>', '')) AS model,
        REGEXP_REPLACE(serial_number, '<[^>]+>', '') AS serial_number,
        REGEXP_REPLACE(location_notes, '<[^>]+>', '') AS location_notes,

        CASE
            WHEN REGEXP_REPLACE(install_date, '<[^>]+>', '') REGEXP '^[0-9]{4}-[0-9]{2}-[0-9]{2}T'
                THEN STR_TO_DATE(LEFT(REGEXP_REPLACE(install_date, '<[^>]+>', ''), 10), '%Y-%m-%d')
            WHEN REGEXP_REPLACE(install_date, '<[^>]+>', '') REGEXP '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
                THEN STR_TO_DATE(REGEXP_REPLACE(install_date, '<[^>]+>', ''), '%Y-%m-%d')
            WHEN REGEXP_REPLACE(install_date, '<[^>]+>', '') REGEXP '^[0-9]{4}/[0-9]{2}/[0-9]{2}$'
                THEN STR_TO_DATE(REGEXP_REPLACE(install_date, '<[^>]+>', ''), '%Y/%m/%d')
            WHEN REGEXP_REPLACE(install_date, '<[^>]+>', '') REGEXP '^[0-9]{2}/[0-9]{2}/[0-9]{4}$'
                THEN STR_TO_DATE(REGEXP_REPLACE(install_date, '<[^>]+>', ''), '%m/%d/%Y')
            WHEN REGEXP_REPLACE(install_date, '<[^>]+>', '') REGEXP '^[0-9]{2}-[0-9]{2}-[0-9]{4}$'
                THEN STR_TO_DATE(REGEXP_REPLACE(install_date, '<[^>]+>', ''), '%m-%d-%Y')
            ELSE NULL
        END AS install_date_parsed,

        CASE
            WHEN REGEXP_REPLACE(warranty_expiration, '<[^>]+>', '') REGEXP '^[0-9]{4}-[0-9]{2}-[0-9]{2}T'
                THEN STR_TO_DATE(LEFT(REGEXP_REPLACE(warranty_expiration, '<[^>]+>', ''), 10), '%Y-%m-%d')
            WHEN REGEXP_REPLACE(warranty_expiration, '<[^>]+>', '') REGEXP '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
                THEN STR_TO_DATE(REGEXP_REPLACE(warranty_expiration, '<[^>]+>', ''), '%Y-%m-%d')
            WHEN REGEXP_REPLACE(warranty_expiration, '<[^>]+>', '') REGEXP '^[0-9]{4}/[0-9]{2}/[0-9]{2}$'
                THEN STR_TO_DATE(REGEXP_REPLACE(warranty_expiration, '<[^>]+>', ''), '%Y/%m/%d')
            WHEN REGEXP_REPLACE(warranty_expiration, '<[^>]+>', '') REGEXP '^[0-9]{2}/[0-9]{2}/[0-9]{4}$'
                THEN STR_TO_DATE(REGEXP_REPLACE(warranty_expiration, '<[^>]+>', ''), '%m/%d/%Y')
            WHEN REGEXP_REPLACE(warranty_expiration, '<[^>]+>', '') REGEXP '^[0-9]{2}-[0-9]{2}-[0-9]{4}$'
                THEN STR_TO_DATE(REGEXP_REPLACE(warranty_expiration, '<[^>]+>', ''), '%m-%d-%Y')
            ELSE NULL
        END AS warranty_expiration_parsed,

        CASE LOWER(TRIM(REGEXP_REPLACE(REGEXP_REPLACE(status, '<[^>]+>', ''), '[\\r\\n]+$', '')))
            WHEN 'in service'     THEN 'In Service'
            WHEN 'maintenance'    THEN 'Maintenance'
            WHEN 'standby'        THEN 'Standby'
            WHEN 'decommissioned' THEN 'Decommissioned'
            ELSE NULL
        END AS status_clean
    FROM tmp_equipment_ordered
),
ranked AS (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY equipment_id
            ORDER BY
                (status_clean = 'Decommissioned') DESC,
                row_id DESC
        ) AS rn
    FROM parsed
)
SELECT
    equipment_id,
    customer_id,
    model,
    NULLIF(NULLIF(TRIM(serial_number), ''), 'NULL') AS serial_number,
    install_date_parsed AS install_date,
    warranty_expiration_parsed AS warranty_expiration,
    status_clean AS status,
    NULLIF(TRIM(REGEXP_REPLACE(location_notes, '\\s+', ' ')), 'NULL') AS location_notes
FROM ranked
WHERE rn = 1;

DROP TEMPORARY TABLE IF EXISTS tmp_equipment_ordered;

-- ------------------------------------------------------------------
-- service_logs — no dedup needed (dispatch_id has zero duplicates)
-- ------------------------------------------------------------------
INSERT INTO service_logs
SELECT
    TRIM(REGEXP_REPLACE(d.dispatch_id, '<[^>]+>', '')) AS dispatch_id,
    eu.equipment_id,
    c.customer_id,

    CASE
        WHEN REGEXP_REPLACE(d.dispatch_date, '<[^>]+>', '') REGEXP '^[0-9]{4}-[0-9]{2}-[0-9]{2}T'
            THEN STR_TO_DATE(LEFT(REGEXP_REPLACE(d.dispatch_date, '<[^>]+>', ''), 10), '%Y-%m-%d')
        WHEN REGEXP_REPLACE(d.dispatch_date, '<[^>]+>', '') REGEXP '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
            THEN STR_TO_DATE(REGEXP_REPLACE(d.dispatch_date, '<[^>]+>', ''), '%Y-%m-%d')
        WHEN REGEXP_REPLACE(d.dispatch_date, '<[^>]+>', '') REGEXP '^[0-9]{4}/[0-9]{2}/[0-9]{2}$'
            THEN STR_TO_DATE(REGEXP_REPLACE(d.dispatch_date, '<[^>]+>', ''), '%Y/%m/%d')
        WHEN REGEXP_REPLACE(d.dispatch_date, '<[^>]+>', '') REGEXP '^[0-9]{2}/[0-9]{2}/[0-9]{4}$'
            THEN STR_TO_DATE(REGEXP_REPLACE(d.dispatch_date, '<[^>]+>', ''), '%m/%d/%Y')
        WHEN REGEXP_REPLACE(d.dispatch_date, '<[^>]+>', '') REGEXP '^[0-9]{2}-[0-9]{2}-[0-9]{4}$'
            THEN STR_TO_DATE(REGEXP_REPLACE(d.dispatch_date, '<[^>]+>', ''), '%m-%d-%Y')
        ELSE NULL
    END AS dispatch_date,

    NULLIF(TRIM(REGEXP_REPLACE(REGEXP_REPLACE(d.technician, '<[^>]+>', ''), '\\s+', ' ')), '') AS technician,
    TRIM(REGEXP_REPLACE(d.service_type, '<[^>]+>', '')) AS service_type,
    CAST(TRIM(REGEXP_REPLACE(d.hours_spent, '<[^>]+>', '')) AS DECIMAL(5,1)) AS hours_spent,
    CAST(REGEXP_REPLACE(REGEXP_REPLACE(d.labor_cost, '<[^>]+>', ''), '[^0-9.]', '') AS DECIMAL(10,2)) AS labor_cost,
    TRIM(REGEXP_REPLACE(REGEXP_REPLACE(d.resolution_summary, '<[^>]+>', ''), '\\s+', ' ')) AS resolution_summary,

    CASE LOWER(TRIM(REGEXP_REPLACE(REGEXP_REPLACE(d.status, '<[^>]+>', ''), '[\\r\\n]+$', '')))
        WHEN 'pending'     THEN 'Pending'
        WHEN 'in progress' THEN 'In Progress'
        WHEN 'completed'   THEN 'Completed'
        WHEN 'cancelled'   THEN 'Cancelled'
        ELSE NULL
    END AS status

FROM import_dispatches d
LEFT JOIN equipment_units eu ON eu.equipment_id = TRIM(REGEXP_REPLACE(d.equipment_id, '<[^>]+>', ''))
LEFT JOIN customers c ON c.customer_id = TRIM(REGEXP_REPLACE(d.customer_id, '<[^>]+>', ''));

-- ------------------------------------------------------------------
-- parts_inventory — no dedup needed, no FK columns
-- ------------------------------------------------------------------
INSERT INTO parts_inventory
SELECT
    TRIM(REGEXP_REPLACE(part_id, '<[^>]+>', '')) AS part_id,
    TRIM(REGEXP_REPLACE(REGEXP_REPLACE(part_name, '<[^>]+>', ''), '\\s+', ' ')) AS part_name,
    TRIM(REGEXP_REPLACE(category, '<[^>]+>', '')) AS category,
    TRIM(REGEXP_REPLACE(manufacturer, '<[^>]+>', '')) AS manufacturer,
    TRIM(REGEXP_REPLACE(supplier, '<[^>]+>', '')) AS supplier,
    CAST(TRIM(REGEXP_REPLACE(unit_cost, '<[^>]+>', '')) AS DECIMAL(10,2)) AS unit_cost,
    CAST(TRIM(REGEXP_REPLACE(unit_price, '<[^>]+>', '')) AS DECIMAL(10,2)) AS unit_price,
    CAST(TRIM(REGEXP_REPLACE(stock_quantity, '<[^>]+>', '')) AS SIGNED) AS stock_quantity,
    CAST(TRIM(REGEXP_REPLACE(REGEXP_REPLACE(reorder_level, '<[^>]+>', ''), '[\\r\\n]+$', '')) AS SIGNED) AS reorder_level
FROM import_parts;

-- ------------------------------------------------------------------
-- warranty_claims — 46 exact-duplicate groups, no tiebreak needed
-- ------------------------------------------------------------------
INSERT INTO warranty_claims
WITH ranked AS (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY TRIM(REGEXP_REPLACE(claim_id, '<[^>]+>', ''))
            ORDER BY claim_id
        ) AS rn
    FROM import_warranty_claims
)
SELECT
    TRIM(REGEXP_REPLACE(claim_id, '<[^>]+>', '')) AS claim_id,
    TRIM(REGEXP_REPLACE(equipment_id, '<[^>]+>', '')) AS equipment_id,
    NULLIF(NULLIF(TRIM(REGEXP_REPLACE(dispatch_id, '<[^>]+>', '')), ''), 'NULL') AS dispatch_id,
    NULLIF(NULLIF(TRIM(REGEXP_REPLACE(part_id, '<[^>]+>', '')), ''), 'NULL') AS part_id,

    CASE
        WHEN REGEXP_REPLACE(claim_date, '<[^>]+>', '') REGEXP '^[0-9]{4}-[0-9]{2}-[0-9]{2}T'
            THEN STR_TO_DATE(LEFT(REGEXP_REPLACE(claim_date, '<[^>]+>', ''), 10), '%Y-%m-%d')
        WHEN REGEXP_REPLACE(claim_date, '<[^>]+>', '') REGEXP '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
            THEN STR_TO_DATE(REGEXP_REPLACE(claim_date, '<[^>]+>', ''), '%Y-%m-%d')
        WHEN REGEXP_REPLACE(claim_date, '<[^>]+>', '') REGEXP '^[0-9]{4}/[0-9]{2}/[0-9]{2}$'
            THEN STR_TO_DATE(REGEXP_REPLACE(claim_date, '<[^>]+>', ''), '%Y/%m/%d')
        WHEN REGEXP_REPLACE(claim_date, '<[^>]+>', '') REGEXP '^[0-9]{2}/[0-9]{2}/[0-9]{4}$'
            THEN STR_TO_DATE(REGEXP_REPLACE(claim_date, '<[^>]+>', ''), '%m/%d/%Y')
        WHEN REGEXP_REPLACE(claim_date, '<[^>]+>', '') REGEXP '^[0-9]{2}-[0-9]{2}-[0-9]{4}$'
            THEN STR_TO_DATE(REGEXP_REPLACE(claim_date, '<[^>]+>', ''), '%m-%d-%Y')
        ELSE NULL
    END AS claim_date,

    CAST(TRIM(REGEXP_REPLACE(claim_amount, '<[^>]+>', '')) AS DECIMAL(10,2)) AS claim_amount,

    CASE
        WHEN TRIM(REGEXP_REPLACE(approved_amount, '<[^>]+>', '')) = ''
             OR UPPER(TRIM(REGEXP_REPLACE(approved_amount, '<[^>]+>', ''))) = 'NULL' THEN NULL
        ELSE CAST(TRIM(REGEXP_REPLACE(approved_amount, '<[^>]+>', '')) AS DECIMAL(10,2))
    END AS approved_amount,

    CASE LOWER(TRIM(REGEXP_REPLACE(status, '<[^>]+>', '')))
        WHEN 'pending'      THEN 'Pending'
        WHEN 'under review' THEN 'Under Review'
        WHEN 'approved'     THEN 'Approved'
        WHEN 'rejected'     THEN 'Rejected'
        ELSE NULL
    END AS status,

    NULLIF(
        NULLIF(
            TRIM(REGEXP_REPLACE(REGEXP_REPLACE(denial_reason, '<[^>]+>', ''), '\\s+', ' ')),
            ''
        ),
        'N/A'
    ) AS denial_reason,

    TRIM(REGEXP_REPLACE(REGEXP_REPLACE(REGEXP_REPLACE(claim_notes, '<[^>]+>', ''), '[\\r\\n]+$', ''), '\\s+', ' ')) AS claim_notes

FROM ranked
WHERE rn = 1;