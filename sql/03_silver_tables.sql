use gigavolt_erp;

drop table if exists warranty_claims;
drop table if exists service_logs;
drop table if exists equipment_units;
drop table if exists customers;
drop table if exists locations;
drop table if exists equipment_models;
drop table if exists parts_inventory;

-- locations: one row per zip (zip -> city, state, country)
create table locations(
zip char(5) primary key,
city varchar(100) not null,
state char(2) not null,
country varchar(3)
) engine=InnoDB;

-- customers (3NF): city/state/country removed, zip is the FK
create table customers(
customer_id varchar(50) primary key,
company_name varchar(150) not null,
contact_name varchar(100) not null,
phone varchar(20),
email varchar(150),
address varchar(200),
zip char(5),
created_date date,
status varchar(10),
foreign key (zip) references locations(zip)
on delete restrict
on update cascade
) engine=InnoDB;

create table equipment_models(
model varchar(20) primary key,
capacity_kw int not null,
voltage int not null
) engine=InnoDB;
 
-- equipment_units (3NF): capacity_kw/voltage removed, model is the FK
create table equipment_units(
equipment_id varchar(50) primary key,
customer_id varchar(50),
model varchar(20),
serial_number varchar(50),
install_date date,
warranty_expiration date,
status varchar(20),
location_notes varchar(255),
foreign key (customer_id) references customers(customer_id)
on delete set null
on update cascade,
foreign key (model) references equipment_models(model)
on delete set null
on update cascade
) engine=InnoDB;

create table service_logs(
dispatch_id varchar(50) primary key,
equipment_id varchar(50),
customer_id varchar(50),
dispatch_date date,
technician varchar(100),
service_type varchar(50),
hours_spent decimal(5,1),
labor_cost decimal(10,2),
resolution_summary varchar(1000),
status varchar(20),
foreign key (equipment_id) references equipment_units(equipment_id)
on delete set null
on update cascade,
foreign key (customer_id) references customers(customer_id)
on delete set null
on update cascade
) engine=InnoDB;

create table parts_inventory(
part_id varchar(50) primary key,
part_name varchar(150) not null,
category varchar(50),
manufacturer varchar(100),
supplier varchar(50),
unit_cost decimal(10,2),
unit_price decimal(10,2),
stock_quantity int,
reorder_level int
) engine=InnoDB;

create table warranty_claims(
claim_id varchar(50) primary key,
equipment_id varchar(50),
dispatch_id varchar(50),
part_id varchar(50),
claim_date date,
claim_amount decimal(10,2),
approved_amount decimal(10,2),
status varchar(20),
denial_reason varchar(255),
claim_notes varchar(500),
foreign key (equipment_id) references equipment_units(equipment_id)
on delete cascade
on update cascade,
foreign key (dispatch_id) references service_logs(dispatch_id)
on delete set null
on update cascade,
foreign key (part_id) references parts_inventory(part_id)
on delete set null
on update cascade
) engine=InnoDB;