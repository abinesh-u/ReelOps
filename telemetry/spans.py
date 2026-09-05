"""Job timelines to the canonical span chain in `docs/telemetry-contract.md`.

```text
vfx.render_request -> render.enqueue -> worker.render -> storage.write
```

`render.enqueue` and `worker.render` are siblings under the request rather than
nested in each other: a render does not happen *inside* its queue wait, and a
trace that says otherwise misleads whoever reads it. `storage.write` is the
tail of the render, so it nests there.

Two details decide whether Tempo receives anything at all:

- The simulator's `trace_id` is 64 bits and OTel needs 128. Widening the
  generator would change how much of the seeded stream each job consumes and
  destroy the calibration, so the run nonce is prepended here instead. That
  also stops two takes of the same seed from colliding into one trace.
- Spans are given a synthetic *remote* parent to carry that trace id. A
  parent-based sampler reads "not sampled" off such a parent and silently drops
  everything, which is why the provider is pinned to `ALWAYS_ON`.
"""

import hashlib
from collections.abc import Callable
from datetime import datetime

from opentelemetry import trace
from opentelemetry.trace import (
    NonRecordingSpan,
    SpanContext,
    Status,
    StatusCode,
    TraceFlags,
    Tracer,
)

from simulator.models import JobAttempt, SceneReview

_MASK64 = (1 << 64) - 1
_MASK128 = (1 << 128) - 1

# Fraction of a completed render spent writing frames out. Derived from the
# simulated duration rather than modelled separately; the render path is what
# the golden scenario degrades.
STORAGE_WRITE_FRACTION = 0.02

WallClock = Callable[[datetime], int]


def derive_trace_id(run_nonce: int, sim_trace_id: str) -> int:
    low = int(sim_trace_id, 16) & _MASK64 if sim_trace_id else 0
    return (((run_nonce & _MASK64) << 64) | low) & _MASK128 or 1


def job_anchor_span_id(job_id: str) -> int:
    """The synthetic parent every attempt of a job hangs from.

    Log records point at it so Grafana can jump from a line to its trace; it is
    the same span id for every retry, which is what makes one job one trace.
    """
    return _span_id("upstream", job_id)


def _span_id(*parts: object) -> int:
    key = "|".join(str(p) for p in parts).encode()
    return int.from_bytes(hashlib.blake2b(key, digest_size=8).digest(), "big") or 1


def _remote_parent(trace_id: int, span_id: int) -> trace.Context:
    context = SpanContext(
        trace_id=trace_id,
        span_id=span_id,
        is_remote=True,
        trace_flags=TraceFlags(TraceFlags.SAMPLED),
    )
    return trace.set_span_in_context(NonRecordingSpan(context))


def emit_job_trace(
    tracer: Tracer,
    attempt: JobAttempt,
    run_nonce: int,
    wall_ns: WallClock,
    base_attributes: dict[str, str],
) -> int:
    """Emit one attempt's spans. Returns the trace id used, for log correlation."""
    trace_id = derive_trace_id(run_nonce, attempt.trace_id)
    parent = _remote_parent(trace_id, job_anchor_span_id(attempt.job_id))

    common = {
        **base_attributes,
        "job.id": attempt.job_id,
        "scene.id": attempt.scene_id,
        "shot.id": attempt.shot_id or "",
        "worker.id": attempt.worker_id,
        "render.attempt": attempt.attempt,
        "render.frames": attempt.frames,
        "outcome": attempt.outcome,
        # Wall-clock spans are compressed by SIM_SPEED; this is the real figure.
        "render.sim_duration_seconds": attempt.duration_seconds,
    }
    queued_ns = wall_ns(attempt.queued_at)
    started_ns = wall_ns(attempt.started_at)
    ended_ns = wall_ns(attempt.ended_at)
    failed = attempt.outcome != "completed"

    root = tracer.start_span(
        "vfx.render_request", context=parent, start_time=queued_ns, attributes=common
    )
    if failed:
        root.set_status(Status(StatusCode.ERROR, attempt.outcome))
    root_context = trace.set_span_in_context(root)

    enqueue = tracer.start_span(
        "render.enqueue", context=root_context, start_time=queued_ns, attributes=common
    )
    enqueue.end(end_time=started_ns)

    render = tracer.start_span(
        "worker.render", context=root_context, start_time=started_ns, attributes=common
    )
    if failed:
        render.set_status(Status(StatusCode.ERROR, attempt.outcome))
    else:
        write_ns = int((ended_ns - started_ns) * STORAGE_WRITE_FRACTION)
        storage = tracer.start_span(
            "storage.write",
            context=trace.set_span_in_context(render),
            start_time=ended_ns - write_ns,
            attributes=common,
        )
        storage.end(end_time=ended_ns)
    render.end(end_time=ended_ns)
    root.end(end_time=ended_ns)
    return trace_id


def emit_review_trace(
    tracer: Tracer,
    review: SceneReview,
    run_nonce: int,
    wall_ns: WallClock,
    base_attributes: dict[str, str],
) -> None:
    """`editorial.review` for a finished scene review, on its own trace."""
    trace_id = derive_trace_id(run_nonce, f"{_span_id('review', review.scene_id):016x}")
    parent = _remote_parent(trace_id, _span_id("upstream-review", review.scene_id))
    span = tracer.start_span(
        "editorial.review",
        context=parent,
        start_time=wall_ns(review.started_at),
        attributes={
            **base_attributes,
            "scene.id": review.scene_id,
            "scene.shots": review.shots,
            "review.wait_seconds": (review.started_at - review.ready_at).total_seconds(),
        },
    )
    span.end(end_time=wall_ns(review.completed_at))
