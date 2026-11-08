USE gigavolt_erp;

DELIMITER $$

DROP PROCEDURE IF EXISTS sp_Prepare_RAG_Payloads $$

-- =====================================================================
-- sp_Prepare_RAG_Payloads
-- Single source of truth for ERP text that feeds the RAG pipeline (Phase 5).
-- Rebuilds rag_payloads from the cleansed Silver tables. Idempotent:
-- every call deletes and regenerates all rows inside one transaction.
--
--   p_only_completed  TRUE  -> service events with status 'Completed'
--                     FALSE -> all service events that have a resolution
--
-- Payload types produced (one row per source record, so the
-- (source_table, source_id) unique key is never violated):
--   1. service_event  one row per service_logs dispatch, enriched with
--                     equipment model/specs, warranty status as of the
--                     dispatch date, serial number, site notes, customer
--                     company + location (NO PII), and every warranty claim
--                     tied to the dispatch AND the same unit (with claim date
--                     and part supplier).
--   2. warranty_claim one row per every other claim: no dispatch, or a dispatch
--                     for a DIFFERENT unit. Source data check: 967 of the 968
--                     dispatch-linked claims name a different unit than their
--                     dispatch, so wc.equipment_id decides who owns a claim and
--                     the dispatch link is only reported as recorded.
--
-- claim_notes is deliberately omitted: all 1,200 values are the same template
--   ("Claim for replacement part X under equipment warranty"), so it adds
--   embedding tokens but no information. The part ID is shown instead.
--
-- Privacy: contact_name / phone / email / street address are never
--   read here, so rag_payloads is safe for both support_staff and
--   data_manager roles.
-- =====================================================================
CREATE PROCEDURE sp_Prepare_RAG_Payloads(
  IN p_only_completed BOOLEAN
)
BEGIN
  -- Any failure rolls back, leaving the previous payloads intact.
  DECLARE EXIT HANDLER FOR SQLEXCEPTION
  BEGIN
    ROLLBACK;
    RESIGNAL;
  END;

  -- Default 1024 bytes would silently truncate long claim lists.
  SET SESSION group_concat_max_len = 100000;

  START TRANSACTION;

  DELETE FROM rag_payloads;

  -- ------------------------------------------------------------------
  -- 1. SERVICE EVENTS
  -- ------------------------------------------------------------------
  INSERT INTO rag_payloads
    (source_table, source_id, payload_type, equipment_id, equipment_model,
     customer_id, event_date, record_status, warranty_status,
     payload_text, metadata, char_length)
  SELECT
    t.source_table, t.source_id, t.payload_type, t.equipment_id,
    t.equipment_model, t.customer_id, t.event_date, t.record_status,
    t.warranty_status, t.payload_text,
    JSON_OBJECT(
      'source_system',   'mariadb',
      'source_table',    t.source_table,
      'source_id',       t.source_id,
      'payload_type',    t.payload_type,
      'equipment_id',    t.equipment_id,
      'equipment_model', t.equipment_model,
      'customer_id',     t.customer_id,
      'event_date',      DATE_FORMAT(t.event_date, '%Y-%m-%d'),
      'record_status',   t.record_status,
      'warranty_status', t.warranty_status,
      'service_type',    t.service_type,
      'serial_number',   t.serial_number,
      'claim_ids',       t.claim_ids
    ),
    CHAR_LENGTH(t.payload_text)
  FROM (
    SELECT
      'service_logs'               AS source_table,
      sl.dispatch_id               AS source_id,
      'service_event'              AS payload_type,
      sl.equipment_id              AS equipment_id,
      eu.model                     AS equipment_model,
      sl.customer_id               AS customer_id,
      sl.dispatch_date             AS event_date,
      sl.status                    AS record_status,
      sl.service_type              AS service_type,
      eu.serial_number             AS serial_number,
      CASE
        WHEN eu.warranty_expiration IS NULL OR sl.dispatch_date IS NULL THEN 'Unknown'
        WHEN sl.dispatch_date <= eu.warranty_expiration                 THEN 'In Warranty'
        ELSE 'Out of Warranty'
      END                          AS warranty_status,
      COALESCE(
        (SELECT JSON_ARRAYAGG(wc.claim_id)
         FROM warranty_claims wc
         WHERE wc.dispatch_id = sl.dispatch_id
           AND wc.equipment_id = sl.equipment_id),
        JSON_ARRAY())              AS claim_ids,
      TRIM(REGEXP_REPLACE(
        CONCAT_WS('\n',
          CONCAT('Service Event ', sl.dispatch_id, ': ',
                 COALESCE(sl.service_type, 'N/A'), ' on ',
                 COALESCE(DATE_FORMAT(sl.dispatch_date, '%Y-%m-%d'), 'N/A'),
                 ' (', COALESCE(sl.status, 'N/A'), ')'),
          CONCAT('Equipment: ', COALESCE(sl.equipment_id, 'UNKNOWN'),
                 ' | Serial: ', COALESCE(eu.serial_number, 'N/A'),
                 ' | Model: ', COALESCE(em.model, 'Unknown'),
                 ' (', COALESCE(em.capacity_kw, '?'), ' kW, ',
                 COALESCE(em.voltage, '?'), ' V)',
                 ' | Unit status: ', COALESCE(eu.status, 'N/A'),
                 ' | Site: ', COALESCE(NULLIF(eu.location_notes, ''), 'N/A')),
          CONCAT('Installed: ',
                 COALESCE(DATE_FORMAT(eu.install_date, '%Y-%m-%d'), 'N/A'),
                 ' | Warranty expires: ',
                 COALESCE(DATE_FORMAT(eu.warranty_expiration, '%Y-%m-%d'), 'N/A'),
                 ' | Warranty at service date: ',
                 CASE
                   WHEN eu.warranty_expiration IS NULL OR sl.dispatch_date IS NULL THEN 'Unknown'
                   WHEN sl.dispatch_date <= eu.warranty_expiration THEN 'In Warranty'
                   ELSE 'Out of Warranty'
                 END),
          CONCAT('Customer: ', COALESCE(c.company_name, 'Unknown'),
                 ' (', COALESCE(loc.city, '?'), ', ',
                 COALESCE(loc.state, '?'), ')'),
          CONCAT('Technician: ', COALESCE(sl.technician, 'Unassigned'),
                 ' | Hours: ', COALESCE(sl.hours_spent, 'N/A'),
                 ' | Labor cost: $', COALESCE(sl.labor_cost, 'N/A')),
          CONCAT('Resolution: ',
                 COALESCE(sl.resolution_summary, 'No resolution recorded')),
          COALESCE(
            (SELECT GROUP_CONCAT(
               CONCAT('Warranty Claim ', wc.claim_id,
                      ' | Filed: ', COALESCE(DATE_FORMAT(wc.claim_date, '%Y-%m-%d'), 'N/A'),
                      ' | Part: ', COALESCE(pi.part_name, 'N/A'), ' (', COALESCE(wc.part_id, 'no part ID'), ')',
                      ' | Supplier: ', COALESCE(pi.supplier, 'N/A'),
                      ' | Status: ', COALESCE(wc.status, 'N/A'),
                      ' | Claimed: $', COALESCE(wc.claim_amount, '0'),
                      ' | Approved: ',
                      CASE WHEN wc.approved_amount IS NOT NULL THEN CONCAT('$', wc.approved_amount)
                           WHEN wc.status = 'Approved' THEN 'Amount not recorded'
                           ELSE 'Pending' END,
                      ' | Denial reason: ', COALESCE(wc.denial_reason, 'None'))
               ORDER BY wc.claim_id SEPARATOR '\n')
             FROM warranty_claims wc
             LEFT JOIN parts_inventory pi ON pi.part_id = wc.part_id
             WHERE wc.dispatch_id = sl.dispatch_id
               AND wc.equipment_id = sl.equipment_id),
            'Warranty Claim: None linked to this dispatch for this unit')
        ),
        '\n{2,}', '\n'))           AS payload_text
    FROM service_logs sl
    LEFT JOIN equipment_units  eu  ON eu.equipment_id = sl.equipment_id
    LEFT JOIN equipment_models em  ON em.model        = eu.model
    LEFT JOIN customers        c   ON c.customer_id   = sl.customer_id
    LEFT JOIN locations        loc ON loc.zip         = c.zip
    WHERE (p_only_completed = FALSE OR sl.status = 'Completed')
      AND sl.resolution_summary IS NOT NULL
  ) t;

  -- ------------------------------------------------------------------
  -- 2. WARRANTY CLAIMS NOT TIED TO A DISPATCH
  -- ------------------------------------------------------------------
  INSERT INTO rag_payloads
    (source_table, source_id, payload_type, equipment_id, equipment_model,
     customer_id, event_date, record_status, warranty_status,
     payload_text, metadata, char_length)
  SELECT
    t.source_table, t.source_id, t.payload_type, t.equipment_id,
    t.equipment_model, t.customer_id, t.event_date, t.record_status,
    t.warranty_status, t.payload_text,
    JSON_OBJECT(
      'source_system',   'mariadb',
      'source_table',    t.source_table,
      'source_id',       t.source_id,
      'payload_type',    t.payload_type,
      'equipment_id',    t.equipment_id,
      'equipment_model', t.equipment_model,
      'customer_id',     t.customer_id,
      'event_date',      DATE_FORMAT(t.event_date, '%Y-%m-%d'),
      'record_status',   t.record_status,
      'warranty_status', t.warranty_status,
      'serial_number',   t.serial_number,
      'part_supplier',   t.part_supplier,
      'recorded_dispatch', t.recorded_dispatch
    ),
    CHAR_LENGTH(t.payload_text)
  FROM (
    SELECT
      'warranty_claims'            AS source_table,
      wc.claim_id                  AS source_id,
      'warranty_claim'             AS payload_type,
      wc.equipment_id              AS equipment_id,
      eu.model                     AS equipment_model,
      eu.customer_id               AS customer_id,
      wc.claim_date                AS event_date,
      wc.status                    AS record_status,
      eu.serial_number             AS serial_number,
      pi.supplier                  AS part_supplier,
      wc.dispatch_id               AS recorded_dispatch,
      CASE
        WHEN eu.warranty_expiration IS NULL OR wc.claim_date IS NULL THEN 'Unknown'
        WHEN wc.claim_date <= eu.warranty_expiration                 THEN 'In Warranty'
        ELSE 'Out of Warranty'
      END                          AS warranty_status,
      TRIM(REGEXP_REPLACE(
        CONCAT_WS('\n',
          CONCAT('Warranty Claim ', wc.claim_id, ' filed ',
                 COALESCE(DATE_FORMAT(wc.claim_date, '%Y-%m-%d'), 'N/A'),
                 ' (', COALESCE(wc.status, 'N/A'), ')'),
          CONCAT('Equipment: ', COALESCE(wc.equipment_id, 'UNKNOWN'),
                 ' | Serial: ', COALESCE(eu.serial_number, 'N/A'),
                 ' | Model: ', COALESCE(em.model, 'Unknown'),
                 ' (', COALESCE(em.capacity_kw, '?'), ' kW, ',
                 COALESCE(em.voltage, '?'), ' V)',
                 ' | Warranty expires: ',
                 COALESCE(DATE_FORMAT(eu.warranty_expiration, '%Y-%m-%d'), 'N/A'),
                 ' | Site: ', COALESCE(NULLIF(eu.location_notes, ''), 'N/A')),
          CONCAT('Part: ', COALESCE(pi.part_name, 'N/A'), ' (', COALESCE(wc.part_id, 'no part ID'), ')',
                 ' | Supplier: ', COALESCE(pi.supplier, 'N/A'),
                 ' | Claimed: $', COALESCE(wc.claim_amount, '0'),
                 ' | Approved: ',
                 CASE WHEN wc.approved_amount IS NOT NULL THEN CONCAT('$', wc.approved_amount)
                      WHEN wc.status = 'Approved' THEN 'Amount not recorded'
                      ELSE 'Pending' END),
          CONCAT('Denial reason: ', COALESCE(wc.denial_reason, 'None')),
          CONCAT('Warranty at claim date: ',
                 CASE
                   WHEN eu.warranty_expiration IS NULL OR wc.claim_date IS NULL THEN 'Unknown'
                   WHEN wc.claim_date <= eu.warranty_expiration THEN 'In Warranty'
                   ELSE 'Out of Warranty'
                 END),
          CASE
            WHEN wc.dispatch_id IS NULL THEN 'Recorded dispatch link: None'
            WHEN dl.equipment_id IS NULL THEN CONCAT('Recorded dispatch link: ', wc.dispatch_id)
            ELSE CONCAT('Recorded dispatch link: ', wc.dispatch_id,
                        ' (that dispatch is recorded for a different unit, ', dl.equipment_id, ')')
          END
        ),
        '\n{2,}', '\n'))           AS payload_text
    FROM warranty_claims wc
    LEFT JOIN equipment_units  eu ON eu.equipment_id = wc.equipment_id
    LEFT JOIN equipment_models em ON em.model        = eu.model
    LEFT JOIN parts_inventory  pi ON pi.part_id      = wc.part_id
    LEFT JOIN service_logs     dl ON dl.dispatch_id  = wc.dispatch_id
    WHERE wc.dispatch_id IS NULL
       OR dl.dispatch_id IS NULL
       OR NOT (dl.equipment_id <=> wc.equipment_id)
  ) t;

  COMMIT;

  -- Summary result set (for the screencast and for pipeline logging)
  SELECT payload_type,
         COUNT(*)                   AS payloads_generated,
         MIN(char_length)           AS min_chars,
         MAX(char_length)           AS max_chars,
         ROUND(AVG(char_length), 1) AS avg_chars
  FROM rag_payloads
  GROUP BY payload_type;
END $$

DELIMITER ;
