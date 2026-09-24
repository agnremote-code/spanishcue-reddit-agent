# SpanishCue Reddit Agent

Autonomous Reddit assistant for Spanish teachers, powered by a local Ollama model.

## Current mode

The agent is intentionally configured with `DRY_RUN=true`.

It is designed to:
- monitor a limited list of teaching/tutoring subreddits;
- ignore learners, students and unrelated platform discussions;
- only engage with posts relevant to Spanish teachers/tutors;
- avoid duplicate or substantially similar replies;
- respect subreddit rules;
- disclose affiliation whenever SpanishCue is mentioned;
- never vote, send unsolicited DMs, or bypass Reddit safeguards.

## Local setup

```bash
cd ~/spanishcue-reddit-agent
git pull origin main
zsh prepare_mac.sh
python agent.py --preflight
```

The real `.env` file is local-only and must never be committed.

## Configuration

Copy/edit `.env.example` as `.env`.

Important defaults:

```
OLLAMA_MODEL=alejandro:latest
SUBREDDITS=SpanishTeachers,Preply,iTalki,Cambly
DRY_RUN=true
MAX_COMMENTS_PER_DAY=3
MIN_HOURS_BETWEEN_COMMENTS=4
POST_AGE_HOURS=72
SCAN_LIMIT=60
```

## Tests

```bash
python agent.py --self-test
```

## After Reddit API approval

Add these values to the local `.env`:

```
REDDIT_CLIENT_ID=
REDDIT_CLIENT_SECRET=
REDDIT_REFRESH_TOKEN=
```

Then verify:

```bash
python agent.py --preflight
```

The output should show:
- Ollama: OK
- Reddit login: SpanishCue
- Reddit credentials: OK

Do not paste Reddit secrets into GitHub or chat.

## Automatic Mac scheduling

Once Reddit credentials are approved and verified:

```bash
zsh enable_agent.sh
```

This installs a macOS LaunchAgent that runs the agent once every 60 minutes.

It will remain non-posting while:

```
DRY_RUN=true
```

Check status/logs:

```bash
zsh status_agent.sh
```

Disable scheduling:

```bash
zsh disable_agent.sh
```

Logs are stored locally under `logs/` and are excluded from Git.

## Going live

Only after Reddit API approval, successful credential verification, and a clean dry-run review should `.env` be changed to:

```
DRY_RUN=false
```

The existing safeguards still apply:
- maximum 3 posted comments per UTC day;
- minimum 4 hours between posted comments;
- only recent posts;
- Spanish-teacher relevance threshold;
- subreddit rule check;
- duplicate/similarity blocking;
- explicit SpanishCue affiliation disclosure when relevant.
