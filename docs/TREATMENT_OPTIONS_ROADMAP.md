# Similar-Patient Treatment Options Roadmap

The treatment options roadmap is clinician-facing decision support built from
the local append-only outcomes registry. It does not choose a treatment. It
builds a transparent set of active protocol options that a physician may review,
modify or reject.

## Endpoint

`GET /api/v1/visits/{visit_id}/treatment-options-roadmap`

Allowed roles:

- `physician`
- `admin`

No patient, visit or treatment identifier from a historical cohort is returned.
Only aggregate metrics and immutable outcome hashes used for an eligible
reportable window are exposed.

## Safety gate

The roadmap returns no options until the visit has:

1. a final structured clinical intake;
2. a safety evaluation matching the exact current clinical-context hash; and
3. no safety finding whose latest review state remains unreviewed,
   acknowledged or escalated.

An assessed finding does not mean clearance. The roadmap response always keeps
`is_clinical_clearance=false`.

If safety is missing, stale or still pending review, the endpoint returns a
traceable blocked status with an empty option list.

## Deterministic similarity policy

Version 1 uses only structured variables that the system can reproduce:

- same normalized body region is mandatory;
- the current patient's own historical outcomes are excluded;
- if target age is known, historical age must be known and within 15 years;
- if target baseline pain is known, historical baseline pain must be known and
  within 3 points on the 0–10 scale;
- if target symptom-duration band is known, the historical band must match;
- if target laterality group is known, the historical group must match;
- a historical outcome is excluded when the historical visit's current
  structured-context hash no longer equals the context hash frozen into that
  outcome.

The engine does not use free-text diagnosis similarity, embeddings or an opaque
machine-learning similarity score in this version.

## Follow-up windows

The roadmap uses fixed windows to reduce cherry-picking:

- early: day 28–70;
- intermediate: day 71–180;
- long term: day 181–365.

Only one observation per unique patient, protocol version and follow-up window
is used. When several observations exist, the one closest to the fixed window
midpoint is selected; ties prefer the later recorded observation.

## Minimum cohort and metrics

A protocol option is shown only when at least one window contains five unique
similar patients and the exact protocol code/version is currently active.

Five is a minimum reporting threshold, not a claim of strong evidence. Data
volume is labelled separately as very limited, limited, moderate or substantial.

For each reportable window the system can show:

- unique-patient count;
- outcome distribution;
- observed proportion recorded as improved;
- Wilson 95% interval around that observed proportion;
- median patient rating;
- median physician rating;
- median baseline-to-follow-up pain change;
- median follow-up function score;
- proportion with a documented adverse event.

A metric is suppressed when fewer than five records contain the value needed
for that metric.

Patient and physician ratings remain separate. No composite success score is
calculated.

## Option generation is not ranking

Options are ordered only by protocol code and version. The service does not
sort protocols by improvement proportion, ratings, pain change, adverse events
or any combined score.

A protocol card means only:

- the exact protocol version is active;
- local outcomes exist in the same body region;
- the deterministic similarity rules were met;
- at least one follow-up window reached the minimum local cohort size.

It does not mean the protocol is superior, indicated, safe for this patient or
supported by adequate external evidence.

## External evidence

Local clinic outcomes are observational and must remain separate from the
governed medical-knowledge and clinician-selected evidence workflows. The
roadmap does not automatically infer that an external paper or guideline
applies to a patient or to a protocol.

The physician should independently review relevant approved evidence before
selecting, modifying or rejecting an option.

## Bias and interpretation limits

The roadmap cannot remove confounding, selection bias, concomitant treatment,
loss to follow-up, documentation bias, protocol drift or measurement-quality
problems. It does not establish causality or produce an individualized
probability of benefit or harm.

The roadmap hash binds the current target profile, safety status, cohort
definition, exclusion counts, aggregate options and source outcome hashes. It
supports auditability; it is not a clinical signature or authorization.
