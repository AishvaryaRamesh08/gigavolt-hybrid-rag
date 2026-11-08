-- 06_rag_payloads_table.sql
-- Target table of sp_Prepare_RAG_Payloads() (07_sp_prepare_rag_payloads.sql). Holds the embedding-ready
-- ERP text + provenance metadata that the Phase 5 pipeline embeds into ChromaDB and
-- that the SQL retriever filters (equipment_id / model / warranty_status).
USE gigavolt_erp;

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
