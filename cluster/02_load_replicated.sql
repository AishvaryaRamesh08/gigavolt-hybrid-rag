-- =============================================================================
-- 02_load_replicated.sql - silver tables -> materialized view -> InnoDB table
--
-- RUN ON ANY NODE, in a NORMAL session (wsrep_on stays ON):
--     sudo mariadb < 02_load_replicated.sql
-- The data lands on all three nodes through Galera replication.
-- =============================================================================
SET autocommit = 1;      -- each INSERT below is its own transaction (see batching)
USE gigavolt_analytics;

-- -----------------------------------------------------------------------------
-- STEP 1: (re)build the materialized view from the silver tables.
--         Expect mv_rows = rows in gigavolt_erp.service_logs (5,000).
-- -----------------------------------------------------------------------------
CALL sp_refresh_mv_service_analytics();

-- -----------------------------------------------------------------------------
-- STEP 2: MV -> InnoDB, replicated N times, IN BATCHES.
--
-- SIZE: 40 copies x 5,000 MV rows = 200,000 rows. Big enough that a column store
-- beats a row store on aggregates, small enough for a 1 GB lab node (a 1.5M-row
-- load ran the node out of memory during ColumnStore's bulk import).
--
-- WHY BATCHES: Galera sends each transaction to every node as ONE writeset and
-- certifies it before commit. One giant INSERT would be a huge writeset: slow,
-- memory hungry, and able to stall the cluster (flow control). Four batches of
-- ~50,000 rows are ordinary-sized transactions that replicate smoothly.
--
-- WHAT THE COPIES ARE: the real data is only the 5,000 MV rows. Each copy re-uses
-- them with labor and claim amounts scaled by 0-9% (seq % 10), so copies are
-- similar but not identical. THE EXTRA ROWS ARE SYNTHETIC; say so in the write-up.
--
-- seq_1_to_1000 is a virtual table from the SEQUENCE engine with one column,
-- seq = 1..1000. We keep only the numbers belonging to the current batch.
--
-- Usage: CALL sp_load_svc_analytics_innodb(copies, copies_per_batch);
--        40 copies x 5,000 rows = 200,000 rows, in 4 batches of 10 copies.
-- -----------------------------------------------------------------------------
DELIMITER $$
DROP PROCEDURE IF EXISTS sp_load_svc_analytics_innodb $$
CREATE PROCEDURE sp_load_svc_analytics_innodb(IN p_copies INT, IN p_per_batch INT)
BEGIN
  DECLARE v_from INT DEFAULT 1;
  DECLARE v_to   INT;

  TRUNCATE TABLE svc_analytics_innodb;          -- start clean so reruns never duplicate

  WHILE v_from <= p_copies DO
    SET v_to = LEAST(v_from + p_per_batch - 1, p_copies);

    INSERT INTO svc_analytics_innodb
      (copy_id, dispatch_id, dispatch_date, service_type, technician, dispatch_status,
       hours_spent, labor_cost, equipment_id, model, capacity_kw, voltage,
       equipment_status, warranty_expiration, under_warranty, customer_id,
       company_name, customer_state, customer_city, claim_count,
       claim_amount_total, approved_amount_total)
    SELECT
      s.seq, m.dispatch_id, m.dispatch_date, m.service_type, m.technician, m.dispatch_status,
      m.hours_spent,
      m.labor_cost            * (1 + (s.seq % 10) / 100),
      m.equipment_id, m.model, m.capacity_kw, m.voltage,
      m.equipment_status, m.warranty_expiration, m.under_warranty, m.customer_id,
      m.company_name, m.customer_state, m.customer_city, m.claim_count,
      m.claim_amount_total    * (1 + (s.seq % 10) / 100),
      m.approved_amount_total * (1 + (s.seq % 10) / 100)
    FROM mv_service_analytics m
    CROSS JOIN seq_1_to_1000 s                  -- every MV row paired with every seq number
    WHERE s.seq BETWEEN v_from AND v_to;        -- ...but only this batch's numbers

    SET v_from = v_to + 1;
  END WHILE;
END $$
DELIMITER ;

CALL sp_load_svc_analytics_innodb(40, 10);     -- 200,000 rows

-- ANALYZE refreshes the index statistics the optimizer uses to pick plans. Without
-- it InnoDB could choose a poor plan on a freshly bulk-loaded table, which would
-- make the later comparison unfair to InnoDB.
ANALYZE TABLE svc_analytics_innodb;

SELECT 'materialized view' AS tbl, COUNT(*) AS row_count FROM mv_service_analytics
UNION ALL SELECT 'InnoDB (replicated)', COUNT(*) FROM svc_analytics_innodb;
