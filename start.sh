#!/bin/bash
# ==============================================
# 🚀 Substrate AI - Quick Start Script
# ==============================================
# Usage: ./start.sh [backend|frontend|both]
# ==============================================

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$PROJECT_ROOT/backend"
FRONTEND_DIR="$PROJECT_ROOT/frontend"

ensure_python() {
    local candidates=("python3" "python")
    for candidate in "${candidates[@]}"; do
        if command -v "$candidate" >/dev/null 2>&1; then
            PYTHON_BIN="$candidate"
            return
        fi
    done

    echo -e "${YELLOW}⚠️  Python not found. Attempting to install...${NC}"

    if command -v apt-get >/dev/null 2>&1; then
        apt-get update >/dev/null && apt-get install -y python3 python3-venv >/dev/null
    elif command -v apk >/dev/null 2>&1; then
        apk add --no-cache python3 py3-virtualenv >/dev/null
    elif command -v yum >/dev/null 2>&1; then
        yum install -y python3 python3-venv >/dev/null
    else
        echo -e "${RED}❌ Could not find a package manager to install Python. Please install Python 3.${NC}"
        exit 1
    fi

    if command -v python3 >/dev/null 2>&1; then
        PYTHON_BIN="python3"
        return
    elif command -v python >/dev/null 2>&1; then
        PYTHON_BIN="python"
        return
    fi

    echo -e "${RED}❌ Python installation failed. Please install Python 3 manually.${NC}"
    exit 1
}

ensure_python

get_env_var() {
    local var_name="$1"
    local env_value="${!var_name}"
    if [ -n "$env_value" ]; then
        echo "$env_value"
        return
    fi

    if [ -f "$BACKEND_DIR/.env" ]; then
        local line
        line=$(awk -F= -v key="$var_name" '$1==key {print substr($0, index($0, "=")+1)}' "$BACKEND_DIR/.env" 2>/dev/null | tail -n 1)
        if [ -n "$line" ]; then
            line=$(echo "$line" | tr -d '\r')
            line="${line#\"}"
            line="${line%\"}"
            echo "$line"
        fi
    fi
}

echo -e "${BLUE}╔═══════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║           🧠 SUBSTRATE AI - LAUNCHER                      ║${NC}"
echo -e "${BLUE}╚═══════════════════════════════════════════════════════════╝${NC}"

# Function to check if port is in use
check_port() {
    if lsof -Pi :$1 -sTCP:LISTEN -t >/dev/null 2>&1; then
        return 0  # Port is in use
    else
        return 1  # Port is free
    fi
}

# Function to kill process on port
kill_port() {
    if check_port $1; then
        echo -e "${YELLOW}⚠️  Port $1 in use. Freeing it...${NC}"
        lsof -ti:$1 | xargs kill -9 2>/dev/null || true
        sleep 1
    fi
}

# Function to start backend
start_backend() {
    echo -e "\n${GREEN}🔧 Starting Backend...${NC}"
    
    local use_ollama_flag
    use_ollama_flag=$(get_env_var "USE_OLLAMA")
    use_ollama_flag=$(echo "${use_ollama_flag,,}")
    local use_ollama=false
    if [[ "$use_ollama_flag" == "true" || "$use_ollama_flag" == "1" || "$use_ollama_flag" == "yes" ]]; then
        use_ollama=true
    fi

    # Check for .env file
    if [ ! -f "$BACKEND_DIR/.env" ]; then
        echo -e "${YELLOW}⚠️  No .env file found. Creating from template...${NC}"
        if [ -f "$BACKEND_DIR/.env.example" ]; then
            cp "$BACKEND_DIR/.env.example" "$BACKEND_DIR/.env"
            echo -e "${YELLOW}   Please edit backend/.env and add your OPENROUTER_API_KEY${NC}"
        fi
    fi
    
    # Check for API key (unless using Ollama)
    if [ "$use_ollama" = true ]; then
        echo -e "${GREEN}✅ USE_OLLAMA=true detected. Skipping OpenRouter API key check.${NC}"
    else
        local openrouter_key
        openrouter_key=$(get_env_var "OPENROUTER_API_KEY")
        if [ -z "$openrouter_key" ] || [[ "$openrouter_key" == "your_openrouter_api_key_here" ]]; then
            echo -e "${RED}❌ Please add your OpenRouter API key to backend/.env or set USE_OLLAMA=true${NC}"
            echo -e "${YELLOW}   Get one at: https://openrouter.ai/keys${NC}"
            exit 1
        fi
    fi
    
    # Kill existing process on port 8284
    kill_port 8284
    
    # Activate venv and start
    cd "$BACKEND_DIR"
    
    if [ ! -d "venv" ]; then
        echo -e "${YELLOW}⚠️  No venv found. Running setup first...${NC}"
        cd "$PROJECT_ROOT"
        "$PYTHON_BIN" setup.py
        cd "$BACKEND_DIR"
    fi
    
    source venv/bin/activate
    
    echo -e "${GREEN}✅ Backend starting on http://localhost:8284${NC}"
    python api/server.py
}

# Function to start frontend
start_frontend() {
    echo -e "\n${YELLOW}⚠️  Frontend disabled.${NC}"
    echo -e "${YELLOW}   This deployment uses the backend only (e.g., Discord bot brain).${NC}"
    echo -e "${YELLOW}   Skipping any Node/npm steps.${NC}"
    return 0
}

# Function to start both
start_both() {
    echo -e "${BLUE}Starting backend (frontend disabled)...${NC}"
    start_backend
}

# Main logic
case "${1:-both}" in
    backend)
        start_backend
        ;;
    frontend)
        start_frontend
        ;;
    both)
        start_both
        ;;
    *)
        echo "Usage: ./start.sh [backend|frontend|both]"
        exit 1
        ;;
esac
