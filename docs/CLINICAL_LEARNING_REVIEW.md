# Clinical Learning Review

The Clinical Learning Review is a read-only, aggregate data-quality view over the
local decision → treatment → outcome dataset.

Its purpose is to answer a less glamorous but much more important question than
"which treatment is winning?": is the clinic collecting enough complete,
traceable follow-up data to support responsible local learning?

## Endpoint

`GET /api/v1/learning/review`

Allowed roles:

- `admin`
- `physician`

No patient names, patient codes, visit identifiers or individual clinical
narratives are returned.

## What it measures

The global review reports:

- total immutable clinician decision events;
- current decisions;
- current actionable decisions;
- Treatments linked to a clinician decision;
- legacy or otherwise unlinked Treatments;
- Treatments with at least one structured Outcome;
- total structured Outcome records;
- coverage of patient rating;
- coverage of physician rating;
- coverage of follow-up pain score;
- coverage of function score;
- count of Outcome records containing a documented adverse event.

Each exact protocol code/version is then reviewed separately for:

- decision references;
- current-decision references;
- Treatment count;
- Decision-linked Treatment count;
- Treatments with Outcome data;
- Outcome record count;
- follow-up counts in the standard early, intermediate and long-term windows;
- completeness of patient rating, physician rating, pain and function fields;
- simple data-quality flags;
- sample-volume label based on the number of Treatments with Outcome data.

## Data-volume labels

The volume label describes only the amount of local structured follow-up data:

- insufficient: fewer than 5 Treatments with Outcome data;
- very limited: 5–9;
- limited: 10–29;
- moderate: 30–99;
- substantial: 100 or more.

It is not an evidence grade and is not a treatment-quality score.

## No effectiveness league table

This review deliberately does not calculate:

- a protocol success score;
- a composite learning score;
- cross-protocol effectiveness ranking;
- individualized probability of benefit;
- automated protocol promotion or demotion.

Outcome-effect observations remain in the similar-patient roadmap, where they
are separated into defined follow-up windows and minimum-cohort rules.

Mixing six-week and twelve-month outcomes into one attractive number would make
the dashboard simpler and the inference worse. This review therefore focuses on
data readiness and missingness.

## Traceability

Before aggregation, stored clinician decisions and treatment outcomes are
individually integrity-checked.

A Decision-linked Treatment must point to an existing immutable Decision and its
stored Decision SHA-256 must match exactly. Broken provenance causes the endpoint
to fail closed rather than silently exclude the record.

The response contains:

- `source_manifest_sha256`, a canonical digest over the sorted immutable
  Decision and Outcome hashes used by the review;
- `review_sha256`, a canonical digest over the aggregate review payload.

The generated timestamp is excluded from the review digest, so the same
underlying data produces the same review hash.

## Interpretation

This is an operational and clinical-data-quality instrument.

It can show that a protocol has, for example, very limited local follow-up data
or poor rating completeness. It cannot conclude that another protocol is more
effective or should be preferred.

Local outcomes remain observational and subject to confounding, selection bias,
loss to follow-up, measurement quality, concomitant treatment and documentation
bias.

The review never changes a protocol automatically.
