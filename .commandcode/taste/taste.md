# Taste

## Communication
- User mixes Indonesian and English within one request (e.g. "add 1 more filter yang tidak mengalami kerugian (laba terus)"). Replies in English are fine, but expect code-switching and read Indonesian phrases literally — "laba terus" ("profit continuously") became the "No net loss" filter. Confidence: 0.9

## Tooling
- Frontend tests must be run with `NODE_ENV=test` (e.g. `$env:NODE_ENV='test'; npx vitest run`): the shell has a global `NODE_ENV=production`, which loads React's production build and makes every RTL test fail with `React.act is not a function`. Pre-existing — affects clean HEAD too, not just new changes. Confidence: 0.95
- Validation gate before declaring work done: frontend `npx vitest run` + `npx tsc -b` + `npx oxlint`, and backend `python -m pytest tests/ -q`; report all of the results. Confidence: 0.8

## Design
- Visual polish is a hard requirement, not a nice-to-have: the user bluntly rejects UI that looks off ("your style look shit... like ewww" about a vertical checkbox stack that towered over the neighbouring `h-10` filter selects). Controls must stay compact and consistent with the surrounding design language; expect terse, blunt criticism when they don't. Confidence: 0.75

## Workflow
- When tests fail, first check whether the failure pre-exists on clean HEAD (git stash → run → stash pop) before attributing it to the change at hand; still fix pre-existing failures if they sit on the feature's path (e.g. positional test indices shifted by a newly committed column). Confidence: 0.75
