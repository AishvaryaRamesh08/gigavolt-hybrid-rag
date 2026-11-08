DROP DATABASE IF EXISTS gigavolt_erp;
CREATE DATABASE gigavolt_erp
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE gigavolt_erp;

CREATE TABLE import_customers (
    customer_id     TEXT,
    company_name    TEXT,
    contact_name    TEXT,
    phone           TEXT,
    email           TEXT,
    address         TEXT,
    city            TEXT,
    state           TEXT,
    zip             TEXT,
    country         TEXT,
    created_date    TEXT,
    status          TEXT
) ENGINE = InnoDB;

CREATE TABLE import_equipment (
    equipment_id        TEXT,
    customer_id         TEXT,
    model                TEXT,
    serial_number        TEXT,
    install_date         TEXT,
    capacity_kw          TEXT,
    voltage              TEXT,
    warranty_expiration  TEXT,
    status               TEXT,
    location_notes       TEXT
) ENGINE = InnoDB;

CREATE TABLE import_dispatches (
    dispatch_id          TEXT,
    equipment_id         TEXT,
    customer_id          TEXT,
    dispatch_date        TEXT,
    technician           TEXT,
    service_type         TEXT,
    hours_spent          TEXT,
    labor_cost           TEXT,
    resolution_summary   TEXT,
    status               TEXT
) ENGINE = InnoDB;

CREATE TABLE import_parts (
    part_id          TEXT,
    part_name        TEXT,
    category         TEXT,
    manufacturer     TEXT,
    supplier         TEXT,
    unit_cost        TEXT,
    unit_price       TEXT,
    stock_quantity   TEXT,
    reorder_level    TEXT
) ENGINE = InnoDB;

CREATE TABLE import_warranty_claims (
    claim_id          TEXT,
    equipment_id      TEXT,
    dispatch_id       TEXT,
    part_id           TEXT,
    claim_date        TEXT,
    claim_amount      TEXT,
    approved_amount   TEXT,
    status            TEXT,
    denial_reason     TEXT,
    claim_notes       TEXT
) ENGINE = InnoDB;
