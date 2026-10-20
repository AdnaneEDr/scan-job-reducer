# Run guide

Requires Python 3.10 or later and the standard library only. Run these commands
from the candidate directory (use python3 instead of python where appropriate):

```sh
python app.py --input inputs/primary.json
python app.py --input inputs/secondary.json
python -m unittest discover -s tests -p '*_test.py' -v
```

On Windows, TESTER.cmd runs both scenarios and the test suite. It tries the
Python launcher, the python command, then an optional bundled Python runtime.

## Verified results

Both fixture commands exit with code 0. All 12 automated tests pass.

| Fixture | Final jobs | Accepted | Rejected |
| --- | --- | --- | --- |
| primary.json | j1 failed (2 attempts), j2 succeeded (1), j3 cancelled (0) | 7 | 6 |
| secondary.json | x succeeded (2 attempts) | 4 | 1 |

Primary rejects event rows 4, 6, 9, 10, 12 and 13. Secondary rejects event e
at row 5 because event d at row 4 has already made the job terminal.
File and top-level validation failures exit with code 2 and a readable stderr
message. Rejected individual events are recorded in the audit and do not
cause the command to fail.

## Technical walkthrough

main parses --input, reads UTF-8 text and converts JSON into Python data.
reduce_jobs validates the policy, job definitions and events array before
creating fresh job states. All jobs initially have state queued, zero attempts
and next_start_at equal to zero.

Events are processed in their supplied order. Each valid nonempty event ID is
reserved on first occurrence, including rejected events. The global watermark
advances for integer timestamps that are at least its current value, even if
another validation rule rejects the event. Earlier times are rejected. Boolean
timestamps are invalid and cannot advance the clock.

After validation, start increments attempts and enters running. Success enters
succeeded. Failure either enters retry_wait with a calculated due time or enters
failed when attempts are exhausted. Cancel enters cancelled. Terminal states
cannot be changed by later events.

For example, primary e3 fails at time 1. With a backoff of 5, its next start is
at 6. Event e4 at time 2 is rejected; e7 at exactly 6 is accepted. Event e8
exhausts the second attempt, so e9 cannot change the resulting failed state.

Each audit entry records the one-based input row, event ID, acceptance and
reason. For known jobs it also contains a copied job snapshot. Copying preserves
the historical state when later events change the current job. The final job
list is sorted by job ID. summary counts accepted and rejected events.
The reducer does not mutate its input or depend on real time.

## Decisions and work log

Priority was the core state machine, validation and reproducible tests. Real
scans, services, persistence and a user interface were deferred as outside scope.

A central difficulty is that rejected events still affect ID reservation and
the global clock. These operations occur before transition validation. The
constructed test with an unknown job at time 10, a subsequent event at 9 and
reuse of the original ID checks these rules independently.

Validation also covers an exact retry boundary and a constructed zero-backoff
case with four events at the same timestamp. Python treats booleans as integers
in some contexts; explicit type checks exclude them as required by the contract.

Assumptions: nonempty strings are accepted literally without trimming; extra
fields are ignored. Multiple validation errors are joined in reason. A known
job's resulting snapshot is stored under audit.job; unknown jobs have no snapshot.

Known limits: this is a local deterministic simulation with no persistence or
execution of scans. A possible next step is additional generated event-stream
tests; no extra infrastructure is required for the current contract.

## AI-use note

AI assistance was used for project explanations, implementation, automated tests
and technical documentation. One accepted output was the retry-time calculation
1 + 5 = 6 for primary event e3. It was checked against event e7 and the automated
retry-boundary test. Both supplied scenarios and all 12 tests were run
successfully, including a local Windows run.
