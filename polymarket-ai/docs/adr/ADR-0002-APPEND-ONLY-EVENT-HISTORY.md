# ADR-0002: Append-Only Experiment History

Status: ACCEPTED DESIGN PRINCIPLE

## Context

The system must preserve failed samples, forecast versions, baseline timing, and evaluation history. Mutable status rows can hide rewrites and concurrent race outcomes.

## Decision

Use append-only events with:

- sequence number;
- previous hash;
- event hash;
- experiment identity;
- market identity where applicable;
- guarded lifecycle transitions.

Critical artifacts are content-addressed or hash-referenced from events.

## Consequences

- Forecast V2 does not overwrite V1.
- Failures remain visible.
- Restart recovery can reconstruct state.
- Tampering can be detected.
- Concurrency needs transaction-like guarded append.
