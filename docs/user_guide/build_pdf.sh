#!/bin/bash
#
# Build PDF user guide from Markdown source using pandoc + LaTeX
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INPUT="$SCRIPT_DIR/tutorial.md"
OUTPUT="$SCRIPT_DIR/ClinicalDataVisualizer_UserGuide.pdf"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Check for pandoc
if ! command -v pandoc &> /dev/null; then
    echo -e "${RED}Error: pandoc is not installed.${NC}"
    echo "Install it with: brew install pandoc"
    exit 1
fi

# Check for a LaTeX engine
PDF_ENGINE=""
if command -v xelatex &> /dev/null; then
    PDF_ENGINE="xelatex"
elif command -v pdflatex &> /dev/null; then
    PDF_ENGINE="pdflatex"
else
    echo -e "${RED}Error: No LaTeX engine found (xelatex or pdflatex).${NC}"
    echo "Install BasicTeX with: brew install --cask basictex"
    echo "Then restart your terminal and run: sudo tlmgr update --self && sudo tlmgr install collection-fontsrecommended"
    exit 1
fi

echo -e "${GREEN}Building PDF user guide...${NC}"
echo "  Source:     $INPUT"
echo "  Output:     $OUTPUT"
echo "  PDF engine: $PDF_ENGINE"
echo ""

cd "$SCRIPT_DIR"

pandoc "$INPUT" \
    -o "$OUTPUT" \
    --pdf-engine="$PDF_ENGINE" \
    --resource-path="." \
    --syntax-highlighting=tango \
    -V colorlinks=true \
    -V linkcolor=blue \
    -V urlcolor=blue

echo ""
echo -e "${GREEN}PDF generated successfully: $OUTPUT${NC}"
