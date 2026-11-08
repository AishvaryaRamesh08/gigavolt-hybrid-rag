-- =============================================================================
-- failover_01_setup.sql - a small replicated table to watch during the failover test
--
-- RUN ONCE, ON ANY NODE, in a NORMAL session (it must replicate to all nodes):
--     sudo mariadb < failover_01_setup.sql
--
-- A separate database keeps the test rows away from the GigaVolt data. The table is
-- plain InnoDB with a PRIMARY KEY, which Galera requires for replicated tables.
-- Each row records WHICH node wrote it and WHEN (millisecond precision), so after the
-- test you can see exactly which rows were written while a node was down.
-- =============================================================================
DROP DATABASE IF EXISTS failover_test;
CREATE DATABASE failover_test;
USE failover_test;

CREATE TABLE heartbeat (
  id          BIGINT       NOT NULL AUTO_INCREMENT,   -- Galera hands each node its own
                                                      -- id offsets, so gaps are normal
  written_by  VARCHAR(64)  NOT NULL,                  -- hostname of the writing node
  note        VARCHAR(64),
  written_at  TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (id)
) ENGINE = InnoDB;

SELECT 'failover_test.heartbeat created' AS status;
