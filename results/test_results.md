# Test query results and provenance map

## 1. What are common failure modes for Model X-7000 batteries in high-temperature environments?

Category: sample query 1. Total latency: 1.43 s. Traceable statements: 6/6.

**Answer**

The records for Model X-7000 batteries show specific thermal fault summaries and service resolutions for high-temperature conditions [S1][S2][S5].

* Model X-7000 telemetry records 38 of 61 telemetry readings at or above 60 C [S5].
* Fault ERR_INV_404 shows 20 readings on 3 units with a maximum temperature of 85.0 C from 2024-09-28 to 2026-09-18 (e.g., TLM-90004, TLM-90016, TLM-90030) [S2].
* Fault ERR_FUSE_001 shows 18 readings on 1 unit with a maximum temperature of 85.0 C from 2026-09-01 to 2026-09-18 (e.g., TLM-90026, TLM-90036, TLM-90046) [S2].
* Emergency dispatch for over-temperature alarm resulted in cleaned heat exchangers [S1].
* Improper thermal management can trigger an irreversible thermal event, with early warning indicators including a rapid delta in cell temperature greater than 2.5 degrees C per minute, a sudden drop in cell terminal voltage below 2.10 V, or outgassing detected by integrated off-gas sniffer arrays [S8].

**Provenance map**

| Tag | Source record | Cited |
|---|---|---|
| S1 | mariadb.service_logs / aggregate:resolutions:X-7000 | yes |
| S2 | mongodb.bms_telemetry / aggregate:model:X-7000 | yes |
| S3 | chromadb.gv_manuals / GV-MAN-X7000-001::c012 / GV-MAN-X7000-001 Manual.pdf p.2 / 2026-11-06T22:09:21+00:00 | no |
| S4 | mariadb.equipment_units+warranty_claims / aggregate:fleet:X-7000 | no |
| S5 | mongodb.bms_telemetry / aggregate:hot:X-7000 | yes |
| S6 | chromadb.gv_manuals / GV-MAN-X7000-001::c013 / GV-MAN-X7000-001 Manual.pdf p.3 / 2026-11-06T22:09:21+00:00 | no |
| S7 | mongodb.bms_telemetry / TLM-90002 / 2024-09-28T16:04:10.500000+00:00 | no |
| S8 | chromadb.gv_manuals / GV-MAN-X7000-001::c004 / GV-MAN-X7000-001 Manual.pdf p.2 / 2026-11-06T22:09:21+00:00 | yes |
| S9 | mongodb.bms_telemetry / TLM-90003 / 2024-09-28T16:04:11.880000+00:00 | no |
| S10 | chromadb.gv_manuals / GV-MAN-X7000-001::c000 / GV-MAN-X7000-001 Manual.pdf p.1 / 2026-11-06T22:09:21+00:00 | no |
| S11 | mongodb.bms_telemetry / TLM-90004 / 2024-09-28T16:04:12.010000+00:00 | no |
| S12 | chromadb.gv_manuals / GV-SOP-DECOM-601::c001 / GV-SOP-DECOM-601 SOP EOL Decomissioning.pdf p.1 / 2026-11-06T22:09:21+00:00 | no |
| S13 | mongodb.bms_telemetry / TLM-90026 / 2026-09-01T11:30:00+00:00 | no |
| S14 | chromadb.gv_manuals / GV-SUP-REP-401::c001 / GV-SUP-REP-401 Supply Chain Integration Brief.pdf p.1 / 2026-11-06T22:09:21+00:00 | no |

## 2. Which suppliers provide lithium cells for our commercial energy storage units?

Category: sample query 2. Total latency: 3.36 s. Traceable statements: 4/4.

**Answer**

Commercial energy storage unit lithium cells are provided by SinoPower Cell Foundry and Aura Energy Storage Ltd [S2][S8].

* SinoPower Cell Foundry (SUP-SPC-11) supplies Prismacell 280Ah raw cells (CEL-LFP-280) for Megapack X-7000 and CompactGrid C-1200 battery modules [S2][S10].
* Voltaic Core Technologies (SUP-VCT-01) manufactures the Prismacell 280Ah cell under contract [S10].
* Aura Energy Storage Ltd. (SUP-AUR-04) fabricates CobaltMax 65Ah NMC-811 pouch cells (CEL-NMC-065) deployed strictly within PowerStation G-3500 units [S6][S8].

**Provenance map**

| Tag | Source record | Cited |
|---|---|---|
| S1 | mariadb.parts_inventory / aggregate:supplier:Supplier-C | no |
| S2 | chromadb.gv_manuals / GV-SUP-REP-401::c002 / GV-SUP-REP-401 Supply Chain Integration Brief.pdf p.1 / 2026-11-06T22:09:21+00:00 | yes |
| S3 | mariadb.parts_inventory / aggregate:supplier:Supplier-A | no |
| S4 | chromadb.gv_manuals / GV-SUP-REP-401::c001 / GV-SUP-REP-401 Supply Chain Integration Brief.pdf p.1 / 2026-11-06T22:09:21+00:00 | no |
| S5 | mariadb.parts_inventory / aggregate:supplier:Supplier-D | no |
| S6 | chromadb.gv_manuals / GV-SPEC-CELL-NMC-65::c001 / GV-SPEC-CELL-NMC-65 Datasheet.pdf p.1 / 2026-11-06T22:09:21+00:00 | yes |
| S7 | mariadb.parts_inventory / aggregate:supplier:Supplier-E | no |
| S8 | chromadb.gv_manuals / GV-SPEC-CELL-NMC-65::c000 / GV-SPEC-CELL-NMC-65 Datasheet.pdf p.1 / 2026-11-06T22:09:21+00:00 | yes |
| S9 | mariadb.parts_inventory / aggregate:supplier:Supplier-B | no |
| S10 | chromadb.gv_manuals / GV-SPEC-CELL-LFP-08::c000 / GV-SPEC-CELL-LFP-08 Datasheet.pdf p.1 / 2026-11-06T22:09:21+00:00 | yes |
| S11 | chromadb.gv_manuals / GV-SOP-DECOM-601::c001 / GV-SOP-DECOM-601 SOP EOL Decomissioning.pdf p.1 / 2026-11-06T22:09:21+00:00 | no |

## 3. Show me service history for equipment unit SN-4829 and related warranty claims

Category: sample query 3, not in ERP. Total latency: 3.45 s. Traceable statements: 6/6.

**Answer**

Unit SN-4829 has no service or warranty records in the ERP system, and its telemetry shows no faults [S1][S2].

* No ERP record exists for SN-4829 because the equipment_units table has no matching equipment ID or serial number [S1].
* Unit SN-4829 has 18 telemetry readings in total, and none of them contain a fault code [S2].
* Telemetry reading TLM-90178 from 2026-09-16 12:15:00 UTC shows Model G-3500 in standby status with no fault, 800 V, 0 A, 31.0 C, SOC 95.0%, and a delta of 9 mV [S8].
* Telemetry reading TLM-90188 from 2026-09-17 12:15:00 UTC shows Model G-3500 in standby status with no fault, 800 V, 0 A, 31.0 C, SOC 95.0%, and a delta of 9 mV [S6].
* Telemetry reading TLM-90198 from 2026-09-18 12:15:00 UTC shows Model G-3500 in standby status with no fault, 800 V, 0 A, 31.0 C, SOC 95.0%, and a delta of 9 mV [S4].

**Provenance map**

| Tag | Source record | Cited |
|---|---|---|
| S1 | mariadb.equipment_units / lookup:SN-4829 | yes |
| S2 | mongodb.bms_telemetry / aggregate:unit:SN-4829 | yes |
| S3 | chromadb.gv_manuals / GV-SOP-WAR-101::c001 / GV-SOP-WAR-101 SOP Field Warranty Claims.pdf p.2 / 2026-11-06T22:09:21+00:00 | no |
| S4 | mongodb.bms_telemetry / TLM-90198 / 2026-09-18T12:15:00+00:00 | yes |
| S5 | chromadb.gv_manuals / GV-SOP-WAR-101::c000 / GV-SOP-WAR-101 SOP Field Warranty Claims.pdf p.1 / 2026-11-06T22:09:21+00:00 | no |
| S6 | mongodb.bms_telemetry / TLM-90188 / 2026-09-17T12:15:00+00:00 | yes |
| S7 | chromadb.gv_manuals / GV-INC-2024-119::c000 / GV-INC-2024-119 Field Incident Low Isolation Trip.pdf p.1 / 2026-11-06T22:09:21+00:00 | no |
| S8 | mongodb.bms_telemetry / TLM-90178 / 2026-09-16T12:15:00+00:00 | yes |
| S9 | chromadb.gv_manuals / GV-MAN-C1200-003::c007 / GV-MAN-C1200-003 Manual.pdf p.3 / 2026-11-06T22:09:21+00:00 | no |
| S10 | chromadb.gv_manuals / GV-ECO-2024-019::c006 / GV-ECO-2024-019 Engineering Change Order.pdf p.1 / 2026-11-06T22:09:21+00:00 | no |
| S11 | chromadb.gv_manuals / GV-ECO-2024-019::c001 / GV-ECO-2024-019 Engineering Change Order.pdf p.1 / 2026-11-06T22:09:21+00:00 | no |

## 4. Show me the service history and warranty claims for equipment unit EQ-7171

Category: multi-source unit. Total latency: 3.48 s. Traceable statements: 8/8.

**Answer**

The service history and warranty claims for equipment unit EQ-7171 consist of multiple service events and warranty claims recorded in the enterprise database [S1][S2][S3][S4][S5][S6][S7][S8].

* Service Event DISP-14684: Software Update on 2021-06-05 (In Progress), with technician Michael Brown, 1.7 hours, $127.50 labor cost, and resolution to calibrate inverter output [S8].
* Warranty Claim CLM-10026: Filed 2021-09-12 (Under Review) for DisplayTech LCD Unit Model-A (PRT-2138) with claimed amount $1776.70, linked to dispatch DISP-14336 for unit EQ-5220 [S7].
* Warranty Claim CLM-9599: Filed 2021-10-19 (Approved) for DC Contactor 400A Model-B (PRT-2136) with claimed and approved amount $2291.49, linked to dispatch DISP-13247 for unit EQ-5905 [S6].
* Service Event DISP-14701: Software Update on 2022-05-10 (Pending), with 10.3 hours, $1545.00 labor cost, and resolution to replace faulty thermal sensor and verify system bus voltage [S4].
* Warranty Claim CLM-9714: Filed 2022-05-04 (Rejected) for Thermal Sensor Module Model-C (PRT-2147) with claimed $522.82 and approved $0.00 due to unauthorized modification detected, linked to dispatch DISP-13115 for unit EQ-5270 [S5].
* Warranty Claim CLM-9208: Filed 2023-08-06 (Pending) for Fusing Unit 200A Model-PRO (PRT-2020) with claimed $4241.79, linked to dispatch DISP-13497 for unit EQ-5224 [S3].
* Service Event DISP-10768: Emergency Repair on 2023-09-28 (Cancelled), with 10.1 hours, $1515.00 labor cost, and resolution to clean heat exchanger for over-temperature alarm [S2].

**Provenance map**

| Tag | Source record | Cited |
|---|---|---|
| S1 | mariadb.equipment_units / EQ-7171 | yes |
| S2 | mariadb.rag_payloads / DISP-10768 / 2023-09-28 | yes |
| S3 | mariadb.rag_payloads / CLM-9208 / 2023-08-06 | yes |
| S4 | mariadb.rag_payloads / DISP-14701 / 2022-05-10 | yes |
| S5 | mariadb.rag_payloads / CLM-9714 / 2022-05-04 | yes |
| S6 | mariadb.rag_payloads / CLM-9599 / 2021-10-19 | yes |
| S7 | mariadb.rag_payloads / CLM-10026 / 2021-09-12 | yes |
| S8 | mariadb.rag_payloads / DISP-14684 / 2021-06-05 | yes |
| S9 | mongodb.bms_telemetry / aggregate:model:X-7000 | no |
| S10 | chromadb.gv_manuals / GV-SOP-WAR-101::c001 / GV-SOP-WAR-101 SOP Field Warranty Claims.pdf p.2 / 2026-11-06T22:09:21+00:00 | no |
| S11 | mongodb.bms_telemetry / TLM-90002 / 2024-09-28T16:04:10.500000+00:00 | no |
| S12 | chromadb.gv_manuals / GV-SOP-WAR-101::c000 / GV-SOP-WAR-101 SOP Field Warranty Claims.pdf p.1 / 2026-11-06T22:09:21+00:00 | no |
| S13 | mongodb.bms_telemetry / TLM-90003 / 2024-09-28T16:04:11.880000+00:00 | no |
| S14 | chromadb.gv_manuals / GV-MAN-C1200-003::c007 / GV-MAN-C1200-003 Manual.pdf p.3 / 2026-11-06T22:09:21+00:00 | no |

## 5. What happened to unit SN-X7-0094 and which components were flagged?

Category: telemetry unit. Total latency: 1.23 s. Traceable statements: 6/6.

**Answer**

Unit SN-X7-0094 suffered an uncontrolled arc flash within Inverter Bay INV-01 during a scheduled high-power ramp from standby to 1,750 kW full export [S11].
No ERP record exists for SN-X7-0094 [S1].
* A scheduled high-power ramp was initiated on 2024-09-28 at 16:04:10 UTC, status RAMP_UP with no fault and flagged parts none [S4].
* A pre-charge resistor failure was detected on 2024-09-28 at 16:04:11 UTC with firmware v2.4.08 abort failed, and part RES-PR-50 was flagged [S6].
* A DC overcurrent trip and arc flash occurred on 2024-09-28 at 16:04:12 UTC, status CRITICAL_FAULT with fault ERR_INV_404, reaching 85.0 C [S2][S8].
* Parts CON-MAIN-800, PCB-DRV-3500, and INV-SCR-9901 were flagged during the critical fault telemetry reading TLM-90004 [S8].

**Provenance map**

| Tag | Source record | Cited |
|---|---|---|
| S1 | mariadb.equipment_units / lookup:SN-X7-0094 | yes |
| S2 | mongodb.bms_telemetry / aggregate:unit:SN-X7-0094 | yes |
| S3 | chromadb.gv_manuals / GV-INC-2024-119::c000 / GV-INC-2024-119 Field Incident Low Isolation Trip.pdf p.1 / 2026-11-06T22:09:21+00:00 | no |
| S4 | mongodb.bms_telemetry / TLM-90002 / 2024-09-28T16:04:10.500000+00:00 | yes |
| S5 | chromadb.gv_manuals / GV-INC-2024-119::c001 / GV-INC-2024-119 Field Incident Low Isolation Trip.pdf p.1 / 2026-11-06T22:09:21+00:00 | no |
| S6 | mongodb.bms_telemetry / TLM-90003 / 2024-09-28T16:04:11.880000+00:00 | yes |
| S7 | chromadb.gv_manuals / GV-INC-2024-088::c000 / GV-INC-2024-088 Field Incident Investigation Report.pdf p.1 / 2026-11-06T22:09:21+00:00 | no |
| S8 | mongodb.bms_telemetry / TLM-90004 / 2024-09-28T16:04:12.010000+00:00 | yes |
| S9 | chromadb.gv_manuals / GV-ECO-2024-019::c000 / GV-ECO-2024-019 Engineering Change Order.pdf p.1 / 2026-11-06T22:09:21+00:00 | no |
| S10 | chromadb.gv_manuals / GV-SOP-WAR-101::c002 / GV-SOP-WAR-101 SOP Field Warranty Claims.pdf p.2 / 2026-11-06T22:09:21+00:00 | no |
| S11 | chromadb.gv_manuals / GV-INC-2024-104::c001 / GV-INC-2024-104 Field Incident Report Contactor Flashover.pdf p.1 / 2026-11-06T22:09:21+00:00 | yes |

## 6. What does fault code ERR_COOL_302 indicate and on which units has it occurred?

Category: fault code. Total latency: 5.20 s. Traceable statements: 4/4.

**Answer**

Fault code ERR_COOL_302 indicates low coolant flow rate, and it has occurred on units SN-C12-0055 and SN-C12-0001 [S1][S3][S5].

* The model-level manual defines the fault as low coolant flow rate with a moderate severity, stemming from an airlock in the glycol manifold, strainer clog, or impeller cavitation [S2].
* Telemetry reading TLM-90006 for unit SN-C12-0055 recorded status WARNING, moderate severity, 55.4 C, and flagged parts SEN-FL-022 and FLT-GLY-701 [S3].
* Telemetry reading TLM-90020 for unit SN-C12-0001 recorded status WARNING, moderate severity, 56.5 C, and flagged part FLT-GLY-701 with impeller cavitation detected [S5].

**Provenance map**

| Tag | Source record | Cited |
|---|---|---|
| S1 | mongodb.bms_telemetry / aggregate:fault:ERR_COOL_302 | yes |
| S2 | chromadb.gv_manuals / GV-MAN-X7000-001::c015 / GV-MAN-X7000-001 Manual.pdf p.3 / 2026-11-06T22:09:21+00:00 | yes |
| S3 | mongodb.bms_telemetry / TLM-90006 / 2025-01-14T08:30:00+00:00 | yes |
| S4 | chromadb.gv_manuals / GV-ECO-2024-031::c000 / GV-ECO-2024-031 Change Order - Chiller Relief Valve.pdf p.1 / 2026-11-06T22:09:21+00:00 | no |
| S5 | mongodb.bms_telemetry / TLM-90020 / 2026-08-20T15:00:00+00:00 | yes |
| S6 | chromadb.gv_manuals / GV-SOP-WAR-101::c005 / GV-SOP-WAR-101 SOP Field Warranty Claims.pdf p.1 / 2026-11-06T22:09:21+00:00 | no |
| S7 | chromadb.gv_manuals / GV-ECO-2024-031::c001 / GV-ECO-2024-031 Change Order - Chiller Relief Valve.pdf p.1 / 2026-11-06T22:09:21+00:00 | no |
| S8 | chromadb.gv_manuals / GV-MAN-X7000-001::c013 / GV-MAN-X7000-001 Manual.pdf p.3 / 2026-11-06T22:09:21+00:00 | no |
| S9 | chromadb.gv_manuals / GV-MAN-C1200-003::c013 / GV-MAN-C1200-003 Manual.pdf p.3 / 2026-11-06T22:09:21+00:00 | no |

## 7. How hot do C-1200 units get during thermal faults and what do the manuals advise?

Category: thermal, model. Total latency: 1.43 s. Traceable statements: 4/4.

**Answer**

C-1200 units reach temperatures up to 82.5 C during thermal faults [S2][S10], and the manuals advise specific corrective actions and maintenance procedures.
- Telemetry readings show temperatures reaching 82.5 C for fault ERR_BMS_708, 68.2 C for ERR_BMS_705, 56.5 C for ERR_COOL_302, and 51.5 C for ERR_SENS_005 and ERR_HVAC_502 [S2].
- For the C-1200 model, GV-MAN-C1200-003 identifies the primary root cause of humidity excursion fault ERR_SENS_005 as a degraded enclosure door gasket and condensation heater failure, and instructs engineers to inspect condensation heater HTR-CAB-100 and silicone door seal GSK-DR-1200, replacing them if worn or cracked [S3].
- For model X-7000, GV-SOP-COMM-201 instructs technicians to top off with an approved 50/50 ethylene glycol and deionized water mixture, purge air pockets through service valve SV-3 until coolant flow rate sensor SEN-FL-022 reads steady at >= 42 L/min, and energize the 480 V AC 3-phase auxiliary service transformer to confirm cabinet heating elements HTR-CAB-100 and BMS control power come online without triggering auxiliary circuit breakers [S11].
The available records do not show ERP equipment or service records for model C-1200 [S1].

**Provenance map**

| Tag | Source record | Cited |
|---|---|---|
| S1 | mariadb.equipment_models / lookup:C-1200 | no |
| S2 | mongodb.bms_telemetry / aggregate:model:C-1200 | yes |
| S3 | chromadb.gv_manuals / GV-MAN-C1200-003::c013 / GV-MAN-C1200-003 Manual.pdf p.3 / 2026-11-06T22:09:21+00:00 | yes |
| S4 | mongodb.bms_telemetry / aggregate:hot:C-1200 | no |
| S5 | chromadb.gv_manuals / GV-MAN-C1200-003::c012 / GV-MAN-C1200-003 Manual.pdf p.3 / 2026-11-06T22:09:21+00:00 | no |
| S6 | mongodb.bms_telemetry / TLM-90006 / 2025-01-14T08:30:00+00:00 | no |
| S7 | chromadb.gv_manuals / GV-MAN-C1200-003::c008 / GV-MAN-C1200-003 Manual.pdf p.4 / 2026-11-06T22:09:21+00:00 | no |
| S8 | mongodb.bms_telemetry / TLM-90007 / 2025-01-14T08:45:00+00:00 | no |
| S9 | chromadb.gv_manuals / GV-INC-2024-088::c003 / GV-INC-2024-088 Field Incident Investigation Report.pdf p.1 / 2026-11-06T22:09:21+00:00 | no |
| S10 | mongodb.bms_telemetry / TLM-90008 / 2025-01-14T09:00:00+00:00 | yes |
| S11 | chromadb.gv_manuals / GV-SOP-COMM-201::c005 / GV-SOP-COMM-201 SOP Megapack X-7000 SAT.pdf p.1 / 2026-11-06T22:09:21+00:00 | yes |
| S12 | mongodb.bms_telemetry / TLM-90020 / 2026-08-20T15:00:00+00:00 | no |
| S13 | chromadb.gv_manuals / GV-MAN-C1200-003::c001 / GV-MAN-C1200-003 Manual.pdf p.1 / 2026-11-06T22:09:21+00:00 | no |
| S14 | mongodb.bms_telemetry / TLM-90017 / 2026-04-03T11:45:00+00:00 | no |

## 8. What is the procedure for filing a field warranty claim?

Category: procedure. Total latency: 2.77 s. Traceable statements: 5/9.

**Answer**

The procedure for filing a field warranty claim involves four main steps handled by Tier-2 and Tier-3 technical support agents and dispatch coordinators [S1].
* Step 1. Ticket Initiation: A ticket is opened in the relational database linking the customer ID, equipment unit serial number (Equipment_Units), and initial symptom description [S1][S2].
* Step 2. Telemetry Log Attachment: Dispatchers must pull and parse the trailing 48 hours of telemetry logs (bms_telemetry.json), scanning them for pre-trip alerts, peak cell temperatures, and bus voltage anomalies [S2][S3].
* Step 3. Parts Pre-Allocation: Required replacement parts such as FLT-GLY-701, PCB-DRV-3500, or FUS-FAST-600A must be allocated in the Parts_Inventory table prior to dispatching a service technician to prevent truck-roll delays [S3][S4].
* Step 4. Safety Clearance Sign-Off: If any Stage 2 or Stage 3 safety events have occurred, the dispatch coordinator must verify that a site safety clearance certificate has been signed by the facility safety officer before the technician enters the installation perimeter [S4].

**Provenance map**

| Tag | Source record | Cited |
|---|---|---|
| S1 | chromadb.gv_manuals / GV-SOP-WAR-101::c000 / GV-SOP-WAR-101 SOP Field Warranty Claims.pdf p.1 / 2026-11-06T22:09:21+00:00 | yes |
| S2 | chromadb.gv_manuals / GV-SOP-WAR-101::c001 / GV-SOP-WAR-101 SOP Field Warranty Claims.pdf p.2 / 2026-11-06T22:09:21+00:00 | yes |
| S3 | chromadb.gv_manuals / GV-SOP-WAR-101::c002 / GV-SOP-WAR-101 SOP Field Warranty Claims.pdf p.2 / 2026-11-06T22:09:21+00:00 | yes |
| S4 | chromadb.gv_manuals / GV-SOP-WAR-101::c003 / GV-SOP-WAR-101 SOP Field Warranty Claims.pdf p.2 / 2026-11-06T22:09:21+00:00 | yes |
| S5 | chromadb.gv_manuals / GV-SOP-WAR-101::c004 / GV-SOP-WAR-101 SOP Field Warranty Claims.pdf p.1 / 2026-11-06T22:09:21+00:00 | no |
| S6 | chromadb.gv_manuals / GV-SOP-WAR-101::c005 / GV-SOP-WAR-101 SOP Field Warranty Claims.pdf p.1 / 2026-11-06T22:09:21+00:00 | no |
| S7 | chromadb.gv_manuals / GV-SOP-WAR-101::c006 / GV-SOP-WAR-101 SOP Field Warranty Claims.pdf p.2 / 2026-11-06T22:09:21+00:00 | no |
| S8 | chromadb.gv_manuals / GV-SOP-WAR-101::c007 / GV-SOP-WAR-101 SOP Field Warranty Claims.pdf p.2 / 2026-11-06T22:09:21+00:00 | no |
| S9 | chromadb.gv_manuals / GV-INC-2024-104::c000 / GV-INC-2024-104 Field Incident Report Contactor Flashover.pdf p.1 / 2026-11-06T22:09:21+00:00 | no |
| S10 | chromadb.gv_manuals / GV-MAN-C1200-003::c007 / GV-MAN-C1200-003 Manual.pdf p.3 / 2026-11-06T22:09:21+00:00 | no |

**Statements that failed verification**

- no citation: Step 1.
- no citation: Step 2.
- no citation: Step 3.
- no citation: Step 4.

## 9. What should a technician do in a battery fire or thermal runaway emergency?

Category: safety. Total latency: 1.21 s. Traceable statements: 7/7.

**Answer**

During a battery fire or thermal runaway emergency, personnel must follow specific safety and emergency response procedures [S2][S8][S10].

* If smoke, venting, or a continuous audible alarm is present, depress the external emergency stop push-button on the northwest exterior cabinet panel and evacuate to a minimum perimeter distance of 100 meters or 330 feet [S8][S10].
* For telemetry showing a temperature above 75 C, CO/H2 gas detection, or error code ERR_BMS_708, automatic DC contactor drop, Stat-X aerosol deployment, and external horn sounding occur [S2].
* For multi-module fire detection or loss of CAN telemetry, trip the master substation breaker, isolate the medium-voltage transformer, and evacuate 100 meters [S2].
* For an unresponsive cabinet with active external smoke or flame, provide Safety Data Sheets and the battery chemistry manifest to the incident commander [S2].
* No technician may re-enter the unit perimeter until the site has been certified cold for a minimum of 24 consecutive hours with continuous zero-ppm toxic gas readings [S4].
* Secure all thermal imaging logs and telemetry dumps for root cause investigation with Gigavolt Engineering Quality Assurance [S4].

**Provenance map**

| Tag | Source record | Cited |
|---|---|---|
| S1 | mongodb.bms_telemetry / aggregate:fleet | no |
| S2 | chromadb.gv_manuals / GV-SOP-SAFETY-900::c002 / GV-SOP-SAFETY-900 SOP BESS Emergency Response and Fire Safety.pdf p.1 / 2026-11-06T22:09:21+00:00 | yes |
| S3 | mongodb.bms_telemetry / TLM-90002 / 2024-09-28T16:04:10.500000+00:00 | no |
| S4 | chromadb.gv_manuals / GV-SOP-SAFETY-900::c006 / GV-SOP-SAFETY-900 SOP BESS Emergency Response and Fire Safety.pdf p.2 / 2026-11-06T22:09:21+00:00 | yes |
| S5 | mongodb.bms_telemetry / TLM-90003 / 2024-09-28T16:04:11.880000+00:00 | no |
| S6 | chromadb.gv_manuals / GV-INC-2024-088::c001 / GV-INC-2024-088 Field Incident Investigation Report.pdf p.1 / 2026-11-06T22:09:21+00:00 | no |
| S7 | mongodb.bms_telemetry / TLM-90004 / 2024-09-28T16:04:12.010000+00:00 | no |
| S8 | chromadb.gv_manuals / GV-MAN-X7000-001::c008 / GV-MAN-X7000-001 Manual.pdf p.2 / 2026-11-06T22:09:21+00:00 | yes |
| S9 | mongodb.bms_telemetry / TLM-90026 / 2026-09-01T11:30:00+00:00 | no |
| S10 | chromadb.gv_manuals / GV-MAN-X7000-001::c007 / GV-MAN-X7000-001 Manual.pdf p.2 / 2026-11-06T22:09:21+00:00 | yes |
| S11 | mongodb.bms_telemetry / TLM-90008 / 2025-01-14T09:00:00+00:00 | no |
| S12 | chromadb.gv_manuals / GV-INC-2024-088::c002 / GV-INC-2024-088 Field Incident Investigation Report.pdf p.1 / 2026-11-06T22:09:21+00:00 | no |
| S13 | mongodb.bms_telemetry / TLM-90007 / 2025-01-14T08:45:00+00:00 | no |

## 10. What are the specifications of the LFP battery cell?

Category: specification. Total latency: 5.68 s. Traceable statements: 7/7.

**Answer**

The LFP battery cell specifications are detailed in the model-level datasheet for the Prismacell 280Ah LiFePO4 cell [S1].
- The overview specifies Gigavolt Internal P/N CEL-LFP-280, a 280Ah baseline prismatic lithium iron phosphate cell manufactured by Voltaic Core Technologies (Supplier ID SUP-VCT-01) [S1].
- Electro-chemical and physical characteristics include a nominal capacity of 280 Ah, nominal cell voltage of 3.20 V, operational voltage window from 2.50 V to 3.65 V, maximum continuous discharge rate of 1.0 C (280 A), and peak pulse discharge of 2.0 C (560 A) for 30 seconds [S2].
- Additional characteristics include an internal AC impedance (1 kHz) of 0.25 mOhm or less, cycle life to 80% retained capacity of 6,000 cycles or more, dimensions of 71.5 mm (W) by 173.6 mm (L) by 204.0 mm (H), and an individual cell mass of 5.42 kg plus or minus 0.1 kg [S3][S4].
- Terminal post configuration features M6 laser-welded aluminum busbar studs with a torque limit of 8.0 N·m [S4].
- Operating thresholds and thermal management include an optimal operating temperature of 15 °C to 35 °C, permissible charge range of 0 °C to 55 °C with pre-heating required below 0 °C, permissible discharge range of -20 °C to 60 °C, self-discharge rate of 3% or less per month at 50% SoC and 25 °C, and a thermal decomposition onset temperature of 270 °C [S4][S5].
- Safety and compliance ratings include certifications for UL 1973, UL 9540A cell-level test, IEC 62619, and UN 38.3, along with an integrated safety mechanism featuring a bursting vent membrane rated for rupture at 0.45 MPa plus or minus 0.05 MPa [S6].

**Provenance map**

| Tag | Source record | Cited |
|---|---|---|
| S1 | chromadb.gv_manuals / GV-SPEC-CELL-LFP-08::c000 / GV-SPEC-CELL-LFP-08 Datasheet.pdf p.1 / 2026-11-06T22:09:21+00:00 | yes |
| S2 | chromadb.gv_manuals / GV-SPEC-CELL-LFP-08::c001 / GV-SPEC-CELL-LFP-08 Datasheet.pdf p.1 / 2026-11-06T22:09:21+00:00 | yes |
| S3 | chromadb.gv_manuals / GV-SPEC-CELL-LFP-08::c002 / GV-SPEC-CELL-LFP-08 Datasheet.pdf p.1 / 2026-11-06T22:09:21+00:00 | yes |
| S4 | chromadb.gv_manuals / GV-SPEC-CELL-LFP-08::c003 / GV-SPEC-CELL-LFP-08 Datasheet.pdf p.1 / 2026-11-06T22:09:21+00:00 | yes |
| S5 | chromadb.gv_manuals / GV-SPEC-CELL-LFP-08::c004 / GV-SPEC-CELL-LFP-08 Datasheet.pdf p.1 / 2026-11-06T22:09:21+00:00 | yes |
| S6 | chromadb.gv_manuals / GV-SPEC-CELL-LFP-08::c005 / GV-SPEC-CELL-LFP-08 Datasheet.pdf p.1 / 2026-11-06T22:09:21+00:00 | yes |
| S7 | chromadb.gv_manuals / GV-SPEC-CELL-NMC-65::c000 / GV-SPEC-CELL-NMC-65 Datasheet.pdf p.1 / 2026-11-06T22:09:21+00:00 | no |
| S8 | chromadb.gv_manuals / GV-SUP-REP-401::c001 / GV-SUP-REP-401 Supply Chain Integration Brief.pdf p.1 / 2026-11-06T22:09:21+00:00 | no |
| S9 | chromadb.gv_manuals / GV-SPEC-CELL-NMC-65::c001 / GV-SPEC-CELL-NMC-65 Datasheet.pdf p.1 / 2026-11-06T22:09:21+00:00 | no |
| S10 | chromadb.gv_manuals / GV-SOP-DECOM-601::c001 / GV-SOP-DECOM-601 SOP EOL Decomissioning.pdf p.1 / 2026-11-06T22:09:21+00:00 | no |

## 11. What are the most common service resolutions and warranty claim outcomes for X-5000 units?

Category: warranty aggregate. Total latency: 3.44 s. Traceable statements: 7/7.

**Answer**

For X-5000 units, the most common service resolutions include preventive checks, fuse block replacements, and emergency dispatches for over-temperature alarms, alongside approved, pending, under review, and rejected warranty claims [S1][S3].

* Performed standard preventive check and updated firmware to v4.2.1 across 206 dispatches (e.g., DISP-10572, DISP-11563, DISP-10294) [S1].
* Replaced burnt fuse block with test run completed successfully across 203 dispatches (e.g., DISP-10765, DISP-12818, DISP-12713) [S1].
* Emergency dispatch for over-temperature alarm and cleaned heat exchanger across 185 dispatches (e.g., DISP-13324, DISP-13100, DISP-12204) [S1].
* Replaced faulty thermal sensor and verified system bus voltage across 177 dispatches (e.g., DISP-11450, DISP-11158, DISP-12255) [S1].
* Calibrated inverter output with system operating within normal parameters across 175 dispatches (e.g., DISP-11725, DISP-13908, DISP-10110) [S1].
* Warranty claims by status consist of 80 approved claims ($176134.74 claimed), 57 pending claims ($136286.62 claimed), 46 claims under review ($96977.72 claimed), and 37 rejected claims ($80930.38 claimed) [S3].

**Provenance map**

| Tag | Source record | Cited |
|---|---|---|
| S1 | mariadb.service_logs / aggregate:resolutions:X-5000 | yes |
| S2 | chromadb.gv_manuals / GV-SOP-WAR-101::c000 / GV-SOP-WAR-101 SOP Field Warranty Claims.pdf p.1 / 2026-11-06T22:09:21+00:00 | no |
| S3 | mariadb.equipment_units+warranty_claims / aggregate:fleet:X-5000 | yes |
| S4 | chromadb.gv_manuals / GV-SOP-WAR-101::c007 / GV-SOP-WAR-101 SOP Field Warranty Claims.pdf p.2 / 2026-11-06T22:09:21+00:00 | no |
| S5 | chromadb.gv_manuals / GV-SOP-COMM-201::c000 / GV-SOP-COMM-201 SOP Megapack X-7000 SAT.pdf p.1 / 2026-11-06T22:09:21+00:00 | no |
| S6 | chromadb.gv_manuals / GV-SUP-AUD-502::c000 / GV-SUP-AUD-502 Quality Audit Report QA Assessment.pdf p.1 / 2026-11-06T22:09:21+00:00 | no |
| S7 | chromadb.gv_manuals / GV-ECO-2024-052::c001 / GV-ECO-2024-052 Change Order Cabinet Door Seal.pdf p.1 / 2026-11-06T22:09:21+00:00 | no |
| S8 | chromadb.gv_manuals / GV-SUP-AUD-502::c006 / GV-SUP-AUD-502 Quality Audit Report QA Assessment.pdf p.2 / 2026-11-06T22:09:21+00:00 | no |

## 12. What was Gigavolt's total revenue last quarter?

Category: out of scope. Total latency: 2.79 s. Traceable statements: 0/0.

**Answer**

The available records do not show Gigavolt's total revenue last quarter [S1][S2][S3].

**Provenance map**

| Tag | Source record | Cited |
|---|---|---|
| S1 | chromadb.gv_manuals / GV-INC-2024-104::c001 / GV-INC-2024-104 Field Incident Report Contactor Flashover.pdf p.1 / 2026-11-06T22:09:21+00:00 | no |
| S2 | chromadb.gv_manuals / GV-MAN-X7000-001::c000 / GV-MAN-X7000-001 Manual.pdf p.1 / 2026-11-06T22:09:21+00:00 | no |
| S3 | chromadb.gv_manuals / GV-MAN-G3500-002::c000 / GV-MAN-G3500-002 Manual.pdf p.1 / 2026-11-06T22:09:21+00:00 | no |
