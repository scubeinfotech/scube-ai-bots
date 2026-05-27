#!/bin/bash
# WhatsApp Connector Quick Setup

# This script demonstrates how to configure and test WhatsApp integration

set -e

# Configuration
TENANT_ID="rapas"  # Change to your tenant ID
API_BASE_URL="http://localhost:8000"
PHONE_NUMBER_ID="1234567890"  # Get from WhatsApp Business Platform
BUSINESS_ACCOUNT_ID="abcdef"  # Get from WhatsApp Business Platform
ACCESS_TOKEN="EAABSZ..."  # Get from WhatsApp Business Platform
WEBHOOK_VERIFY_TOKEN="my_secure_token_$(date +%s)"
WEBHOOK_URL="https://yourdomain.com/api/whatsapp/webhook/${TENANT_ID}"

echo "==================================="
echo "WhatsApp Connector Setup"
echo "==================================="
echo ""

# Step 1: Configure WhatsApp
echo "Step 1: Configuring WhatsApp for tenant: ${TENANT_ID}"
echo "  phone_number_id: ${PHONE_NUMBER_ID}"
echo "  webhook_url: ${WEBHOOK_URL}"
echo ""

curl -X POST "${API_BASE_URL}/api/whatsapp/configure/${TENANT_ID}" \
  -H "Content-Type: application/json" \
  -d "{
    \"phone_number_id\": \"${PHONE_NUMBER_ID}\",
    \"business_account_id\": \"${BUSINESS_ACCOUNT_ID}\",
    \"access_token\": \"${ACCESS_TOKEN}\",
    \"webhook_url\": \"${WEBHOOK_URL}\",
    \"webhook_verify_token\": \"${WEBHOOK_VERIFY_TOKEN}\",
    \"enable_booking_flow\": false,
    \"enable_interactive_responses\": true,
    \"auto_response_enabled\": true,
    \"short_response_mode\": true
  }"

echo ""
echo ""

# Step 2: Verify Webhook (simulate WhatsApp verification)
echo "Step 2: Testing webhook verification"
CHALLENGE="test_challenge_$(date +%s)"

curl -X GET "${API_BASE_URL}/api/whatsapp/webhook/${TENANT_ID}" \
  -G \
  -d "hub_mode=subscribe" \
  -d "hub_challenge=${CHALLENGE}" \
  -d "hub_verify_token=${WEBHOOK_VERIFY_TOKEN}"

echo ""
echo ""

# Step 3: Get Configuration
echo "Step 3: Retrieving WhatsApp configuration"
curl -X GET "${API_BASE_URL}/api/whatsapp/configure/${TENANT_ID}" \
  -H "Content-Type: application/json"

echo ""
echo ""

# Step 4: Health Check
echo "Step 4: Checking WhatsApp health"
curl -X GET "${API_BASE_URL}/api/whatsapp/health/${TENANT_ID}" \
  -H "Content-Type: application/json"

echo ""
echo ""

echo "==================================="
echo "Setup Complete!"
echo "==================================="
echo ""
echo "Next steps:"
echo "1. Go to WhatsApp Business Platform"
echo "2. Set webhook URL to: ${WEBHOOK_URL}"
echo "3. Set verify token to: ${WEBHOOK_VERIFY_TOKEN}"
echo "4. Test by sending a message to your business number"
echo "5. Check application logs for message processing"
echo ""
echo "For testing locally, use ngrok or similar tunnel:"
echo "  ngrok http 8000"
echo "  Then use the ngrok URL as WEBHOOK_URL"
echo ""
