#!/usr/bin/env bash
# =============================================================================
# OpenConstructionERP — Volume Restore Script
# Restores PostgreSQL, MinIO, and Qdrant data from a backup archive
# Usage: ./restore_volumes.sh <backup_file.tar.gz>
# =============================================================================

set -euo pipefail

if [[ $# -eq 0 ]]; then
    echo "Usage: $0 <backup_file.tar.gz>"
    echo ""
    echo "Available backups:"
    ls -la ./backups/*.tar.gz 2>/dev/null || echo "  No backups found in ./backups/"
    exit 1
fi

BACKUP_FILE="$1"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

if [[ ! -f "${BACKUP_FILE}" ]]; then
    echo "ERROR: Backup file not found: ${BACKUP_FILE}"
    exit 1
fi

BACKUP_NAME=$(basename "${BACKUP_FILE}" .tar.gz)
RESTORE_DIR="/tmp/ocerp_restore_${TIMESTAMP}"

echo "============================================"
echo " OpenConstructionERP Volume Restore"
echo " Backup file: ${BACKUP_FILE}"
echo " Timestamp: ${TIMESTAMP}"
echo "============================================"

# Extract backup
echo ""
echo ">>> Extracting backup..."
mkdir -p "${RESTORE_DIR}"
tar -xzf "${BACKUP_FILE}" -C "${RESTORE_DIR}"

# Find extracted directory
EXTRACTED_DIR=$(find "${RESTORE_DIR}" -mindepth 1 -maxdepth 1 -type d | head -1)
if [[ -z "${EXTRACTED_DIR}" ]]; then
    echo "ERROR: Could not find extracted backup directory"
    exit 1
fi

# Function to stop services before restore
stop_services() {
    echo ""
    echo ">>> Stopping related services..."
    docker compose -f docker-compose.yml stop postgres redis minio qdrant 2>/dev/null || true
    echo "    ✓ Services stopped"
}

# Function to restore a volume
restore_volume() {
    local VOLUME_NAME="$1"
    local SRC_DIR="${EXTRACTED_DIR}/${VOLUME_NAME}"

    echo ""
    echo ">>> Restoring volume: ${VOLUME_NAME}"

    if [[ ! -d "${SRC_DIR}" ]]; then
        echo "    ⚠ ${VOLUME_NAME} not found in backup, skipping"
        return
    fi

    # Stop related services
    stop_services

    # Create new volume if it doesn't exist
    if ! docker volume inspect "${VOLUME_NAME}" > /dev/null 2>&1; then
        echo "    Creating volume ${VOLUME_NAME}..."
        docker volume create "${VOLUME_NAME}"
    fi

    # Clear existing volume data
    docker run --rm \
        -v "${VOLUME_NAME}:/volume" \
        alpine \
        sh -c "rm -rf /volume/*"

    # Restore data
    docker run --rm \
        -v "${VOLUME_NAME}:/volume:rw" \
        -v "${SRC_DIR}:/backup:ro" \
        alpine \
        sh -c "cp -a /backup/. /volume/"

    echo "    ✓ ${VOLUME_NAME} restored"
}

# Restore each volume
restore_volume "pg_data"
restore_volume "minio_data"
restore_volume "qdrant_data"

# Cleanup
rm -rf "${RESTORE_DIR}"

echo ""
echo "============================================"
echo " Restore complete!"
echo " You can now run: docker compose up -d"
echo "============================================"