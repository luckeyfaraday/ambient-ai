# Example: Open-Source Model Video Scenario

The user watches several videos about an open-source AI model.

Ambient AI captures cheap signals:

- YouTube titles and URLs.
- Transcript artifact references.
- Browser tabs for the model repository and docs.
- Local hardware profile references when available.
- Related Athena or repo activity.

Reducers collapse repeated tabs and video events into a candidate thread such as `local-model-viability`. The thread preserves event ids, URLs, and artifact paths instead of embedding large transcripts.

Hermes reads the 5 minute cron prompt and decides whether there is useful work:

- Compare published model requirements with the user's hardware profile.
- Search local context for prior attempts or preferences.
- Run only small, reversible local checks if the model or tooling is already present.
- Draft a short viability note with evidence.
- Ask before huge downloads, spending, external API use, repo changes, or long-running jobs.

If the work is useful and complete, Hermes reports the result. If there is nothing actionable, Hermes stays silent.
