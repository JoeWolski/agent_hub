# Agent Hub Frontend Demo Suite

This suite runs a real, two-phase Agent Hub frontend demo:

1. `plan` phase:
- launches a real `agent_hub`
- performs the scenario without recording
- writes a resolved script with measured timing observations

2. `record` phase:
- relaunches real `agent_hub`
- replays the generated script
- records the run to MP4 with real cursor movement and typing

The runner is scenario-driven:

- scenario file: `tools/demo/scenarios/frontend_default.json`
- action engine: reusable action handlers in `run_demo.mjs`
- failure diagnostics: screenshot + state dump under `tools/demo/output/failures/`

## Scenario coverage

The scripted demo includes:

- new project creation
- real image build progression to `Ready`
- multiple active chats in one project
- chat instruction typing for fake image + fake view + fake video preview
- fake image/view/video artifact publication to that real chat
- opening the fake video preview modal in the UI

## Requirements

- Docker daemon reachable from this environment
- Node 20+
- `xvfb`, `xdotool`, `ffmpeg`, `jq`

## Install

```bash
cd tools/demo
npm install
npx playwright install firefox
```

## Run

```bash
# Both phases (recommended)
cd tools/demo
npm run all

# Plan-only
npm run plan

# Validate-only (runs scenario without recording and without writing demo_script.json)
npm run validate

# Record-only (uses previously generated script)
npm run record
```

## Outputs

Outputs are written under `tools/demo/output/`:

- `demo_script.json`: resolved script and observed timing values
- `agent_hub_demo.mp4`: recorded demo
- `logs/`: per-phase process logs (`hub`, `xvfb`, `ffmpeg`)

Optional overrides:

```bash
node run_demo.mjs all \
  --scenario-file tools/demo/scenarios/frontend_default.json \
  --repo-url /path/to/repo \
  --project-name "Demo Project" \
  --theme dark \
  --port 8765 \
  --display :77 \
  --video-file output/custom_demo.mp4
```
