#!/bin/bash
# Purpose: Install Lucid Vision Labs Arena SDK for x86_64 systems
# This script installs the Arena SDK in the openhsi_ros2 package directory
# for a self-contained ROS2 package structure.
#
# Usage:
#   cd /media/logic/USamsung/ros2_ws/src/openhsi_ros2
#   bash install_arena_sdk_x64.sh
#
# Prerequisites:
#   - ArenaSDK_v0.1.104_Linux_x64.tar.gz in ~/Downloads
#   - arena_api-2.7.1-py3-none-any.zip in ~/Downloads
#
# Created: November 2025
# Updated for Arena SDK v0.1.104 and API v2.7.1

set -e  # Exit on any error

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
ARENA_SDK_VERSION="0.1.104"
ARENA_API_VERSION="2.7.1"
DOWNLOADS_DIR="$HOME/Downloads"
PACKAGE_DIR="$(pwd)"
SDK_INSTALL_DIR="${PACKAGE_DIR}/arena_sdk"

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Lucid Arena SDK Installation (x86_64)${NC}"
echo -e "${GREEN}========================================${NC}"

# Verify system architecture
ARCH=$(uname -m)
if [[ "${ARCH}" != "x86_64" ]]; then
    echo -e "${RED}Error: This script is for x86_64 systems${NC}"
    echo "Detected architecture: ${ARCH}"
    echo "For ARM64 systems, use install_arena_sdk_ARM.sh"
    exit 1
fi

# Verify we're in the correct directory
if [[ ! -f "package.xml" ]] || [[ ! -d "openhsi_ros2" ]]; then
    echo -e "${RED}Error: Must run this script from the openhsi_ros2 package root directory${NC}"
    echo "Current directory: $(pwd)"
    exit 1
fi

# Check for required files
SDK_ARCHIVE="${DOWNLOADS_DIR}/ArenaSDK_v${ARENA_SDK_VERSION}_Linux_x64.tar.gz"
API_ARCHIVE="${DOWNLOADS_DIR}/arena_api-${ARENA_API_VERSION}-py3-none-any.zip"

if [[ ! -f "${SDK_ARCHIVE}" ]]; then
    echo -e "${RED}Error: SDK archive not found: ${SDK_ARCHIVE}${NC}"
    echo "Please download 'ArenaSDK_v${ARENA_SDK_VERSION}_Linux_x64.tar.gz' from:"
    echo "https://thinklucid.com/downloads-hub/"
    echo ""
    echo "Look for: Arena SDK - x64 Ubuntu 18.04/20.04/22.04/24.04, 64-bit"
    exit 1
fi

if [[ ! -f "${API_ARCHIVE}" ]]; then
    echo -e "${RED}Error: API archive not found: ${API_ARCHIVE}${NC}"
    echo "Please download 'arena_api-${ARENA_API_VERSION}-py3-none-any.zip' from:"
    echo "https://thinklucid.com/downloads-hub/"
    echo ""
    echo "Look for: Arena Python Package"
    exit 1
fi

echo -e "${GREEN}Found required archives:${NC}"
echo "  SDK: ${SDK_ARCHIVE}"
echo "  API: ${API_ARCHIVE}"

# Check if old installation exists
if [[ -d "${SDK_INSTALL_DIR}" ]]; then
    echo -e "\n${YELLOW}Warning: Existing SDK installation found${NC}"
    read -p "Remove existing installation and continue? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        rm -rf "${SDK_INSTALL_DIR}"
        echo -e "${GREEN}Removed old installation${NC}"
    else
        echo -e "${RED}Installation cancelled${NC}"
        exit 1
    fi
fi

# Create SDK directory structure
echo -e "\n${YELLOW}Creating SDK directory structure...${NC}"
mkdir -p "${SDK_INSTALL_DIR}"
mkdir -p "${SDK_INSTALL_DIR}/ArenaSDK"
mkdir -p "${SDK_INSTALL_DIR}/ArenaAPI"

# Extract Arena SDK
echo -e "\n${YELLOW}Extracting Arena SDK...${NC}"
tar -xzf "${SDK_ARCHIVE}" -C "${SDK_INSTALL_DIR}/ArenaSDK" --strip-components=1
echo -e "${GREEN}SDK extracted to: ${SDK_INSTALL_DIR}/ArenaSDK${NC}"

# Extract Arena Python API
echo -e "\n${YELLOW}Extracting Arena Python API...${NC}"
unzip -q "${API_ARCHIVE}" -d "${SDK_INSTALL_DIR}/ArenaAPI"
echo -e "${GREEN}API extracted to: ${SDK_INSTALL_DIR}/ArenaAPI${NC}"

# Install SDK libraries (requires sudo)
echo -e "\n${YELLOW}Installing Arena SDK system libraries...${NC}"
echo "This step requires sudo privileges to install shared libraries."
cd "${SDK_INSTALL_DIR}/ArenaSDK"

if [[ -f "Arena_SDK_Linux_x64.conf" ]]; then
    sudo sh Arena_SDK_Linux_x64.conf
    echo -e "${GREEN}SDK libraries installed${NC}"
else
    echo -e "${RED}Warning: Arena_SDK_Linux_x64.conf not found${NC}"
    echo "Available .conf files:"
    ls -1 *.conf 2>/dev/null || echo "None found"
fi

# Install Python package
echo -e "\n${YELLOW}Installing Arena Python API...${NC}"
cd "${SDK_INSTALL_DIR}/ArenaAPI"
WHEEL_FILE=$(ls arena_api-*.whl 2>/dev/null | head -n 1)

if [[ -n "${WHEEL_FILE}" ]]; then
    # Try with --break-system-packages first (for newer Ubuntu versions)
    # Fall back to standard install if that flag is not supported (older pip)
    if pip3 install --user --break-system-packages "${WHEEL_FILE}" 2>/dev/null; then
        echo -e "${GREEN}Python API installed: ${WHEEL_FILE}${NC}"
    else
        echo -e "${YELLOW}Retrying without --break-system-packages flag...${NC}"
        pip3 install --user "${WHEEL_FILE}"
        echo -e "${GREEN}Python API installed: ${WHEEL_FILE}${NC}"
    fi
else
    echo -e "${RED}Error: Could not find .whl file in ${SDK_INSTALL_DIR}/ArenaAPI${NC}"
    exit 1
fi

# Create environment setup script
cd "${PACKAGE_DIR}"
cat > "${SDK_INSTALL_DIR}/setup_arena.sh" << 'EOF'
#!/bin/bash
# Source this script to set up Arena SDK environment variables
# Usage: source arena_sdk/setup_arena.sh

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
ARENA_SDK_DIR="${SCRIPT_DIR}/ArenaSDK"

# Add Arena SDK library paths
export LD_LIBRARY_PATH="${ARENA_SDK_DIR}/lib64:${LD_LIBRARY_PATH}"
export LD_LIBRARY_PATH="${ARENA_SDK_DIR}/GenICam/library/lib/Linux64_x64:${LD_LIBRARY_PATH}"
export LD_LIBRARY_PATH="${ARENA_SDK_DIR}/ffmpeg:${LD_LIBRARY_PATH}"

# GenICam environment variables
export GENICAM_GENTL64_PATH="${ARENA_SDK_DIR}/GenICam/library/lib/Linux64_x64"
export GENICAM_ROOT_V3_1="${ARENA_SDK_DIR}/GenICam"

echo "Arena SDK environment configured (x86_64)"
echo "SDK Path: ${ARENA_SDK_DIR}"
EOF

chmod +x "${SDK_INSTALL_DIR}/setup_arena.sh"

# Create .gitignore for SDK directory
cat > "${SDK_INSTALL_DIR}/.gitignore" << 'EOF'
# Ignore all SDK files except setup scripts
*
!.gitignore
!setup_arena.sh
!README.md
EOF

# Create README in SDK directory
cat > "${SDK_INSTALL_DIR}/README.md" << EOF
# Lucid Vision Labs Arena SDK

This directory contains the Lucid Arena SDK v${ARENA_SDK_VERSION} and Python API v${ARENA_API_VERSION}.

## Installation

The SDK has been installed using the \`install_arena_sdk_x64.sh\` script.

## Usage

Before running the ROS2 node, source the environment setup:

\`\`\`bash
source arena_sdk/setup_arena.sh
\`\`\`

Or add this to your ROS2 launch file.

## Directory Structure

- \`ArenaSDK/\` - Core SDK libraries and binaries
- \`ArenaAPI/\` - Python API wheel package
- \`setup_arena.sh\` - Environment setup script

## Version Information

- Arena SDK: v${ARENA_SDK_VERSION}
- Arena Python API: v${ARENA_API_VERSION}
- Target Platform: Linux x86_64 (Ubuntu 18.04/20.04/22.04/24.04)

## Documentation

Visit: https://thinklucid.com/downloads-hub/
EOF

echo -e "\n${GREEN}========================================${NC}"
echo -e "${GREEN}Installation Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "SDK installed in: ${SDK_INSTALL_DIR}"
echo ""
echo -e "${YELLOW}Next steps:${NC}"
echo "1. Source the environment setup:"
echo "   source ${SDK_INSTALL_DIR}/setup_arena.sh"
echo ""
echo "2. Test the installation:"
echo "   python3 -c 'import arena_api; print(\"Arena API version:\", arena_api.__version__)'"
echo ""
echo "3. Add to your ~/.bashrc for automatic setup (optional):"
echo "   echo 'source ${SDK_INSTALL_DIR}/setup_arena.sh' >> ~/.bashrc"
echo ""
echo "4. Update your ROS2 launch file to source the setup script"
echo ""
echo -e "${GREEN}SDK is now ready for use with openhsi_ros2!${NC}"
