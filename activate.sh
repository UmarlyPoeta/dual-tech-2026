#!/bin/bash
export PATH=$(echo "$PATH" | tr ':' '\n' | grep -v '\.pyenv' | tr '\n' ':' | sed 's/:$//')
unset PYENV_ROOT PYENV_VERSION 2>/dev/null || true
source "/home/patryk/dual-tech-2026/venv/bin/activate"
echo "venv active: $(python3 --version) @ $(which python3)"
