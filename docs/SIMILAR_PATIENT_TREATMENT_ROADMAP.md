# Similar-Patient Treatment Options Roadmap

The treatment options roadmap is a physician-facing decision-support view built
from the clinic's own structured, immutable treatment outcomes.

It does not choose treatment. It does not rank protocols. It does not claim that
a local observed outcome was caused by a treatment. Its purpose is narrower:
show several reviewable protocol options when enough reproducible local data
exist for patients with a predefined set of similar structured features.

## Endpoint

`GET /api/v1/visits/{visit_id}/treatment-options-roadmap`

Allowed roles:

- `physician`
- `admin`

The endpoint is read-only.

## Safety gate

The roadmap does not expose treatment options unless:

1. the visit has a final structured clinical intake;
2. the current body region is known;
3. a safety evaluation exists for the exact current clinical-context hash;
4. findings in that current evaluation have no unresolved review state.

The safety gate is fail-closed. A missing, stale or pending-review evaluation
returns a blocked roadmap with no treatment options.

A current safety evaluation is still not clinical clearance.

## Similar-patient cohort v1

Version 1 intentionally uses only structured variables that the current 4B-MOS
schema can reproduce consistently:

- same normalized body region;
- patient age at the historical visit, within 15 years when the target age is
  known;
- baseline pain score, within 3 points when the target score is known;
- the same symptom-duration band when the target duration is known;
- the same laterality group when the target laterality is known.

The current patient's own prior outcomes are excluded from the similar-patient
cohort.

Historical outcomes are also excluded when the exact historical clinical
context used when the outcome was recorded can no longer be reproduced from the
current immutable record chain. The engine does not silently rematch those
records against a later context.

## Follow-up windows

Outcomes are summarized separately in predefined windows:

- early: 28 to 70 days;
- intermediate: 71 to 180 days;
- long term: 181 to 365 days.

For a given patient, protocol and follow-up window, at most one observation is
used. The observation closest to the window midpoint is selected
deterministically.

## Minimum cohort threshold

No window-level result is reportable below 5 unique patients.

Below that threshold, metrics are suppressed rather than converted into a
percentage, median or other deceptively precise number.

Local data volume is described only as:

- insufficient: fewer than 5;
- very limited: 5 to 9;
- limited: 10 to 29;
- moderate: 30 to 99;
- substantial: 100 or more.

These labels describe sample size, not treatment quality.

## Reported observations

For reportable windows the roadmap can display:

- observed outcome distribution;
- observed improvement proportion;
- Wilson 95% interval for the observed improvement proportion;
- median patient rating;
- median physician rating;
- median change in pain score, where the baseline is available;
- median function score;
- proportion of observations with a documented adverse event.

Patient and physician ratings remain separate.

The observed-improvement proportion is a descriptive local statistic. It is not
a treatment effect estimate and is not adjusted for confounding.

## Protocol eligibility

A local outcome contributes to a protocol option only when the exact protocol
code and version still exist as an active protocol and its treatment type agrees
with the stored outcome.

A protocol option appears only when at least one follow-up window reaches the
minimum reportable cohort size.

Options are ordered by protocol code and version. They are never ordered by
improvement rate, rating, adverse events, a composite score or any inferred
clinical preference.

## Privacy

The roadmap returns aggregate cohort statistics and immutable outcome hashes.
It does not expose patient identifiers, patient codes, names or individual
clinical narratives from the comparison cohort.

## Interpretation limits

Local observational outcomes can be distorted by patient selection,
confounding, concomitant treatment, protocol drift, missing follow-up,
measurement quality and documentation practices.

Similarity on the v1 structured variables does not imply complete biological or
prognostic similarity.

External evidence remains separate. The physician must independently review
relevant evidence, contraindications and patient-specific circumstances before
selecting, modifying or rejecting any option.

The roadmap:

- is not a prescription;
- is not clinical clearance;
- is not a causal analysis;
- does not learn by automatically rewriting protocol rules or knowledge;
- does not select a preferred treatment;
- requires independent physician review.
