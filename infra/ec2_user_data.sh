#!/bin/bash
# ==============================================================================
# Project Gigavolt - Milestone 5 EC2 init script (EC2 "User data", Ubuntu)
# ------------------------------------------------------------------------------
# Installs ONLY what the Phase 5 hybrid-RAG pipeline needs:
#   * MariaDB 12.3 (single node)  -> ERP source of truth + rag_payloads (SQL filters)
#   * MongoDB 7.0                 -> IoT telemetry document store
#   * Python venv                 -> ChromaDB (vector DB, HNSW), sentence-transformers
#                                    (all-MiniLM-L6-v2, CPU), pdfplumber, pymongo,
#                                    pymysql, google-genai (Gemini), ollama (clients)
#   * Ollama                      -> local LLM fallback / latency-comparison backend
# Deliberately NOT installed (not needed for the RAG pipeline): Galera cluster, ColumnStore,
# Neo4j / graph database.
#
# Based on init_script.txt (MariaDB repo + logging pattern). Log: /var/log/user-data.log
# Re-runnable: every step is idempotent.
# ==============================================================================
set -euo pipefail
exec > >(tee -a /var/log/user-data.log) 2>&1

# ---- Edit these before launching (or change later in /opt/gigavolt/config.env) --
APP_DB_USER="gv_app"
APP_DB_PASS="CHANGE_ME"       # MariaDB app user used by the Python code
ERP_DB="gigavolt_erp"
MONGO_DB="gigavolt_iot"
EMBED_MODEL="sentence-transformers/all-MiniLM-L6-v2"   # same model as Phase 4
LLM_MODEL="qwen2.5:1.5b"             # local fallback only (Gemini is the main generator)
INSTALL_OLLAMA="auto"                # yes | no | auto (auto = only when the instance has >= 7 GB RAM)
# -------------------------------------------------------------------------------

log() { echo "[$(date '+%F %T')] $*"; }
export DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a
CODENAME="$(lsb_release -cs)"
MEM_MB=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
log "Instance RAM: ${MEM_MB} MB"
log "Starting Phase 5 init on Ubuntu ${CODENAME}"

# ---- 1. Base packages ---------------------------------------------------------
log "[1/8] Base packages"
apt-get update -y
apt-get upgrade -y -o Dpkg::Options::="--force-confdef" -o Dpkg::Options::="--force-confold"
apt-get install -y apt-transport-https curl gnupg ca-certificates unzip wget zstd \
                   python3-pip python3-venv python3-dev build-essential

# Small instances (< 6 GB RAM): add swap (2 GB, or 4 GB under 3 GB RAM) so embedding/model loads cannot OOM
if [ "${MEM_MB}" -lt 6000 ] && [ ! -f /swapfile ]; then
  SWAP_GB=2; [ "${MEM_MB}" -lt 3000 ] && SWAP_GB=4
  log "Low RAM: creating ${SWAP_GB} GB swap"
  fallocate -l ${SWAP_GB}G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

# ---- 2. MariaDB 12.3 ----------------------------------------------------------
log "[2/8] MariaDB 12.3"
mkdir -p /etc/apt/keyrings
curl -fsSL -o /etc/apt/keyrings/mariadb-keyring.asc https://mariadb.org/mariadb_release_signing_key.pgp
cat > /etc/apt/sources.list.d/mariadb.sources <<EOL
X-Repolib-Name: MariaDB
Types: deb
URIs: https://deb.mariadb.org/12.3/ubuntu
Suites: ${CODENAME}
Components: main
Signed-By: /etc/apt/keyrings/mariadb-keyring.asc
EOL
apt-get update -y
apt-get install -y mariadb-server mariadb-client

# utf8mb4 + LOAD DATA LOCAL INFILE (needed by 02_load_staging.sql)
cat > /etc/mysql/mariadb.conf.d/90-gigavolt.cnf <<'EOL'
[mysqld]
character-set-server = utf8mb4
collation-server     = utf8mb4_unicode_ci
local_infile         = 1
bind-address         = 127.0.0.1
innodb_buffer_pool_size = 256M
performance_schema   = OFF

[client]
default-character-set = utf8mb4
local-infile          = 1
EOL
systemctl enable mariadb
systemctl restart mariadb

mariadb <<SQL
CREATE DATABASE IF NOT EXISTS ${ERP_DB} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS '${APP_DB_USER}'@'localhost' IDENTIFIED BY '${APP_DB_PASS}';
ALTER USER '${APP_DB_USER}'@'localhost' IDENTIFIED BY '${APP_DB_PASS}';
GRANT ALL PRIVILEGES ON ${ERP_DB}.* TO '${APP_DB_USER}'@'localhost';
FLUSH PRIVILEGES;
SQL

# ---- 3. MongoDB 7.0 (document store for telemetry) ----------------------------
# Why 7.0, not 8.x: MongoDB 8.0+ exits at startup on Linux kernels 6.19 and newer
# (SERVER-121912). Ubuntu 26.04's kernel reports 7.0.0-xxxx, which also misses the
# 7.0.14 exemption (SERVER-136848, open). 7.0 is the workaround listed in that ticket.
# 7.0 is published for jammy only, so the jammy repo is used on every Ubuntu release.
log "[3/8] MongoDB 7.0"
curl -fsSL https://www.mongodb.org/static/pgp/server-7.0.asc | gpg --dearmor --yes -o /etc/apt/keyrings/mongodb-7.0.gpg
echo "deb [signed-by=/etc/apt/keyrings/mongodb-7.0.gpg] https://repo.mongodb.org/apt/ubuntu jammy/mongodb-org/7.0 multiverse" \
  > /etc/apt/sources.list.d/mongodb-org-7.0.list
apt-get update -y
apt-get install -y mongodb-org
apt-get clean
# Small cache is plenty for the telemetry set and saves RAM on small instances
grep -q cacheSizeGB /etc/mongod.conf || sed -i '/^storage:/a\  wiredTiger:\n    engineConfig:\n      cacheSizeGB: 0.25' /etc/mongod.conf
systemctl enable --now mongod      # listens on 127.0.0.1:27017 only (default)

# ---- 4. Directory layout ------------------------------------------------------
log "[4/8] Directories + course data"
mkdir -p /opt/data /opt/gigavolt/{src,sql,manuals,telemetry,chroma_db,logs,hf_cache}

# Download course data (each archive extracted in its own scratch dir, then sorted by type)
DL=/var/tmp/gv_download; rm -rf "$DL"; mkdir -p "$DL/erp" "$DL/docs"
wget -q --tries=3 -O "$DL/fall2026.zip"          https://622.gomillion.org/data/fall2026.zip
wget -q --tries=3 -O "$DL/UnstructuredData.zip"  https://622.gomillion.org/data/UnstructuredData.zip
wget -q --tries=3 -O /opt/gigavolt/telemetry/telemetry_data.json https://622.gomillion.org/data/telemetry_data.json
unzip -q -o "$DL/fall2026.zip"         -d "$DL/erp"
unzip -q -o "$DL/UnstructuredData.zip" -d "$DL/docs"
# ERP CSVs -> /opt/data (flattened; 02_load_staging.sql reads /opt/data/<name>.csv)
find "$DL/erp"  -type f -iname '*.csv' -not -path '*/__MACOSX/*' -exec cp -f {} /opt/data/ \;
# PDFs -> manuals (flattened)
find "$DL/docs" -type f -iname '*.pdf' -not -path '*/__MACOSX/*' -exec cp -f {} /opt/gigavolt/manuals/ \;
log "Downloaded: $(ls /opt/data/*.csv 2>/dev/null | wc -l) CSVs, $(ls /opt/gigavolt/manuals/*.pdf 2>/dev/null | wc -l) PDFs, $(wc -l < /opt/gigavolt/telemetry/telemetry_data.json) telemetry lines"
log "Files in /opt/data: $(ls /opt/data | tr '\n' ' ')"
log "Non-CSV/PDF files left in the zips (check if you expected them): $(find "$DL" -type f ! -iname '*.csv' ! -iname '*.pdf' ! -iname '*.zip' ! -path '*/__MACOSX/*' | head -20 | tr '\n' ' ')"
rm -rf "$DL"
chown -R ubuntu:ubuntu /opt/data /opt/gigavolt

# ---- 5. Python environment ----------------------------------------------------
log "[5/8] Python venv (CPU-only torch; pip temp on EBS, not RAM tmpfs)"
export TMPDIR=/var/tmp
python3 -m venv /opt/gigavolt_env
/opt/gigavolt_env/bin/pip install --no-cache-dir --upgrade pip
/opt/gigavolt_env/bin/pip install --no-cache-dir torch --extra-index-url https://download.pytorch.org/whl/cpu
/opt/gigavolt_env/bin/pip install --no-cache-dir \
    sentence-transformers chromadb pdfplumber pymongo pymysql ollama google-genai \
    numpy pandas matplotlib

# ---- 6. Pre-download the embedding model (so the first demo run is fast) ------
log "[6/8] Caching ${EMBED_MODEL}"
HF_HOME=/opt/gigavolt/hf_cache /opt/gigavolt_env/bin/python - <<PY
from sentence_transformers import SentenceTransformer
SentenceTransformer("${EMBED_MODEL}")
print("embedding model cached")
PY
chown -R ubuntu:ubuntu /opt/gigavolt /opt/gigavolt_env

# ---- 7. Ollama (local LLM server) ---------------------------------------------
if [ "${INSTALL_OLLAMA}" = "yes" ] || { [ "${INSTALL_OLLAMA}" = "auto" ] && [ "${MEM_MB}" -ge 7000 ]; }; then
  log "[7/8] Ollama + model (${LLM_MODEL})"
  curl -fsSL https://ollama.com/install.sh | sh
  mkdir -p /etc/systemd/system/ollama.service.d
  cat > /etc/systemd/system/ollama.service.d/gigavolt.conf <<'EOL'
[Service]
Environment="OLLAMA_HOST=127.0.0.1:11434"
Environment="OLLAMA_KEEP_ALIVE=-1"
Environment="OLLAMA_NUM_PARALLEL=1"
Environment="OLLAMA_MAX_LOADED_MODELS=1"
EOL
  systemctl daemon-reload
  systemctl enable ollama
  systemctl restart ollama
  for i in $(seq 1 30); do curl -fs http://127.0.0.1:11434/api/tags >/dev/null && break; sleep 2; done
  ollama pull "${LLM_MODEL}"
  # Warm-up: loads the default model into RAM (kept resident by OLLAMA_KEEP_ALIVE=-1)
  curl -s http://127.0.0.1:11434/api/generate -d "{\"model\":\"${LLM_MODEL}\",\"prompt\":\"ok\",\"stream\":false,\"options\":{\"num_predict\":1}}" >/dev/null || true
else
  log "[7/8] Skipping Ollama (INSTALL_OLLAMA=${INSTALL_OLLAMA}, RAM ${MEM_MB} MB) - Gemini only"
fi

# ---- 8. Shared config + shell setup -------------------------------------------
log "[8/8] Config + shell"
cat > /opt/gigavolt/config.env <<EOL
# Gigavolt Phase 5 runtime config (sourced by ~/.bashrc; Python reads os.environ)
MARIADB_HOST=127.0.0.1
MARIADB_PORT=3306
MARIADB_USER=${APP_DB_USER}
MARIADB_PASSWORD=${APP_DB_PASS}
MARIADB_DB=${ERP_DB}
MONGO_URI=mongodb://127.0.0.1:27017
MONGO_DB=${MONGO_DB}
CHROMA_PATH=/opt/gigavolt/chroma_db
EMBED_MODEL=${EMBED_MODEL}
HF_HOME=/opt/gigavolt/hf_cache
# Main generator: Gemini (free tier, hosted). Fallback / comparison: Ollama (local).
LLM_BACKEND=gemini
GEMINI_MODEL=gemini-3.5-flash-lite
# Paste your key here AFTER launch (never put it in user-data):
GEMINI_API_KEY=
OLLAMA_URL=http://127.0.0.1:11434
LLM_MODEL=${LLM_MODEL}
EOL
chown ubuntu:ubuntu /opt/gigavolt/config.env
chmod 600 /opt/gigavolt/config.env

if ! grep -q gigavolt_env /home/ubuntu/.bashrc; then
cat >> /home/ubuntu/.bashrc <<'EOL'

# --- Gigavolt Phase 5 ---
source /opt/gigavolt_env/bin/activate
set -a; source /opt/gigavolt/config.env; set +a
alias gvsql='mariadb -u $MARIADB_USER -p$MARIADB_PASSWORD $MARIADB_DB'
alias gvmongo='mongosh $MONGO_URI/$MONGO_DB'
EOL
fi

# ---- Final health check: never report success if a database is down -----------
sleep 5
FAILED=""
for svc in mariadb mongod; do systemctl is-active --quiet "$svc" || FAILED="${FAILED} ${svc}"; done
if [ -n "${FAILED}" ]; then
  log "INIT FINISHED WITH ERRORS - not running:${FAILED}"
  for svc in ${FAILED}; do journalctl -u "$svc" -n 20 --no-pager; done
  exit 1
fi
OLLAMA_STATE="not installed"
systemctl list-unit-files ollama.service >/dev/null 2>&1 && OLLAMA_STATE="$(systemctl is-active ollama || true)"
date > /opt/gigavolt/INIT_DONE
log "Phase 5 init complete. MariaDB: active | MongoDB: active | Ollama: ${OLLAMA_STATE}"
