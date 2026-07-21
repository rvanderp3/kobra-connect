.PHONY: help build start stop restart logs clean

KOBRA_IP ?= 192.168.0.71
WEBCAM_URL ?= http://192.168.0.35
OE_DATA_DIR ?= $(HOME)/oe-data
OE_DATA_DIR_BAMBU ?= $(HOME)/oe-data-bambu
BAMBU_ACCESS_CODE ?=
BAMBU_SERIAL ?=
BAMBU_IP ?=

help:
	@echo "Kobra Moonraker Bridge + OctoEverywhere Companion"
	@echo ""
	@echo "Usage:"
	@echo "  make build      - Build the bridge Docker image"
	@echo "  make start      - Start bridge and companion (Bambu optional, see below)"
	@echo "  make stop       - Stop all containers"
	@echo "  make restart    - Restart all containers"
	@echo "  make logs       - Follow logs for all containers"
	@echo "  make logs-bridge - Follow bridge logs only"
	@echo "  make logs-oe     - Follow Kobra OE companion logs"
	@echo "  make logs-bambu  - Follow Bambu OE companion logs"
	@echo "  make status     - Show container status"
	@echo "  make start-bambu - Start Bambu Connect companion"
	@echo "  make stop-bambu  - Stop Bambu Connect companion"
	@echo "  make clean      - Stop and remove all containers + volumes"
	@echo ""
	@echo "Config (override via env):"
	@echo "  KOBRA_IP=$(KOBRA_IP)"
	@echo "  WEBCAM_URL=$(WEBCAM_URL)"
	@echo "  OE_DATA_DIR=$(OE_DATA_DIR)"
	@echo "  BAMBU_IP=$(BAMBU_IP)"
	@echo "  BAMBU_ACCESS_CODE=$(BAMBU_ACCESS_CODE)"
	@echo "  BAMBU_SERIAL=$(BAMBU_SERIAL)"
	@echo ""
	@echo "Bambu Connect is optional — set all three BAMBU_* vars to enable:"
	@echo "  BAMBU_IP=192.168.0.50 BAMBU_ACCESS_CODE=abc123 BAMBU_SERIAL=12345 make start"

build:
	podman build -f Dockerfile.bridge -t kobra-moonraker-bridge:latest .

start: build
	@mkdir -p $(OE_DATA_DIR)
	@mkdir -p $(OE_DATA_DIR_BAMBU)
	@echo "Starting Kobra Moonraker Bridge on port 7125..."
	podman run -d --name kobra-moonraker-bridge \
	  -e KOBRA_IP=$(KOBRA_IP) \
	  -e LOG_LEVEL=INFO \
	  -p 7125:7125 \
	  kobra-moonraker-bridge:latest
	@echo "Waiting for bridge to be ready..."
	@sleep 3
	@echo "Starting Nginx proxy on port 8080..."
	podman run -d --name kobra-nginx \
	  --network host \
	  -v $(PWD)/nginx.conf:/etc/nginx/nginx.conf:ro \
	  -v /dev/null:/etc/nginx/conf.d/default.conf:ro \
	  nginx:alpine
	@sleep 2
	@echo "Starting OctoEverywhere Companion..."
	podman run -d --name octoeverywhere-kobra \
	  --network host \
	  -e COMPANION_MODE=klipper \
	  -e PRINTER_IP=127.0.0.1 \
	  -e MOONRAKER_PORT=7125 \
	  -e WEBSERVER_PORT=8080 \
	  -v $(OE_DATA_DIR):/data \
	  octoeverywhere/octoeverywhere:latest
	@if [ -n "$(BAMBU_ACCESS_CODE)" ] && [ -n "$(BAMBU_SERIAL)" ] && [ -n "$(BAMBU_IP)" ]; then \
	  echo "Starting OctoEverywhere Bambu Connect..."; \
	  podman run -d --name octoeverywhere-bambu \
	    --network host \
	    -e COMPANION_MODE=bambu \
	    -e ACCESS_CODE=$(BAMBU_ACCESS_CODE) \
	    -e SERIAL_NUMBER=$(BAMBU_SERIAL) \
	    -e PRINTER_IP=$(BAMBU_IP) \
	    -e TZ=UTC \
	    -v $(OE_DATA_DIR_BAMBU):/data \
	    octoeverywhere/octoeverywhere:latest; \
	  echo "Bambu companion logs: make logs-bambu"; \
	else \
	  echo "Skipping Bambu Connect (set BAMBU_ACCESS_CODE, BAMBU_SERIAL, BAMBU_IP to enable)"; \
	fi
	@echo ""
	@echo "Bridge:   http://localhost:7125"
	@echo "Nginx:    http://localhost:8080 (proxies to bridge)"
	@echo "Webcam:   http://localhost:8080/webcam/?action=stream"
	@echo "Kobra companion logs: make logs-oe"

stop:
	@echo "Stopping containers..."
	-podman rm -f octoeverywhere-kobra octoeverywhere-bambu kobra-nginx kobra-moonraker-bridge 2>/dev/null

restart: stop start

logs:
	podman logs -f kobra-moonraker-bridge 2>/dev/null & podman logs -f octoeverywhere-kobra 2>/dev/null & podman logs -f octoeverywhere-bambu 2>/dev/null; wait

logs-bridge:
	podman logs -f kobra-moonraker-bridge

logs-oe:
	podman logs -f octoeverywhere-kobra

logs-bambu:
	podman logs -f octoeverywhere-bambu

status:
	@echo "=== Container Status ==="
	@podman ps -a --filter "name=kobra-moonraker-bridge" --filter "name=octoeverywhere-kobra" --filter "name=octoeverywhere-bambu" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
	@echo ""
	@echo "=== Bridge Health ==="
	@curl -s http://localhost:7125/server/info 2>/dev/null | jq . 2>/dev/null || echo "Bridge not responding"

link-code:
	@podman logs octoeverywhere-kobra 2>/dev/null | grep -A 2 "Code:" || echo "No link code found yet. Check: make logs-oe"

link-code-bambu:
	@podman logs octoeverywhere-bambu 2>/dev/null | grep -A 2 "Code:" || echo "No link code found yet. Check: make logs-bambu"

# Backup/Restore
BACKUP_DIR ?= $(PWD)/backups
TIMESTAMP := $(shell date +%Y%m%d-%H%M%S)

backup:
	@mkdir -p $(BACKUP_DIR)
	@echo "Backing up $(OE_DATA_DIR) to $(BACKUP_DIR)/kobra-oe-$(TIMESTAMP).tar.gz"
	@tar -czf $(BACKUP_DIR)/kobra-oe-$(TIMESTAMP).tar.gz -C $(dir $(OE_DATA_DIR)) $(notdir $(OE_DATA_DIR))
	@if [ -d "$(OE_DATA_DIR_BAMBU)" ]; then \
		echo "Backing up $(OE_DATA_DIR_BAMBU) to $(BACKUP_DIR)/bambu-oe-$(TIMESTAMP).tar.gz"; \
		tar -czf $(BACKUP_DIR)/bambu-oe-$(TIMESTAMP).tar.gz -C $(dir $(OE_DATA_DIR_BAMBU)) $(notdir $(OE_DATA_DIR_BAMBU)); \
	fi
	@echo "Done. Backups in $(BACKUP_DIR)/"

restore:
	@if [ -z "$(BACKUP_FILE)" ]; then \
		echo "Usage: make restore BACKUP_FILE=$(BACKUP_DIR)/kobra-oe-20240115-120000.tar.gz"; \
		echo "Available backups:"; \
		ls -la $(BACKUP_DIR)/ 2>/dev/null || echo "  (none)"; \
		exit 1; \
	fi
	@echo "Restoring from $(BACKUP_FILE) to $(OE_DATA_DIR)..."
	@mkdir -p $(OE_DATA_DIR)
	@tar -xzf $(BACKUP_FILE) -C $(dir $(OE_DATA_DIR))
	@echo "Done. Restart with: make restart"

restore-bambu:
	@if [ -z "$(BACKUP_FILE)" ]; then \
		echo "Usage: make restore-bambu BACKUP_FILE=$(BACKUP_DIR)/bambu-oe-20240115-120000.tar.gz"; \
		echo "Available backups:"; \
		ls -la $(BACKUP_DIR)/ 2>/dev/null || echo "  (none)"; \
		exit 1; \
	fi
	@echo "Restoring Bambu from $(BACKUP_FILE) to $(OE_DATA_DIR_BAMBU)..."
	@mkdir -p $(OE_DATA_DIR_BAMBU)
	@tar -xzf $(BACKUP_FILE) -C $(dir $(OE_DATA_DIR_BAMBU))
	@echo "Done. Restart with: make start"

list-backups:
	@echo "Available backups in $(BACKUP_DIR):"
	@ls -lh $(BACKUP_DIR)/ 2>/dev/null || echo "  (none)"

start-bambu:
	@mkdir -p $(OE_DATA_DIR_BAMBU)
	@echo "Starting OctoEverywhere Bambu Connect..."
	podman run -d --name octoeverywhere-bambu \
	  --network host \
	  -e COMPANION_MODE=bambu \
	  -e ACCESS_CODE=$(BAMBU_ACCESS_CODE) \
	  -e SERIAL_NUMBER=$(BAMBU_SERIAL) \
	  -e PRINTER_IP=$(BAMBU_IP) \
	  -e TZ=UTC \
	  -v $(OE_DATA_DIR_BAMBU):/data \
	  octoeverywhere/octoeverywhere:latest
	@echo ""
	@echo "Bambu companion started. Check: make logs-bambu"

stop-bambu:
	-podman stop octoeverywhere-bambu
	-podman rm octoeverywhere-bambu

clean: stop
	@echo "Removing data directories..."
	rm -rf $(OE_DATA_DIR)
	rm -rf $(OE_DATA_DIR_BAMBU)
	@echo "Removing bridge image..."
	-podman rmi kobra-moonraker-bridge:latest