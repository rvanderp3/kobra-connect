.PHONY: help build start stop restart logs clean

KOBRA_IP ?= 192.168.0.71
WEBCAM_URL ?= http://192.168.0.35
OE_DATA_DIR ?= /Users/rvanderp/oe-data

help:
	@echo "Kobra Moonraker Bridge + OctoEverywhere Companion"
	@echo ""
	@echo "Usage:"
	@echo "  make build      - Build the bridge Docker image"
	@echo "  make start      - Start bridge and companion"
	@echo "  make stop       - Stop both containers"
	@echo "  make restart    - Restart both containers"
	@echo "  make logs       - Follow logs for both containers"
	@echo "  make logs-bridge - Follow bridge logs only"
	@echo "  make logs-oe     - Follow companion logs only"
	@echo "  make status     - Show container status"
	@echo "  make clean      - Stop and remove containers + volumes"
	@echo ""
	@echo "Config (override via env):"
	@echo "  KOBRA_IP=$(KOBRA_IP)"
	@echo "  WEBCAM_URL=$(WEBCAM_URL)"
	@echo "  OE_DATA_DIR=$(OE_DATA_DIR)"

build:
	podman build -f Dockerfile.bridge -t kobra-moonraker-bridge:latest .

start: build
	@mkdir -p $(OE_DATA_DIR)
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
	@echo ""
	@echo "Bridge:   http://localhost:7125"
	@echo "Nginx:    http://localhost:8080 (proxies to bridge)"
	@echo "Webcam:   http://localhost:8080/webcam/?action=stream"
	@echo "Companion logs (link code): make logs-oe"

stop:
	@echo "Stopping containers..."
	-podman stop octoeverywhere-kobra kobra-nginx kobra-moonraker-bridge
	-podman rm octoeverywhere-kobra kobra-nginx kobra-moonraker-bridge

restart: stop start

logs:
	podman logs -f kobra-moonraker-bridge & podman logs -f octoeverywhere-kobra

logs-bridge:
	podman logs -f kobra-moonraker-bridge

logs-oe:
	podman logs -f octoeverywhere-kobra

status:
	@echo "=== Container Status ==="
	@podman ps -a --filter "name=kobra-moonraker-bridge" --filter "name=octoeverywhere-kobra" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
	@echo ""
	@echo "=== Bridge Health ==="
	@curl -s http://localhost:7125/server/info 2>/dev/null | jq . 2>/dev/null || echo "Bridge not responding"

link-code:
	@podman logs octoeverywhere-kobra 2>/dev/null | grep -A 2 "Code:" || echo "No link code found yet. Check: make logs-oe"

clean: stop
	@echo "Removing data directory..."
	rm -rf $(OE_DATA_DIR)
	@echo "Removing bridge image..."
	-podman rmi kobra-moonraker-bridge:latest