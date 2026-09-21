# Clinical safety escalation queue

Stage 21 adds a cross-visit operational queue for safety findings whose latest
verified review event is `escalated`. It is derived from the existing immutable
evaluation and hash-chained review records and introduces no migration, new
clinical rule, recommendation or external notification channel.

## Meaning of an open item

An item is open only when its complete review chain passes integrity validation
and its final event is `escalated`. A physician `assessed` event removes the item
from the open queue without deleting or changing any earlier event. The original
evaluation, finding, escalation and assessment remain readable in the visit
safety inbox.

The queue is ordered by escalation timestamp, oldest first, with the finding ID
as a deterministic tie-breaker. This is an administrative ordering only. It is
not clinical priority, severity ranking, triage, a response-time promise or
permission to begin or continue treatment.

An escalation remains visible when a later intake/report correction makes its
evaluation snapshot stale. The response marks whether the snapshot matches the
current clinical-context hash; staff must open the visit and apply independent
clinical judgment.

## API

`GET /api/v1/safety/escalations?offset=0&limit=50`

- Allowed roles: active `admin`, `physician` and `nurse`.
- `limit` is 1–100 and the response reports `total`, `offset` and `limit`.
- The service validates every stored review chain before filtering, so a
  one-sided corrupt non-escalated chain fails the request closed with `409`
  instead of silently hiding a possible item.
- The aggregate deliberately omits review notes, actor snapshots, condition
  traces and patient values. Staff open the exact visit to read the verified
  timeline.
- Every queue and item response states that it is neither clinical-priority
  order nor clinical clearance.

The current implementation derives the queue from append-only source records and
returns a bounded page. Benchmark the intended database size before production;
a future indexed projection must preserve source-chain verification and cannot
become an independently editable status table.

## Console journey

The **صف ارجاع‌های باز** section appears inside `/app/` → **صندوق ایمنی
بالینی**. It loads the first 50 open items and shows only minimum routing data:
visit ID, escalation time, rule identity, configured action, severity and context
freshness. Selecting an item opens the existing visit safety inbox, where an
authorized physician or nurse can read the full immutable timeline and use the
existing role-gated actions.

No note or patient value is rendered in the cross-visit list. All strings remain
text-only, bearer tokens stay in memory and the browser rejects a response that
claims clinical priority or clearance.

## Controlled acceptance

Before staff use, validate with synthetic staging records:

1. admin/physician/nurse visibility and operator/viewer denial;
2. direct escalation appearing in the queue;
3. physician assessment removing only the corresponding open item;
4. stale-context marking without losing the immutable escalation;
5. pagination and oldest-first administrative ordering;
6. fail-closed behavior for a corrupt chain; and
7. Persian terminology, keyboard navigation, small-screen layout and actual
   staffing ownership.

## Explicitly deferred

- SMS, email, push, pager or webhook delivery and delivery receipts;
- clinical priority, triage, escalation deadlines or response-time enforcement;
- assignment, handoff, on-call schedules and alert-fatigue policy;
- override, dismissal, suppression, treatment authorization or clearance;
- diagnosis, recommendation, autonomous interpretation or patient-data learning;
- external terminology validation, digital signatures and trusted timestamps.

Those items require explicit clinical, operational, privacy and deployment
decisions. A visible queue and green CI are engineering controls only, not
clinical validation or production authorization.
