#!/bin/bash

# ==============================================================================
# Centralized LLM Platform - Service Control Script
# ==============================================================================
# Usage:
#   ./service-control.sh start    - Start all services
#   ./service-control.sh stop     - Stop all services  
#   ./service-control.sh restart  - Restart all services
#   ./service-control.sh status   - Check service status
#   ./service-control.sh dbsize   - Show database size utilization
#   ./service-control.sh logs     - View service logs
#   ./service-control.sh clean    - Stop and remove all data
# ==============================================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

CORE_SERVICES="api postgres"
API_PORT=8001
DB_PORT=5432

show_banner() {
    echo -e "${BLUE}╔════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║        Centralized LLM Platform - Service Controller          ║${NC}"
    echo -e "${BLUE}╚════════════════════════════════════════════════════════════════╝${NC}"
    echo ""
}

start_services() {
    show_banner
    echo -e "${YELLOW}Starting services...${NC}"
    echo ""
    
    # Check if already running
    if docker ps | grep -q "llm-api"; then
        echo -e "${YELLOW}⚠ Services are already running${NC}"
    docker-compose up -d $CORE_SERVICES
        docker-compose ps $CORE_SERVICES
        echo ""
        echo -e "${GREEN}API: http://localhost:${API_PORT}${NC}"
        echo -e "${GREEN}Docs: http://localhost:${API_PORT}/docs${NC}"
        return
    fi
    
    # Start services
    docker-compose up -d
    
    echo ""
    echo -e "${YELLOW}Waiting for services to be healthy...${NC}"
    sleep 5
    
    # Check health
    MAX_RETRIES=30
    RETRY_COUNT=0
    
    while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
        if curl -s -f "http://localhost:${API_PORT}/health" > /dev/null 2>&1; then
            echo -e "${GREEN}✅ Services started successfully!${NC}"
            echo ""
            docker-compose ps $CORE_SERVICES
            echo ""
            echo -e "${GREEN}╔════════════════════════════════════════════════════════════════╗${NC}"
            echo -e "${GREEN}║                   SERVICES ARE RUNNING                         ║${NC}"
            echo "   • Stop:       docker-compose stop $CORE_SERVICES"
            echo ""
            echo "📊 Access Points:"
            echo -e "   • API:      ${GREEN}http://localhost:${API_PORT}${NC}"
            echo -e "   • API Docs: ${GREEN}http://localhost:${API_PORT}/docs${NC}"
            echo -e "   • Database: ${GREEN}localhost:${DB_PORT}${NC}"
            echo ""
            echo "📋 Quick Commands:"
            echo "   • View logs:  docker-compose logs -f"
            echo "   • Stop:       docker-compose down"
            echo "   • Restart:    ./service-control.sh restart"
            echo ""
            return 0
        fi
        
        RETRY_COUNT=$((RETRY_COUNT + 1))
        echo -n "."
        sleep 2
    done
    
    echo ""
    docker-compose stop $CORE_SERVICES
    echo -e "${YELLOW}Check logs with: docker-compose logs api${NC}"
}

stop_services() {
    show_banner
    echo -e "${YELLOW}Stopping services...${NC}"
    echo ""
    
    docker-compose down
    
    docker-compose restart $CORE_SERVICES
    echo -e "${GREEN}✅ Services stopped${NC}"
}

restart_services() {
    show_banner
    echo -e "${YELLOW}Restarting services...${NC}"
    echo ""
    
    docker-compose restart
    
    echo ""
    echo -e "${YELLOW}Waiting for services to be healthy...${NC}"
    sleep 5
    
    # Check health with retries
    MAX_RETRIES=30
    RETRY_COUNT=0
    
    while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
        if curl -s -f "http://localhost:${API_PORT}/health" > /dev/null 2>&1; then
            echo -e "${GREEN}✅ Services restarted successfully!${NC}"
            echo ""
            docker-compose ps $CORE_SERVICES
            echo ""
            echo -e "${GREEN}╔════════════════════════════════════════════════════════════════╗${NC}"
            echo -e "${GREEN}║                   SERVICES ARE RUNNING                         ║${NC}"
            echo "   • Stop:       docker-compose stop $CORE_SERVICES"
            echo ""
            echo "📊 Access Points:"
            echo -e "   • API:      ${GREEN}http://localhost:${API_PORT}${NC}"
            echo -e "   • API Docs: ${GREEN}http://localhost:${API_PORT}/docs${NC}"
            echo -e "   • Database: ${GREEN}localhost:${DB_PORT}${NC}"
            echo ""
            echo "📋 Quick Commands:"
            echo "   • View logs:  docker-compose logs -f"
            echo "   • Stop:       docker-compose down"
            echo "   • Restart:    ./service-control.sh restart"
            echo ""
            return 0
        fi
        
        RETRY_COUNT=$((RETRY_COUNT + 1))
        echo -n "."
        sleep 2
    done
    
    echo ""
    echo -e "${RED}⚠ Services restarted but API is not responding yet${NC}"
    echo -e "${YELLOW}Check logs with: docker-compose logs api${NC}"
}

check_status() {
    show_banner
    echo -e "${YELLOW}Service Status:${NC}"
    echo ""
    
    docker-compose ps $CORE_SERVICES
    
    echo ""
    echo -e "${YELLOW}Health Check:${NC}"
    echo ""
    
    # Check API
    if curl -s -f "http://localhost:${API_PORT}/health" > /dev/null 2>&1; then
        HEALTH=$(curl -s "http://localhost:${API_PORT}/health")
        echo -e "   API (port ${API_PORT}):  ${GREEN}✓ Healthy${NC}"
        echo "      Response: ${HEALTH}"
    else
        echo -e "   API (port ${API_PORT}):  ${RED}✗ Not responding${NC}"
    fi
    
    # Check Database
    if docker exec llm-postgres pg_isready -U llmuser > /dev/null 2>&1; then
        echo -e "   Database (port ${DB_PORT}): ${GREEN}✓ Ready${NC}"

        DB_SIZE_PRETTY=$(docker exec llm-postgres psql -U llmuser -d llm_chatbot -t -A -c "SELECT pg_size_pretty(pg_database_size('llm_chatbot'));" 2>/dev/null | tr -d '\r')
        DB_SIZE_BYTES=$(docker exec llm-postgres psql -U llmuser -d llm_chatbot -t -A -c "SELECT pg_database_size('llm_chatbot');" 2>/dev/null | tr -d '\r')

        if [ -n "$DB_SIZE_PRETTY" ]; then
            echo -e "   DB Utilization: ${GREEN}${DB_SIZE_PRETTY}${NC} (${DB_SIZE_BYTES} bytes)"
        fi
    else
        echo -e "   Database (port ${DB_PORT}): ${RED}✗ Not ready${NC}"
    fi
    
    echo ""
}

show_db_size() {
    show_banner
    echo -e "${YELLOW}Database Size Utilization:${NC}"
    echo ""

    if ! docker exec llm-postgres pg_isready -U llmuser > /dev/null 2>&1; then
        echo -e "${RED}Database is not ready. Start services first.${NC}"
        return 1
    fi

    DB_SIZE_PRETTY=$(docker exec llm-postgres psql -U llmuser -d llm_chatbot -t -A -c "SELECT pg_size_pretty(pg_database_size('llm_chatbot'));" | tr -d '\r')
    DB_SIZE_BYTES=$(docker exec llm-postgres psql -U llmuser -d llm_chatbot -t -A -c "SELECT pg_database_size('llm_chatbot');" | tr -d '\r')

    echo -e "   Database: ${GREEN}llm_chatbot${NC}"
    echo -e "   Size:     ${GREEN}${DB_SIZE_PRETTY}${NC} (${DB_SIZE_BYTES} bytes)"
    echo ""
    echo -e "${YELLOW}Top 10 Largest Tables:${NC}"
    docker exec llm-postgres psql -U llmuser -d llm_chatbot -c "
        SELECT
            schemaname || '.' || relname AS table_name,
            pg_size_pretty(pg_total_relation_size(relid)) AS total_size
        FROM pg_catalog.pg_statio_user_tables
        ORDER BY pg_total_relation_size(relid) DESC
        LIMIT 10;
    "
}

view_logs() {
    show_banner
    echo -e "${YELLOW}Service Logs (press Ctrl+C to exit):${NC}"
    echo ""
    
    docker-compose logs -f --tail=50
}

check_whatsapp_status() {
    show_banner
    echo -e "${YELLOW}WhatsApp Integration Status:${NC}"
    echo ""
    
    if ! curl -s -f "http://localhost:${API_PORT}/health" > /dev/null 2>&1; then
        echo -e "${RED}✗ API is not responding. Start services first.${NC}"
        return 1
    fi
    
    # Check if WhatsApp is available
    if curl -s "http://localhost:${API_PORT}/api/whatsapp/health" > /dev/null 2>&1; then
        echo -e "${GREEN}✅ WhatsApp API is available${NC}"
    else
        echo -e "${YELLOW}⚠ WhatsApp API not responding${NC}"
    fi
    
    echo ""
    echo -e "${YELLOW}WhatsApp Database Tables:${NC}"
    docker exec llm-postgres psql -U llmuser -d llm_chatbot -t -A -c "
        SELECT
            schemaname,
            tablename,
            pg_size_pretty(pg_total_relation_size('\"' || schemaname || '\".\"' || tablename || '\"')) as size
        FROM pg_tables
        WHERE tablename LIKE 'whatsapp%'
        ORDER BY pg_total_relation_size('\"' || schemaname || '\".\"' || tablename || '\"') DESC;
    " 2>/dev/null || echo "   No WhatsApp tables found"
    
    echo ""
    echo -e "${YELLOW}WhatsApp Configurations:${NC}"
    docker exec llm-postgres psql -U llmuser -d llm_chatbot -t -A -c "
        SELECT 
            COUNT(*) as total_configs,
            SUM(CASE WHEN is_active = true THEN 1 ELSE 0 END) as active_configs
        FROM whatsapp_configurations;
    " 2>/dev/null || echo "   Unable to query configurations"
    
    echo ""
}

show_whatsapp_metrics() {
    show_banner
    echo -e "${YELLOW}WhatsApp Metrics:${NC}"
    echo ""
    
    if ! docker exec llm-postgres pg_isready -U llmuser > /dev/null 2>&1; then
        echo -e "${RED}Database is not ready. Start services first.${NC}"
        return 1
    fi
    
    echo -e "${YELLOW}Message Statistics:${NC}"
    docker exec llm-postgres psql -U llmuser -d llm_chatbot -c "
        SELECT
            COUNT(*) AS total_messages,
            COUNT(*) FILTER (WHERE direction = 'inbound') AS inbound_messages,
            COUNT(*) FILTER (WHERE direction = 'outbound') AS outbound_messages,
            COUNT(*) FILTER (WHERE delivery_status = 'failed') AS failed_messages,
            COUNT(*) FILTER (WHERE processed = true) AS processed_messages
        FROM whatsapp_messages;
    "
    
    echo ""
    echo -e "${YELLOW}Message Volume (Last 24 hours):${NC}"
    docker exec llm-postgres psql -U llmuser -d llm_chatbot -c "
        SELECT
            DATE(created_at) AS date,
            COUNT(*) AS message_count,
            COUNT(*) FILTER (WHERE direction = 'inbound') AS inbound,
            COUNT(*) FILTER (WHERE direction = 'outbound') AS outbound,
            COUNT(*) FILTER (WHERE delivery_status = 'failed') AS failed
        FROM whatsapp_messages
        WHERE created_at >= NOW() - INTERVAL '24 hours'
        GROUP BY DATE(created_at)
        ORDER BY date DESC;
    "
    
    echo ""
}

show_whatsapp_logs() {
    show_banner
    echo -e "${YELLOW}WhatsApp Service Logs (press Ctrl+C to exit):${NC}"
    echo ""
    
    docker-compose logs -f --tail=100 api | grep -i "whatsapp\|message_broker\|webhook" || \
        echo -e "${YELLOW}No WhatsApp logs found. Showing all API logs...${NC}" && \
        docker-compose logs -f --tail=100 api
}

clean_all() {
    show_banner
    echo -e "${RED}WARNING: This will stop services and remove ALL data!${NC}"
    echo -e "${YELLOW}Are you sure? (type 'yes' to confirm)${NC}"
    read -r CONFIRM
    
    if [ "$CONFIRM" = "yes" ]; then
        echo ""
        echo -e "${YELLOW}Cleaning up...${NC}"
        docker-compose down -v
        echo ""
        echo -e "${GREEN}✅ All services and data removed${NC}"
        echo -e "${YELLOW}Run './service-control.sh start' to start fresh${NC}"
    else
        echo ""
        echo -e "${GREEN}Cancelled${NC}"
    fi
}

# Main script
case "${1:-}" in
    start)
        start_services
        ;;
    stop)
        stop_services
        ;;
    restart)
        restart_services
        ;;
    status)
        check_status
        ;;
    whatsapp)
        check_whatsapp_status
        ;;
    whatsapp-metrics)
        show_whatsapp_metrics
        ;;
    whatsapp-logs)
        show_whatsapp_logs
        ;;
    dbsize)
        show_db_size
        ;;
    logs)
        view_logs
        ;;
    clean)
        clean_all
        ;;
    *)
        show_banner
        echo "Usage: $0 {start|stop|restart|status|dbsize|logs|clean|whatsapp|whatsapp-metrics|whatsapp-logs}"
        echo ""
        echo "Core Commands:"
        echo "  start            - Start all services"
        echo "  stop             - Stop all services"
        echo "  restart          - Restart all services"
        echo "  status           - Check service status and health"
        echo "  dbsize           - Show database size utilization"
        echo "  logs             - View service logs (live)"
        echo "  clean            - Stop services and remove all data"
        echo ""
        echo "WhatsApp Commands:"
        echo "  whatsapp         - Check WhatsApp integration status"
        echo "  whatsapp-metrics - Show WhatsApp message statistics"
        echo "  whatsapp-logs    - View WhatsApp service logs"
        echo ""
        exit 1
        ;;
esac
