# Research Firewall Policy

## Forbidden Fields (any nesting level)

- price, current_price, market_price, market_probability, implied_probability
- bid, best_bid, ask, best_ask
- mid, midpoint, spread
- volume, price_history, market_trend
- betting_odds, trader_sentiment, orderbook

## Forbidden Source Domains

- polymarket.com, polymarket
- predictionmarket.com, kalshi.com

## Detection

- Recursive key scan at all nesting levels (dict and list).
- Source URL domain scan on evidence entries.
- Commodity prices (e.g. "coffee price") are NOT flagged — only
  prediction-market-specific field names trigger contamination.

## Violation

`MarketTaintError` is raised. The experiment MUST fail closed — no forecast is
generated from a contaminated package.
