# Domain model

Firestore holds production semantics. Collections stay small and semantically clear; runtime state lives in Grafana, not here.

## Project

```text
project_id, name, status, timezone
```

## Scene

```text
scene_id, project_id, name, status, editorial_review_deadline
```

## Shot

```text
shot_id, scene_id, status, priority
```

## Asset

```text
asset_id, shot_id, asset_type, version, status
```

## Job

```text
job_id, asset_id, service, status, priority, expected_duration_seconds
```

## Dependency

```text
dependency_id, from, to, type
```

## Schedule

```text
schedule_id, project_id, events[]
```

The Impact Analyst walks `Dependency` and `Schedule` to turn a technical fault into a schedule risk. Agents read these documents; writes go through the Action Gateway.
