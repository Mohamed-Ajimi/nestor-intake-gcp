# Research trace — offline UI fixture

From `frontend`, run:

```sh
npx vite --config tools/research-trace/vite.config.ts
```

Open `http://127.0.0.1:5188`. This renders the actual `RunFeed` component with local,
deterministic events. It has no application router, authentication or research API calls.
This fixture is not an application route and is not included in the normal production build.

Check question disclosures, original events, audit buttons, inactive state, legacy events,
English/Dutch/French, and desktop/mobile layouts. The audit panel is a local placeholder;
it does not test audit fetching or authorization. Data is illustrative, not a production run.

## Event contract

New `deep_research` events carry scalar `meta` fields:

- `trace_execution_id`: fresh per `run_angles` invocation, not a worker lease or run attempt.
- `trace_task_id`: stable within that invocation, including coverage retries.
- `trace_group_id`: explicit corroboration identity, or unique task identity if unavailable.
- `trace_question`, `provider`: display labels; never used as correlation keys.
- `trace_state`: queued, running, retrying, completed, restored, skipped or failed.
- `trace_attempt`: attempt within this task/invocation.
- `trace_total`: task count on the dispatch event only.

Queued records use the requested provider; started/finished records use the actual provider.
The pure projection orders by event sequence, deduplicates replay, keeps execution identities
separate, and rejects incomplete/mismatched task metadata. Original records remain accessible.
Progress counts outputs received (including restored outputs), not verified claims or report readiness.
Skipped/failed work never increases the received count. Missing outcomes are not invented.

Historical runs without these fields retain the original trace. No backfill or migration is
required. Both the frontend and engine changes must be deployed for newly executed work to
use grouping; this implementation task does not perform that deployment.

## Verification boundaries

Pure reducer tests cover concurrent completion, replay, retries, partial history and execution
identity. SSR tests exercise the real components, translations, escaped text, raw events and
audit affordances. Browser checks exercise disclosures, local audit interactions and narrow
layouts. None of these establish production delivery, provider behavior, large-feed performance
or the health of a running research job.
