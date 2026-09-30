#!/bin/bash
export QT_QPA_PLATFORM=offscreen HOME=/root
calamares -d 2>&1 | tail -30
echo "CALAMARES_EXIT=$?"
