USE gigavolt_erp;

-- =====================================================================
-- RAG PAYLOAD TABLE  (single source of truth for the Phase 5 RAG pipeline)
-- DESIGN CHANGE (post-M2): the generated column on service_logs was
--   removed. A generated column cannot JOIN other tables, so it could
--   only ever produce a partial preview of the text that
--   sp_Prepare_RAG_Payloads() builds. All RAG text assembly now lives
--   in ONE place -- the stored procedure -- and lands in this table.
--
-- Downstream consumers (Python, Phase 5):
--   * embedding step reads payload_text and stores it with the
--     metadata JSON in ChromaDB (vector side of the ERP source)
--   * the filter columns (equipment_id, equipment_model, customer_id,
--     dispatch_date, warranty_status) let the retriever apply SQL-style
--     pre-filters and link to telemetry via equipment_id
--   * metadata (JSON) carries provenance: which source tables/IDs
--     produced each payload, so answers can cite them
-- =====================================================================
DROP TABLE IF EXISTS rag_payloads;
CREATE TABLE rag_payloads (
  payload_id      INT AUTO_INCREMENT PRIMARY KEY,
  source_table    VARCHAR(50)  NOT NULL,   -- 'service_logs' | 'warranty_claims'
  source_id       VARCHAR(50)  NOT NULL,   -- dispatch_id / claim_id (provenance)
  payload_type    VARCHAR(30)  NOT NULL,   -- 'service_event' | 'warranty_claim'
  equipment_id    VARCHAR(50),             -- ERP id (EQ-xxxx); telemetry links by MODEL, not by this id
  equipment_model VARCHAR(20),
  customer_id     VARCHAR(50),
  event_date      DATE,                    -- dispatch_date / claim_date
  record_status   VARCHAR(20),             -- service or claim status
  warranty_status VARCHAR(20),             -- In Warranty | Out of Warranty | Unknown (as of event_date)
  payload_text    TEXT         NOT NULL,   -- embedding-ready text block
  metadata        JSON,                    -- provenance + filter fields for the vector store
  char_length     INT,
  generated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_source   (source_table, source_id),
  KEY        idx_equip   (equipment_id),
  KEY        idx_model   (equipment_model),
  KEY        idx_date    (event_date)
) ENGINE=InnoDB;


-- =====================================================================
-- AUDIT LOG TABLE
-- DECISION: old_values and new_values stored as JSON (not pipe-delimited
--   VARCHAR strings). Reasons:
--     1. JSON is queryable with JSON_VALUE() without brittle string
--        parsing — e.g. JSON_VALUE(old_values,'$.status') gives
--        exactly the pre-change status field.
--     2. Self-documenting: key names travel with the data, so the log
--        is readable without a data dictionary.
--     3. Schema-flexible: adding a new field to capture in a trigger
--        requires no ALTER TABLE — just add a key to the JSON object.
--     4. NULL is typed in JSON (null vs "NULL" string ambiguity gone).
--     5. Directly consumable by the Python provenance/citation system
--        in Phase 5 — json.loads() with no pre-processing.
--   MariaDB 12.3 supports the JSON type and JSON_VALUE() natively.
-- IMMUTABILITY: enforced by BEFORE UPDATE/DELETE guard triggers below
--   AND by granting app roles only INSERT + SELECT (Part 3 security).
-- =====================================================================
DROP TABLE IF EXISTS Audit_Logs;
CREATE TABLE Audit_Logs (
  audit_id        BIGINT AUTO_INCREMENT PRIMARY KEY,
  changed_at      TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,  -- timestamp
  changed_by      VARCHAR(128),                            -- user
  table_name      VARCHAR(64)  NOT NULL,                   -- which table
  operation_type  VARCHAR(10)  NOT NULL,                   -- INSERT/UPDATE
  record_id       VARCHAR(50),                             -- PK of changed row
  old_values      JSON,          -- pre-change snapshot  (NULL on INSERT)
  new_values      JSON,          -- post-change snapshot
  change_desc     VARCHAR(255),  -- human-readable summary
  KEY idx_table_op  (table_name, operation_type),
  KEY idx_record    (record_id),
  KEY idx_changed_at(changed_at)
) ENGINE=InnoDB;