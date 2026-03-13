# nexa-bidkit

[![CI](https://github.com/phasenexa/nexa-bidkit/actions/workflows/ci.yml/badge.svg)](https://github.com/phasenexa/nexa-bidkit/actions/workflows/ci.yml)

A Python library for generating day-ahead and intraday auction bids for European power markets. EUPHEMIA-compatible output formats.

Part of the Phase Nexa ecosystem.

## Features

- **Type-safe bid construction**: Pydantic v2 models with strict validation
- **DataFrame-first API**: Build curves from pandas DataFrames
- **15-minute MTU support**: Handle both hourly and quarter-hourly market time units
- **EUPHEMIA compatibility**: Output formats compatible with European power market coupling

## Installation

```bash
pip install nexa-bidkit
```

## Quick Start

### Constructing curves from DataFrames

```python
import pandas as pd
from decimal import Decimal
from datetime import datetime
from zoneinfo import ZoneInfo
from nexa_bidkit import (
    CurveType,
    MTUDuration,
    MTUInterval,
    from_dataframe,
)

# Your bid data as a DataFrame
df = pd.DataFrame({
    "price": [10.5, 25.0, 45.0, 80.0],
    "volume": [50, 100, 75, 25],
})

# Define the MTU this curve applies to
mtu = MTUInterval.from_start(
    datetime(2026, 4, 1, 13, 0, tzinfo=ZoneInfo("Europe/Oslo")),
    MTUDuration.QUARTER_HOURLY
)

# Convert to a validated supply curve
curve = from_dataframe(df, curve_type=CurveType.SUPPLY, mtu=mtu)

print(f"Total volume: {curve.total_volume} MW")
print(f"Price range: {curve.min_price} - {curve.max_price} EUR/MWh")
```

### Combining multiple bids

```python
from nexa_bidkit import merge_curves

# Combine bids from multiple plants
plant_curves = [
    from_dataframe(plant1_df, curve_type=CurveType.SUPPLY, mtu=mtu),
    from_dataframe(plant2_df, curve_type=CurveType.SUPPLY, mtu=mtu),
]
portfolio = merge_curves(plant_curves, aggregation="sum")
```

### Applying constraints

```python
from nexa_bidkit import clip_curve, filter_zero_volume, aggregate_by_price

# Clean and constrain curve
curve = from_dataframe(df, curve_type=CurveType.SUPPLY, mtu=mtu)
curve = filter_zero_volume(curve)  # Remove empty steps
curve = clip_curve(
    curve,
    min_price=Decimal("0"),  # No negative prices
    max_volume=Decimal("500")  # Capacity constraint
)
curve = aggregate_by_price(curve)  # Consolidate for smaller message size
```

## Core Concepts

### Market Time Units (MTU)

EU power markets transitioned to 15-minute MTUs on 30 Sept 2025. The library handles both:

- `MTUDuration.QUARTER_HOURLY` - 15-minute intervals (96 per day)
- `MTUDuration.HOURLY` - Hourly intervals (24 per day)

### Price-Quantity Curves

Merit-order curves represent supply or demand:

- **Supply curves**: Steps sorted ascending by price (cheapest generation first)
- **Demand curves**: Steps sorted descending by price (highest-value consumption first)

### EUPHEMIA Bid Types

- Simple hourly bids (price-quantity pairs per MTU)
- Block bids (fixed price/volume across consecutive MTUs)
- Linked block bids (parent-child relationships)
- Exclusive groups (mutually exclusive block bids)

## Development

### Setup

```bash
# Install poetry
curl -sSL https://install.python-poetry.org | python3 -

# Install dependencies
poetry install

# Run tests
poetry run pytest

# Type checking
poetry run mypy src

# Linting
poetry run ruff check src
```

### Running tests

```bash
# All tests with coverage
make test

# Or using poetry directly
poetry run pytest tests/ -v
poetry run pytest --cov=nexa_bidkit --cov-report=term-missing
```

## License

MIT

## Contributing

This is an internal Phase Nexa project. For issues or questions, contact the Nexa team.
