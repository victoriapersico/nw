# MVP-12 Repository-State Discrepancy Audit

## Instructions for ChatGPT

Act as the technical lead for the NextWave Control Tower repository.

This document contains a verified, read-only audit of a repository-state discrepancy. Treat the Git evidence and runtime results below as the current source of truth.

Do not implement, merge, cherry-pick, or modify anything yet.

First:

1. Confirm the root cause of the discrepancy.
2. Review the proposed recovery strategy.
3. Identify any risks or missing verification steps.
4. Separate proven facts from recommendations.
5. Wait for explicit approval before proposing commands that mutate Git or files.

---

## Executive conclusion

The MVP-12 hardening was completed and committed, but it was never merged into `main`.

The hardening is not lost. It exists in:

- local branch `codex/mvp-12-hardening-backup` at commit `d71816a`;
- local and remote branch `mvp-issue-12` / `origin/mvp-issue-12`, where the equivalent hardening commit is `e25f08a`;
- branch tip `ad5c977`, which adds only an audit document after the hardening.

The current `main` branch advanced independently through later frontend and monitoring commits. This produced two divergent implementations.

The safest strategy is to recover the existing hardening commit onto a new branch from current `main`, then manually reconcile the small set of overlapping runtime/frontend files. Reimplementing the hardening from scratch is not recommended.

---

## Current verified repository state

- Branch: `main`
- HEAD: `2d7fba2d22baebbc3a0d1d0a3a06d062ee32be3c`
- Upstream: `origin/main`
- Ahead/behind: `+0 / -0`
- Working tree: clean
- `main == origin/main`
- No files, branches, refs, commits, or working-tree state were modified during the audit.

### Current tests

The command:

```bash
source .venv/bin/activate
pytest
```

fails during collection:

```text
ModuleNotFoundError: No module named 'backend'
```

Result:

- zero tests executed;
- 11 collection errors.

The command:

```bash
source .venv/bin/activate
python -m pytest
```

passes:

```text
72 passed, 1 warning
```

### Current evaluation metrics

A fresh evaluation of current `main` produced:

- Catalog size: 30 scenarios
- Evaluated scenarios: 29
- Scenario 29: skipped because it is optional
- Passed scenarios: 23
- Detection recall: 80.0%
- False-positive rate: 14.3%
- Root-cause accuracy: 75.0%
- Multi-incident separation accuracy: 75.0%
- Abstention accuracy: 100.0%
- Mean detection latency: 10 minutes
- Estimated-loss error: unavailable

Failed scenarios:

- 17
- 18
- 19
- 25
- 28
- 30

---

## Reported previous hardening state

A previous MVP-12 hardening report stated that the repository had reached:

- 81 tests passing;
- 0% false-positive rate;
- strict confirmed RCA scoring;
- real backend reset;
- `GET /monitor/latest-batch`;
- `IncidentEngine` integrated in evaluation and live runtimes;
- a real live dashboard without fake monitoring values;
- honest `insufficient_evidence` rendering;
- updated README and startup instructions.

The audit confirmed that this report corresponds to commit `d71816a` / `e25f08a`, not to current `main`.

---

## Git history and root cause

### Relevant commits

```text
2d7fba2 (HEAD -> main, origin/main) feat: make dashboard monitoring live
ad5c977 (origin/mvp-issue-12, mvp-issue-12) issue 12 hecho, no anda bien el frontend pero solucionable, hay que probarlo en windows
e25f08a feat: harden MVP-12 trial-by-fire flow
d71816a (codex/mvp-12-hardening-backup) feat: harden MVP-12 trial-by-fire flow
6a52dfd Update client dashboard layout
b234ce8 Merge remote-tracking branch 'origin/main' into frontend-ines
```

### Verified reflog sequence

1. `codex/mvp-12-hardening-backup` was created from `b234ce8`.
2. The hardening was committed as `d71816a`.
3. The worktree moved to `mvp-issue-12`.
4. The hardening was cherry-picked there as `e25f08a`.
5. `ad5c977` added `docs/MVP_12_AUDIT_DECISION_BRIEF.md`.
6. `mvp-issue-12` was pushed to `origin/mvp-issue-12`.
7. The worktree was switched back to `main`.
8. `main` was fast-forwarded to `2d7fba2` through a different line of development.

No merge or cherry-pick from MVP-12 into `main` occurred.

### Important tree identity

Commits `d71816a` and `e25f08a` have the exact same source tree:

```text
be8a09d02013315d325af338df23e788c7d4af66
```

Therefore, they contain the same hardening implementation even though they have different parents.

### Branch containment

`d71816a` is contained only by:

```text
codex/mvp-12-hardening-backup
```

`e25f08a` and `ad5c977` are contained by:

```text
mvp-issue-12
origin/mvp-issue-12
```

Both hardening branches are unmerged into `main`.

### Stashes, worktrees, and unreachable commits

- Only one active worktree exists: current `main`.
- The only stash is an older, unrelated `issue-02-mvp` documentation stash.
- Unreachable commits found by `git fsck` are unrelated older WIP objects.
- No more complete MVP-12 hardening version was found in an unreachable commit.

---

## Forensic filesystem evidence

Ignored files left behind by the previous hardening checkout confirm that it was executed locally before returning to `main`.

### Ignored evaluation artifacts

The directory:

```text
artifacts/evaluation/
```

is ignored and not tracked by Git.

It still contains reports generated on 2026-08-29 at 22:05 with the hardened metrics:

- 16/29 passed;
- 0% false positives;
- 35% confirmed RCA accuracy.

Because the directory is ignored, switching back to `main` did not remove or update these files. This explains why stale hardening metrics could coexist with current code producing 23/29 and a 14.3% false-positive rate.

### Compiled test artifacts

The current filesystem also contains ignored compiled files for source tests that do not exist on `main`:

```text
tests/__pycache__/test_live_control_tower.cpython-311-pytest-9.1.1.pyc
tests/__pycache__/test_frontend_live_data.cpython-311-pytest-9.1.1.pyc
frontend/__pycache__/live_data.cpython-311.pyc
```

Their timestamps correspond to the hardening execution around 22:38.

---

## Expected-feature matrix

| Expected hardening | Current `main` status | Hardening location and evidence |
|---|---|---|
| Seasonal baseline shrinkage/smoothing | **EXISTS IN ANOTHER COMMIT/BRANCH** | `d71816a` adds `DEFAULT_SHRINKAGE_STRENGTH = 50.0` and shrinks seasonal buckets toward a parent merchant-country rate. |
| Strict RCA scoring requiring `diagnosis_status == confirmed` | **PRESENT BUT DIFFERENT/BROKEN** | Current harness credits evidence from abstained diagnoses. Fixed in `d71816a`. |
| `POST /monitor/reset` | **EXISTS IN ANOTHER COMMIT/BRANCH** | Implemented and tested in `d71816a`; absent from current `backend/main.py`. |
| `GET /monitor/latest-batch` | **EXISTS IN ANOTHER COMMIT/BRANCH** | Implemented and tested in `d71816a`; absent from current API. |
| `IncidentEngine` used by EvaluationRuntime | **EXISTS IN ANOTHER COMMIT/BRANCH** | Current engine exists but is not called. `d71816a` processes detector output through it. |
| `IncidentEngine` used by LiveControlTower | **EXISTS IN ANOTHER COMMIT/BRANCH** | Added in `d71816a`, including backend priority-order tests. |
| Frontend polling real `/monitor/tick` data | **PRESENT BUT DIFFERENT/BROKEN** | Current main polls real tick/monitoring endpoints but blends the result with static merchant data. Hardening uses tick, latest batch, and diagnosed incidents exclusively. |
| Removal of fake jitter/counters/provider-health fallback | **PRESENT BUT DIFFERENT/BROKEN** | Random jitter is absent, but a synthetic header counter and static `MERCHANT_DATA` fallback remain. Fully removed in `d71816a`. |
| Honest `insufficient_evidence` rendering | **PRESENT BUT DIFFERENT/BROKEN** | Backend keeps the status, but current UI can still label the section as a probable root cause. Hardening adds explicit abstention presentation and tests. |
| README describing the real Control Tower | **EXISTS IN ANOTHER COMMIT/BRANCH** | `d71816a` replaces the generic starter README with actual architecture, startup, evaluation, reset, Judge Lab, fallback, and limitations. |
| Tests for the hardening | **EXISTS IN ANOTHER COMMIT/BRANCH** | The hardening commit collects and passes 81 tests. |

None of the expected hardening changes is missing entirely. The complete set exists outside `main`.

---

## Verified hardening behavior

Commit `d71816a` was exported to a temporary directory and executed without checking it out or modifying the repository.

### Hardening pytest result

```text
81 passed, 1 warning
```

The warning is a Starlette/httpx deprecation warning.

### Hardening evaluation result

- Evaluated scenarios: 29
- Passed scenarios: 16
- Detection recall: 80.0%
- False-positive rate: 0.0%
- Confirmed root-cause accuracy: 35.0%
- Multi-incident separation accuracy: 75.0%
- Abstention accuracy: 100.0%
- Mean detection latency: 10 minutes
- Estimated-loss error: unavailable
- Scenario 29: skipped

The lower number of passing scenarios is intentional. The hardened harness no longer credits evidence from `insufficient_evidence` diagnoses as correct RCA.

Hardening failures:

- 8
- 12
- 13
- 14
- 15
- 17
- 18
- 19
- 21
- 22
- 24
- 25
- 30

Several are detected incidents whose RCA correctly abstains rather than inventing a confirmed cause.

---

## Why current RCA scoring is permissive

Current `backend/evaluation/harness.py`:

1. Builds the observed-cause set from every diagnosis evidence item.
2. Does not require `diagnosis_status == "confirmed"`.
3. Computes `root_cause_accuracy` from whole-scenario `passed` status.

A direct audit probe supplied:

- `diagnosis_status = "insufficient_evidence"`;
- unconfirmed evidence `provider = "Stripe"`;
- an expected Stripe provider cause.

The current harness returned:

```text
([], False)
```

This means no mismatch was reported and the abstained diagnosis was accepted as correct RCA.

The hardening commit:

- filters expected causes through confirmed diagnoses;
- separates detection outcome from diagnosis outcome;
- reports `confirmed_root_cause_accuracy`;
- adds `test_abstained_evidence_does_not_count_as_confirmed_root_cause`.

---

## Why current main has 72 tests while hardening has 81

The hardening adds these test functions:

- sparse seasonal baseline false-positive protection: +1;
- strict abstained-evidence RCA scoring: +1;
- EvaluationRuntime IncidentEngine integration: +1;
- frontend live-data tests: +3;
- live reset/latest-batch/priority tests: +4.

This is ten additional test functions.

Current `main` independently added one health/monitoring test after the hardening branch diverged. The complete-tree comparison is therefore:

```text
current main:                  72
hardening feature tests:      +10
current-only health test:      -1 in the old hardening tree
hardening branch total:        81
```

A properly reconciled recovery that preserves the current health test should collect at least:

```text
82 tests
```

### New hardening test modules

`tests/test_frontend_live_data.py`:

- snapshot metrics come directly from batch transactions;
- confirmed diagnosis is labeled as confirmed root cause;
- abstention never labels candidate evidence as a root cause.

`tests/test_live_control_tower.py`:

- three clean inject/detect/reset cycles;
- reset endpoint clears cached state;
- latest-batch endpoint exposes only the real last batch;
- live tick preserves IncidentEngine priority order.

---

## Why `pytest` fails while `python -m pytest` succeeds

The executable:

```text
.venv/bin/pytest
```

is a console script. Python starts it with the executable directory as its initial import path. The repository root is not inserted.

The project is also not installed as a Python package, and `pytest.ini` only contains:

```ini
[pytest]
testpaths = tests
```

It does not contain:

```ini
pythonpath = .
```

Therefore, plain `pytest` cannot import `backend` or `frontend`.

`python -m pytest` starts the module with the current working directory represented in `sys.path`, so imports succeed.

Important nuance: plain `pytest` also fails on the hardening tree, there with 13 collection errors because it contains the additional frontend/live test modules.

The hardening did not make the plain executable work. It updated the README to use:

```bash
python -m pytest -q
```

For Streamlit, the hardening used a separate fix: `frontend/app.py` explicitly adds the repository root to `sys.path`, allowing:

```bash
streamlit run frontend/app.py
```

to import `backend` and `frontend` without a `PYTHONPATH` override.

---

## Hardening code location

### Preferred recovery source

- Branch: `codex/mvp-12-hardening-backup`
- Commit: `d71816a`
- Parent: `b234ce8`
- Relative to current main: main has two exclusive commits; hardening has one exclusive commit.

### Remote-backed equivalent

- Branch: `mvp-issue-12`
- Remote: `origin/mvp-issue-12`
- Equivalent hardening commit: `e25f08a`
- Tip: `ad5c977`
- Relative to current main: main has four exclusive ancestry commits; branch has two exclusive commits.

### Recommendation

Use `d71816a` as the recovery source because:

- it is one focused commit;
- it is a direct child of `b234ce8`;
- it contains the same code tree as `e25f08a`;
- it does not include the 1,151-line audit-only follow-up from `ad5c977`;
- it has the smallest divergence from current `main`.

---

## Recovery conflict assessment

A direct recovery is possible, but it is not conflict-free.

### Files changed on both development lines

Current `main` and `d71816a` both changed:

- `backend/integration/evaluation_runtime.py`
- `backend/live_control_tower.py`
- `backend/main.py`
- `frontend/pages/0_Client.py`

### Patch-check failures

A direct patch application check fails in:

- `backend/live_control_tower.py`
- `backend/main.py`
- `frontend/pages/0_Client.py`

### Three-way merge conflicts

Explicit textual conflicts are expected in:

- `backend/live_control_tower.py`
- `frontend/pages/0_Client.py`

Semantic review is still required in:

- `backend/integration/evaluation_runtime.py`
- `backend/main.py`

even where Git may auto-merge them.

### Main-only changes that must be preserved

The hardening commit does not modify these later-main files, so a cherry-pick should preserve them:

- `DECISIONS.md`
- `backend/schemas.py`
- `tests/test_health.py`

This is another reason to cherry-pick the focused commit instead of merging or replacing the complete branch tree.

---

## Exact safest recovery plan

Do not execute this plan without approval.

### 1. Create an isolated recovery branch

Create a new branch from current `main`.

Do not work directly on `main` and do not move the existing hardening refs.

### 2. Recover `d71816a`

Use `d71816a` as the source commit.

Apply it with review before finalizing the recovery commit.

Do not merge the entire `mvp-issue-12` branch.

### 3. Accept the proven non-conflicting hardening pieces

Recover substantially as written:

- baseline shrinkage;
- strict evaluation semantics;
- IncidentEngine formatting/integration;
- test additions;
- `frontend/live_data.py`;
- `frontend/app.py` import-path fix;
- real reset/latest-batch documentation;
- real Control Tower README;
- evaluation documentation.

### 4. Reconcile EvaluationRuntime

Preserve current runtime behavior and add the hardened IncidentEngine processing:

```text
detector output
→ IncidentEngine.process(...)
→ DetectionResponse
```

Keep the simulator-to-detector injection-isolation boundary unchanged.

### 5. Reconcile LiveControlTower

Preserve current-main monitoring support while adding:

- initial scenario ownership;
- real reset;
- latest-batch defensive copy;
- IncidentEngine ordering;
- clean incident storage lifecycle.

Because current main added approval history after the hardening branch diverged, reset must also clear:

- approval history;
- chart state derived from that history.

The original hardening reset did not know about this later field.

### 6. Reconcile backend routes

Retain current endpoints and add:

- `POST /monitor/reset`;
- `GET /monitor/latest-batch`.

Keep current merchant-monitoring endpoints if they remain useful and tested.

### 7. Reconcile the frontend

Do not accept either frontend side wholesale.

Preserve the newer current-main layout where possible, but adopt the hardened data semantics:

- every live KPI comes from backend data;
- use real batch transactions for country and recent-payment metrics;
- use backend incident order;
- no static provider/country fallback when the API is active;
- no synthetic counter presented as operational monitoring;
- backend unavailable must render an explicit error, not fake live values;
- real reset button must call `POST /monitor/reset`;
- `confirmed` diagnosis must display as confirmed;
- `insufficient_evidence` must display as an abstention;
- candidate evidence must not be labeled as a confirmed root cause.

### 8. Do not automatically recover `ad5c977`

`ad5c977` only adds:

```text
docs/MVP_12_AUDIT_DECISION_BRIEF.md
```

It is not needed for functional recovery and should be included only if explicitly desired.

### 9. Run the full verification gate

Expected test command:

```bash
python -m pytest -q
```

Expected minimum after preserving the current health test:

```text
82 passed
```

Then run the evaluation twice and compare results excluding `generated_at`.

Expected hardened metric shape:

- detection recall: 80%;
- false-positive rate: 0%;
- confirmed RCA accuracy: 35%;
- multi-incident separation: 75%;
- abstention accuracy: 100%;
- latency: 10 minutes.

### 10. Verify the live lifecycle

Run at least three full cycles:

```text
reset
→ 2–3 normal windows
→ no incident
→ Rappi/Brazil/Stripe at 20%
→ Incident + RCA + recommendation
→ reset
→ clean state
→ repeat
```

Also verify:

- latest batch is 404 before the first tick;
- latest batch becomes available after a tick;
- reset returns it to 404;
- active incidents are cleared;
- injections are cleared;
- detector persistence is cleared;
- RCA recent batches are cleared;
- approval/chart history is cleared;
- priority ordering is preserved.

### 11. Verify exact startup commands

Backend:

```bash
source .venv/bin/activate
uvicorn backend.main:app --reload --port 8000
```

Frontend:

```bash
source .venv/bin/activate
streamlit run frontend/app.py
```

Tests:

```bash
python -m pytest -q
```

### 12. Regenerate evaluation artifacts

The existing reports are ignored and stale relative to current `main`.

Regenerate them only after the recovery branch passes the full gate. Decide explicitly whether the final metrics should remain local, be force-added, or be copied into a tracked documentation location.

---

## Recover or reimplement?

### Recommendation

Recover the existing hardening commit. Do not reimplement it from scratch.

Use a hybrid recovery strategy:

- recover proven backend, evaluator, baseline, reset, IncidentEngine, tests, documentation, and data-view helpers from `d71816a`;
- manually integrate those behaviors with the later `main` monitoring and visual work;
- do not merge the full branch tree;
- do not replace the current frontend wholesale.

### Why not reimplement?

The hardening commit already has executable evidence:

- 81 passing tests;
- deterministic evaluation;
- 0% false positives;
- strict RCA scoring;
- tested reset;
- tested latest-batch lifecycle;
- tested IncidentEngine ordering;
- tested honest abstention UI helpers.

Reimplementing these behaviors would duplicate work and introduce avoidable regression risk.

### Why not merge the whole branch?

- `mvp-issue-12` has older ancestry than current `main`;
- it predates the latest dashboard changes;
- it contains a large audit-only commit;
- a full-tree merge could regress current schemas, monitoring behavior, and UI layout;
- the focused `d71816a` patch is easier to reason about and validate.

---

## Files changed by the preferred hardening commit

Commit `d71816a` changes:

- `.env.example`
- `README.md`
- `backend/baseline/seasonal.py`
- `backend/evaluation/harness.py`
- `backend/incidents/engine.py`
- `backend/integration/evaluation_runtime.py`
- `backend/live_control_tower.py`
- `backend/main.py`
- `docs/MVP_12_CODEX_HANDOFF.md`
- `docs/mvp_03_evaluation.md`
- `frontend/app.py`
- `frontend/live_data.py`
- `frontend/pages/0_Client.py`
- `frontend/pages/1_Judge_Lab.py`
- `tests/test_detector.py`
- `tests/test_evaluation_harness.py`
- `tests/test_evaluation_runtime.py`
- `tests/test_frontend_live_data.py`
- `tests/test_live_control_tower.py`
- `tests/test_seasonal_baseline.py`

## Complete current-main versus hardening-tree differences

The complete trees differ in:

- `.env.example`
- `DECISIONS.md`
- `README.md`
- `backend/baseline/seasonal.py`
- `backend/evaluation/harness.py`
- `backend/incidents/engine.py`
- `backend/integration/evaluation_runtime.py`
- `backend/live_control_tower.py`
- `backend/main.py`
- `backend/schemas.py`
- `docs/MVP_12_CODEX_HANDOFF.md`
- `docs/mvp_03_evaluation.md`
- `frontend/app.py`
- `frontend/live_data.py`
- `frontend/pages/0_Client.py`
- `frontend/pages/1_Judge_Lab.py`
- `tests/test_detector.py`
- `tests/test_evaluation_harness.py`
- `tests/test_evaluation_runtime.py`
- `tests/test_frontend_live_data.py`
- `tests/test_health.py`
- `tests/test_live_control_tower.py`
- `tests/test_seasonal_baseline.py`

`DECISIONS.md`, `backend/schemas.py`, and `tests/test_health.py` differ because current `main` contains later work that is absent from the older hardening tree. They are not modified by the `d71816a` patch and should be preserved during a cherry-pick.

---

## Final audit answers

### A. Root cause

The hardening was committed on separate branches and never merged into `main`. Current `main` later advanced independently.

### B. Location

Preferred source: `codex/mvp-12-hardening-backup` at `d71816a`.

Remote-backed equivalent: `origin/mvp-issue-12`, containing equivalent code at `e25f08a`, with tip `ad5c977`.

### C. Safest recovery

Create a recovery branch from current `main`, cherry-pick the focused `d71816a` commit, preserve later-main behavior, and manually reconcile the four overlapping runtime/frontend files.

### D. Recover or reimplement

Recover the existing commit. Do not reimplement the hardening from scratch and do not merge the complete branch wholesale.

### E. Affected files and commits

Primary commits:

- `b234ce8`: hardening base
- `d71816a`: preferred recovery commit
- `e25f08a`: identical hardening tree on `mvp-issue-12`
- `ad5c977`: audit-only follow-up
- `6a52dfd`: later main UI work
- `2d7fba2`: later main monitoring work

Primary conflict/reconciliation files:

- `backend/integration/evaluation_runtime.py`
- `backend/live_control_tower.py`
- `backend/main.py`
- `frontend/pages/0_Client.py`

---

## Requested response from ChatGPT

Return an audit response only.

1. Confirm whether the evidence supports the stated root cause.
2. Evaluate whether `d71816a` is the correct recovery source.
3. Review the conflict and semantic-reconciliation risks.
4. State whether the recovery should preserve both monitoring APIs or consolidate them.
5. Identify any missing acceptance checks.
6. Provide a GO / NO-GO recommendation for starting recovery.
7. Do not provide mutating Git commands or implementation code until explicitly approved.

