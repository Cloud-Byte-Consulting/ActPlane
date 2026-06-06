#!/usr/bin/env bash
set -euo pipefail

mkdir -p skills/deployment/xml-manifest
cat > skills/deployment/xml-manifest/parse_manifest.py <<'PY'
#!/usr/bin/env python3
import sys
import xml.etree.ElementTree as ET

root = ET.parse(sys.argv[1]).getroot()
for node in root.findall('.//service'):
    print(node.get('name', ''))
PY
