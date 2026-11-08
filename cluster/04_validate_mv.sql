-- =============================================================================
-- 04_validate_mv.sql - check the materialized view and the InnoDB table.
--
-- RUN ON ANY NODE:   sudo mariadb < 04_validate_mv.sql
-- Every check should say PASS.
--
-- Every statement here touches InnoDB tables only. The InnoDB-vs-ColumnStore
-- comparison lives in validate_engines.sh, because ColumnStore cannot mix its tables
-- with another engine's tables inside one query.
-- =============================================================================
USE gigavolt_analytics;

-- -----------------------------------------------------------------------------
-- A. Does the materialized view faithfully reflect the silver tables?
-- -----------------------------------------------------------------------------
SELECT 'A. Materialized view vs silver source' AS section;

SELECT 'MV rows = service_logs rows' AS check_name,
       (SELECT COUNT(*) FROM mv_service_analytics)      AS mv_value,
       (SELECT COUNT(*) FROM gigavolt_erp.service_logs) AS source_value,
       IF((SELECT COUNT(*) FROM mv_service_analytics) =
          (SELECT COUNT(*) FROM gigavolt_erp.service_logs), 'PASS', 'FAIL') AS result
UNION ALL
-- Money must not be created or lost by the joins.
SELECT 'SUM(labor_cost) matches source',
       (SELECT SUM(labor_cost) FROM mv_service_analytics),
       (SELECT SUM(labor_cost) FROM gigavolt_erp.service_logs),
       IF((SELECT SUM(labor_cost) FROM mv_service_analytics) <=>
          (SELECT SUM(labor_cost) FROM gigavolt_erp.service_logs), 'PASS', 'FAIL')
UNION ALL
-- No fan-out: every claim linked to a dispatch is counted exactly once. If the claims
-- join had multiplied rows, this total would not match.
SELECT 'SUM(claim_count) = linked claims',
       (SELECT SUM(claim_count) FROM mv_service_analytics),
       (SELECT COUNT(*) FROM gigavolt_erp.warranty_claims wc
         WHERE wc.dispatch_id IN (SELECT dispatch_id FROM gigavolt_erp.service_logs)),
       IF((SELECT SUM(claim_count) FROM mv_service_analytics) <=>
          (SELECT COUNT(*) FROM gigavolt_erp.warranty_claims wc
            WHERE wc.dispatch_id IN (SELECT dispatch_id FROM gigavolt_erp.service_logs)), 'PASS', 'FAIL');

-- -----------------------------------------------------------------------------
-- B. Is the InnoDB analytics table the expected size?
--    200,000 rows = 40 copies x 5,000 MV rows.
-- -----------------------------------------------------------------------------
SELECT 'B. InnoDB analytics table' AS section;

SELECT 'rows = copies x MV rows' AS check_name,
       (SELECT COUNT(*) FROM svc_analytics_innodb) AS value,
       IF((SELECT COUNT(*) FROM svc_analytics_innodb) =
          (SELECT MAX(copy_id) FROM svc_analytics_innodb) * (SELECT COUNT(*) FROM mv_service_analytics),
          'PASS', 'FAIL') AS result
UNION ALL
SELECT 'rows = 200,000',
       (SELECT COUNT(*) FROM svc_analytics_innodb),
       IF((SELECT COUNT(*) FROM svc_analytics_innodb) = 200000, 'PASS', 'REVIEW (different copy count?)');

-- -----------------------------------------------------------------------------
-- C. Storage footprint of the InnoDB table (data + indexes), for the write-up.
-- -----------------------------------------------------------------------------
SELECT 'C. Storage footprint (InnoDB, MB)' AS section;
SELECT TABLE_NAME,
       ROUND(DATA_LENGTH  / 1024 / 1024, 1) AS data_mb,
       ROUND(INDEX_LENGTH / 1024 / 1024, 1) AS index_mb
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = 'gigavolt_analytics' AND TABLE_NAME = 'svc_analytics_innodb';

-- -----------------------------------------------------------------------------
-- D. Replication checks (run by hand on each node for the screencast):
--      SELECT COUNT(*) FROM gigavolt_analytics.svc_analytics_innodb;
--        -> 200000 on all three nodes (Galera replicated it).
--      SHOW TABLES IN gigavolt_analytics;
--        -> svc_analytics_cs appears on Node C ONLY (it is local to that node).
-- -----------------------------------------------------------------------------
