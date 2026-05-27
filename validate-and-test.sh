#!/bin/bash

# ==============================================================================
# Centralized LLM Platform - Complete Test & Validation Script
# ==============================================================================
# This script validates all configurations and tests the platform
# ==============================================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║   Centralized LLM Platform - Configuration Validator          ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════════╝${NC}"
echo ""

# ==============================================================================
# SECTION 1: VALIDATE PORT CONFIGURATION
# ==============================================================================
echo -e "${YELLOW}[1/7] Validating Port Configuration...${NC}"
echo ""

# Expected ports
API_PORT=8001
DB_PORT=5432
CONTAINER_API_PORT=8000

echo "✓ Expected Configuration:"
echo "  - External API Port (host): ${API_PORT}"
echo "  - Internal API Port (container): ${CONTAINER_API_PORT}"
echo "  - PostgreSQL Port: ${DB_PORT}"
echo ""

# Check docker-compose.yml
if grep -q "\"8001:8000\"" docker-compose.yml; then
    echo -e "${GREEN}✓ docker-compose.yml: Port mapping 8001:8000 CORRECT${NC}"
else
    echo -e "${RED}✗ docker-compose.yml: Port mapping incorrect${NC}"
    exit 1
fi

if grep -q "\"5432:5432\"" docker-compose.yml; then
    echo -e "${GREEN}✓ docker-compose.yml: PostgreSQL port 5432 CORRECT${NC}"
else
    echo -e "${RED}✗ docker-compose.yml: PostgreSQL port incorrect${NC}"
    exit 1
fi

echo ""

# ==============================================================================
# SECTION 2: VALIDATE DOCKER COMPOSE
# ==============================================================================
echo -e "${YELLOW}[2/7] Validating Docker Compose Configuration...${NC}"
echo ""

if [ -f "docker-compose.yml" ]; then
    echo -e "${GREEN}✓ docker-compose.yml exists${NC}"
    
    # Validate syntax
    if docker-compose config > /dev/null 2>&1; then
        echo -e "${GREEN}✓ docker-compose.yml syntax valid${NC}"
    else
        echo -e "${RED}✗ docker-compose.yml has syntax errors${NC}"
        exit 1
    fi
else
    echo -e "${RED}✗ docker-compose.yml not found${NC}"
    exit 1
fi

echo ""

# ==============================================================================
# SECTION 3: VALIDATE ENVIRONMENT FILES
# ==============================================================================
echo -e "${YELLOW}[3/7] Validating Environment Configuration...${NC}"
echo ""

if [ -f "backend/.env" ]; then
    echo -e "${GREEN}✓ backend/.env exists${NC}"
    
    # Check required variables
    if grep -q "DATABASE_URL" backend/.env; then
        echo -e "${GREEN}✓ DATABASE_URL configured${NC}"
    else
        echo -e "${RED}✗ DATABASE_URL missing${NC}"
        exit 1
    fi
    
    if grep -q "LLM_PROVIDER" backend/.env; then
        echo -e "${GREEN}✓ LLM_PROVIDER configured${NC}"
        LLM_PROVIDER=$(grep "^LLM_PROVIDER=" backend/.env | cut -d'=' -f2)
        echo "  → Provider: ${LLM_PROVIDER}"
    else
        echo -e "${YELLOW}⚠ LLM_PROVIDER not set (will use default)${NC}"
    fi
else
    echo -e "${RED}✗ backend/.env not found${NC}"
    exit 1
fi

echo ""

# ==============================================================================
# SECTION 4: CHECK DOCKER SERVICES
# ==============================================================================
echo -e "${YELLOW}[4/7] Checking Docker Services...${NC}"
echo ""

if docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" | grep -q "llm-"; then
    echo -e "${GREEN}✓ Docker services are running:${NC}"
    docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" | grep "llm-" || echo "  (No services running)"
else
    echo -e "${YELLOW}⚠ No services running yet${NC}"
fi

echo ""

# ==============================================================================
# SECTION 5: VALIDATE API ENDPOINTS
# ==============================================================================
echo -e "${YELLOW}[5/7] Testing API Endpoints...${NC}"
echo ""

# Wait a moment for services to settle
sleep 2

# Test health endpoint
echo "Testing API health endpoint..."
if curl -s -f "http://localhost:${API_PORT}/health" > /dev/null 2>&1; then
    HEALTH_RESPONSE=$(curl -s "http://localhost:${API_PORT}/health")
    echo -e "${GREEN}✓ API is responding on port ${API_PORT}${NC}"
    echo "  Response: ${HEALTH_RESPONSE}"
else
    echo -e "${RED}✗ API is not responding on port ${API_PORT}${NC}"
    echo -e "${YELLOW}  Checking API logs...${NC}"
    docker logs llm-api --tail 20 2>&1 | tail -10
fi

echo ""

# Test API documentation
echo "Testing API documentation endpoint..."
if curl -s -f "http://localhost:${API_PORT}/docs" > /dev/null 2>&1; then
    echo -e "${GREEN}✓ API docs available at http://localhost:${API_PORT}/docs${NC}"
else
    echo -e "${YELLOW}⚠ API docs endpoint not responding (may be normal if API is starting)${NC}"
fi

echo ""

# ==============================================================================
# SECTION 6: VALIDATE DATABASE CONNECTION
# ==============================================================================
echo -e "${YELLOW}[6/7] Testing Database Connection...${NC}"
echo ""

if docker exec llm-postgres pg_isready -U llmuser > /dev/null 2>&1; then
    echo -e "${GREEN}✓ PostgreSQL is accepting connections${NC}"
    
    # Check if tables exist
    TABLE_COUNT=$(docker exec llm-postgres psql -U llmuser -d llm_chatbot -t -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public';" 2>/dev/null | xargs || echo "0")
    echo "  → Database tables: ${TABLE_COUNT}"
    
    if [ "$TABLE_COUNT" -gt "0" ]; then
        echo -e "${GREEN}✓ Database schema initialized${NC}"
    else
        echo -e "${YELLOW}⚠ Database schema not initialized yet${NC}"
    fi
else
    echo -e "${RED}✗ PostgreSQL is not responding${NC}"
fi

echo ""

# ==============================================================================
# SECTION 7: SUMMARY AND RECOMMENDATIONS
# ==============================================================================
echo -e "${YELLOW}[7/7] Configuration Summary${NC}"
echo ""
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║                    CONFIGURATION VALIDATED                     ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""
echo "📊 Service URLs:"
echo "   • API:              http://localhost:${API_PORT}"
echo "   • API Docs:         http://localhost:${API_PORT}/docs"
echo "   • PostgreSQL:       localhost:${DB_PORT}"
echo ""
echo "🔧 Available Commands:"
echo ""
echo "   Start Services:"
echo "   $ docker-compose up -d"
echo ""
echo "   Stop Services:"
echo "   $ docker-compose down"
echo ""
echo "   View Logs:"
echo "   $ docker-compose logs -f"
echo "   $ docker-compose logs -f api        # API logs only"
echo "   $ docker-compose logs -f postgres   # Database logs only"
echo ""
echo "   Restart Services:"
echo "   $ docker-compose restart"
echo "   $ docker restart llm-api            # Restart API only"
echo ""
echo "   Check Status:"
echo "   $ docker-compose ps"
echo ""
echo "   Clean Restart (Remove all data):"
echo "   $ docker-compose down -v"
echo "   $ docker-compose up -d"
echo ""
echo "📋 Quick Health Checks:"
echo ""
echo "   Test API Health:"
echo "   $ curl http://localhost:${API_PORT}/health"
echo ""
echo "   Test Database:"
echo "   $ docker exec llm-postgres pg_isready -U llmuser"
echo ""
echo "   Create Test Tenant:"
echo "   $ curl -X POST http://localhost:${API_PORT}/api/tenants/ \\"
echo "     -H 'Content-Type: application/json' \\"
echo "     -d '{\"name\":\"Test Co\",\"slug\":\"test\",\"domain\":\"test.com\"}'"
echo ""
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║                    ✅ VALIDATION COMPLETE                      ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""

# ==============================================================================
# TEST SCENARIOS
# ==============================================================================
echo -e "${BLUE}Would you like to run functional tests? (y/n)${NC}"
read -r RUN_TESTS

if [[ "$RUN_TESTS" == "y" || "$RUN_TESTS" == "Y" ]]; then
    echo ""
    echo -e "${YELLOW}Running Functional Tests...${NC}"
    echo ""
    
    # Test 1: Create a tenant
    echo "Test 1: Creating test tenant..."
    TEST_SUFFIX=$(date +%s)
    TENANT_RESPONSE=$(curl -s -X POST "http://localhost:${API_PORT}/api/tenants/" \
        -H "Content-Type: application/json" \
        -d "{\"name\":\"POC Test Tenant\",\"slug\":\"poc-test-${TEST_SUFFIX}\",\"domain\":\"poctest.com\"}" 2>&1)
    
    if echo "$TENANT_RESPONSE" | grep -q "id"; then
        echo -e "${GREEN}✓ Tenant created successfully${NC}"
        TENANT_ID=$(echo "$TENANT_RESPONSE" | grep -o '"id":"[^"]*"' | cut -d'"' -f4)
        echo "  → Tenant ID: ${TENANT_ID}"
        
        # Test 2: Send a message
        echo ""
        echo "Test 2: Sending test message..."
        MESSAGE_RESPONSE=$(curl -s -X POST "http://localhost:${API_PORT}/api/tenants/${TENANT_ID}/chat" \
            -H "Content-Type: application/json" \
            -d '{"content":"Hello, this is a test message"}' 2>&1)
        
        if echo "$MESSAGE_RESPONSE" | grep -q "id"; then
            echo -e "${GREEN}✓ Message sent successfully${NC}"
            SESSION_ID=$(echo "$MESSAGE_RESPONSE" | grep -o '"session_id":"[^"]*"' | cut -d'"' -f4)
            echo "  → Session ID: ${SESSION_ID}"
            
            # Test 3: Get conversation
            echo ""
            echo "Test 3: Retrieving conversation..."
            CONV_RESPONSE=$(curl -s "http://localhost:${API_PORT}/api/admin/conversations/session/${SESSION_ID}" 2>&1)
            
            if echo "$CONV_RESPONSE" | grep -q "messages"; then
                echo -e "${GREEN}✓ Conversation retrieved successfully${NC}"
                MSG_COUNT=$(echo "$CONV_RESPONSE" | grep -o '"message_count":[0-9]*' | cut -d':' -f2)
                echo "  → Message count: ${MSG_COUNT}"
            else
                echo -e "${RED}✗ Failed to retrieve conversation${NC}"
            fi
        else
            echo -e "${RED}✗ Failed to send message${NC}"
        fi
        
        # Test 4: List tenants
        echo ""
        echo "Test 4: Listing all tenants..."
        TENANTS_RESPONSE=$(curl -s "http://localhost:${API_PORT}/api/tenants/" 2>&1)
        
        if echo "$TENANTS_RESPONSE" | grep -q "poc-test-${TEST_SUFFIX}"; then
            echo -e "${GREEN}✓ Tenant listing works${NC}"
        else
            echo -e "${RED}✗ Failed to list tenants${NC}"
        fi
        
    else
        echo -e "${RED}✗ Failed to create tenant${NC}"
        echo "Response: $TENANT_RESPONSE"
    fi
    
    echo ""
    echo -e "${GREEN}✅ Functional tests complete!${NC}"
fi

echo ""
echo -e "${GREEN}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║           🎉 PLATFORM IS READY FOR POC TESTING! 🎉            ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════════════════╝${NC}"
echo ""
