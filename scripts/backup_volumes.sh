#!/usr/bin/env bash
# =============================================================================
# OpenConstructionERP — Volume Backup Script
# Backups PostgreSQL, MinIO, and Qdrant data volumes to ./backups/
# =============================================================================

set -euo pipefail

BACKUP_DIR="${BACKGROUND_DIR:-./backups}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_NAME="ocerp_backup_${TIMESTAMP}"
BACKUP_PATH="${BACKUP_DIR}/${BACKUP_NAME}"

mkdir -p "${BACKUP_PATH}"

echo "============================================"
echo " OpenConstructionERP Volume Backup"
echo " Timestamp: ${TIMESTAMP}"
echo " Backup location: ${BACKUP_PATH}"
echo "============================================"

backup_volume() {
    local VOLUME_NAME="$1"
    local DEST_DIR="${BACKUP_PATH}/${VOLUME_NAME}"

    echo ""
    echo ">>> Backing up volume: ${VOLUME_NAME}"

    if ! docker volume inspect "${VOLUME_NAME}" > /dev/null 2>&1; then
        echo "    ⚠ ${VOLUME_NAME} does not exist, skipping"
        return
    fi

    mkdir -p "${DEST_DIR}"

    docker run --rm \
        -v "${VOLUME_NAME}:/volume:ro" \
        -v "${DEST_DIR}:/backup:rw" \
        alpine \
        sh -c "cp -a /volume/. /backup/"

    local SIZE=$(du -sh "${DEST_DIR}" 2>/dev/null | cut -f1 || echo "?")
    echo "    ✓ ${VOLUME_NAME} backed up (${SIZE})"
}

backup_volume "ocerp_pg_data"
backup_volume "ocerp_minio_data"
backup_volume "ocerp_qdrant_data"

cat > "${BACKUP_PATH}/metadata.json" << EOF
{
  "timestamp": "${TIMESTAMP}",
  "volumes": ["ocerp_pg_data", "ocerp_minio_data", "ocerp_qdrant_data"],
  "created_at": "$(date -Iseconds)",
  "backup_path": "${BACKUP_PATH}"
}
EOF

echo ""
echo ">>> Creating compressed archive..."
sudo tar --no-same-owner -czf "${BACKUP_DIR}/${BACKUP_NAME}.tar.gz" -C "${BACKUP_DIR}" "${BACKUP_NAME}"
sudo rm -rf "${BACKUP_PATH}"

echo ""
echo "============================================"
echo " Backup complete: ${BACKUP_NAME}.tar.gz"
echo " Size: $(du -sh "${BACKUP_DIR}/${BACKUP_NAME}.tar.gz" | cut -f1)"
echo "============================================"