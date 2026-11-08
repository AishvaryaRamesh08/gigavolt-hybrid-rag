#!/bin/bash
# =============================================================================
# failover_status.sh - one-block health and data summary for THIS node.
#
#   sudo ./failover_status.sh         run on EACH node, then compare the blocks
#
# After recovery every node must show: cluster_size 3, Primary, Synced, the SAME
# cluster_state_uuid, recv_queue 0, and identical row counts and checksums.
# (Stop the writer before comparing checksums, or the table keeps changing.)
# =============================================================================
q() { mariadb -N -B -e "$1" 2>&1 | head -1; }
st() { q "SELECT VARIABLE_VALUE FROM information_schema.GLOBAL_STATUS WHERE VARIABLE_NAME='$1'"; }

echo "================ $(hostname)  $(date '+%H:%M:%S') ================"
echo "wsrep_cluster_size          : $(st WSREP_CLUSTER_SIZE)"
echo "wsrep_cluster_status        : $(st WSREP_CLUSTER_STATUS)"
echo "wsrep_local_state_comment   : $(st WSREP_LOCAL_STATE_COMMENT)"
echo "wsrep_ready                 : $(st WSREP_READY)"
echo "wsrep_cluster_state_uuid    : $(st WSREP_CLUSTER_STATE_UUID)"
echo "wsrep_local_recv_queue      : $(st WSREP_LOCAL_RECV_QUEUE)"
echo "heartbeat rows              : $(q 'SELECT COUNT(*) FROM failover_test.heartbeat')"
echo "heartbeat checksum          : $(mariadb -N -B -e 'CHECKSUM TABLE failover_test.heartbeat' 2>&1 | awk '{print $2}' | head -1)"
echo "svc_analytics_innodb rows   : $(q 'SELECT COUNT(*) FROM gigavolt_analytics.svc_analytics_innodb')"
echo "gigavolt_erp.service_logs   : $(q 'SELECT COUNT(*) FROM gigavolt_erp.service_logs')"
