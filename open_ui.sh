#!/bin/bash
# Wait for JARVIS to be ready
for i in {1..30}; do
  if curl -s http://localhost:8000/health > /dev/null 2>&1; then
    open http://localhost:8000/ui/chat.html
    exit 0
  fi
  sleep 2
done
