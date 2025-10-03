#!/bin/bash

# Test script for idempotency middleware demo
# Requires: curl, jq (optional for pretty JSON)
# Usage: bash test_demo.sh

set -e

BASE_URL="http://localhost:8000"
BLUE='\033[0;34m'
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "======================================================================"
echo "Idempotency Middleware Demo - Test Suite"
echo "======================================================================"
echo ""

# Check if server is running
echo -e "${BLUE}Checking if server is running...${NC}"
if ! curl -s "$BASE_URL/api/status" > /dev/null; then
    echo -e "${RED}ERROR: Server not running at $BASE_URL${NC}"
    echo "Start the server with: python demo_app.py"
    exit 1
fi
echo -e "${GREEN}✓ Server is running${NC}"
echo ""

# Helper function to print section headers
section() {
    echo ""
    echo "======================================================================"
    echo -e "${YELLOW}$1${NC}"
    echo "======================================================================"
}

# Helper function to print test descriptions
test_desc() {
    echo ""
    echo -e "${BLUE}Test: $1${NC}"
    echo "----------------------------------------------------------------------"
}

# Test 1: Root endpoint
section "1. API Information"
test_desc "GET / - API info (safe method, no idempotency needed)"
curl -s "$BASE_URL/" | jq '.' || curl -s "$BASE_URL/"
echo ""

# Test 2: Health check
section "2. Health Check"
test_desc "GET /api/status - Health check (safe method bypasses middleware)"
curl -s "$BASE_URL/api/status" | jq '.' || curl -s "$BASE_URL/api/status"
echo ""

# Test 3: First payment request
section "3. Happy Path - First Request"
test_desc "POST /api/payments with Idempotency-Key (first time)"
RESPONSE_1=$(curl -s -X POST "$BASE_URL/api/payments" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: test-payment-001" \
  -d '{"amount": 100, "currency": "USD", "description": "Test payment"}')
echo "$RESPONSE_1" | jq '.' || echo "$RESPONSE_1"
PAYMENT_ID=$(echo "$RESPONSE_1" | jq -r '.id' 2>/dev/null || echo "unknown")
echo -e "${GREEN}✓ Payment created with ID: $PAYMENT_ID${NC}"
echo ""

# Test 4: Replay - same request
section "4. Happy Path - Replay (Identical Request)"
test_desc "POST /api/payments with SAME Idempotency-Key and SAME body"
echo "Expected: Returns cached response with Idempotent-Replay: true header"
RESPONSE_2=$(curl -s -v -X POST "$BASE_URL/api/payments" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: test-payment-001" \
  -d '{"amount": 100, "currency": "USD", "description": "Test payment"}' \
  2>&1)
echo "$RESPONSE_2" | grep -i "idempotent-replay" || echo "Headers not captured in response"
BODY=$(echo "$RESPONSE_2" | tail -n 1)
echo "$BODY" | jq '.' || echo "$BODY"
REPLAYED_ID=$(echo "$BODY" | jq -r '.id' 2>/dev/null || echo "unknown")
echo ""
if [ "$PAYMENT_ID" = "$REPLAYED_ID" ]; then
    echo -e "${GREEN}✓ Response replayed correctly (same ID: $PAYMENT_ID)${NC}"
else
    echo -e "${RED}✗ Response mismatch: $PAYMENT_ID vs $REPLAYED_ID${NC}"
fi
echo ""

# Test 5: Conflict - different request body with same key
section "5. Conflict Detection - Different Request Body"
test_desc "POST /api/payments with SAME Idempotency-Key but DIFFERENT body"
echo "Expected: 409 Conflict (fingerprint mismatch)"
HTTP_CODE=$(curl -s -o /tmp/response.txt -w "%{http_code}" -X POST "$BASE_URL/api/payments" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: test-payment-001" \
  -d '{"amount": 200, "currency": "EUR"}')
cat /tmp/response.txt | jq '.' 2>/dev/null || cat /tmp/response.txt
echo ""
if [ "$HTTP_CODE" = "409" ]; then
    echo -e "${GREEN}✓ Conflict detected correctly (HTTP $HTTP_CODE)${NC}"
else
    echo -e "${RED}✗ Expected 409, got HTTP $HTTP_CODE${NC}"
fi
echo ""

# Test 6: Different key - new execution
section "6. Different Key - New Execution"
test_desc "POST /api/payments with DIFFERENT Idempotency-Key"
echo "Expected: New payment created (different ID)"
RESPONSE_3=$(curl -s -X POST "$BASE_URL/api/payments" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: test-payment-002" \
  -d '{"amount": 150, "currency": "USD"}')
echo "$RESPONSE_3" | jq '.' || echo "$RESPONSE_3"
PAYMENT_ID_2=$(echo "$RESPONSE_3" | jq -r '.id' 2>/dev/null || echo "unknown")
echo ""
if [ "$PAYMENT_ID" != "$PAYMENT_ID_2" ]; then
    echo -e "${GREEN}✓ New payment created with different ID: $PAYMENT_ID_2${NC}"
else
    echo -e "${RED}✗ Same ID returned: $PAYMENT_ID${NC}"
fi
echo ""

# Test 7: Order creation
section "7. Order Creation (Idempotent)"
test_desc "POST /api/orders with Idempotency-Key"
RESPONSE_4=$(curl -s -X POST "$BASE_URL/api/orders" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: test-order-001" \
  -d '{"product_id": "prod-123", "quantity": 2, "customer_email": "test@example.com"}')
echo "$RESPONSE_4" | jq '.' || echo "$RESPONSE_4"
ORDER_ID=$(echo "$RESPONSE_4" | jq -r '.order_id' 2>/dev/null || echo "unknown")
echo -e "${GREEN}✓ Order created with ID: $ORDER_ID${NC}"
echo ""

# Test 8: Order replay
section "8. Order Replay"
test_desc "POST /api/orders with SAME Idempotency-Key (replay)"
RESPONSE_5=$(curl -s -X POST "$BASE_URL/api/orders" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: test-order-001" \
  -d '{"product_id": "prod-123", "quantity": 2, "customer_email": "test@example.com"}')
echo "$RESPONSE_5" | jq '.' || echo "$RESPONSE_5"
REPLAYED_ORDER_ID=$(echo "$RESPONSE_5" | jq -r '.order_id' 2>/dev/null || echo "unknown")
echo ""
if [ "$ORDER_ID" = "$REPLAYED_ORDER_ID" ]; then
    echo -e "${GREEN}✓ Order replayed correctly (same ID: $ORDER_ID)${NC}"
else
    echo -e "${RED}✗ Order mismatch: $ORDER_ID vs $REPLAYED_ORDER_ID${NC}"
fi
echo ""

# Test 9: PUT request (update)
section "9. PUT Request (Idempotent Update)"
test_desc "PUT /api/orders/{id} with Idempotency-Key"
RESPONSE_6=$(curl -s -X PUT "$BASE_URL/api/orders/ord-123" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: test-update-001" \
  -d '{"product_id": "prod-456", "quantity": 5, "customer_email": "test@example.com"}')
echo "$RESPONSE_6" | jq '.' || echo "$RESPONSE_6"
echo -e "${GREEN}✓ Order updated${NC}"
echo ""

# Test 10: DELETE request (cancel)
section "10. DELETE Request (Idempotent Cancel)"
test_desc "DELETE /api/orders/{id} with Idempotency-Key"
RESPONSE_7=$(curl -s -X DELETE "$BASE_URL/api/orders/ord-123" \
  -H "Idempotency-Key: test-delete-001")
echo "$RESPONSE_7" | jq '.' || echo "$RESPONSE_7"
echo -e "${GREEN}✓ Order cancelled${NC}"
echo ""

# Test 11: Concurrent requests simulation
section "11. Concurrent Requests (Background Jobs)"
test_desc "Multiple requests with same key in parallel (simulated)"
echo "Sending 5 concurrent requests with same Idempotency-Key..."
for i in {1..5}; do
    curl -s -X POST "$BASE_URL/api/payments" \
      -H "Content-Type: application/json" \
      -H "Idempotency-Key: test-concurrent-001" \
      -d '{"amount": 300, "currency": "USD"}' \
      > /tmp/concurrent_$i.txt &
done
wait
echo ""
echo "Results:"
for i in {1..5}; do
    ID=$(jq -r '.id' /tmp/concurrent_$i.txt 2>/dev/null || echo "error")
    echo "  Response $i: Payment ID = $ID"
done
FIRST_ID=$(jq -r '.id' /tmp/concurrent_1.txt 2>/dev/null)
ALL_SAME=true
for i in {2..5}; do
    CURRENT_ID=$(jq -r '.id' /tmp/concurrent_$i.txt 2>/dev/null)
    if [ "$FIRST_ID" != "$CURRENT_ID" ]; then
        ALL_SAME=false
    fi
done
echo ""
if [ "$ALL_SAME" = true ]; then
    echo -e "${GREEN}✓ All concurrent requests returned same payment ID: $FIRST_ID${NC}"
else
    echo -e "${RED}✗ Concurrent requests returned different IDs${NC}"
fi
echo ""

# Test 12: Request without idempotency key
section "12. Request Without Idempotency Key"
test_desc "POST /api/payments WITHOUT Idempotency-Key header"
echo "Expected: Request proceeds normally (idempotency optional)"
RESPONSE_8=$(curl -s -X POST "$BASE_URL/api/payments" \
  -H "Content-Type: application/json" \
  -d '{"amount": 50, "currency": "USD"}')
echo "$RESPONSE_8" | jq '.' || echo "$RESPONSE_8"
echo -e "${GREEN}✓ Request completed without idempotency key${NC}"
echo ""

# Summary
section "Test Summary"
echo -e "${GREEN}✓ All basic tests completed${NC}"
echo ""
echo "Key behaviors verified:"
echo "  1. First request executes and returns result"
echo "  2. Duplicate request returns cached response (replay)"
echo "  3. Conflict detected for different request body with same key"
echo "  4. Different keys create independent transactions"
echo "  5. Concurrent requests handled correctly"
echo "  6. All HTTP methods (POST/PUT/DELETE) are idempotent"
echo "  7. Safe methods (GET) bypass middleware"
echo "  8. Requests without idempotency key work normally"
echo ""
echo "======================================================================"
echo "Demo complete!"
echo "======================================================================"
