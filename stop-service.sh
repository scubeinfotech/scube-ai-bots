#!/bin/bash

# Stop centralized LLM platform services
# This script stops all Docker containers gracefully

set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

echo "=========================================="
echo "Stopping Centralized LLM Platform"
echo "=========================================="
echo ""

# Stop containers
echo "Stopping Docker containers..."
docker-compose down

echo ""
echo "=========================================="
echo "✅ Services stopped successfully!"
echo "=========================================="
echo ""
