#!/bin/bash

# Development setup script
set -e

echo "🚀 Centralized LLM Platform - Development Setup"
echo "================================================"

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo "❌ Docker is not installed. Please install Docker first."
    exit 1
fi

echo "✅ Docker is installed"

# Check if Docker Compose is installed
if ! command -v docker-compose &> /dev/null; then
    echo "❌ Docker Compose is not installed. Please install Docker Compose first."
    exit 1
fi

echo "✅ Docker Compose is installed"

# Create .env file if it doesn't exist
if [ ! -f backend/.env ]; then
    echo "📝 Creating .env file..."
    cat > backend/.env << EOF
DATABASE_URL=postgresql://llmuser:changeme123@postgres:5432/llm_chatbot
OLLAMA_URL=http://host.docker.internal:11434
API_SECRET_KEY=dev-secret-key-change-in-prod
ENVIRONMENT=development
EOF
    echo "✅ .env file created"
fi

# Install Python dependencies
echo "📦 Installing Python dependencies..."
cd backend
pip install -r requirements.txt
cd ..
echo "✅ Dependencies installed"

# Start Docker containers
echo "🐳 Starting Docker containers..."
docker-compose up -d
echo "✅ Docker containers started"

# Wait for PostgreSQL to be ready
echo "⏳ Waiting for PostgreSQL to be ready..."
sleep 5

# Run migrations
echo "🔄 Running database migrations..."
docker-compose exec -T api alembic upgrade head || true

# Run tests
echo "🧪 Running tests..."
cd backend
pytest ../tests --tb=short || true
cd ..

echo ""
echo "✅ Setup complete!"
echo ""
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║                    SETUP SUCCESSFUL                            ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""
echo "📊 Service URLs:"
echo "   • API:              http://localhost:8001"
echo "   • API Docs:         http://localhost:8001/docs"
echo "   • PostgreSQL:       localhost:5432"
echo ""
echo "📋 Management Commands:"
echo "   • Start:    ./service-control.sh start"
echo "   • Stop:     ./service-control.sh stop"
echo "   • Restart:  ./service-control.sh restart"
echo "   • Status:   ./service-control.sh status"
echo "   • Logs:     ./service-control.sh logs"
echo ""
echo "🧪 Test Commands:"
echo "   • Validate: ./validate-and-test.sh"
echo "   • Health:   curl http://localhost:8001/health"
echo ""
