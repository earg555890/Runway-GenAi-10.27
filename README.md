# Runway

An AI agent for college students: projects their money forward through the semester across separate sources, explains why with evidence, and drafts actions for them to approve. Built for the GenAI Works Open Agent Hackathon (Track 2).

## Setup

Requires Python 3.11+ and Java 8+ (for the Zetaris JDBC driver). Developed on Windows on ARM with Python 3.14 (x64 build) and Temurin JDK 21.

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # macOS/Linux: .venv/bin/python
cp .env.example .env                                       # then fill in the values
```

`.env` holds the NVIDIA API key, model ID and base URL, and the Zetaris JDBC URL, user, password, jar path and `JAVA_HOME`. It is gitignored.

Zetaris itself runs separately in Docker (see the Zetaris bundle's README); it must be up for the Zetaris data path.

## Checks

```bash
.venv/Scripts/python nemotron_smoke_test.py   # NVIDIA Nemotron: chat, tool calling, reasoning on/off
```
