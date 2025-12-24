#!/bin/bash
# Purpose: Install Lucid Vision Labs Arena SDK for ARM64 systems
# This script installs the Arena SDK in the openhsi_ros2 package directory
# for a self-contained ROS2 package structure.
#
# Usage:
#   cd /media/logic/USamsung/ros2_ws/src/openhsi_ros2
#   bash install_arena_sdk.sh
#
# Prerequisites:
#   - ArenaSDK_v0.1.78_Linux_ARM64.tar.gz in ~/Downloads
#   - arena_api-2.7.1-py3-none-any.zip in ~/Downloads
#
# Created: November 2025
# Updated for Arena SDK v0.1.78 and API v2.7.1

set -e  # Exit on any error

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
ARENA_SDK_VERSION="0.1.78"
ARENA_API_VERSION="2.7.1"
DOWNLOADS_DIR="$HOME/Downloads"
PACKAGE_DIR="$(pwd)"
SDK_INSTALL_DIR="${PACKAGE_DIR}/arena_sdk"

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Lucid Arena SDK Installation${NC}"
echo -e "${GREEN}========================================${NC}"

# Verify we're in the correct directory
if [[ ! -f "package.xml" ]] || [[ ! -d "openhsi_ros2" ]]; then
    echo -e "${RED}Error: Must run this script from the openhsi_ros2 package root directory${NC}"
    echo "Current directory: $(pwd)"
    exit 1
fi

# Check for required files
SDK_ARCHIVE="${DOWNLOADS_DIR}/ArenaSDK_v${ARENA_SDK_VERSION}_Linux_ARM64.tar.gz"
API_ARCHIVE="${DOWNLOADS_DIR}/arena_api-${ARENA_API_VERSION}-py3-none-any.zip"

if [[ ! -f "${SDK_ARCHIVE}" ]]; then
    echo -e "${RED}Error: SDK archive not found: ${SDK_ARCHIVE}${NC}"
    echo "Please download from: https://thinklucid.com/downloads-hub/"
    exit 1
fi

if [[ ! -f "${API_ARCHIVE}" ]]; then
    echo -e "${RED}Error: API archive not found: ${API_ARCHIVE}${NC}"
    echo "Please download from: https://thinklucid.com/downloads-hub/"
    exit 1
fi

echo -e "${GREEN}Found required archives:${NC}"
echo "  SDK: ${SDK_ARCHIVE}"
echo "  API: ${API_ARCHIVE}"

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
# NOTE: We do NOT run the bundled Arena_SDK_ARM64.conf script because it adds
# all of Metavision/lib to the system ldconfig without filtering. The Metavision/lib
# directory contains ~100 third-party libraries compiled for Ubuntu 22.04 that depend
# on libldap-2.5.so.0, libgeos, libgdal, etc. These conflict with Ubuntu 24.04 system
# libraries and break python3-opencv and other packages.
#
# However, libarena.so depends on libmetavision_sdk_core.so, which in turn requires
# the bundled OpenCV 4.0 and Intel TBB libraries. So we MUST include Metavision/lib
# in ldconfig, but we quarantine the conflicting third-party libraries by moving them
# to a disabled/ subfolder.
#
# Our approach:
# - lib64: Core Arena SDK libraries (libarena*.so, GenTL_LUCID.cti)
# - GenICam: GenICam transport layer libraries (ARM64 path)
# - ffmpeg: Video encoding support (optional, but harmless)
# - Metavision/lib: Metavision SDK (with third-party libs quarantined)
#
# Libraries kept in Metavision/lib:
# - libmetavision_sdk_*.so* (core Metavision SDK)
# - libopencv*.so* (OpenCV 4.0 - required by Metavision, doesn't conflict with system OpenCV 4.6)
# - libtbb*.so* (Intel TBB - required by OpenCV)
#
# See README.md section "Arena SDK Ubuntu 24.04 Compatibility" for details.

echo -e "\n${YELLOW}Installing Arena SDK system libraries...${NC}"
echo "This step requires sudo privileges to install shared libraries."
cd "${SDK_INSTALL_DIR}/ArenaSDK"

CONF_FILE="Arena_SDK.conf"
CURRENTDIR="${PWD}"

echo -e "${YELLOW}Configuring Arena SDK library paths...${NC}"
echo ""
echo "Adding the following paths to /etc/ld.so.conf.d/${CONF_FILE}:"
echo "  ${CURRENTDIR}/lib64"
echo "  ${CURRENTDIR}/GenICam/library/lib/Linux64_ARM"
echo "  ${CURRENTDIR}/ffmpeg"
echo "  ${CURRENTDIR}/Metavision/lib"
echo ""
echo -e "${YELLOW}NOTE: Metavision/lib is included (libarena.so depends on it)${NC}"
echo -e "${YELLOW}      Conflicting third-party libraries will be quarantined for Ubuntu 24.04 compatibility${NC}"

# Remove existing conf file if present (clean install)
sudo rm -f /etc/ld.so.conf.d/${CONF_FILE}

# Create new conf file with required paths (including Metavision for libarena.so dependency)
sudo sh -c "echo '${CURRENTDIR}/lib64' > /etc/ld.so.conf.d/${CONF_FILE}"
sudo sh -c "echo '${CURRENTDIR}/GenICam/library/lib/Linux64_ARM' >> /etc/ld.so.conf.d/${CONF_FILE}"
sudo sh -c "echo '${CURRENTDIR}/ffmpeg' >> /etc/ld.so.conf.d/${CONF_FILE}"
sudo sh -c "echo '${CURRENTDIR}/Metavision/lib' >> /etc/ld.so.conf.d/${CONF_FILE}"

# Quarantine conflicting third-party libraries in Metavision/lib
# These libraries were compiled for Ubuntu 22.04 and conflict with Ubuntu 24.04 system libs
# We keep only: libmetavision_sdk_* (core SDK), libopencv* (OpenCV 4.0), libtbb* (Intel TBB)
echo -e "\n${YELLOW}Quarantining conflicting Metavision third-party libraries...${NC}"
METAVISION_LIB="${CURRENTDIR}/Metavision/lib"
if [[ -d "${METAVISION_LIB}" ]]; then
    mkdir -p "${METAVISION_LIB}/disabled"
    cd "${METAVISION_LIB}"
    QUARANTINE_COUNT=0
    for f in *.so*; do
        [[ -e "$f" ]] || continue  # Skip if no matches
        case "$f" in
            libmetavision_sdk*|libopencv*|libtbb*)
                # Keep these libraries - required by Arena SDK
                ;;
            *)
                mv "$f" disabled/
                ((QUARANTINE_COUNT++))
                ;;
        esac
    done
    echo -e "${GREEN}Quarantined ${QUARANTINE_COUNT} conflicting libraries to Metavision/lib/disabled/${NC}"
    cd "${SDK_INSTALL_DIR}/ArenaSDK"
fi

# Install runtime dependencies
echo -e "\n${YELLOW}Installing runtime dependencies...${NC}"
sudo apt-get -y install libibverbs1 librdmacm1

# Configure network buffer sizes for GigE Vision performance
echo -e "\n${YELLOW}Configuring network buffer sizes...${NC}"
if ! grep -q "net.core.rmem_default=33554432" /etc/sysctl.conf 2>/dev/null; then
    sudo sh -c "echo 'net.core.rmem_default=33554432' >> /etc/sysctl.conf"
fi
if ! grep -q "net.core.rmem_max=33554432" /etc/sysctl.conf 2>/dev/null; then
    sudo sh -c "echo 'net.core.rmem_max=33554432' >> /etc/sysctl.conf"
fi

# Update library cache
sudo ldconfig

echo -e "${GREEN}SDK libraries installed (Ubuntu 24.04 compatible)${NC}"

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
export LD_LIBRARY_PATH="${ARENA_SDK_DIR}/GenICam/library/lib/Linux64_ARM:${LD_LIBRARY_PATH}"
export LD_LIBRARY_PATH="${ARENA_SDK_DIR}/ffmpeg:${LD_LIBRARY_PATH}"
export LD_LIBRARY_PATH="${ARENA_SDK_DIR}/Metavision/lib:${LD_LIBRARY_PATH}"

# GenICam environment variables
export GENICAM_GENTL64_PATH="${ARENA_SDK_DIR}/GenICam/library/lib/Linux64_ARM"
export GENICAM_ROOT_V3_1="${ARENA_SDK_DIR}/GenICam"

echo "Arena SDK environment configured (ARM64)"
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

The SDK has been installed using the \`install_arena_sdk.sh\` script.

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
- Target Platform: Linux ARM64 (Ubuntu 18.04/20.04/22.04)

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
echo "2. Add to your ~/.bashrc for automatic setup:"
echo "   echo 'source ${SDK_INSTALL_DIR}/setup_arena.sh' >> ~/.bashrc"
echo ""
echo "3. Update your ROS2 launch file to source the setup script"
echo ""
echo -e "${GREEN}SDK is now ready for use with openhsi_ros2!${NC}"