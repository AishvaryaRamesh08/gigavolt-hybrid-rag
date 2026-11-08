#!/usr/bin/env python3
"""
hybrid_retrieval.py - Hybrid retrieval across the three Gigavolt data stores.

    question -> analyze_query() -> parallel retrievers -> ranked, provenance-tagged Snippets

    SQLRetriever       MariaDB   exact filters and aggregates (units, warranty, service, suppliers)
    VectorRetriever    ChromaDB  semantic search over manuals (gv_manuals) and ERP text (gv_erp)
    DocumentRetriever  MongoDB   telemetry patterns (fault counts, temperatures, event sequences)

Design notes
  * Telemetry IDs (SN-X7-0094) never match ERP IDs (EQ-7326), so sources are linked only by
    model key. A model-level telemetry result is labelled as such, never as that unit's history.
  * An exact lookup that finds nothing returns a "no record" snippet. The generator can then
    state the absence with a citation instead of filling the gap.
  * One failing store never fails the query: the error is recorded and the others still answer.
  * The ERP has 5 distinct resolution texts, so SQL is its primary path and gv_erp is only
    searched with a model filter, when no specific unit was named.

Usage (retrieval only, no LLM or API key needed):
    python hybrid_retrieval.py --q "What causes high temperature faults on the X-7000?"
"""
import argparse
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Dict, List, Optional

ERP_MODELS = {"X-3000", "X-5000", "X-7000", "X-9000", "X-12000"}
TELEMETRY_MODELS = {"X-7000", "C-1200", "G-3500"}
MANUAL_FOR_MODEL = {"X-7000": "GV-MAN-X7000-001", "C-1200": "GV-MAN-C1200-003",
                    "G-3500": "GV-MAN-G3500-002"}
CELL_DATASHEET_FOR_MODEL = {"X-7000": "GV-SPEC-CELL-LFP-08", "C-1200": "GV-SPEC-CELL-LFP-08",
                            "G-3500": "GV-SPEC-CELL-NMC-65"}
HIGH_TEMP_C = 60
MAX_CHUNKS_PER_DOC = 2
MAX_CHUNKS_DETAIL = 8
RELATIVE_DISTANCE = 0.25   # drop chunks this much further than the best match
MAX_DISTANCE = 0.80     # weaker vector matches are dropped, so off-topic questions retrieve nothing

MODEL_RE = re.compile(r"\b([XCG])-?(\d{3,5})\b")
EQUIPMENT_RE = re.compile(r"\bEQ-\d+\b")
DISPATCH_RE = re.compile(r"\bDISP-[A-Z0-9]+\b")
CLAIM_RE = re.compile(r"\bCLM-\d+\b")
SERIAL_RE = re.compile(r"\bSN-[A-Z0-9-]*[A-Z0-9]\b")
FAULT_RE = re.compile(r"\bERR_[A-Z]+_\d+\b")

HISTORY_WORDS = ("service", "history", "dispatch", "warranty", "claim", "repair", "maintenance",
                 "technician", "labor", "customer")
SUPPLIER_WORDS = ("supplier", "supply chain", "vendor", "single-source", "single source", "procure")
TELEMETRY_WORDS = ("telemetry", "sensor", "reading", "fault", "error code", "alarm", "voltage",
                   "current", "state of charge", "soc", "bms")
THERMAL_WORDS = ("temperature", "thermal", "overheat", "over-temperature", "hot", "heat", "coolant",
                 "cooling")
DETAIL_WORDS = ("procedure", "step", "how do", "how to", "how should", "process", "filing", "specification",
                "datasheet")
FAILURE_WORDS = ("fail", "failure", "fault", "cause", "root cause", "problem", "issue", "incident",
                 "alarm", "runaway")
PART_STOP_WORDS = {"which", "what", "that", "this", "with", "from", "have", "does", "provide",
                   "provides", "supplier", "suppliers", "supply", "chain", "vendor", "vendors",
                   "commercial", "energy", "storage", "unit", "units", "battery", "batteries",
                   "part", "parts", "their", "they", "them", "there", "show", "list", "give",
                   "tell", "about", "single", "source", "sources", "risk", "risks", "many"}


@dataclass
class QueryPlan:
    question: str
    models: List[str] = field(default_factory=list)
    equipment_ids: List[str] = field(default_factory=list)
    dispatch_ids: List[str] = field(default_factory=list)
    claim_ids: List[str] = field(default_factory=list)
    serials: List[str] = field(default_factory=list)
    fault_codes: List[str] = field(default_factory=list)
    wants_history: bool = False
    wants_supplier: bool = False
    wants_thermal: bool = False
    wants_failure: bool = False
    wants_detail: bool = False
    use_sql: bool = False
    use_mongo: bool = False
    use_erp_vectors: bool = False
    reasons: List[str] = field(default_factory=list)

    @property
    def has_exact_entity(self):
        return bool(self.equipment_ids or self.dispatch_ids or self.claim_ids or self.serials)


@dataclass
class Snippet:
    """One piece of evidence. These fields are what a citation is built from."""
    db: str                     # mariadb | chromadb | mongodb
    source: str                 # table or collection
    record_id: str
    text: str
    timestamp: str = ""
    doc: str = ""
    chunk: str = ""
    page: Optional[int] = None
    score: Optional[float] = None
    tag: str = ""               # S1, S2, ... assigned when the context is assembled

    def citation(self):
        return {key: value for key, value in self.__dict__.items()
                if key != "text" and value not in ("", None)}


@dataclass
class RetrievalResult:
    plan: QueryPlan
    snippets: Dict[str, List[Snippet]]
    timings_ms: Dict[str, float]
    errors: Dict[str, str]


def has_word(text, words):
    return any(re.search(rf"\b{re.escape(word)}", text) for word in words)


def unique(values):
    return list(dict.fromkeys(values))


def analyze_query(question):
    """Rule-based router: extract entities and intent, then choose the stores to query. No LLM call."""
    upper, lower = question.upper(), question.lower()
    models = []
    for letter, digits in MODEL_RE.findall(upper):
        candidate = f"{letter}-{digits}"
        if candidate in ERP_MODELS | TELEMETRY_MODELS:    # C-1128 is a customer ID, not a model
            models.append(candidate)
    plan = QueryPlan(
        question=question, models=unique(models),
        equipment_ids=unique(EQUIPMENT_RE.findall(upper)),
        dispatch_ids=unique(DISPATCH_RE.findall(upper)), claim_ids=unique(CLAIM_RE.findall(upper)),
        serials=unique(SERIAL_RE.findall(upper)), fault_codes=unique(FAULT_RE.findall(upper)),
        wants_history=has_word(lower, HISTORY_WORDS), wants_supplier=has_word(lower, SUPPLIER_WORDS),
        wants_thermal=has_word(lower, THERMAL_WORDS), wants_failure=has_word(lower, FAILURE_WORDS),
        wants_detail=has_word(lower, DETAIL_WORDS))

    if plan.has_exact_entity:
        plan.use_sql = True
        plan.reasons.append("SQL: exact identifier in the question")
    if plan.wants_history or plan.wants_supplier:
        plan.use_sql = True
        plan.reasons.append("SQL: service, warranty or supplier intent")
    if plan.models and (plan.wants_failure or plan.wants_thermal):
        plan.use_sql = True
        plan.reasons.append("SQL: resolution and warranty aggregates for the model")

    if plan.serials or plan.fault_codes:
        plan.use_mongo = True
        plan.reasons.append("MongoDB: serial or fault code in the question")
    if has_word(lower, TELEMETRY_WORDS) or plan.wants_thermal or plan.wants_failure:
        plan.use_mongo = True
        plan.reasons.append("MongoDB: telemetry, thermal or failure intent")

    plan.use_erp_vectors = bool(plan.models and plan.wants_failure and not plan.has_exact_entity)
    if plan.use_erp_vectors:
        plan.reasons.append("gv_erp: similar service events, filtered by model")
    plan.reasons.append("gv_manuals: technical documentation (always searched)")
    return plan


def part_terms(question):
    """Words that could match a part name: 'lithium cells' -> ['lithium', 'cell']."""
    words = re.findall(r"[a-z]{4,}", question.lower())
    terms = [w[:-1] if w.endswith("s") else w for w in words if w not in PART_STOP_WORDS]
    return unique(terms)[:4]


class SQLRetriever:
    """Parameterized, read-only queries. Customer PII columns are never selected."""

    def __init__(self):
        import pymysql
        self._pymysql = pymysql
        self._settings = dict(host=os.environ.get("MARIADB_HOST", "127.0.0.1"),
                              port=int(os.environ.get("MARIADB_PORT", 3306)),
                              user=os.environ["MARIADB_USER"], password=os.environ["MARIADB_PASSWORD"],
                              database=os.environ.get("MARIADB_DB", "gigavolt_erp"), charset="utf8mb4",
                              cursorclass=pymysql.cursors.DictCursor, connect_timeout=5)

    def _rows(self, sql, params=()):
        conn = self._pymysql.connect(**self._settings)
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return cur.fetchall()
        finally:
            conn.close()

    def unit_model(self, identifier):
        rows = self._rows("SELECT model FROM equipment_units WHERE equipment_id=%s OR serial_number=%s",
                          (identifier, identifier))
        return rows[0]["model"] if rows else None

    def _payload_snippet(self, row):
        return Snippet("mariadb", "rag_payloads", row["source_id"], row["payload_text"],
                       timestamp=str(row["event_date"] or ""))

    def unit(self, identifier, max_events=8):
        rows = self._rows(
            "SELECT eu.equipment_id, eu.serial_number, eu.model, em.capacity_kw, em.voltage, eu.install_date, "
            "eu.warranty_expiration, eu.status, eu.location_notes, c.company_name, l.city, l.state "
            "FROM equipment_units eu LEFT JOIN equipment_models em ON em.model=eu.model "
            "LEFT JOIN customers c ON c.customer_id=eu.customer_id LEFT JOIN locations l ON l.zip=c.zip "
            "WHERE eu.equipment_id=%s OR eu.serial_number=%s", (identifier, identifier))
        if not rows:
            return [Snippet("mariadb", "equipment_units", f"lookup:{identifier}",
                            f"No ERP record exists for {identifier}: equipment_units has no matching "
                            "equipment_id or serial_number.")]
        unit = rows[0]
        equipment_id = unit["equipment_id"]
        total = self._rows("SELECT payload_type, COUNT(*) n FROM rag_payloads WHERE equipment_id=%s "
                           "GROUP BY payload_type", (equipment_id,))
        counts = ", ".join(f"{r['n']} {r['payload_type']}" for r in total) or "no service or claim records"
        out = [Snippet("mariadb", "equipment_units", equipment_id,
                       f"Unit {equipment_id} | Serial {unit['serial_number']} | Model {unit['model']} "
                       f"({unit['capacity_kw']} kW, {unit['voltage']} V) | Status {unit['status']} | "
                       f"Site {unit['location_notes'] or 'N/A'} | Installed {unit['install_date']} | "
                       f"Warranty expires {unit['warranty_expiration']} | Customer {unit['company_name']} "
                       f"({unit['city']}, {unit['state']}) | Records on file: {counts}.")]
        events = self._rows("SELECT source_id, payload_text, event_date FROM rag_payloads WHERE equipment_id=%s "
                            "ORDER BY event_date DESC LIMIT %s", (equipment_id, max_events))
        return out + [self._payload_snippet(row) for row in events]

    def record(self, record_id):
        rows = self._rows(
            "SELECT source_id, payload_text, event_date FROM rag_payloads WHERE source_id=%s OR payload_text LIKE %s",
            (record_id, f"%Warranty Claim {record_id} |%"))
        if rows:
            return [self._payload_snippet(row) for row in rows]
        return [Snippet("mariadb", "rag_payloads", f"lookup:{record_id}",
                        f"No ERP service or warranty record exists for {record_id}.")]

    def model_summary(self, model):
        if model not in ERP_MODELS:
            return [Snippet("mariadb", "equipment_models", f"lookup:{model}",
                            f"The ERP has no equipment or service records for model {model}. "
                            f"ERP models are: {', '.join(sorted(ERP_MODELS))}.")]
        units = self._rows("SELECT status, COUNT(*) n FROM equipment_units WHERE model=%s GROUP BY status "
                           "ORDER BY n DESC", (model,))
        resolutions = self._rows(
            "SELECT sl.resolution_summary r, COUNT(*) n, SUBSTRING_INDEX(GROUP_CONCAT(sl.dispatch_id "
            "ORDER BY sl.dispatch_date DESC), ',', 3) examples FROM service_logs sl JOIN equipment_units eu "
            "ON eu.equipment_id=sl.equipment_id WHERE eu.model=%s GROUP BY sl.resolution_summary ORDER BY n DESC",
            (model,))
        claims = self._rows(
            "SELECT wc.status, COUNT(*) n, SUM(wc.claim_amount) claimed FROM warranty_claims wc "
            "JOIN equipment_units eu ON eu.equipment_id=wc.equipment_id WHERE eu.model=%s GROUP BY wc.status "
            "ORDER BY n DESC", (model,))
        out = []
        if resolutions:
            lines = [f"{r['r']} ({r['n']} dispatches, e.g. {r['examples']})" for r in resolutions]
            out.append(Snippet("mariadb", "service_logs", f"aggregate:resolutions:{model}",
                               f"Service resolutions recorded for {model} units, most common first: "
                               + "; ".join(lines) + "."))
        fleet = ", ".join(f"{r['status']}: {r['n']}" for r in units)
        claim_text = ", ".join(f"{r['status']}: {r['n']} claims, ${r['claimed']} claimed" for r in claims)
        out.append(Snippet("mariadb", "equipment_units+warranty_claims", f"aggregate:fleet:{model}",
                           f"{model} fleet by status: {fleet}. Warranty claims by status: {claim_text}."))
        return out

    def suppliers(self, question):
        terms = part_terms(question)
        if not terms:
            return []
        where = " OR ".join(["part_name LIKE %s"] * len(terms))
        rows = self._rows(
            "SELECT supplier, COUNT(*) n, SUBSTRING_INDEX(GROUP_CONCAT(CONCAT(part_name, ' (', part_id, ')') "
            f"ORDER BY part_name SEPARATOR '; '), '; ', 4) examples FROM parts_inventory WHERE {where} "
            "GROUP BY supplier ORDER BY n DESC", [f"%{term}%" for term in terms])
        return [Snippet("mariadb", "parts_inventory", f"aggregate:supplier:{row['supplier']}",
                        f"{row['supplier']} supplies {row['n']} matching catalog part(s), e.g. {row['examples']}. "
                        "ERP supplier names are anonymized codes.") for row in rows]

    def retrieve(self, plan):
        out = []
        for identifier in plan.equipment_ids + plan.serials:
            out += self.unit(identifier)
        for record_id in plan.dispatch_ids + plan.claim_ids:
            out += self.record(record_id)
        if plan.wants_supplier:
            out += self.suppliers(plan.question)
        if plan.wants_failure or plan.wants_thermal or plan.wants_history:
            for model in plan.models:
                out += self.model_summary(model)
        return out


class VectorRetriever:
    def __init__(self):
        import chromadb
        from embed import load_model
        self.model = load_model()
        client = chromadb.PersistentClient(path=os.environ.get("CHROMA_PATH", "/opt/gigavolt/chroma_db"))
        self.manuals = client.get_collection("gv_manuals", embedding_function=None)
        self.erp = client.get_collection("gv_erp", embedding_function=None)

    def encode(self, question):
        return self.model.encode(question, normalize_embeddings=True).tolist()

    @staticmethod
    def _search(collection, vector, k, where=None, where_document=None):
        result = collection.query(query_embeddings=[vector], n_results=k, where=where,
                                  where_document=where_document,
                                  include=["documents", "metadatas", "distances"])
        return [row for row in zip(result["ids"][0], result["documents"][0], result["metadatas"][0],
                                   result["distances"][0]) if row[3] <= MAX_DISTANCE]

    def _manual_snippet(self, row):
        chunk_id, text, meta, distance = row
        return Snippet("chromadb", "gv_manuals", chunk_id, text, timestamp=meta.get("ingested_at_iso", ""),
                       doc=meta.get("source_file", ""), chunk=chunk_id, page=meta.get("page"),
                       score=round(1 - distance, 3))

    @staticmethod
    def _select_chunks(plan, rows, exact_ids):
        """Choose document evidence from candidates sorted by distance."""
        own_manuals = {MANUAL_FOR_MODEL[m] for m in plan.models if m in MANUAL_FOR_MODEL}
        own_cells = {CELL_DATASHEET_FOR_MODEL[m] for m in plan.models if m in CELL_DATASHEET_FOR_MODEL}
        best = rows[0][3] if rows else 0
        top_doc = rows[0][2].get("doc_id") if rows else None
        per_document, kept = {}, []
        for row in rows:
            doc_id = row[2].get("doc_id", "")
            if row[0] not in exact_ids:
                # Another model's manual must not answer for this model
                if own_manuals and doc_id.startswith("GV-MAN-") and doc_id not in own_manuals:
                    continue
                # An X-7000 question must not get the G-3500's NMC cell chemistry, or the reverse
                if own_cells and doc_id.startswith("GV-SPEC-CELL-") and doc_id not in own_cells:
                    continue
                if row[3] > best + RELATIVE_DISTANCE and doc_id != top_doc:
                    continue
            # Procedure and spec questions need one document in depth. Otherwise cap each
            # document, so overlapping chunks of one manual cannot crowd out reports and SOPs.
            cap = MAX_CHUNKS_DETAIL if plan.wants_detail and doc_id == top_doc else MAX_CHUNKS_PER_DOC
            if row[0] in exact_ids or per_document.get(doc_id, 0) < cap:
                per_document[doc_id] = per_document.get(doc_id, 0) + 1
                kept.append(row)
        kept.sort(key=lambda row: row[0] not in exact_ids)      # exact matches survive the limit below
        kept = kept[:MAX_CHUNKS_DETAIL + 2 if plan.wants_detail else 6]
        if plan.wants_detail:       # keep a procedure's steps in document order
            kept.sort(key=lambda row: (row[2].get("doc_id") != top_doc, row[2].get("chunk_index", 0)))
        return kept

    def retrieve(self, plan, vector):
        rows = []
        if plan.wants_supplier:
            rows += self._search(self.manuals, vector, 4, {"doc_type": "SUP"})
        for model in plan.models:
            if model in MANUAL_FOR_MODEL:
                rows += self._search(self.manuals, vector, 2, {"doc_id": MANUAL_FOR_MODEL[model]})
        for code in plan.fault_codes:     # exact text match: a fault code has no semantic neighbours
            rows += self._search(self.manuals, vector, 4, where_document={"$contains": code})
        if plan.wants_failure or plan.wants_thermal:     # the model's own fault table: causes and corrective actions
            for model in plan.models:
                if model in MANUAL_FOR_MODEL:
                    rows += self._search(self.manuals, vector, 2, {"doc_id": MANUAL_FOR_MODEL[model]},
                                         {"$contains": "Fault Code"})
        exact_ids = {row[0] for row in rows if plan.fault_codes or "Fault Code" in row[1]}
        rows += self._search(self.manuals, vector, 12)
        rows = sorted({row[0]: row for row in rows}.values(), key=lambda row: row[3])
        if plan.wants_detail and rows:      # procedure or spec question: read the best document in full
            rows += self._search(self.manuals, vector, MAX_CHUNKS_DETAIL + 2, {"doc_id": rows[0][2].get("doc_id")})
            top = rows[0]
            rows = sorted({row[0]: row for row in rows}.values(), key=lambda row: row[3])
            rows.remove(top)
            rows.insert(0, top)
        kept = self._select_chunks(plan, rows, exact_ids)
        out = [self._manual_snippet(row) for row in kept]

        if plan.use_erp_vectors:
            for model in plan.models:
                if model in ERP_MODELS:
                    # ERP text has 5 resolution templates, so filter on the event kind that was asked about
                    text_filter = {"$contains": "over-temperature"} if plan.wants_thermal else None
                    for chunk_id, text, meta, distance in self._search(self.erp, vector, 2,
                                                                       {"equipment_model": model}, text_filter):
                        out.append(Snippet("chromadb", "gv_erp", meta.get("source_id", chunk_id), text,
                                           timestamp=meta.get("event_date", ""), chunk=chunk_id,
                                           score=round(1 - distance, 3)))
        return out


class DocumentRetriever:
    def __init__(self):
        from pymongo import MongoClient
        client = MongoClient(os.environ.get("MONGO_URI", "mongodb://127.0.0.1:27017"),
                             serverSelectionTimeoutMS=3000, tz_aware=True)
        self.col = client[os.environ.get("MONGO_DB", "gigavolt_iot")]["bms_telemetry"]

    @staticmethod
    def reading_text(doc):
        t = doc.get("telemetry", {})
        parts = ", ".join(doc.get("flagged_components") or []) or "none"
        return (f"{doc['log_id']} | {doc['timestamp'].strftime('%Y-%m-%d %H:%M:%S')} UTC | Unit {doc['equipment_id']} | "
                f"Model {doc.get('model_key')} | Status {doc.get('status')} | Fault {doc.get('fault_code') or 'none'} | "
                f"Severity {doc.get('severity')} | {t.get('voltage_v')} V, {t.get('current_a')} A, "
                f"{t.get('temperature_c')} C, SOC {t.get('soc_percent')}%, delta {t.get('voltage_delta_mv')} mV | "
                f"Flagged parts: {parts} | Note: {doc.get('notes', '')}")

    def _reading(self, doc):
        return Snippet("mongodb", "bms_telemetry", doc["log_id"], self.reading_text(doc),
                       timestamp=doc["timestamp"].isoformat())

    def _summary(self, match, record_id, label):
        groups = list(self.col.aggregate([
            {"$match": {"fault_code": {"$ne": None}, **match}},
            {"$group": {"_id": "$fault_code", "n": {"$sum": 1}, "max_temp": {"$max": "$telemetry.temperature_c"},
                        "units": {"$addToSet": "$equipment_id"}, "logs": {"$push": "$log_id"},
                        "first": {"$min": "$timestamp"}, "last": {"$max": "$timestamp"}}},
            {"$sort": {"n": -1}}]))
        if not groups:
            return []
        lines = [f"{g['_id']}: {g['n']} reading(s) on {len(g['units'])} unit(s), max {g['max_temp']} C, "
                 f"{g['first'].date()} to {g['last'].date()}, e.g. {', '.join(sorted(g['logs'])[:3])}"
                 for g in groups]
        return [Snippet("mongodb", "bms_telemetry", record_id, f"{label}: " + "; ".join(lines) + ".")]

    def unit(self, equipment_id):
        match = {"equipment_id": equipment_id}
        total = self.col.count_documents(match)
        if not total:
            return [Snippet("mongodb", "bms_telemetry", f"lookup:{equipment_id}",
                            f"No telemetry exists for unit {equipment_id}.")]
        summary = self._summary(match, f"aggregate:unit:{equipment_id}",
                                f"Telemetry fault summary for unit {equipment_id} ({total} readings in total)")
        readings = self.notable_readings(match)
        if not readings:
            recent = self.col.find(match).sort("timestamp", -1).limit(3)
            readings = [self._reading(doc) for doc in recent]
            summary = [Snippet("mongodb", "bms_telemetry", f"aggregate:unit:{equipment_id}",
                               f"Unit {equipment_id} has {total} telemetry readings and none has a fault code.")]
        return summary + readings

    def fault(self, code):
        first_per_unit = {}
        for doc in self.col.find({"fault_code": code}).sort("timestamp", 1):
            first_per_unit.setdefault(doc["equipment_id"], doc)
        if not first_per_unit:
            return [Snippet("mongodb", "bms_telemetry", f"lookup:{code}", f"No telemetry reading has fault code {code}.")]
        summary = self._summary({"fault_code": code}, f"aggregate:fault:{code}", f"Telemetry summary for {code}")
        return summary + [self._reading(doc) for doc in list(first_per_unit.values())[:4]]

    def notable_readings(self, match, limit=6):
        """Evidence for a fault pattern without repetition. The telemetry repeats identical readings
        day after day, so keep the hottest, earliest reading per fault code, plus the two readings
        that led up to the hottest event overall."""
        cursor = self.col.find({"fault_code": {"$ne": None}, **match}).sort(
            [("telemetry.temperature_c", -1), ("timestamp", 1)])
        per_code = {}
        for doc in cursor:
            per_code.setdefault(doc["fault_code"], doc)
        if not per_code:
            return []
        top = next(iter(per_code.values()))
        before = list(self.col.find({"equipment_id": top["equipment_id"], "timestamp": {"$lt": top["timestamp"]}})
                      .sort("timestamp", -1).limit(2))
        docs = list(reversed(before)) + list(per_code.values())
        return [self._reading(doc) for doc in {d["log_id"]: d for d in docs}.values()][:limit]

    def model(self, model, thermal, unit_context=None):
        if model not in TELEMETRY_MODELS:
            return [Snippet("mongodb", "bms_telemetry", f"lookup:{model}",
                            f"No telemetry exists for model {model}. Telemetry covers: "
                            f"{', '.join(sorted(TELEMETRY_MODELS))}.")]
        match = {"model_key": model}
        scope = f"model {model}"
        if unit_context:
            scope += f" (model-level data: telemetry unit IDs do not map to ERP unit {unit_context})"
        out = self._summary(match, f"aggregate:model:{model}", f"Telemetry fault summary for {scope}")
        if thermal:
            hot = self.col.count_documents({**match, "telemetry.temperature_c": {"$gte": HIGH_TEMP_C}})
            total = self.col.count_documents(match)
            out.append(Snippet("mongodb", "bms_telemetry", f"aggregate:hot:{model}",
                               f"{hot} of {total} telemetry readings for {model} are at or above {HIGH_TEMP_C} C."))
        return out + self.notable_readings(match)

    def retrieve(self, plan, unit_models):
        out = []
        for serial in plan.serials:
            out += self.unit(serial)
        for code in plan.fault_codes:
            out += self.fault(code)
        for model in plan.models:
            out += self.model(model, plan.wants_thermal)
        for equipment_id, model in unit_models.items():
            if model in TELEMETRY_MODELS and model not in plan.models and equipment_id in plan.equipment_ids:
                out += self.model(model, plan.wants_thermal, unit_context=equipment_id)
        if not out:     # no entity named: report the fleet-wide picture
            match = {"telemetry.temperature_c": {"$gte": HIGH_TEMP_C}} if plan.wants_thermal else {}
            label = f"Fleet telemetry fault summary{' at or above %d C' % HIGH_TEMP_C if plan.wants_thermal else ''}"
            out += self._summary(match, "aggregate:fleet", label)
            out += self.notable_readings(match)
        return out


class HybridRetriever:
    """Opens each store once, so the embedding model is only loaded at startup."""

    def __init__(self):
        self.sql = SQLRetriever()
        self.vector = VectorRetriever()
        self.document = DocumentRetriever()
        self.pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="retriever")

    def warmup(self):
        self.retrieve("warm-up query about thermal faults on the X-7000")

    @staticmethod
    def _timed(name, func, *args):
        start = time.perf_counter()
        try:
            return name, func(*args), (time.perf_counter() - start) * 1000, None
        except Exception as exc:    # one store failing must not fail the whole query
            return name, [], (time.perf_counter() - start) * 1000, f"{type(exc).__name__}: {exc}"

    def retrieve(self, question):
        timings, errors = {}, {}
        start = time.perf_counter()
        plan = analyze_query(question)
        timings["route"] = (time.perf_counter() - start) * 1000

        # ERP unit -> model lets the model-level telemetry and manual join in
        unit_models = {}
        if plan.equipment_ids or plan.serials:
            start = time.perf_counter()
            try:
                for identifier in plan.equipment_ids + plan.serials:
                    model = self.sql.unit_model(identifier)
                    if model:
                        unit_models[identifier] = model
            except Exception as exc:
                errors["resolve"] = f"{type(exc).__name__}: {exc}"
            timings["resolve"] = (time.perf_counter() - start) * 1000
            if any(m in TELEMETRY_MODELS for m in unit_models.values()):
                plan.use_mongo = True
                plan.reasons.append("MongoDB: the named ERP unit's model has telemetry (model-level link)")

        start = time.perf_counter()
        vector = self.vector.encode(question)
        timings["encode"] = (time.perf_counter() - start) * 1000

        start = time.perf_counter()
        jobs = [self.pool.submit(self._timed, "vector", self.vector.retrieve, plan, vector)]
        if plan.use_sql:
            jobs.append(self.pool.submit(self._timed, "sql", self.sql.retrieve, plan))
        if plan.use_mongo:
            jobs.append(self.pool.submit(self._timed, "mongo", self.document.retrieve, plan, unit_models))
        snippets = {}
        for job in jobs:
            name, found, elapsed, error = job.result()
            snippets[name] = found
            timings[name] = elapsed
            if error:
                errors[name] = error
        timings["retrieve_parallel"] = (time.perf_counter() - start) * 1000
        return RetrievalResult(plan, snippets, timings, errors)


def assemble_context(result, max_snippets=14, max_chars=9000):
    """Take snippets round-robin across stores, so one store cannot crowd out the others, and tag them."""
    queues = {name: list(items) for name, items in result.snippets.items() if items}
    order = [name for name in ("sql", "mongo", "vector") if name in queues]
    chosen, used = [], 0
    if result.plan.has_exact_entity and "sql" in queues:    # the named record's own history comes first
        for snippet in queues.pop("sql")[:max_snippets]:
            if used + len(snippet.text) <= max_chars:
                used += len(snippet.text)
                chosen.append(snippet)
        order.remove("sql")
    while order and len(chosen) < max_snippets:
        for name in list(order):
            if not queues[name]:
                order.remove(name)
                continue
            snippet = queues[name].pop(0)
            if used + len(snippet.text) > max_chars:
                continue
            used += len(snippet.text)
            chosen.append(snippet)
            if len(chosen) == max_snippets:
                break
    for number, snippet in enumerate(chosen, start=1):
        snippet.tag = f"S{number}"
    return chosen


def format_snippet(snippet):
    header = f"[{snippet.tag}] source={snippet.db}.{snippet.source} record={snippet.record_id}"
    if snippet.doc:
        header += f" document={snippet.doc} page={snippet.page}"
    return f"{header}\n{snippet.text}"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--q", required=True, help="question to retrieve evidence for")
    args = ap.parse_args()
    retriever = HybridRetriever()
    retriever.warmup()
    result = retriever.retrieve(args.q)
    print("Routing:")
    for reason in result.plan.reasons:
        print(f"  - {reason}")
    print("\nTimings (ms): " + ", ".join(f"{k}={v:.1f}" for k, v in result.timings_ms.items()))
    for store, error in result.errors.items():
        print(f"ERROR in {store}: {error}")
    print()
    for snippet in assemble_context(result):
        print(format_snippet(snippet)[:600] + "\n")


if __name__ == "__main__":
    main()
