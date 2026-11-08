USE gigavolt_erp;

DELIMITER $$

-- =====================================================================
-- IMMUTABILITY GUARDS
-- BEFORE UPDATE and BEFORE DELETE on Audit_Logs raise an error so
-- historical rows can never be altered or removed via SQL.
-- =====================================================================
CREATE TRIGGER trg_auditlogs_no_update
BEFORE UPDATE ON Audit_Logs FOR EACH ROW
BEGIN
  SIGNAL SQLSTATE '45000'
    SET MESSAGE_TEXT = 'Audit_Logs is immutable: UPDATE not permitted';
END $$

CREATE TRIGGER trg_auditlogs_no_delete
BEFORE DELETE ON Audit_Logs FOR EACH ROW
BEGIN
  SIGNAL SQLSTATE '45000'
    SET MESSAGE_TEXT = 'Audit_Logs is immutable: DELETE not permitted';
END $$


-- =====================================================================
-- service_logs TRIGGERS
-- DECISION: Audit the financially and operationally significant fields
--   (technician, status, labor_cost, resolution_summary).
--   JSON_OBJECT() builds a typed, queryable snapshot — no pipe strings.
-- =====================================================================

-- AFTER INSERT: track new service log creation
CREATE TRIGGER trg_service_logs_ai
AFTER INSERT ON service_logs FOR EACH ROW
BEGIN
  INSERT INTO Audit_Logs
    (changed_by, table_name, operation_type, record_id,
     old_values, new_values, change_desc)
  VALUES (
    CURRENT_USER(),
    'service_logs',
    'INSERT',
    NEW.dispatch_id,
    NULL,   -- no prior state on insert
    JSON_OBJECT(
      'dispatch_id',        NEW.dispatch_id,
      'equipment_id',       NEW.equipment_id,
      'customer_id',        NEW.customer_id,
      'dispatch_date',      DATE_FORMAT(NEW.dispatch_date, '%Y-%m-%d'),
      'technician',         NEW.technician,
      'service_type',       NEW.service_type,
      'hours_spent',        NEW.hours_spent,
      'labor_cost',         NEW.labor_cost,
      'status',             NEW.status,
      'resolution_summary', NEW.resolution_summary
    ),
    CONCAT('New service log created: ', NEW.dispatch_id)
  );
END $$

-- BEFORE UPDATE: capture old values before they are overwritten
CREATE TRIGGER trg_service_logs_bu
BEFORE UPDATE ON service_logs FOR EACH ROW
BEGIN
  INSERT INTO Audit_Logs
    (changed_by, table_name, operation_type, record_id,
     old_values, new_values, change_desc)
  VALUES (
    CURRENT_USER(),
    'service_logs',
    'UPDATE',
    OLD.dispatch_id,
    -- pre-change snapshot (the whole point of BEFORE UPDATE)
    JSON_OBJECT(
      'technician',         OLD.technician,
      'service_type',       OLD.service_type,
      'hours_spent',        OLD.hours_spent,
      'labor_cost',         OLD.labor_cost,
      'status',             OLD.status,
      'resolution_summary', OLD.resolution_summary
    ),
    -- post-change snapshot (NEW is already available in BEFORE trigger)
    JSON_OBJECT(
      'technician',         NEW.technician,
      'service_type',       NEW.service_type,
      'hours_spent',        NEW.hours_spent,
      'labor_cost',         NEW.labor_cost,
      'status',             NEW.status,
      'resolution_summary', NEW.resolution_summary
    ),
    CONCAT('Service log updated: ', OLD.dispatch_id)
  );
END $$


-- =====================================================================
-- warranty_claims TRIGGERS
-- Financial data (claim_amount, approved_amount) is the most important
-- field set to audit here.
-- =====================================================================

CREATE TRIGGER trg_warranty_claims_ai
AFTER INSERT ON warranty_claims FOR EACH ROW
BEGIN
  INSERT INTO Audit_Logs
    (changed_by, table_name, operation_type, record_id,
     old_values, new_values, change_desc)
  VALUES (
    CURRENT_USER(),
    'warranty_claims',
    'INSERT',
    NEW.claim_id,
    NULL,
    JSON_OBJECT(
      'claim_id',       NEW.claim_id,
      'equipment_id',   NEW.equipment_id,
      'dispatch_id',    NEW.dispatch_id,
      'part_id',        NEW.part_id,
      'claim_date',     DATE_FORMAT(NEW.claim_date, '%Y-%m-%d'),
      'claim_amount',   NEW.claim_amount,
      'approved_amount',NEW.approved_amount,
      'status',         NEW.status,
      'denial_reason',  NEW.denial_reason
    ),
    CONCAT('New warranty claim created: ', NEW.claim_id)
  );
END $$

CREATE TRIGGER trg_warranty_claims_bu
BEFORE UPDATE ON warranty_claims FOR EACH ROW
BEGIN
  INSERT INTO Audit_Logs
    (changed_by, table_name, operation_type, record_id,
     old_values, new_values, change_desc)
  VALUES (
    CURRENT_USER(),
    'warranty_claims',
    'UPDATE',
    OLD.claim_id,
    JSON_OBJECT(
      'claim_amount',   OLD.claim_amount,
      'approved_amount',OLD.approved_amount,
      'status',         OLD.status,
      'denial_reason',  OLD.denial_reason,
      'claim_notes',    OLD.claim_notes
    ),
    JSON_OBJECT(
      'claim_amount',   NEW.claim_amount,
      'approved_amount',NEW.approved_amount,
      'status',         NEW.status,
      'denial_reason',  NEW.denial_reason,
      'claim_notes',    NEW.claim_notes
    ),
    CONCAT('Warranty claim updated: ', OLD.claim_id)
  );
END $$


-- =====================================================================
-- customers TRIGGERS
-- Customers hold sensitive PII (contact names, email, phone, address).
-- Auditing changes here also supports the security model rationale.
-- =====================================================================

CREATE TRIGGER trg_customers_ai
AFTER INSERT ON customers FOR EACH ROW
BEGIN
  INSERT INTO Audit_Logs
    (changed_by, table_name, operation_type, record_id,
     old_values, new_values, change_desc)
  VALUES (
    CURRENT_USER(),
    'customers',
    'INSERT',
    NEW.customer_id,
    NULL,
    JSON_OBJECT(
      'customer_id',  NEW.customer_id,
      'company_name', NEW.company_name,
      'contact_name', NEW.contact_name,
      'email',        NEW.email,
      'phone',        NEW.phone,
      'status',       NEW.status
    ),
    CONCAT('New customer created: ', NEW.customer_id)
  );
END $$

CREATE TRIGGER trg_customers_bu
BEFORE UPDATE ON customers FOR EACH ROW
BEGIN
  INSERT INTO Audit_Logs
    (changed_by, table_name, operation_type, record_id,
     old_values, new_values, change_desc)
  VALUES (
    CURRENT_USER(),
    'customers',
    'UPDATE',
    OLD.customer_id,
    JSON_OBJECT(
      'company_name', OLD.company_name,
      'contact_name', OLD.contact_name,
      'email',        OLD.email,
      'phone',        OLD.phone,
      'address',      OLD.address,
      'status',       OLD.status
    ),
    JSON_OBJECT(
      'company_name', NEW.company_name,
      'contact_name', NEW.contact_name,
      'email',        NEW.email,
      'phone',        NEW.phone,
      'address',      NEW.address,
      'status',       NEW.status
    ),
    CONCAT('Customer updated: ', OLD.customer_id)
  );
END $$

-- =====================================================================
-- equipment_units TRIGGERS
-- JUSTIFICATION: Equipment status changes (e.g., In Service ->
--   Decommissioned) affect warranty eligibility and service dispatch.
--   Auditing these changes closes the loop between service_logs and
--   warranty_claims audit trails already captured above.
-- =====================================================================

CREATE TRIGGER trg_equipment_units_ai
AFTER INSERT ON equipment_units FOR EACH ROW
BEGIN
  INSERT INTO Audit_Logs
    (changed_by, table_name, operation_type, record_id,
     old_values, new_values, change_desc)
  VALUES (
    CURRENT_USER(),
    'equipment_units',
    'INSERT',
    NEW.equipment_id,
    NULL,
    JSON_OBJECT(
      'equipment_id',   NEW.equipment_id,
      'customer_id',    NEW.customer_id,
      'model',          NEW.model,
      'serial_number',  NEW.serial_number,
      'status',         NEW.status,
      'warranty_expiration', DATE_FORMAT(NEW.warranty_expiration, '%Y-%m-%d')
    ),
    CONCAT('New equipment unit registered: ', NEW.equipment_id)
  );
END $$

CREATE TRIGGER trg_equipment_units_bu
BEFORE UPDATE ON equipment_units FOR EACH ROW
BEGIN
  INSERT INTO Audit_Logs
    (changed_by, table_name, operation_type, record_id,
     old_values, new_values, change_desc)
  VALUES (
    CURRENT_USER(),
    'equipment_units',
    'UPDATE',
    OLD.equipment_id,
    JSON_OBJECT(
      'status',              OLD.status,
      'customer_id',         OLD.customer_id,
      'warranty_expiration', DATE_FORMAT(OLD.warranty_expiration, '%Y-%m-%d'),
      'location_notes',      OLD.location_notes
    ),
    JSON_OBJECT(
      'status',              NEW.status,
      'customer_id',         NEW.customer_id,
      'warranty_expiration', DATE_FORMAT(NEW.warranty_expiration, '%Y-%m-%d'),
      'location_notes',      NEW.location_notes
    ),
    CONCAT('Equipment unit updated: ', OLD.equipment_id)
  );
END $$

DELIMITER ;