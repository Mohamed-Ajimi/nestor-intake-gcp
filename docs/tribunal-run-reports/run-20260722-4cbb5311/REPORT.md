# Tribunal Deep-Research Run — Forensic Report

**Nestor research_run_id:** `4cbb5311-9f5f-4504-84bb-b0dda2aedf48` (intake `e08620c5`)
**Tribunal run_id:** `9c84e5a9-1bb9-4b6e-a3ce-2351eda9df63`
**Date:** 2026-07-22 · **Outcome:** `completed` (green) · **Subject:** LUKOIL BeNeLux strategy (dynamic pricing, coffee, Germany-entry 2027)

This report is written for an engineer improving the Tribunal engine. It reconstructs the entire run from the 228 per-call audit records plus the worker log. The headline finding: **the run completed and produced a report, but its adversarial fact-checking arm (the group skeptic) was effectively non-functional** — a serialization bug silently discarded 24 groups' verdicts, and an Anthropic usage-limit wall killed the last ~776 skeptic attempts. The "green" status masks near-total loss of verification.

---

## 1. Run overview

| Field | Value |
|---|---|
| Triggered | 2026-07-22 **11:16:46Z** |
| Worker claimed | **11:16:57Z** (`run_claimed engine=tribunal`) |
| Terminal `completed` | **12:04:28Z** (~48 min wall-clock) |
| Engine | `nestor_pulse_sdk` `TribunalPipeline` (delegator variant, quick task 260721-twy) |
| Worker image | `tribunal-worker:20260721-220957` |
| Dispatch | `dispatch_runner: engine=tribunal -> TribunalPipeline (explicit A/B arm)` |
| Delegation / tribunal model | `claude-sonnet-4-6` |
| Deep-research models | Google `deep-research-max-preview-04-2026` (primary) + Claude `claude-sonnet-4-6 +web` (high-stakes redundancy) |
| Labeling / grouping / distill model | `gemini-2.5-flash` |
| Synthesis / conflict / scrub model | `gemini-2.5-pro` |
| LLM calls audited | **228** |

### Fetching the raw records

All 228 audit bodies (one JSON per LLM call: `{run_id, audit_id, seq, provider, model, request, response}`) live permanently in GCS:

```
gs://project-cb01b861-cb4a-438d-b9a-nestor-audit/runs/9c84e5a9-1bb9-4b6e-a3ce-2351eda9df63/
# list with mtimes (mtime is the only reliable ordering key — see note below):
gcloud storage ls -l gs://project-cb01b861-cb4a-438d-b9a-nestor-audit/runs/9c84e5a9-1bb9-4b6e-a3ce-2351eda9df63/ \
  --project=project-cb01b861-cb4a-438d-b9a
```

Human-readable per-call extracts are in [`calls/`](calls/) (`NNN-<provider>-<model>.md`, full input + output). Machine-readable index: [`index.json`](index.json). Group/claim inventory: [`GROUPS.md`](GROUPS.md).

> **Ordering caveat.** Every record stores `seq = 0` (the per-run sequence counter was not populated in this run's bodies — itself a minor audit defect). This report orders calls by **GCS object mtime** (the write time of the audit body), which tracks call-completion order closely. Anthropic bodies carry no timestamp of their own; Google bodies carry an HTTP `date` header. The `seq` column in the tables below is this report's mtime-derived ordinal, not the engine's.

---

## 2. Call index (228 calls)

Grouped totals first, then the full ordered table.

| Stage | Calls | Model |
|---|---|---|
| intake (delegator) | 2 | anthropic/claude-sonnet-4-6 |
| deep_research | 6 | 3x google DR-max + 3x claude redundancy |
| distill (claim extraction) | 8 | gemini-2.5-flash |
| grouping (entity\|attribute tagging) | 30 | gemini-2.5-flash |
| group_skeptic (verify) | 176 | anthropic/claude-sonnet-4-6 |
| conflict (contradiction detection) | 1 | gemini-2.5-pro |
| scrub (remove discredited passages) | 1 | gemini-2.5-pro |
| synthesize (report sections) | 4 | gemini-2.5-pro |
| **Total** | **228** | |

Full ordered index (time is `HH:MM:SS` of GCS write; output size in KB; tokens in/out):

| seq | time | provider/model | stage | out | tok in/out | extract |
|---|---|---|---|---|---|---|
| 1 | 11:17:45 | anthropic/sonnet46 | intake | 7KB | 3771/2048 | [file](calls/001-anthropic-claude-sonnet-4-6.md) |
| 2 | 11:18:24 | anthropic/sonnet46 | intake | 7KB | 5407/2048 | [file](calls/002-anthropic-claude-sonnet-4-6.md) |
| 3 | 11:23:06 | anthropic/sonnet46 | deep_research | 33KB | 0/0 | [file](calls/003-anthropic-claude-sonnet-4-6.md) |
| 4 | 11:23:39 | anthropic/sonnet46 | deep_research | 37KB | 0/0 | [file](calls/004-anthropic-claude-sonnet-4-6.md) |
| 5 | 11:27:35 | anthropic/sonnet46 | deep_research | 27KB | 0/0 | [file](calls/005-anthropic-claude-sonnet-4-6.md) |
| 6 | 11:28:13 | google/DR-max | deep_research | 53KB | 0/0 | [file](calls/006-google-deep-research-max-preview-04-2026.md) |
| 7 | 11:30:17 | google/DR-max | deep_research | 71KB | 0/0 | [file](calls/007-google-deep-research-max-preview-04-2026.md) |
| 8 | 11:34:30 | google/DR-max | deep_research | 75KB | 0/0 | [file](calls/008-google-deep-research-max-preview-04-2026.md) |
| 9 | 11:35:26 | google/g2.5-flash | distill | 54KB | 25478/13987 | [file](calls/009-google-gemini-2.5-flash.md) |
| 10 | 11:35:51 | google/g2.5-flash | distill | 79KB | 11360/20677 | [file](calls/010-google-gemini-2.5-flash.md) |
| 11 | 11:36:08 | google/g2.5-flash | distill | 74KB | 26491/25638 | [file](calls/011-google-gemini-2.5-flash.md) |
| 12 | 11:36:11 | google/g2.5-flash | distill | 43KB | 9625/11996 | [file](calls/012-google-gemini-2.5-flash.md) |
| 13 | 11:36:51 | google/g2.5-flash | distill | 52KB | 26210/14632 | [file](calls/013-google-gemini-2.5-flash.md) |
| 14 | 11:37:00 | google/g2.5-flash | distill | 42KB | 7957/12088 | [file](calls/014-google-gemini-2.5-flash.md) |
| 15 | 11:38:33 | google/g2.5-flash | distill | 239KB | 9481/65535 | [file](calls/015-google-gemini-2.5-flash.md) |
| 16 | 11:40:00 | google/g2.5-flash | distill | 235KB | 11409/65535 | [file](calls/016-google-gemini-2.5-flash.md) |
| 17 | 11:40:02 | google/g2.5-flash | grouping | 3KB | 1678/401 | [file](calls/017-google-gemini-2.5-flash.md) |
| 18 | 11:40:02 | google/g2.5-flash | grouping | 3KB | 1453/397 | [file](calls/018-google-gemini-2.5-flash.md) |
| 19 | 11:40:03 | google/g2.5-flash | grouping | 3KB | 1637/466 | [file](calls/019-google-gemini-2.5-flash.md) |
| 20 | 11:40:04 | google/g2.5-flash | grouping | 4KB | 1655/666 | [file](calls/020-google-gemini-2.5-flash.md) |
| 21 | 11:40:05 | google/g2.5-flash | grouping | 3KB | 1425/402 | [file](calls/021-google-gemini-2.5-flash.md) |
| 22 | 11:40:06 | google/g2.5-flash | grouping | 4KB | 1644/642 | [file](calls/022-google-gemini-2.5-flash.md) |
| 23 | 11:40:06 | google/g2.5-flash | grouping | 3KB | 1486/440 | [file](calls/023-google-gemini-2.5-flash.md) |
| 24 | 11:40:06 | google/g2.5-flash | grouping | 3KB | 1393/593 | [file](calls/024-google-gemini-2.5-flash.md) |
| 25 | 11:40:08 | google/g2.5-flash | grouping | 4KB | 1505/568 | [file](calls/025-google-gemini-2.5-flash.md) |
| 26 | 11:40:09 | google/g2.5-flash | grouping | 3KB | 1391/513 | [file](calls/026-google-gemini-2.5-flash.md) |
| 27 | 11:40:09 | google/g2.5-flash | grouping | 3KB | 1558/521 | [file](calls/027-google-gemini-2.5-flash.md) |
| 28 | 11:40:10 | google/g2.5-flash | grouping | 3KB | 1531/586 | [file](calls/028-google-gemini-2.5-flash.md) |
| 29 | 11:40:11 | google/g2.5-flash | grouping | 3KB | 1474/362 | [file](calls/029-google-gemini-2.5-flash.md) |
| 30 | 11:40:12 | google/g2.5-flash | grouping | 3KB | 1378/418 | [file](calls/030-google-gemini-2.5-flash.md) |
| 31 | 11:40:12 | google/g2.5-flash | grouping | 3KB | 1556/528 | [file](calls/031-google-gemini-2.5-flash.md) |
| 32 | 11:40:12 | google/g2.5-flash | grouping | 3KB | 1438/407 | [file](calls/032-google-gemini-2.5-flash.md) |
| 33 | 11:40:13 | google/g2.5-flash | grouping | 3KB | 1393/409 | [file](calls/033-google-gemini-2.5-flash.md) |
| 34 | 11:40:15 | google/g2.5-flash | grouping | 3KB | 1332/446 | [file](calls/034-google-gemini-2.5-flash.md) |
| 35 | 11:40:15 | google/g2.5-flash | grouping | 3KB | 1379/411 | [file](calls/035-google-gemini-2.5-flash.md) |
| 36 | 11:40:15 | google/g2.5-flash | grouping | 3KB | 1493/427 | [file](calls/036-google-gemini-2.5-flash.md) |
| 37 | 11:40:16 | google/g2.5-flash | grouping | 3KB | 1406/459 | [file](calls/037-google-gemini-2.5-flash.md) |
| 38 | 11:40:17 | google/g2.5-flash | grouping | 3KB | 1335/429 | [file](calls/038-google-gemini-2.5-flash.md) |
| 39 | 11:40:17 | google/g2.5-flash | grouping | 3KB | 1317/349 | [file](calls/039-google-gemini-2.5-flash.md) |
| 40 | 11:40:18 | google/g2.5-flash | grouping | 3KB | 1375/349 | [file](calls/040-google-gemini-2.5-flash.md) |
| 41 | 11:40:18 | google/g2.5-flash | grouping | 3KB | 1383/489 | [file](calls/041-google-gemini-2.5-flash.md) |
| 42 | 11:40:19 | google/g2.5-flash | grouping | 3KB | 1379/366 | [file](calls/042-google-gemini-2.5-flash.md) |
| 43 | 11:40:20 | google/g2.5-flash | grouping | 3KB | 1351/465 | [file](calls/043-google-gemini-2.5-flash.md) |
| 44 | 11:40:20 | google/g2.5-flash | grouping | 2KB | 362/30 | [file](calls/044-google-gemini-2.5-flash.md) |
| 45 | 11:40:21 | google/g2.5-flash | grouping | 3KB | 1300/569 | [file](calls/045-google-gemini-2.5-flash.md) |
| 46 | 11:40:21 | google/g2.5-flash | grouping | 3KB | 1407/587 | [file](calls/046-google-gemini-2.5-flash.md) |
| 47 | 11:40:40 | anthropic/sonnet46 | group_skeptic | 86KB | 70282/623 | [file](calls/047-anthropic-claude-sonnet-4-6.md) |
| 48 | 11:40:42 | anthropic/sonnet46 | group_skeptic | 59KB | 40583/689 | [file](calls/048-anthropic-claude-sonnet-4-6.md) |
| 49 | 11:40:43 | anthropic/sonnet46 | group_skeptic | 57KB | 38958/727 | [file](calls/049-anthropic-claude-sonnet-4-6.md) |
| 50 | 11:40:44 | anthropic/sonnet46 | group_skeptic | 64KB | 39317/860 | [file](calls/050-anthropic-claude-sonnet-4-6.md) |
| 51 | 11:40:45 | anthropic/sonnet46 | group_skeptic | 80KB | 47713/732 | [file](calls/051-anthropic-claude-sonnet-4-6.md) |
| 52 | 11:40:50 | anthropic/sonnet46 | group_skeptic | 83KB | 46313/1136 | [file](calls/052-anthropic-claude-sonnet-4-6.md) |
| 53 | 11:41:04 | anthropic/sonnet46 | group_skeptic | 11125KB | 225172/754 | [file](calls/053-anthropic-claude-sonnet-4-6.md) |
| 54 | 11:41:21 | anthropic/sonnet46 | group_skeptic | 11178KB | 274076/1907 | [file](calls/054-anthropic-claude-sonnet-4-6.md) |
| 55 | 11:41:46 | anthropic/sonnet46 | group_skeptic | 64KB | 42876/1064 | [file](calls/055-anthropic-claude-sonnet-4-6.md) |
| 56 | 11:41:48 | anthropic/sonnet46 | group_skeptic | 71KB | 45593/983 | [file](calls/056-anthropic-claude-sonnet-4-6.md) |
| 57 | 11:41:48 | anthropic/sonnet46 | group_skeptic | 95KB | 76337/761 | [file](calls/057-anthropic-claude-sonnet-4-6.md) |
| 58 | 11:41:49 | anthropic/sonnet46 | group_skeptic | 94KB | 76825/899 | [file](calls/058-anthropic-claude-sonnet-4-6.md) |
| 59 | 11:41:54 | anthropic/sonnet46 | group_skeptic | 109KB | 62095/1220 | [file](calls/059-anthropic-claude-sonnet-4-6.md) |
| 60 | 11:41:55 | anthropic/sonnet46 | group_skeptic | 87KB | 81806/1305 | [file](calls/060-anthropic-claude-sonnet-4-6.md) |
| 61 | 11:41:58 | anthropic/sonnet46 | group_skeptic | 100KB | 80494/1036 | [file](calls/061-anthropic-claude-sonnet-4-6.md) |
| 62 | 11:42:02 | anthropic/sonnet46 | group_skeptic | 70KB | 46549/1504 | [file](calls/062-anthropic-claude-sonnet-4-6.md) |
| 63 | 11:42:26 | anthropic/sonnet46 | group_skeptic | 65KB | 46855/917 | [file](calls/063-anthropic-claude-sonnet-4-6.md) |
| 64 | 11:42:27 | anthropic/sonnet46 | group_skeptic | 73KB | 47962/864 | [file](calls/064-anthropic-claude-sonnet-4-6.md) |
| 65 | 11:42:33 | anthropic/sonnet46 | group_skeptic | 11143KB | 230877/603 | [file](calls/065-anthropic-claude-sonnet-4-6.md) |
| 66 | 11:42:35 | anthropic/sonnet46 | group_skeptic | 74KB | 42619/845 | [file](calls/066-anthropic-claude-sonnet-4-6.md) |
| 67 | 11:42:36 | anthropic/sonnet46 | group_skeptic | 78KB | 47781/1385 | [file](calls/067-anthropic-claude-sonnet-4-6.md) |
| 68 | 11:42:42 | anthropic/sonnet46 | group_skeptic | 11168KB | 265218/963 | [file](calls/068-anthropic-claude-sonnet-4-6.md) |
| 69 | 11:42:45 | anthropic/sonnet46 | group_skeptic | 103KB | 82716/1741 | [file](calls/069-anthropic-claude-sonnet-4-6.md) |
| 70 | 11:42:46 | anthropic/sonnet46 | group_skeptic | 84KB | 70997/916 | [file](calls/070-anthropic-claude-sonnet-4-6.md) |
| 71 | 11:43:03 | anthropic/sonnet46 | group_skeptic | 67KB | 44238/629 | [file](calls/071-anthropic-claude-sonnet-4-6.md) |
| 72 | 11:43:05 | anthropic/sonnet46 | group_skeptic | 63KB | 43069/729 | [file](calls/072-anthropic-claude-sonnet-4-6.md) |
| 73 | 11:43:06 | anthropic/sonnet46 | group_skeptic | 64KB | 44662/782 | [file](calls/073-anthropic-claude-sonnet-4-6.md) |
| 74 | 11:43:12 | anthropic/sonnet46 | group_skeptic | 94KB | 50817/778 | [file](calls/074-anthropic-claude-sonnet-4-6.md) |
| 75 | 11:43:18 | anthropic/sonnet46 | group_skeptic | 68KB | 45515/1116 | [file](calls/075-anthropic-claude-sonnet-4-6.md) |
| 76 | 11:43:18 | anthropic/sonnet46 | group_skeptic | 88KB | 74453/1197 | [file](calls/076-anthropic-claude-sonnet-4-6.md) |
| 77 | 11:43:23 | anthropic/sonnet46 | group_skeptic | 97KB | 51232/1571 | [file](calls/077-anthropic-claude-sonnet-4-6.md) |
| 78 | 11:43:40 | anthropic/sonnet46 | group_skeptic | 11170KB | 261669/1749 | [file](calls/078-anthropic-claude-sonnet-4-6.md) |
| 79 | 11:43:51 | anthropic/sonnet46 | group_skeptic | 46KB | 20290/386 | [file](calls/079-anthropic-claude-sonnet-4-6.md) |
| 80 | 11:44:00 | anthropic/sonnet46 | group_skeptic | 79KB | 47769/760 | [file](calls/080-anthropic-claude-sonnet-4-6.md) |
| 81 | 11:44:10 | anthropic/sonnet46 | group_skeptic | 116KB | 142713/1019 | [file](calls/081-anthropic-claude-sonnet-4-6.md) |
| 82 | 11:44:13 | anthropic/sonnet46 | group_skeptic | 95KB | 87454/1337 | [file](calls/082-anthropic-claude-sonnet-4-6.md) |
| 83 | 11:44:20 | anthropic/sonnet46 | group_skeptic | 70KB | 46017/1556 | [file](calls/083-anthropic-claude-sonnet-4-6.md) |
| 84 | 11:44:22 | anthropic/sonnet46 | group_skeptic | 122KB | 162076/1562 | [file](calls/084-anthropic-claude-sonnet-4-6.md) |
| 85 | 11:44:24 | anthropic/sonnet46 | group_skeptic | 11170KB | 450997/1231 | [file](calls/085-anthropic-claude-sonnet-4-6.md) |
| 86 | 11:44:32 | anthropic/sonnet46 | group_skeptic | 11178KB | 272527/1739 | [file](calls/086-anthropic-claude-sonnet-4-6.md) |
| 87 | 11:44:51 | anthropic/sonnet46 | group_skeptic | 49KB | 41362/647 | [file](calls/087-anthropic-claude-sonnet-4-6.md) |
| 88 | 11:44:59 | anthropic/sonnet46 | group_skeptic | 76KB | 43799/1114 | [file](calls/088-anthropic-claude-sonnet-4-6.md) |
| 89 | 11:45:00 | anthropic/sonnet46 | group_skeptic | 105KB | 75278/1110 | [file](calls/089-anthropic-claude-sonnet-4-6.md) |
| 90 | 11:45:03 | anthropic/sonnet46 | group_skeptic | 123KB | 80902/1164 | [file](calls/090-anthropic-claude-sonnet-4-6.md) |
| 91 | 11:45:09 | anthropic/sonnet46 | group_skeptic | 95KB | 81015/1317 | [file](calls/091-anthropic-claude-sonnet-4-6.md) |
| 92 | 11:45:09 | anthropic/sonnet46 | group_skeptic | 127KB | 83360/1210 | [file](calls/092-anthropic-claude-sonnet-4-6.md) |
| 93 | 11:45:12 | anthropic/sonnet46 | group_skeptic | 117KB | 125712/1431 | [file](calls/093-anthropic-claude-sonnet-4-6.md) |
| 94 | 11:45:16 | anthropic/sonnet46 | group_skeptic | 71KB | 45719/1417 | [file](calls/094-anthropic-claude-sonnet-4-6.md) |
| 95 | 11:45:30 | anthropic/sonnet46 | group_skeptic | 48KB | 20873/546 | [file](calls/095-anthropic-claude-sonnet-4-6.md) |
| 96 | 11:45:35 | anthropic/sonnet46 | group_skeptic | 66KB | 41198/756 | [file](calls/096-anthropic-claude-sonnet-4-6.md) |
| 97 | 11:45:36 | anthropic/sonnet46 | group_skeptic | 66KB | 40746/732 | [file](calls/097-anthropic-claude-sonnet-4-6.md) |
| 98 | 11:45:42 | anthropic/sonnet46 | group_skeptic | 108KB | 81617/969 | [file](calls/098-anthropic-claude-sonnet-4-6.md) |
| 99 | 11:45:46 | anthropic/sonnet46 | group_skeptic | 63KB | 43269/1209 | [file](calls/099-anthropic-claude-sonnet-4-6.md) |
| 100 | 11:45:47 | anthropic/sonnet46 | group_skeptic | 123KB | 106776/998 | [file](calls/100-anthropic-claude-sonnet-4-6.md) |
| 101 | 11:45:49 | anthropic/sonnet46 | group_skeptic | 106KB | 105136/1085 | [file](calls/101-anthropic-claude-sonnet-4-6.md) |
| 102 | 11:45:53 | anthropic/sonnet46 | group_skeptic | 125KB | 117430/1194 | [file](calls/102-anthropic-claude-sonnet-4-6.md) |
| 103 | 11:46:15 | anthropic/sonnet46 | group_skeptic | 83KB | 63576/803 | [file](calls/103-anthropic-claude-sonnet-4-6.md) |
| 104 | 11:46:15 | anthropic/sonnet46 | group_skeptic | 74KB | 47310/757 | [file](calls/104-anthropic-claude-sonnet-4-6.md) |
| 105 | 11:46:17 | anthropic/sonnet46 | group_skeptic | 68KB | 42528/904 | [file](calls/105-anthropic-claude-sonnet-4-6.md) |
| 106 | 11:46:19 | anthropic/sonnet46 | group_skeptic | 110KB | 113768/858 | [file](calls/106-anthropic-claude-sonnet-4-6.md) |
| 107 | 11:46:27 | anthropic/sonnet46 | group_skeptic | 71KB | 48430/1309 | [file](calls/107-anthropic-claude-sonnet-4-6.md) |
| 108 | 11:46:30 | anthropic/sonnet46 | group_skeptic | 105KB | 132105/1339 | [file](calls/108-anthropic-claude-sonnet-4-6.md) |
| 109 | 11:46:33 | anthropic/sonnet46 | group_skeptic | 67KB | 66354/1536 | [file](calls/109-anthropic-claude-sonnet-4-6.md) |
| 110 | 11:47:30 | anthropic/sonnet46 | group_skeptic | 9422KB | 877497/1660 | [file](calls/110-anthropic-claude-sonnet-4-6.md) |
| 111 | 11:47:45 | anthropic/sonnet46 | group_skeptic | 22KB | 14103/535 | [file](calls/111-anthropic-claude-sonnet-4-6.md) |
| 112 | 11:47:51 | anthropic/sonnet46 | group_skeptic | 79KB | 70791/755 | [file](calls/112-anthropic-claude-sonnet-4-6.md) |
| 113 | 11:47:51 | anthropic/sonnet46 | group_skeptic | 72KB | 42153/750 | [file](calls/113-anthropic-claude-sonnet-4-6.md) |
| 114 | 11:47:52 | anthropic/sonnet46 | group_skeptic | 56KB | 39435/964 | [file](calls/114-anthropic-claude-sonnet-4-6.md) |
| 115 | 11:47:54 | anthropic/sonnet46 | group_skeptic | 613KB | 57348/816 | [file](calls/115-anthropic-claude-sonnet-4-6.md) |
| 116 | 11:47:56 | anthropic/sonnet46 | group_skeptic | 43KB | 19300/1304 | [file](calls/116-anthropic-claude-sonnet-4-6.md) |
| 117 | 11:48:07 | anthropic/sonnet46 | group_skeptic | 94KB | 140422/1054 | [file](calls/117-anthropic-claude-sonnet-4-6.md) |
| 118 | 11:48:59 | anthropic/sonnet46 | group_skeptic | 9424KB | 904660/1791 | [file](calls/118-anthropic-claude-sonnet-4-6.md) |
| 119 | 11:49:18 | anthropic/sonnet46 | group_skeptic | 51KB | 21659/722 | [file](calls/119-anthropic-claude-sonnet-4-6.md) |
| 120 | 11:49:28 | anthropic/sonnet46 | group_skeptic | 74KB | 45794/959 | [file](calls/120-anthropic-claude-sonnet-4-6.md) |
| 121 | 11:49:32 | anthropic/sonnet46 | group_skeptic | 115KB | 83059/1198 | [file](calls/121-anthropic-claude-sonnet-4-6.md) |
| 122 | 11:49:33 | anthropic/sonnet46 | group_skeptic | 100KB | 76724/1294 | [file](calls/122-anthropic-claude-sonnet-4-6.md) |
| 123 | 11:49:33 | anthropic/sonnet46 | group_skeptic | 90KB | 70409/1405 | [file](calls/123-anthropic-claude-sonnet-4-6.md) |
| 124 | 11:49:46 | anthropic/sonnet46 | group_skeptic | 115KB | 111481/1560 | [file](calls/124-anthropic-claude-sonnet-4-6.md) |
| 125 | 11:49:53 | anthropic/sonnet46 | group_skeptic | 1050KB | 154903/1852 | [file](calls/125-anthropic-claude-sonnet-4-6.md) |
| 126 | 11:49:54 | anthropic/sonnet46 | group_skeptic | 782KB | 171304/1673 | [file](calls/126-anthropic-claude-sonnet-4-6.md) |
| 127 | 11:50:08 | anthropic/sonnet46 | group_skeptic | 49KB | 22529/504 | [file](calls/127-anthropic-claude-sonnet-4-6.md) |
| 128 | 11:50:09 | anthropic/sonnet46 | group_skeptic | 46KB | 21809/598 | [file](calls/128-anthropic-claude-sonnet-4-6.md) |
| 129 | 11:50:10 | anthropic/sonnet46 | group_skeptic | 41KB | 20122/634 | [file](calls/129-anthropic-claude-sonnet-4-6.md) |
| 130 | 11:50:13 | anthropic/sonnet46 | group_skeptic | 50KB | 22871/721 | [file](calls/130-anthropic-claude-sonnet-4-6.md) |
| 131 | 11:50:17 | anthropic/sonnet46 | group_skeptic | 259KB | 68345/832 | [file](calls/131-anthropic-claude-sonnet-4-6.md) |
| 132 | 11:50:17 | anthropic/sonnet46 | group_skeptic | 86KB | 51973/821 | [file](calls/132-anthropic-claude-sonnet-4-6.md) |
| 133 | 11:50:24 | anthropic/sonnet46 | group_skeptic | 97KB | 70733/1112 | [file](calls/133-anthropic-claude-sonnet-4-6.md) |
| 134 | 11:50:27 | anthropic/sonnet46 | group_skeptic | 78KB | 50209/1085 | [file](calls/134-anthropic-claude-sonnet-4-6.md) |
| 135 | 11:50:44 | anthropic/sonnet46 | group_skeptic | 77KB | 49331/694 | [file](calls/135-anthropic-claude-sonnet-4-6.md) |
| 136 | 11:50:48 | anthropic/sonnet46 | group_skeptic | 77KB | 49527/873 | [file](calls/136-anthropic-claude-sonnet-4-6.md) |
| 137 | 11:50:50 | anthropic/sonnet46 | group_skeptic | 76KB | 44408/774 | [file](calls/137-anthropic-claude-sonnet-4-6.md) |
| 138 | 11:50:50 | anthropic/sonnet46 | group_skeptic | 87KB | 50993/988 | [file](calls/138-anthropic-claude-sonnet-4-6.md) |
| 139 | 11:50:51 | anthropic/sonnet46 | group_skeptic | 91KB | 78168/1165 | [file](calls/139-anthropic-claude-sonnet-4-6.md) |
| 140 | 11:50:57 | anthropic/sonnet46 | group_skeptic | 99KB | 82751/988 | [file](calls/140-anthropic-claude-sonnet-4-6.md) |
| 141 | 11:50:58 | anthropic/sonnet46 | group_skeptic | 97KB | 83484/1305 | [file](calls/141-anthropic-claude-sonnet-4-6.md) |
| 142 | 11:50:58 | anthropic/sonnet46 | group_skeptic | 82KB | 73958/1290 | [file](calls/142-anthropic-claude-sonnet-4-6.md) |
| 143 | 11:51:18 | anthropic/sonnet46 | group_skeptic | 50KB | 20640/830 | [file](calls/143-anthropic-claude-sonnet-4-6.md) |
| 144 | 11:51:25 | anthropic/sonnet46 | group_skeptic | 57KB | 64243/1080 | [file](calls/144-anthropic-claude-sonnet-4-6.md) |
| 145 | 11:51:30 | anthropic/sonnet46 | group_skeptic | 85KB | 52505/1273 | [file](calls/145-anthropic-claude-sonnet-4-6.md) |
| 146 | 11:51:31 | anthropic/sonnet46 | group_skeptic | 102KB | 77119/876 | [file](calls/146-anthropic-claude-sonnet-4-6.md) |
| 147 | 11:51:33 | anthropic/sonnet46 | group_skeptic | 109KB | 109525/1187 | [file](calls/147-anthropic-claude-sonnet-4-6.md) |
| 148 | 11:51:42 | anthropic/sonnet46 | group_skeptic | 118KB | 117311/1690 | [file](calls/148-anthropic-claude-sonnet-4-6.md) |
| 149 | 11:51:45 | anthropic/sonnet46 | group_skeptic | 100KB | 75992/1640 | [file](calls/149-anthropic-claude-sonnet-4-6.md) |
| 150 | 11:51:54 | anthropic/sonnet46 | group_skeptic | 11136KB | 231748/1651 | [file](calls/150-anthropic-claude-sonnet-4-6.md) |
| 151 | 11:52:09 | anthropic/sonnet46 | group_skeptic | 37KB | 21603/728 | [file](calls/151-anthropic-claude-sonnet-4-6.md) |
| 152 | 11:52:20 | anthropic/sonnet46 | group_skeptic | 57KB | 45847/758 | [file](calls/152-anthropic-claude-sonnet-4-6.md) |
| 153 | 11:52:24 | anthropic/sonnet46 | group_skeptic | 2366KB | 82349/953 | [file](calls/153-anthropic-claude-sonnet-4-6.md) |
| 154 | 11:52:24 | anthropic/sonnet46 | group_skeptic | 61KB | 82435/1218 | [file](calls/154-anthropic-claude-sonnet-4-6.md) |
| 155 | 11:52:25 | anthropic/sonnet46 | group_skeptic | 75KB | 50737/1175 | [file](calls/155-anthropic-claude-sonnet-4-6.md) |
| 156 | 11:52:32 | anthropic/sonnet46 | group_skeptic | 219KB | 70974/1133 | [file](calls/156-anthropic-claude-sonnet-4-6.md) |
| 157 | 11:52:32 | anthropic/sonnet46 | group_skeptic | 62KB | 44569/1236 | [file](calls/157-anthropic-claude-sonnet-4-6.md) |
| 158 | 11:52:47 | anthropic/sonnet46 | group_skeptic | 88KB | 135138/1864 | [file](calls/158-anthropic-claude-sonnet-4-6.md) |
| 159 | 11:53:02 | anthropic/sonnet46 | group_skeptic | 64KB | 42827/475 | [file](calls/159-anthropic-claude-sonnet-4-6.md) |
| 160 | 11:53:11 | anthropic/sonnet46 | group_skeptic | 81KB | 74827/839 | [file](calls/160-anthropic-claude-sonnet-4-6.md) |
| 161 | 11:53:14 | anthropic/sonnet46 | group_skeptic | 79KB | 69206/1156 | [file](calls/161-anthropic-claude-sonnet-4-6.md) |
| 162 | 11:53:16 | anthropic/sonnet46 | group_skeptic | 76KB | 72287/1113 | [file](calls/162-anthropic-claude-sonnet-4-6.md) |
| 163 | 11:53:19 | anthropic/sonnet46 | group_skeptic | 110KB | 95142/1147 | [file](calls/163-anthropic-claude-sonnet-4-6.md) |
| 164 | 11:53:20 | anthropic/sonnet46 | group_skeptic | 84KB | 53963/1248 | [file](calls/164-anthropic-claude-sonnet-4-6.md) |
| 165 | 11:53:20 | anthropic/sonnet46 | group_skeptic | 113KB | 60884/1328 | [file](calls/165-anthropic-claude-sonnet-4-6.md) |
| 166 | 11:53:30 | anthropic/sonnet46 | group_skeptic | 79KB | 72729/1680 | [file](calls/166-anthropic-claude-sonnet-4-6.md) |
| 167 | 11:53:45 | anthropic/sonnet46 | group_skeptic | 62KB | 44530/510 | [file](calls/167-anthropic-claude-sonnet-4-6.md) |
| 168 | 11:53:47 | anthropic/sonnet46 | group_skeptic | 62KB | 41162/523 | [file](calls/168-anthropic-claude-sonnet-4-6.md) |
| 169 | 11:53:47 | anthropic/sonnet46 | group_skeptic | 57KB | 39262/672 | [file](calls/169-anthropic-claude-sonnet-4-6.md) |
| 170 | 11:53:48 | anthropic/sonnet46 | group_skeptic | 59KB | 38818/663 | [file](calls/170-anthropic-claude-sonnet-4-6.md) |
| 171 | 11:53:48 | anthropic/sonnet46 | group_skeptic | 74KB | 45878/655 | [file](calls/171-anthropic-claude-sonnet-4-6.md) |
| 172 | 11:53:49 | anthropic/sonnet46 | group_skeptic | 75KB | 45992/701 | [file](calls/172-anthropic-claude-sonnet-4-6.md) |
| 173 | 11:53:59 | anthropic/sonnet46 | group_skeptic | 110KB | 83535/951 | [file](calls/173-anthropic-claude-sonnet-4-6.md) |
| 174 | 11:54:05 | anthropic/sonnet46 | group_skeptic | 84KB | 49829/1249 | [file](calls/174-anthropic-claude-sonnet-4-6.md) |
| 175 | 11:54:20 | anthropic/sonnet46 | group_skeptic | 61KB | 40632/490 | [file](calls/175-anthropic-claude-sonnet-4-6.md) |
| 176 | 11:54:23 | anthropic/sonnet46 | group_skeptic | 48KB | 24001/692 | [file](calls/176-anthropic-claude-sonnet-4-6.md) |
| 177 | 11:54:25 | anthropic/sonnet46 | group_skeptic | 73KB | 42452/846 | [file](calls/177-anthropic-claude-sonnet-4-6.md) |
| 178 | 11:54:27 | anthropic/sonnet46 | group_skeptic | 79KB | 51657/888 | [file](calls/178-anthropic-claude-sonnet-4-6.md) |
| 179 | 11:54:32 | anthropic/sonnet46 | group_skeptic | 84KB | 53559/845 | [file](calls/179-anthropic-claude-sonnet-4-6.md) |
| 180 | 11:54:34 | anthropic/sonnet46 | group_skeptic | 58KB | 42766/1068 | [file](calls/180-anthropic-claude-sonnet-4-6.md) |
| 181 | 11:54:34 | anthropic/sonnet46 | group_skeptic | 2366KB | 82584/982 | [file](calls/181-anthropic-claude-sonnet-4-6.md) |
| 182 | 11:54:53 | anthropic/sonnet46 | group_skeptic | 137KB | 173112/1882 | [file](calls/182-anthropic-claude-sonnet-4-6.md) |
| 183 | 11:55:13 | anthropic/sonnet46 | group_skeptic | 107KB | 83382/670 | [file](calls/183-anthropic-claude-sonnet-4-6.md) |
| 184 | 11:55:14 | anthropic/sonnet46 | group_skeptic | 45KB | 40073/798 | [file](calls/184-anthropic-claude-sonnet-4-6.md) |
| 185 | 11:55:21 | anthropic/sonnet46 | group_skeptic | 67KB | 51625/1107 | [file](calls/185-anthropic-claude-sonnet-4-6.md) |
| 186 | 11:55:22 | anthropic/sonnet46 | group_skeptic | 49KB | 43704/1200 | [file](calls/186-anthropic-claude-sonnet-4-6.md) |
| 187 | 11:55:33 | anthropic/sonnet46 | group_skeptic | 81KB | 78240/1509 | [file](calls/187-anthropic-claude-sonnet-4-6.md) |
| 188 | 11:55:45 | anthropic/sonnet46 | group_skeptic | 80KB | 79920/1248 | [file](calls/188-anthropic-claude-sonnet-4-6.md) |
| 189 | 11:55:45 | anthropic/sonnet46 | group_skeptic | 81KB | 75430/1372 | [file](calls/189-anthropic-claude-sonnet-4-6.md) |
| 190 | 11:55:45 | anthropic/sonnet46 | group_skeptic | 11171KB | 269096/904 | [file](calls/190-anthropic-claude-sonnet-4-6.md) |
| 191 | 11:56:05 | anthropic/sonnet46 | group_skeptic | 49KB | 22678/824 | [file](calls/191-anthropic-claude-sonnet-4-6.md) |
| 192 | 11:56:09 | anthropic/sonnet46 | group_skeptic | 61KB | 47470/961 | [file](calls/192-anthropic-claude-sonnet-4-6.md) |
| 193 | 11:56:12 | anthropic/sonnet46 | group_skeptic | 69KB | 49658/1029 | [file](calls/193-anthropic-claude-sonnet-4-6.md) |
| 194 | 11:56:15 | anthropic/sonnet46 | group_skeptic | 90KB | 85178/1052 | [file](calls/194-anthropic-claude-sonnet-4-6.md) |
| 195 | 11:56:17 | anthropic/sonnet46 | group_skeptic | 59KB | 44721/1175 | [file](calls/195-anthropic-claude-sonnet-4-6.md) |
| 196 | 11:56:33 | anthropic/sonnet46 | group_skeptic | 109KB | 114065/1667 | [file](calls/196-anthropic-claude-sonnet-4-6.md) |
| 197 | 11:56:34 | anthropic/sonnet46 | group_skeptic | 63KB | 51616/1596 | [file](calls/197-anthropic-claude-sonnet-4-6.md) |
| 198 | 11:56:38 | anthropic/sonnet46 | group_skeptic | 1408KB | 253026/1491 | [file](calls/198-anthropic-claude-sonnet-4-6.md) |
| 199 | 11:56:48 | anthropic/sonnet46 | group_skeptic | 20KB | 14755/377 | [file](calls/199-anthropic-claude-sonnet-4-6.md) |
| 200 | 11:56:49 | anthropic/sonnet46 | group_skeptic | 24KB | 15720/400 | [file](calls/200-anthropic-claude-sonnet-4-6.md) |
| 201 | 11:56:51 | anthropic/sonnet46 | group_skeptic | 42KB | 20648/514 | [file](calls/201-anthropic-claude-sonnet-4-6.md) |
| 202 | 11:56:59 | anthropic/sonnet46 | group_skeptic | 49KB | 55608/692 | [file](calls/202-anthropic-claude-sonnet-4-6.md) |
| 203 | 11:57:00 | anthropic/sonnet46 | group_skeptic | 67KB | 39997/772 | [file](calls/203-anthropic-claude-sonnet-4-6.md) |
| 204 | 11:57:04 | anthropic/sonnet46 | group_skeptic | 112KB | 83523/1045 | [file](calls/204-anthropic-claude-sonnet-4-6.md) |
| 205 | 11:57:05 | anthropic/sonnet46 | group_skeptic | 68KB | 43914/1236 | [file](calls/205-anthropic-claude-sonnet-4-6.md) |
| 206 | 11:57:08 | anthropic/sonnet46 | group_skeptic | 101KB | 81042/911 | [file](calls/206-anthropic-claude-sonnet-4-6.md) |
| 207 | 11:57:24 | anthropic/sonnet46 | group_skeptic | 62KB | 42560/681 | [file](calls/207-anthropic-claude-sonnet-4-6.md) |
| 208 | 11:57:25 | anthropic/sonnet46 | group_skeptic | 52KB | 41043/686 | [file](calls/208-anthropic-claude-sonnet-4-6.md) |
| 209 | 11:57:30 | anthropic/sonnet46 | group_skeptic | 48KB | 39643/900 | [file](calls/209-anthropic-claude-sonnet-4-6.md) |
| 210 | 11:57:31 | anthropic/sonnet46 | group_skeptic | 44KB | 22112/820 | [file](calls/210-anthropic-claude-sonnet-4-6.md) |
| 211 | 11:57:32 | anthropic/sonnet46 | group_skeptic | 58KB | 44306/945 | [file](calls/211-anthropic-claude-sonnet-4-6.md) |
| 212 | 11:57:33 | anthropic/sonnet46 | group_skeptic | 73KB | 43126/954 | [file](calls/212-anthropic-claude-sonnet-4-6.md) |
| 213 | 11:57:43 | anthropic/sonnet46 | group_skeptic | 938KB | 78780/1234 | [file](calls/213-anthropic-claude-sonnet-4-6.md) |
| 214 | 11:57:46 | anthropic/sonnet46 | group_skeptic | 73KB | 47931/1505 | [file](calls/214-anthropic-claude-sonnet-4-6.md) |
| 215 | 11:58:07 | anthropic/sonnet46 | group_skeptic | 63KB | 37729/782 | [file](calls/215-anthropic-claude-sonnet-4-6.md) |
| 216 | 11:58:08 | anthropic/sonnet46 | group_skeptic | 73KB | 64282/862 | [file](calls/216-anthropic-claude-sonnet-4-6.md) |
| 217 | 11:58:12 | anthropic/sonnet46 | group_skeptic | 72KB | 70768/915 | [file](calls/217-anthropic-claude-sonnet-4-6.md) |
| 218 | 11:58:13 | anthropic/sonnet46 | group_skeptic | 51KB | 21365/1249 | [file](calls/218-anthropic-claude-sonnet-4-6.md) |
| 219 | 11:58:14 | anthropic/sonnet46 | group_skeptic | 60KB | 61712/1025 | [file](calls/219-anthropic-claude-sonnet-4-6.md) |
| 220 | 11:58:26 | anthropic/sonnet46 | group_skeptic | 61KB | 45066/1589 | [file](calls/220-anthropic-claude-sonnet-4-6.md) |
| 221 | 11:58:36 | anthropic/sonnet46 | group_skeptic | 2430KB | 124091/1803 | [file](calls/221-anthropic-claude-sonnet-4-6.md) |
| 222 | 11:58:45 | anthropic/sonnet46 | group_skeptic | 2792KB | 270490/1953 | [file](calls/222-anthropic-claude-sonnet-4-6.md) |
| 223 | 12:01:04 | google/g2.5-pro | conflict | 7KB | 70359/1589 | [file](calls/223-google-gemini-2.5-pro.md) |
| 224 | 12:02:24 | google/g2.5-pro | scrub | 1KB | 127363/0 | [file](calls/224-google-gemini-2.5-pro.md) |
| 225 | 12:03:01 | google/g2.5-pro | synthesize | 7KB | 125272/1661 | [file](calls/225-google-gemini-2.5-pro.md) |
| 226 | 12:03:11 | google/g2.5-pro | synthesize | 10KB | 125293/2771 | [file](calls/226-google-gemini-2.5-pro.md) |
| 227 | 12:03:34 | google/g2.5-pro | synthesize | 13KB | 125264/4785 | [file](calls/227-google-gemini-2.5-pro.md) |
| 228 | 12:04:25 | google/g2.5-pro | synthesize | 12KB | 10149/2963 | [file](calls/228-google-gemini-2.5-pro.md) |

---

## 3. Stage-by-stage narrative

The pipeline is a hand-written async loop in `tribunal/nestor_pulse_sdk/pipeline/tribunal/pipeline.py`:
`intake -> research division -> deep research -> distill -> group -> verify (group skeptic) -> adjudicate -> coverage gate -> conflict -> scrub -> synthesize`.

### 3.1 Intake — DELEGATOR (2 calls, `claude-sonnet-4-6`)

`adaptive_intake()` (`intake.py`) turns the operator-validated brief into a mission plan (focus areas, each with taxonomy + stakes + a self-contained `research_prompt`). It is a pure delegator — it may not ask clarifying questions.

- **Call 1** ([seq 1](calls/001-anthropic-claude-sonnet-4-6.md), 11:17:45, `stop_reason=max_tokens` at 2048 out-tokens) produced only **2 focus areas** (dynamic-pricing, coffee) before hitting the token cap. The coverage check immediately failed:
  `adaptive_intake: coverage check FAILED — 2 focus areas for 29 detected questions; forcing one retry`.
- **Call 2** ([seq 2](calls/002-anthropic-claude-sonnet-4-6.md), 11:18:24, again `stop_reason=max_tokens`) produced **3 focus areas** — dynamic pricing, coffee, and *"Strategische beslissingsopties: Germany-entry 2027 vs. BeNeLux-consolidatie"* — all tagged **STAKES: high**.

The full mission plan (3 focus areas, each with a multi-section Dutch `research_prompt`) is the verbatim input to research division; read it in [seq 2](calls/002-anthropic-claude-sonnet-4-6.md). **Defect:** both intake calls hit `max_tokens=2048` (`intake.py:_MAX_OUTPUT_TOKENS`), truncating the plan — the first truncation is what caused the coverage retry. Raising the cap would remove a whole wasted intake round-trip.

### 3.2 Research division + deep research (6 DR calls)

`divide()` (`research_division.py`) maps the 3 high-stakes focus areas to research angles. Because all 3 are **high stakes**, each angle is **doubled** for 2-provider redundancy (`_HIGH_REDUNDANCY_PROVIDER = "claude"`): a primary Google `deep-research-max` pass **plus** a Claude `+web` pass. Result: **6 deep-research reports** (3 questions x 2 providers).

| angle | Google DR-max | Claude redundancy | report sizes |
|---|---|---|---|
| Coffee strategies BeNeLux petroliers | [seq 6](calls/006-google-deep-research-max-preview-04-2026.md) (53KB) | [seq 3](calls/003-anthropic-claude-sonnet-4-6.md) (33KB) | full DR reports |
| Dynamic pricing EU fuel retailers | [seq 7](calls/007-google-deep-research-max-preview-04-2026.md) (71KB) | [seq 4](calls/004-anthropic-claude-sonnet-4-6.md) (37KB) | full DR reports |
| Germany-entry vs. BeNeLux consolidation | [seq 8](calls/008-google-deep-research-max-preview-04-2026.md) (75KB) | [seq 5](calls/005-anthropic-claude-sonnet-4-6.md) (27KB) | full DR reports |

Each call's assignment (the rewritten, self-contained `research_prompt`) and full findings are in its extract. See §5 for the per-agent findings summary. **All 6 returned `status: success`.**

> **Audit-provenance defect.** The 3 Claude-redundancy DR calls are recorded with `provider=anthropic, model=claude-sonnet-4-6` but their **body shape is the deep-research shape** (`request.query` + `response.report`), not the Messages API shape. They are genuine Claude-`+web` deep-research passes, but a reader filtering the audit by `provider=google` to find "the deep research" will miss half of it, and their **token usage is not recorded at all** (no `usage` block). See §6, Token accounting.

### 3.3 Claim distillation (8 calls, `gemini-2.5-flash`)

`claim_distiller` (`synthesis/steps.py`) extracts atomic claims from the 6 research reports in plain-text line format (never JSON — citations vs structured-outputs = 400). 8 batched calls, ~230K output tokens. Output feeds grouping. Extracts: the 8 `distill`-stage rows in the index.

### 3.4 Grouping (30 calls, `gemini-2.5-flash`)

`group_claims()` (`grouping.py`) tags each claim with `ENTITY | ATTRIBUTE` (thinking disabled, plain-text) so variants about the same fact verify together. 30 tagging calls (batch size 40) -> **176 groups** (163 single-claim, 13 multi-claim). Merge-happy normalization by design.

### 3.5 Verify — GROUP SKEPTIC (176 calls, `claude-sonnet-4-6` + web) — **the broken arm**

`run_group_skeptic()` (`group_skeptic.py`) runs ONE tool-use session per group: `web_search` + `web_fetch` (server-side, resolved inline) then a forced `emit_group_verdict` client tool, plus a cross-variant reconciliation. Depth (turns/searches/fetches) scales with stakes; low-stakes groups wave through unverified.

What actually happened:

- **176 group-skeptic calls reached the API and returned** (all `stop_reason=tool_use`, all emitted `emit_group_verdict` on turn 1 — the server-tool loop resolves all searches/fetches within a single audited call). Across them: **516 web_search + 216 web_fetch** requests. So the LLM *did* do real research and *did* emit verdicts (raw tally across 198 claim-slots: 76 support / 31 refute / 91 insufficient).
- **BUT 24 of those 176 calls (13.6%) then crashed in post-processing** with `'str' object has no attribute 'get'` (worker log, 11:40:50–11:58:36). Root cause is a hard defect — see §4.1. For those 24 groups the exception is caught in `pipeline.py:_one_group_pass` -> returns `None` -> **no verdicts are recorded** -> those claims survive **unverified**.
- **Then at 11:58:46 the Anthropic key hit its usage limit.** From 11:58:46–11:59:41 the log shows **776** further `group skeptic failed … 400 … "You have reached your specified API usage limits. You will regain access on 2026-08-01"`. These are the coverage-gate re-entry / remaining group passes that never got a response (not audited). Every one of them = a group waved through unverified.

Net: **every one of the run's groups ended up with no usable skeptic verdict** — the 24 that ran crashed on parse, and the rest either 400'd on the credit wall or were re-entered after credits died. The verification appendix the report appends is therefore misleading (§4.3). The worker log's ~800 "group skeptic failed" lines (24 str.get + 776 usage-limit) are the audit trail of the skeptic arm collapsing. Full per-group inventory (subject|property, claims, emitted verdicts, and which crashed) is in [`GROUPS.md`](GROUPS.md).

### 3.6 Adjudicate -> coverage gate -> conflict -> scrub

- **Adjudicate** (`adjudicate.py`, in-process, no LLM call) applies the majority-independent survival rule over whatever verdicts survived.
- **Coverage gate** (`coverage_gate.py`) re-runs skeptics for uncovered high-stakes claims (bounded by `MAX_REENTRY`). This re-entry is almost certainly what generated much of the 11:58–11:59 usage-limit burst — it fired *after* credits were exhausted, so every re-entry 400'd.
- **Conflict detection** ([seq 223](calls/223-google-gemini-2.5-pro.md), `gemini-2.5-pro`, 12:01:04, out 1589 tok): "Identify direct contradictions between these already-fact-checked research claims."
- **Scrub** ([seq 224](calls/224-google-gemini-2.5-pro.md), `gemini-2.5-pro`, 12:02:24): removes passages that state/depend on discredited claims. **Defect: this call returned an EMPTY output (0 candidate tokens).** With the skeptic arm dead, few/no claims were discredited, so scrub had little to do — but a 0-token gemini-pro response is a degenerate result worth guarding (empty scrub = unscrubbed research forwarded to synthesis).

### 3.7 Synthesis (4 calls, `gemini-2.5-pro`)

`synthesize_report` fans out into **4 section-writer calls** (all 12:03–12:04), each writing one Dutch report section:

| section | extract | out tokens |
|---|---|---|
| Germany-entry vs. consolidation | [seq 225](calls/225-google-gemini-2.5-pro.md) | 1661 |
| Coffee strategy | [seq 226](calls/226-google-gemini-2.5-pro.md) | 2771 |
| Dynamic pricing operational model | [seq 227](calls/227-google-gemini-2.5-pro.md) | 4785 |
| Management summary | [seq 228](calls/228-google-gemini-2.5-pro.md) | 2963 |

After synthesis, `strip_unresolved_cite_markers` (`pipeline.py:838`) removed **28 unresolved `[cite:]` markers** (12:04:25) — see §4.4. A deterministic verification appendix is appended, then the run reports `completed` at 12:04:28.

> **Audit-fidelity defect.** All 6 `gemini-2.5-pro` request bodies store `request.contents` **truncated to exactly 2000 chars**. The synthesis/conflict/scrub INPUT prompts (the scrubbed research corpus fed to the writer) are therefore **not recoverable from the audit** — only the first 2000 chars survive. Anthropic request bodies are stored in full; flash bodies up to ~2001 chars (also capped). This blocks full reconstruction of exactly what synthesis saw.

---

## 4. Defects & enhancement leads

### 4.1 [P0] Group-skeptic `reconciliation`-as-string crash — the skeptic arm's silent killer

**Symptom:** 24x `tribunal_pipeline: group skeptic failed for '<entity>'|'<attr>': 'str' object has no attribute 'get'` (11:40:50–11:58:36).

**Root cause (pinned by audit evidence):** In `pipeline/tribunal/group_skeptic.py`, `_parse_group_verdict()` assumes the tool input's `reconciliation` field is a dict:

```python
# group_skeptic.py:91 and :119-124
recon = inp.get("reconciliation") or {}
...
"reconciliation": {
    "disputed": bool(recon.get("disputed", False)),   # <-- crashes if recon is a str
    "relation": recon.get("relation", "single" if n_claims == 1 else "agree"),
    "note": recon.get("note", ""),
    "canonical": recon.get("canonical", ""),
},
```

**Exactly 24 of the 176 `emit_group_verdict` tool calls returned `reconciliation` as a JSON *string***
(`"{\"disputed\": false, \"relation\": \"single\", ...}"`) instead of a real object. `recon or {}` keeps the non-empty string, then `recon.get("disputed")` on a `str` raises `AttributeError: 'str' object has no attribute 'get'`. The other 152 returned `reconciliation` as an object and parsed fine. The 24-string count matches the 24 log failures exactly.

**Impact:** all 24 crashing groups had their verdicts thrown away (caught -> `None` -> claims survive unverified), even though the LLM had already done the web research and emitted verdicts. Note also that the `emit_group_verdict` **tool schema declares `reconciliation` as `type: object`** (confirmed in the audit request `tools`), so the model is violating the schema — but the client must be defensive regardless.

**Fix:** coerce a stringified `reconciliation` (and defensively, the whole tool `input`) back to a dict before `.get()`, e.g. `if isinstance(recon, str): recon = json.loads(recon) except -> {}`. Same guard belongs on `inp` itself. This is a ~3-line fix that restores ~14% of verifications immediately and eliminates a whole class of "model returned valid data as a string" failures.

### 4.2 [P0] Anthropic usage-limit wall wipes out the tail of verification

**Symptom:** 776x `400 … "You have reached your specified API usage limits. You will regain access on 2026-08-01"` in a 55-second burst (11:58:46–11:59:41).

**Root cause:** the run's Anthropic key hit its monthly cap mid-run. Every group-skeptic + coverage-re-entry call after 11:58:46 hard-400'd. The pipeline treats these as ordinary skeptic failures (`_one_group_pass` catches, returns `None`, group waves through) — so the run still finishes "green" with the verification silently gutted. This is the same credit-exhaustion class flagged in prior sessions (Nestor_Claude / Nestor_Claude2 top-ups).

**Enhancement leads:** (a) detect the `invalid_request_error`/usage-limit signature and **fail the run loud** (or park it) rather than silently completing with empty verification; (b) the verification appendix must reflect that N groups were never checked due to a provider cap (it currently only reports the budget-cap governor, not a provider 400 wall); (c) pre-flight credit check before a 48-minute run.

### 4.3 [P1] "Green" completion hides gutted verification — honesty-appendix gap

The run returned `completed` and appended a `## Verification` section, but between 4.1 and 4.2 essentially every group ended up unverified. `_verification_appendix` (`pipeline.py:966`) counts `n_claims - n_unverified` as "independently fact-checked", where `n_unverified` only counts claims with an *empty* verdict list — it cannot distinguish "waved through low-stakes" from "skeptic crashed" from "provider 400'd". The appendix therefore **overstates** how much was fact-checked. Lead: track a distinct `verification_failed` reason per claim and surface it.

### 4.4 [P1] 28 unresolved `[cite:]` markers stripped

`strip_unresolved_cite_markers` removed 28 `[cite:...]` markers the synthesis emitted but that were never tied to a URL (12:04:25). This is the documented failure mode where deep research emits a citation marker the provider never resolves to a source (`pipeline.py:1014-1019`). With the skeptic arm dead, citation recall (populated from skeptic-fetched URLs via `persist_tribunal_claims`) was also degraded, worsening the orphan-marker rate. Lead: resolve markers against the DR reports' own source lists before stripping.

### 4.5 [P2] Pydantic serialization warnings on `web_fetch` result blocks

15 `PydanticSerializationUnexpectedValue` warnings at 11:44:22, all on `WebFetchToolResultBlock` / `WebFetchToolResultErrorBlock` (incl. `error_code='url_not_in_prior_context'`). These come from `_content_to_serialisable` (`skeptic.py:204`) doing a shallow `block.__dict__` copy that does not recursively convert nested server-tool-result blocks, so re-serializing them trips the SDK's model validator. Harmless in this run (the group skeptic never reaches turn 2 — every group emits on turn 1), but it will bite the moment a group needs a follow-up turn.

### 4.6 [P2] Both intake calls truncated at `max_tokens=2048`

`intake.py:_MAX_OUTPUT_TOKENS = 2048`. Both intake calls hit `stop_reason=max_tokens`; the first truncation dropped the plan to 2 focus areas and forced an entire wasted retry round-trip. Raise the cap (the plan for a 3-area brief needs more than 2048 out-tokens).

### 4.7 [P3] Audit-record gaps
- `seq = 0` on all 228 bodies (per-run sequence counter not written) — mtime is the only ordering key.
- `gemini-2.5-pro` request `contents` truncated to 2000 chars -> synthesis/conflict/scrub inputs unrecoverable (§3.7).
- 3 Claude-redundancy deep-research calls recorded as `provider=anthropic` with no token usage (§3.2, §6).
- Empty (0-token) `gemini-2.5-pro` scrub response (§3.6) — degenerate output not guarded.

---

## 5. Deep-research sub-agent outputs (6)

Each angle ran on two providers. Assignments (verbatim `research_prompt`) and full reports are in the extracts.

1. **Coffee strategies — Google DR-max** ([seq 6](calls/006-google-deep-research-max-preview-04-2026.md), 53KB): evolution of Total (Bonjour), Q8, Shell (Select) coffee offers 2023–2026, quantified traffic/conversion impact, conditions for a LUKOIL own coffee brand.
2. **Coffee strategies — Claude +web** ([seq 3](calls/003-anthropic-claude-sonnet-4-6.md), 33KB): same assignment, independent pass; explicitly blends verifiable data with sector expertise where public sources are absent.
3. **Dynamic pricing — Google DR-max** ([seq 7](calls/007-google-deep-research-max-preview-04-2026.md), 71KB): EU fuel retailers applying dynamic pricing, operational models (tech, data feeds, cadence), measured volume/margin impact, regulatory constraints, a LUKOIL implementation model.
4. **Dynamic pricing — Claude +web** ([seq 4](calls/004-anthropic-claude-sonnet-4-6.md), 37KB): same assignment, redundant pass.
5. **Germany-entry vs. consolidation — Google DR-max** ([seq 8](calls/008-google-deep-research-max-preview-04-2026.md), 75KB): evidence-based weighing of the three strategic alternatives (A perfect BeNeLux first / B parallel invest / C Germany-entry 2027); note the report opens with a "critical context reset" challenging the framing.
6. **Germany-entry vs. consolidation — Claude +web** ([seq 5](calls/005-anthropic-claude-sonnet-4-6.md), 27KB): redundant pass.

All 6 reports fed claim distillation (§3.3). Full findings in the extracts; they are long Dutch strategic reports (27–75KB each).

---

## 6. Token accounting (from usage metadata — tokens only, no USD)

| provider/model | calls | tokens in* | tokens out | cache read | cache create | thoughts | web_search | web_fetch |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| anthropic/claude-sonnet-4-6 (intake + 176 group-skeptic) | 181 | 14,899,668 | 190,100 | 5,845,857 | 8,704,037 | 0 | 516 | 216 |
| google/gemini-2.5-flash (distill + grouping) | 38 | 170,425 | 243,783 | 0 | 0 | 0 | — | — |
| google/gemini-2.5-pro (conflict + scrub + 4 synth) | 6 | 583,700 | 13,769 | 0 | 0 | 28,028 | — | — |
| google/deep-research-max-preview-04-2026 | 3 | — | — | — | — | — | — | — |
| **Totals (recorded)** | **228** | **15,653,793** | **447,652** | **5,845,857** | **8,704,037** | **28,028** | **516** | **216** |

\* Anthropic "tokens in" here = `input_tokens + cache_read_input_tokens + cache_creation_input_tokens` (the prompt-cache prefix dominates: 8.7M cache-create + 5.8M cache-read, so the cached claim+sources block is being paid for once and re-read cheaply as intended).

**Not recorded:** the 3 Google `deep-research-max` calls **and** the 3 Claude-redundancy deep-research calls carry **no usage metadata** (the DR response shape has only `{status, report}`). Deep research is the single most expensive stage and its token cost is invisible in the audit — a token-accounting blind spot to close.

---

## 7. What "good" would have looked like

For an engine-enhancement pass, the priority order is:
1. Fix the `reconciliation`-as-string crash (§4.1) — restores 14% of verifications with a ~3-line guard.
2. Detect provider usage-limit 400s and fail/park loud instead of completing green (§4.2, §4.3).
3. Record deep-research token usage and stop truncating gemini-pro request bodies (§4.7, §6).
4. Raise intake `max_tokens` to kill the coverage-retry round-trip (§4.6).

All raw evidence: [`calls/`](calls/) (228 extracts), [`index.json`](index.json), [`GROUPS.md`](GROUPS.md), and the GCS permanent store cited in §1.
