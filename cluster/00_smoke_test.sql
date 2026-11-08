-- =============================================================================
-- 00_smoke_test.sql - confirm the ColumnStore engine actually WORKS before the
-- 200,000-row load. "Listed in SHOW ENGINES" is not the same as "usable": the
-- engine also needs its own background services running.
--
-- RUN ON THE ANALYTICS NODE (Node C):   sudo mariadb < 00_smoke_test.sql
-- Expected: the final SELECT returns total = 30 and the script ends with no error.
-- =============================================================================

-- wsrep_on = OFF: keep this throwaway database local to this node (a ColumnStore
-- table is not a supported Galera scenario, and the other nodes do not need it).
SET SESSION wsrep_on = OFF;

-- Engines this project needs. Expect SUPPORT = YES (or DEFAULT for InnoDB).
--   Columnstore : the column-oriented engine we are benchmarking
--   SEQUENCE    : provides seq_1_to_1000, the row generator used to build the 200,000 rows
SELECT ENGINE, SUPPORT
FROM information_schema.ENGINES
WHERE LOWER(ENGINE) IN ('columnstore', 'sequence', 'innodb');

DROP DATABASE IF EXISTS cs_smoke;
CREATE DATABASE cs_smoke;
USE cs_smoke;

-- If THIS statement fails, ColumnStore is installed but not running correctly.
-- Check:  systemctl list-units 'mariadb-columnstore*' 'mcs*'   and
--         the MariaDB error log (journalctl -u mariadb -n 50)
CREATE TABLE t (id INT, v INT) ENGINE = ColumnStore;

INSERT INTO t VALUES (1, 10), (2, 20);
SELECT SUM(v) AS total FROM t;      -- expect 30

DROP DATABASE cs_smoke;             -- clean up
