#!/bin/bash

# Configuration
PRIMARY_URL="http://localhost:8080"
SECONDARY_URL="http://localhost:8082"

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

function run_scenario() {
    local target_name=$1
    local base_url=$2
    local scenario_path=$3
    
    echo -e "${BLUE}Running $target_name...${NC}"
    echo "URL: $base_url$scenario_path"
    curl -s "$base_url$scenario_path"
    echo -e "\n${GREEN}Done!${NC}"
}

while true; do
    echo "=========================================="
    echo "Interactive Agent Scenario Generator"
    echo "=========================================="
    
    # Select Agent
    echo "Select Agent:"
    echo "1) Primary Agent (Port 8080)"
    echo "2) Secondary Agent (Port 8082)"
    echo "3) Both Agents"
    echo "q) Quit"
    read -p "Choice: " agent_choice
    
    if [ "$agent_choice" == "q" ]; then
        echo "Exiting."
        exit 0
    fi

    # Select Scenario
    echo "------------------------------------------"
    echo "Select Scenario:"
    echo "1) Fanout (High concurrency)"
    echo "2) Chain (Sequential steps)"
    echo "3) Retry Storm (Simulates errors & retries)"
    echo "4) Stream (Token streaming + bg load)"
    echo "5) DAG (Diamond pattern)"
    echo "6) ReAct (Thought/Act loop)"
    echo "7) Human (Long delay)"
    echo "8) RAG (Large payload)"
    read -p "Choice: " scenario_choice

    path=""
    case $scenario_choice in
        1) path="/run?scenario=fanout&fanout=50&concurrency=10&delay_ms=50" ;;
        2) path="/run?scenario=chain&depth=40&delay_ms=30" ;;
        3) path="/run?scenario=retry&fanout=80&concurrency=20&delay_ms=60&error_rate=0.2&max_retries=4" ;;
        4) path="/stream?duration_s=5&tool_delay_ms=300&background_fanout=80" ;;
        5) path="/run?scenario=dag&fanout=20&delay_ms=40" ;;
        6) path="/run?scenario=react&max_steps=5&delay_ms=50" ;;
        7) path="/run?scenario=human&human_delay_s=2.0" ;;
        8) path="/run?scenario=rag&rag_chunks=10&rag_chunk_size_kb=2&delay_ms=30" ;;
        *) echo "Invalid scenario choice"; continue ;;
    esac

    # Execute
    case $agent_choice in
        1)
            run_scenario "Primary Agent" "$PRIMARY_URL" "$path"
            ;;
        2)
            run_scenario "Secondary Agent" "$SECONDARY_URL" "$path"
            ;;
        3)
            # Run in parallelish or sequential? Sequential is easier to read output, parallel is faster.
            # Let's do sequential for clarity, users can just open two terminals if they want parallel spam.
            run_scenario "Primary Agent" "$PRIMARY_URL" "$path"
            run_scenario "Secondary Agent" "$SECONDARY_URL" "$path"
            ;;
        *)
            echo "Invalid agent choice"
            ;;
    esac
    
    echo -e "\nPress Enter to continue..."
    read
done
