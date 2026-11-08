-- =============================================================================
-- 01_ddl_replicated.sql - materialized view + InnoDB table (REPLICATED by Galera)
--
-- RUN ON ANY NODE, in a NORMAL session (wsrep_on stays ON):
--     sudo mariadb < 01_ddl_replicated.sql
--
-- Everything here is ordinary InnoDB, so Galera replicates the DDL and later the
-- data to all three nodes. This is deliberate: it lets you SHOW the analytics
-- data on every node, and it survives a node being rebuilt by SST.
-- The one thing that must NOT replicate is the ColumnStore table: it is created
-- separately, on Node C only, by 03_columnstore_node_c.sql.
--
-- Galera notes: every replicated table needs a PRIMARY KEY (both tables below
-- have one). AUTO_INCREMENT values will step by the cluster size (e.g. 1,4,7...)
-- because Galera gives each node its own offset; gaps in row_id are normal.
-- =============================================================================

SELECT ENGINE, SUPPORT
FROM information_schema.ENGINES
WHERE LOWER(ENGINE) IN ('sequence', 'innodb');   -- both must be available (ColumnStore is checked in 00_smoke_test.sql)

DROP DATABASE IF EXISTS gigavolt_analytics;
CREATE DATABASE gigavolt_analytics CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE gigavolt_analytics;

-- -----------------------------------------------------------------------------
-- 1. MATERIALIZED VIEW (MariaDB has no native one, so: a physical table that
--    stores the result of a join query, refreshed by a stored procedure).
--    One row per service dispatch, denormalised across 6 silver tables.
-- -----------------------------------------------------------------------------
CREATE TABLE mv_service_analytics (
  dispatch_id            VARCHAR(50)   NOT NULL,
  dispatch_date          DATE,
  service_type           VARCHAR(50),
  technician             VARCHAR(100),
  dispatch_status        VARCHAR(20),
  hours_spent            DECIMAL(5,1),
  labor_cost             DECIMAL(10,2),
  equipment_id           VARCHAR(50),
  model                  VARCHAR(20),
  capacity_kw            INT,
  voltage                INT,
  equipment_status       VARCHAR(20),
  warranty_expiration    DATE,
  under_warranty         TINYINT,                 -- 1 if serviced on/before warranty expiry
  customer_id            VARCHAR(50),
  company_name           VARCHAR(150),
  customer_state         CHAR(2),
  customer_city          VARCHAR(100),
  claim_count            INT           NOT NULL DEFAULT 0,
  claim_amount_total     DECIMAL(12,2) NOT NULL DEFAULT 0,
  approved_amount_total  DECIMAL(12,2) NOT NULL DEFAULT 0,
  mv_refreshed_at        TIMESTAMP     DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (dispatch_id)
) ENGINE = InnoDB;

-- Refresh procedure: same error-handling pattern as sp_Prepare_RAG_Payloads.
-- Warranty claims are pre-aggregated per dispatch in a subquery so the join can
-- never multiply dispatch rows. The write replicates normally (5,000 rows).
DELIMITER $$
DROP PROCEDURE IF EXISTS sp_refresh_mv_service_analytics $$
CREATE PROCEDURE sp_refresh_mv_service_analytics()
BEGIN
  DECLARE EXIT HANDLER FOR SQLEXCEPTION
  BEGIN
    ROLLBACK;
    RESIGNAL;
  END;

  START TRANSACTION;

  DELETE FROM mv_service_analytics;

  INSERT INTO mv_service_analytics
    (dispatch_id, dispatch_date, service_type, technician, dispatch_status,
     hours_spent, labor_cost, equipment_id, model, capacity_kw, voltage,
     equipment_status, warranty_expiration, under_warranty, customer_id,
     company_name, customer_state, customer_city, claim_count,
     claim_amount_total, approved_amount_total)
  SELECT
    sl.dispatch_id, sl.dispatch_date, sl.service_type, sl.technician, sl.status,
    sl.hours_spent, sl.labor_cost,
    sl.equipment_id, em.model, em.capacity_kw, em.voltage,
    eu.status, eu.warranty_expiration,
    CASE WHEN eu.warranty_expiration IS NULL OR sl.dispatch_date IS NULL THEN NULL
         WHEN sl.dispatch_date <= eu.warranty_expiration THEN 1
         ELSE 0 END,
    sl.customer_id, c.company_name, loc.state, loc.city,
    COALESCE(wc.claim_count, 0),
    COALESCE(wc.claim_total, 0),
    COALESCE(wc.approved_total, 0)
  FROM gigavolt_erp.service_logs sl
  LEFT JOIN gigavolt_erp.equipment_units  eu  ON eu.equipment_id = sl.equipment_id
  LEFT JOIN gigavolt_erp.equipment_models em  ON em.model        = eu.model
  LEFT JOIN gigavolt_erp.customers        c   ON c.customer_id   = sl.customer_id
  LEFT JOIN gigavolt_erp.locations        loc ON loc.zip         = c.zip
  LEFT JOIN (
      SELECT dispatch_id,
             COUNT(*)                          AS claim_count,
             SUM(claim_amount)                 AS claim_total,
             SUM(COALESCE(approved_amount, 0)) AS approved_total
      FROM gigavolt_erp.warranty_claims
      WHERE dispatch_id IS NOT NULL
      GROUP BY dispatch_id
  ) wc ON wc.dispatch_id = sl.dispatch_id;

  COMMIT;

  SELECT COUNT(*) AS mv_rows, MIN(mv_refreshed_at) AS refreshed_at
  FROM mv_service_analytics;
END $$
DELIMITER ;

-- -----------------------------------------------------------------------------
-- 2. InnoDB (row store): the MV replicated 40x (40 x 5,000 = 200,000 rows) as
--    simulated "fleet copies". 200,000 rows is enough for a column store to show an
--    advantage while fitting the memory of a small (1 GB) lab node.
--    Indexed like a normal OLTP table so the comparison is fair to InnoDB.
-- -----------------------------------------------------------------------------
CREATE TABLE svc_analytics_innodb (
  row_id                 BIGINT        NOT NULL AUTO_INCREMENT,
  copy_id                SMALLINT      NOT NULL,       -- which simulated copy (1..40)
  dispatch_id            VARCHAR(50)   NOT NULL,
  dispatch_date          DATE,
  service_type           VARCHAR(50),
  technician             VARCHAR(100),
  dispatch_status        VARCHAR(20),
  hours_spent            DECIMAL(5,1),
  labor_cost             DECIMAL(10,2),
  equipment_id           VARCHAR(50),
  model                  VARCHAR(20),
  capacity_kw            INT,
  voltage                INT,
  equipment_status       VARCHAR(20),
  warranty_expiration    DATE,
  under_warranty         TINYINT,
  customer_id            VARCHAR(50),
  company_name           VARCHAR(150),
  customer_state         CHAR(2),
  customer_city          VARCHAR(100),
  claim_count            INT           NOT NULL DEFAULT 0,
  claim_amount_total     DECIMAL(12,2) NOT NULL DEFAULT 0,
  approved_amount_total  DECIMAL(12,2) NOT NULL DEFAULT 0,
  PRIMARY KEY (row_id),
  KEY idx_dispatch_date (dispatch_date),
  KEY idx_model         (model),
  KEY idx_service_type  (service_type)
) ENGINE = InnoDB;

SHOW TABLES;
