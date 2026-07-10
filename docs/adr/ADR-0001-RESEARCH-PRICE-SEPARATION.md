# ADR-0001: Research and Market Price Separation

Status: ACCEPTED DESIGN PRINCIPLE

## Context

The core experiment is invalid if the forecast model sees current market price, orderbook, betting odds, or prediction-market commentary before producing and locking its probability.

Prompt instructions alone are insufficient because accidental fields, nested objects, tools, or contaminated parent context can leak market signal.

## Decision

Enforce separation through:

1. tool isolation;
2. input schema restriction;
3. recursive taint validation;
4. blocked source/domain validation;
5. fresh forecast context;
6. durable lock before baseline capture;
7. audit logs and artifact hashes.

## Consequences

- Forecast and market baseline pipelines remain separate until lock.
- Post-lock price capture is allowed only in Market Data/Evaluation Plane.
- Any fallback path that reads price before lock invalidates the sample.
