# OpenTelemetry trace contract

Canonical render path:

`editorial.review → vfx.render_request → render.enqueue → worker.render → storage.write`

Each span should include bounded attributes such as service name, job type, scene ID, and outcome. Keep detailed identifiers available through trace attributes rather than high-cardinality metrics.
