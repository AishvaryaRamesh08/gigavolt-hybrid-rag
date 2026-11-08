-- Set connection charset FIRST, before anything else
SET NAMES utf8mb4;
SET character_set_database = utf8mb4;

-- Then select the database
USE gigavolt_erp;

TRUNCATE TABLE import_customers;
TRUNCATE TABLE import_equipment;
TRUNCATE TABLE import_dispatches;
TRUNCATE TABLE import_parts;
TRUNCATE TABLE import_warranty_claims;

LOAD DATA LOCAL INFILE '/opt/data/customers.csv'
INTO TABLE import_customers
FIELDS TERMINATED BY ','
ENCLOSED BY '"'
LINES TERMINATED BY '\r\n'
IGNORE 1 LINES;

LOAD DATA LOCAL INFILE '/opt/data/equipment.csv'
INTO TABLE import_equipment
FIELDS TERMINATED BY ','
ENCLOSED BY '"'
LINES TERMINATED BY '\r\n'
IGNORE 1 LINES;

LOAD DATA LOCAL INFILE '/opt/data/dispatches.csv'
INTO TABLE import_dispatches
FIELDS TERMINATED BY ','
ENCLOSED BY '"'
LINES TERMINATED BY '\r\n'
IGNORE 1 LINES;

LOAD DATA LOCAL INFILE '/opt/data/parts.csv'
INTO TABLE import_parts
FIELDS TERMINATED BY ','
ENCLOSED BY '"'
LINES TERMINATED BY '\r\n'
IGNORE 1 LINES;

LOAD DATA LOCAL INFILE '/opt/data/warranty_claims.csv'
INTO TABLE import_warranty_claims
FIELDS TERMINATED BY ','
ENCLOSED BY '"'
LINES TERMINATED BY '\r\n'
IGNORE 1 LINES;