#!/bin/bash

# Snow Traffic - Setup Script
# This script helps set up the development environment

set -e

echo "========================================="
echo "Snow Traffic - Setup"
echo "========================================="
echo ""

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if running on macOS or Linux
if [[ "$OSTYPE" == "darwin"* ]]; then
    OS="macOS"
else
    OS="Linux"
fi

echo "Detected OS: $OS"
echo ""

# 1. Set up Python environment for poller
echo -e "${GREEN}[1/5] Setting up Python environment for poller...${NC}"
cd poller

if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo "✓ Virtual environment created"
else
    echo "✓ Virtual environment already exists"
fi

source venv/bin/activate
pip install -r requirements.txt > /dev/null 2>&1
echo "✓ Python dependencies installed"

cd ..
echo ""

# 2. Set up Python environment for API
echo -e "${GREEN}[2/5] Setting up Python environment for API...${NC}"
cd api

if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo "✓ Virtual environment created"
else
    echo "✓ Virtual environment already exists"
fi

source venv/bin/activate
pip install -r requirements.txt > /dev/null 2>&1
echo "✓ Python dependencies installed"

cd ..
echo ""

# 3. Initialize database
echo -e "${GREEN}[3/5] Initializing database...${NC}"
cd poller
source venv/bin/activate
python init_db.py
cd ..
echo ""

# 4. Set up Node environment for UI
echo -e "${GREEN}[4/5] Setting up Node.js environment for UI...${NC}"
cd ui

if [ ! -d "node_modules" ]; then
    npm install > /dev/null 2>&1
    echo "✓ Node dependencies installed"
else
    echo "✓ Node dependencies already installed"
fi

cd ..
echo ""

# 5. Check for Google Maps API key
echo -e "${GREEN}[5/5] Checking environment configuration...${NC}"

if [ -z "$GOOGLE_MAPS_API_KEY" ]; then
    echo -e "${YELLOW}WARNING: GOOGLE_MAPS_API_KEY environment variable not set${NC}"
    echo ""
    echo "To complete setup:"
    echo "1. Get an API key from: https://console.cloud.google.com/apis/credentials"
    echo "2. Enable the Routes API in your Google Cloud project"
    echo "3. Create a .env file in the project root:"
    echo "   echo 'GOOGLE_MAPS_API_KEY=your_key_here' > .env"
    echo ""
else
    echo "✓ GOOGLE_MAPS_API_KEY is set"
fi

echo ""
echo "========================================="
echo "Setup complete!"
echo "========================================="
echo ""
echo "Next steps:"
echo ""
echo "1. Set up your Google Maps API key in .env"
echo ""
echo "2. Test the poller:"
echo "   cd poller"
echo "   source venv/bin/activate"
echo "   python poll_gmaps.py"
echo ""
echo "3. Run the API:"
echo "   cd ../api"
echo "   source venv/bin/activate"
echo "   python main.py"
echo ""
echo "4. Run the UI (in a new terminal):"
echo "   cd ui"
echo "   npm run dev"
echo ""
echo "========================================="
