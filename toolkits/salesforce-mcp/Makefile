SHELL := /bin/bash

setup:
	@echo "Installing uv python package manager..."
	curl -LsSf https://astral.sh/uv/install.sh | sh
	@echo "✅ Installed uv. Please run: source ~/.bashrc or restart your shell"
	@echo "🔁 Then re-run: make setup"
	@echo "Initializing uv..."
	uv init
	@echo "Creating virtual environment..."
	uv venv
	@echo "Installing required packages..."
	pip install -r requirements.txt
	@echo "Setup complete. Dependencies successfully installed."

server:
	@echo "✅ Ensure that you have run 'make setup' first"
	@echo "Starting MCP server..."
	DANGEROUSLY_OMIT_AUTH=true PYTHONPATH=.:../../../../ uv run mcp dev app/server.py

help:
	@echo "Available commands:"
	@echo "  make setup  - Install uv and dependencies"
	@echo "  make server - Run the MCP server"
	@echo "  make help   - Show this help message"
