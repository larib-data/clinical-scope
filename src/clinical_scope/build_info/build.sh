#!/bin/bash
#
# Build script for Clinical Scope
# Creates a standalone executable using PyInstaller
#

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Get script directory and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

# Configuration
SPEC_FILE="$SCRIPT_DIR/core_api.spec"
APP_NAME="ClinicalScope"

# Detect platform
detect_platform() {
    case "$(uname -s)" in
        Darwin*)
            case "$(uname -m)" in
                arm64) echo "macOS_arm" ;;
                x86_64) echo "macOS_intel" ;;
                *) echo "macOS_unknown" ;;
            esac
            ;;
        Linux*)
            echo "linux"
            ;;
        MINGW*|MSYS*|CYGWIN*)
            echo "windows"
            ;;
        *)
            echo "unknown"
            ;;
    esac
}

PLATFORM=$(detect_platform)
DIST_PATH="$PROJECT_ROOT/builded_app/$PLATFORM"

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  Clinical Scope - Build${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "Platform:    ${YELLOW}$PLATFORM${NC}"
echo -e "Project:     $PROJECT_ROOT"
echo -e "Spec file:   $SPEC_FILE"
echo -e "Output:      $DIST_PATH"
echo ""

# Check if pyinstaller is available
if ! command -v pyinstaller &> /dev/null; then
    echo -e "${RED}Error: PyInstaller not found.${NC}"
    echo "Install it with: pip install pyinstaller"
    exit 1
fi

# Check if spec file exists
if [ ! -f "$SPEC_FILE" ]; then
    echo -e "${RED}Error: Spec file not found: $SPEC_FILE${NC}"
    exit 1
fi

# Confirm build
read -p "Start build? [Y/n] " -n 1 -r
echo
if [[ $REPLY =~ ^[Nn]$ ]]; then
    echo "Build cancelled."
    exit 0
fi

echo ""
echo -e "${YELLOW}Building...${NC}"
echo ""

# Change to project root for consistent paths
cd "$PROJECT_ROOT"

# Create output directory if it doesn't exist
mkdir -p "$DIST_PATH"

# Run PyInstaller
pyinstaller "$SPEC_FILE" --clean --distpath "$DIST_PATH" --noconfirm

# Copy user guide PDF into the app bundle root (next to executable)
USER_GUIDE_PDF="$PROJECT_ROOT/docs/user_guide/ClinicalScope_UserGuide.pdf"
if [ -f "$USER_GUIDE_PDF" ]; then
    cp "$USER_GUIDE_PDF" "$DIST_PATH/$APP_NAME/"
    echo -e "${GREEN}User guide PDF copied to bundle.${NC}"
else
    echo -e "${YELLOW}Warning: User guide PDF not found at $USER_GUIDE_PDF${NC}"
    echo -e "${YELLOW}  Run docs/user_guide/build_pdf.sh to generate it first.${NC}"
fi

# Copy disclaimer and license into the app bundle root (next to executable)
DISCLAIMER_FILE="$PROJECT_ROOT/DISCLAIMER.txt"
if [ -f "$DISCLAIMER_FILE" ]; then
    cp "$DISCLAIMER_FILE" "$DIST_PATH/$APP_NAME/"
    echo -e "${GREEN}Disclaimer copied to bundle.${NC}"
else
    echo -e "${YELLOW}Warning: Disclaimer not found at $DISCLAIMER_FILE${NC}"
fi

LICENSE_FILE="$PROJECT_ROOT/LICENSE"
if [ -f "$LICENSE_FILE" ]; then
    cp "$LICENSE_FILE" "$DIST_PATH/$APP_NAME/"
    echo -e "${GREEN}License copied to bundle.${NC}"
else
    echo -e "${YELLOW}Warning: License not found at $LICENSE_FILE${NC}"
fi

# Copy template patient data structure into the app bundle root
TEMPLATE_FOLDER="$PROJECT_ROOT/example/template_patient_data_structure"
if [ -d "$TEMPLATE_FOLDER" ]; then
    cp -r "$TEMPLATE_FOLDER" "$DIST_PATH/$APP_NAME/"
    echo -e "${GREEN}Template patient data structure copied to bundle.${NC}"
else
    echo -e "${YELLOW}Warning: Template folder not found at $TEMPLATE_FOLDER${NC}"
fi

# Copy demo patient data into the app bundle
DEMO_DATABASE="$PROJECT_ROOT/example/demo_database"
if [ -d "$DEMO_DATABASE" ]; then
    cp -r "$DEMO_DATABASE" "$DIST_PATH/$APP_NAME/"
    rm -rf "$DIST_PATH/$APP_NAME/demo_database/demo_patient/clinical_scope_output"
    echo -e "${GREEN}Demo database copied to bundle.${NC}"
else
    echo -e "${YELLOW}Warning: Demo database folder not found at $DEMO_DATABASE${NC}"
fi

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  Build Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "Output location: ${YELLOW}$DIST_PATH/$APP_NAME${NC}"
echo ""

# Show how to run
case "$PLATFORM" in
    macOS*)
        echo "To run the app:"
        echo "  $DIST_PATH/$APP_NAME/$APP_NAME"
        ;;
    linux)
        echo "To run the app:"
        echo "  $DIST_PATH/$APP_NAME/$APP_NAME"
        ;;
    windows)
        echo "To run the app:"
        echo "  $DIST_PATH/$APP_NAME/$APP_NAME.exe"
        ;;
esac
