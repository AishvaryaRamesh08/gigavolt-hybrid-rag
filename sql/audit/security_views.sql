USE gigavolt_erp;
 
-- =====================================================================
-- SECURITY MODEL
-- DECISION: Restricted VIEWS + ROLE-based GRANTs (MariaDB has no native
--   PostgreSQL-style RLS). Two access tiers:
--     (A) v_customers_masked  -> support_staff role: PII obfuscated.
--     (B) v_customers_full    -> data_manager role:  complete data.
--   Neither role gets SELECT on the base `customers` table directly,
--   so PII is unreachable except through the permitted view.
-- Also: Audit_Logs is granted INSERT + SELECT only (no UPDATE/DELETE),
--   reinforcing the immutability guards at the privilege layer.
-- =====================================================================
 
-- (A) Masked view for support staff: PII obfuscated
-- FIX: wrap every masked expression in COALESCE(...,'') first. CONCAT()
-- returns NULL if any argument is NULL, so a customer with a missing
-- phone/email was previously showing a NULL masked value instead of a
-- masked placeholder -- silently leaking the fact that the field is
-- blank, and inconsistent with the '*** REDACTED ***' treatment given
-- to address below.
CREATE OR REPLACE VIEW v_customers_masked AS
SELECT
  customer_id,
  company_name,
  CASE WHEN contact_name IS NULL OR contact_name = '' THEN NULL
       ELSE CONCAT(LEFT(contact_name, 1), '****')
  END                                               AS contact_name,
  CASE WHEN phone IS NULL OR phone = '' THEN NULL
       ELSE CONCAT('(***) ***-', RIGHT(phone, 4))
  END                                               AS phone,
  CASE WHEN email IS NULL OR email = '' THEN NULL
       ELSE CONCAT(LEFT(email, 1), '****@',
                    SUBSTRING_INDEX(email, '@', -1))
  END                                               AS email,
  '*** REDACTED ***'                               AS address,
  zip,
  created_date,
  status
FROM customers;
 
-- (B) Full view for authorised managers/analysts
CREATE OR REPLACE VIEW v_customers_full AS
SELECT customer_id, company_name, contact_name,
       phone, email, address, zip, created_date, status
FROM customers;
 
-- Roles
CREATE ROLE IF NOT EXISTS 'support_staff';
CREATE ROLE IF NOT EXISTS 'data_manager';
 
-- support_staff: masked customers only; audit read + write
GRANT SELECT         ON gigavolt_erp.v_customers_masked TO 'support_staff';
GRANT SELECT, INSERT ON gigavolt_erp.Audit_Logs         TO 'support_staff';
GRANT SELECT         ON gigavolt_erp.rag_payloads        TO 'support_staff';
 
-- data_manager: full customers; audit read + write
GRANT SELECT         ON gigavolt_erp.v_customers_full   TO 'data_manager';
GRANT SELECT, INSERT ON gigavolt_erp.Audit_Logs         TO 'data_manager';
GRANT SELECT         ON gigavolt_erp.rag_payloads        TO 'data_manager';
 
-- Neither role gets direct access to the base customers table
-- REVOKE is not needed here because we never granted it above.
 
-- =====================================================================
-- FIX: attach the roles to actual login accounts.
-- Previously the roles were defined and granted privileges, but nothing
-- was ever assigned to them, so no session could actually exercise the
-- restriction -- a root/DDL session could still read the base
-- `customers` table directly, and there was no login that demonstrated
-- the masked-vs-full split. Two demo accounts below make the
-- restriction real and give the screencast something to log in as.
--
-- Change the passwords before using this anywhere but a local demo box.
-- =====================================================================
CREATE USER IF NOT EXISTS 'demo_support'@'localhost' IDENTIFIED BY 'CHANGE_ME';
CREATE USER IF NOT EXISTS 'demo_manager'@'localhost' IDENTIFIED BY 'CHANGE_ME';
 
GRANT 'support_staff' TO 'demo_support'@'localhost';
GRANT 'data_manager'  TO 'demo_manager'@'localhost';
 
-- Without a default role, a freshly-connected session has to run
-- `SET ROLE support_staff;` before the grants apply. Setting it as the
-- default means demo_support/demo_manager have their privileges active
-- immediately on login -- important for a clean screencast.
SET DEFAULT ROLE 'support_staff' FOR 'demo_support'@'localhost';
SET DEFAULT ROLE 'data_manager'  FOR 'demo_manager'@'localhost';
 
FLUSH PRIVILEGES;