#!/bin/bash

# Start centralized LLM platform services
# This script starts all required Docker containers

set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

echo "=========================================="
echo "Starting Centralized LLM Platform"
echo "=========================================="
echo ""

# Start containers
echo "Starting Docker containers..."
docker-compose up -d postgres api redis

echo ""
echo "Waiting for services to be ready..."
sleep 5

# Check container status
echo ""
echo "Container Status:"
docker-compose ps

# Check API health
echo ""
echo "Checking API health..."
if curl -s http://127.0.0.1:8001/health > /dev/null 2>&1; then
    echo "✅ API is healthy"
else
    echo "⚠️  API is starting, give it a moment..."
    sleep 3
fi

echo ""
echo "=========================================="
echo "✅ Services started successfully!"
echo "=========================================="
echo ""
echo "Access Points:"
echo "  - API: http://127.0.0.1:8001"
echo "  - API Docs: http://127.0.0.1:8001/docs"
echo "  - Database: localhost:5432"
echo "  - Redis: localhost:6379"
echo ""
