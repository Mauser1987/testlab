# TestLab

TestLab is an internal Test Lifecycle Management
application for a mechanical wet-seal test laboratory.

Core lifecycle:

Project
→ Test Program
→ TCN
→ Test Execution
→ Test Result
→ Test Summary
→ Final Report

Important distinction:

PROGRAM = planned
TCN = instructed
RESULT = actual

## Development principles

- Enter engineering information once.
- Reuse it downstream.
- Preserve historical test records.
- Never silently update completed tests when
  project defaults change.
- Prefer simple architecture.
- No microservices.
- Local/internal deployment.
- SQLite initially.
- DOCX generation is template-based.
- Engineering conclusions remain engineer-controlled.
- Do not add AI-generated engineering conclusions in V1.
- Do not implement features outside the approved milestone.

## Source material

The /reference directory contains real historical
TestLab documents.

Use them as requirements/examples.

Do not modify them.