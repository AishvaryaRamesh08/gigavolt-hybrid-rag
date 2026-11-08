-- =============================================================================
-- 03_columnstore_node_c.sql - the ColumnStore table: NODE C ONLY, LOCAL ONLY
--
-- RUN ON NODE C ONLY:     sudo mariadb < 03_columnstore_node_c.sql
-- Run it AFTER 02_load_replicated.sql has finished and Node C has caught up
-- (see the pre-check below).
--
-- WHY THIS ONE TABLE STAYS LOCAL (per Dr. G.)
--   ColumnStore is not transaction-safe and Galera + ColumnStore is not a tested
--   combination: replicating it can give inconsistent results. With wsrep_on = OFF
--   the CREATE TABLE and the INSERT stay on this node. If they ran with wsrep_on
--   ON, the other nodes would receive a table (or rows) they cannot apply, or
--   end up with their own separate, empty ColumnStore tables.
--   RULE: only ever write to svc_analytics_cs from a session with wsrep_on = OFF.
--   Reads are always safe.
--
-- Bonus: if this node is ever rebuilt by SST, only THIS table is lost. The
-- replicated InnoDB data comes back from a donor, and rerunning this file
-- rebuilds the ColumnStore copy in minutes.
-- =============================================================================
SET SESSION wsrep_on = OFF;
SET autocommit = 1;         -- keep ON so ColumnStore can use its bulk path for
                            -- INSERT ... SELECT (as far as I know)
USE gigavolt_analytics;

-- PRE-CHECK: this node must have applied the whole InnoDB load first.
--   wsrep_local_recv_queue must be 0, and the count must equal the other nodes'.
SHOW STATUS LIKE 'wsrep_local_recv_queue';
SELECT COUNT(*) AS innodb_rows_on_this_node FROM svc_analytics_innodb;

-- If this DROP fails with "cpimport with PID ... is currently holding the table
-- lock", a previous bulk load was killed and left a stale ColumnStore lock. Clear it
-- from the shell, then rerun this file:
--     viewtablelock                  (shows the LockID)
--     cleartablelock <LockID>
DROP TABLE IF EXISTS svc_analytics_cs;      -- local only, because wsrep_on is OFF

-- Same columns as the InnoDB table. ColumnStore has no primary keys, indexes or
-- foreign keys, so row_id is a plain column copied from InnoDB.
CREATE TABLE svc_analytics_cs (
  row_id                 BIGINT        NOT NULL,
  copy_id                SMALLINT      NOT NULL,
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
  claim_count            INT           NOT NULL,
  claim_amount_total     DECIMAL(12,2) NOT NULL,
  approved_amount_total  DECIMAL(12,2) NOT NULL
) ENGINE = ColumnStore;

-- Copy every InnoDB row (200,000) so both engines hold identical data.
-- With autocommit ON, ColumnStore handles this INSERT ... SELECT with cpimport, its
-- bulk loader. cpimport needs roughly 200 MB of free RAM; on a 1 GB node make sure
-- swap is enabled (free -m) or the Linux OOM killer can terminate it mid-load.
INSERT INTO svc_analytics_cs
  (row_id, copy_id, dispatch_id, dispatch_date, service_type, technician,
   dispatch_status, hours_spent, labor_cost, equipment_id, model, capacity_kw,
   voltage, equipment_status, warranty_expiration, under_warranty, customer_id,
   company_name, customer_state, customer_city, claim_count,
   claim_amount_total, approved_amount_total)
SELECT
   row_id, copy_id, dispatch_id, dispatch_date, service_type, technician,
   dispatch_status, hours_spent, labor_cost, equipment_id, model, capacity_kw,
   voltage, equipment_status, warranty_expiration, under_warranty, customer_id,
   company_name, customer_state, customer_city, claim_count,
   claim_amount_total, approved_amount_total
FROM svc_analytics_innodb;

-- TWO SEPARATE statements on purpose. ColumnStore cannot mix its tables with tables
-- of another engine in one query unless "cross-engine support" is configured
-- (otherwise: ERROR 1815 ... IDB-8001 CrossEngineSupport ... not properly configured).
-- So every statement in these scripts touches only ONE engine.
SELECT 'InnoDB (replicated)' AS tbl, COUNT(*) AS row_count FROM svc_analytics_innodb;
SELECT 'ColumnStore (Node C only)' AS tbl, COUNT(*) AS row_count FROM svc_analytics_cs;
