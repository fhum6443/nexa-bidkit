# EXAA Order Model Reference

Reference document for EXAA (Energy Exchange Austria) Trading API order structures.
This describes the exchange's order model, validation rules, and wire format as documented
in the EXAA Trading API Technical Description v1.6, OpenAPI spec, and supporting documents.

This is a domain reference, not an implementation spec. Use it to inform design decisions
when building EXAA exchange support into nexa-bidkit.

---

## Auction Types

EXAA runs two day-ahead auction types. No intraday auctions or continuous markets.

### Classic Auction (10:15 CET)

EXAA's own local clearing for Austria, Germany, and the Netherlands.
Auction ID format: `Classic_YYYY-MM-DD` (delivery date).

Supports all three product types: hourly, block, and 15-minute.
Has a unique post-trading phase after clearing where residual volume is available
at the clearing price.

### Market Coupling Auction (12:00 CET)

SDAC/EUPHEMIA market coupling.
Auction ID format: `MC_YYYY-MM-DD` (delivery date).

Supports hourly and block products only. No 15-minute products.
Block orders are restricted to STEP + fill-or-kill only.

---

## Product Types

Products are returned dynamically per auction via `GET /auctions/{auction-id}`.
Product IDs are exchange-assigned strings. The delivery time periods are provided
alongside each product ID in the auction response.

### Hourly Products

One product per delivery hour. Available in both auction types.

Example IDs and their delivery periods:
```
hEXA01  -> [{from: "00:00:00", to: "01:00:00"}]
hEXA02  -> [{from: "01:00:00", to: "02:00:00"}]
...
hEXA24  -> [{from: "23:00:00", to: "24:00:00"}]
```

### 15-Minute Products

One product per quarter-hour. Classic auction only. Not available for time spread accounts.

Example IDs and their delivery periods:
```
qEXA01_1 (00:00 - 00:15)  -> [{from: "00:00:00", to: "00:15:00"}]
qEXA01_2 (00:15 - 00:30)  -> [{from: "00:15:00", to: "00:30:00"}]
qEXA01_3 (00:30 - 00:45)  -> [{from: "00:30:00", to: "00:45:00"}]
qEXA01_4 (00:45 - 01:00)  -> [{from: "00:45:00", to: "01:00:00"}]
...
```

### Block Products

Products spanning multiple delivery hours. Some have non-contiguous delivery periods.

Example IDs and their delivery periods:
```
bEXAbase (01-24)              -> [{from: "00:00:00", to: "24:00:00"}]
bEXApeak (09-20)              -> [{from: "08:00:00", to: "20:00:00"}]
bEXAoffpeak (01-08_21-24)     -> [{from: "00:00:00", to: "08:00:00"},
                                  {from: "20:00:00", to: "24:00:00"}]
bEXAdream (01-06)             -> [{from: "00:00:00", to: "06:00:00"}]
bEXAearlytwin (09-10)         -> [{from: "08:00:00", to: "10:00:00"}]
bEXAlunch (11-14)             -> [{from: "10:00:00", to: "14:00:00"}]
```

Note: Block delivery periods use non-contiguous arrays for products like off-peak.
Location spread block products are limited to BASELOAD and PEAK only.

---

## Trade Accounts

Orders are grouped by trade account. Each account has:

| Field | Type | Description |
|-------|------|-------------|
| accountID | string | Identifier, e.g. "APTAP1" |
| controlArea | string | TSO area: "APG" (AT), "Amprion" (DE), "TenneT" (NL/DE) |
| isSpreadAccount | boolean | True for location spread accounts |
| accountIDSink | string or null | Sink account for spread relationships |
| controlAreaSink | string or null | Sink TSO area |
| originType | enum | "GREY", "GREEN", or "MARKET_COUPLING" |
| constraints | object | Per-account trading limits (see below) |

### Account Constraints

Returned per account in the auction response. All nullable (null = no limit).

| Field | Type | Description |
|-------|------|-------------|
| maxVolume | number or null | Maximum volume per product (MWh/h) |
| maxPriceBuy | number or null | Maximum buy price (EUR/MWh) |
| minPriceSell | number or null | Minimum sell price (EUR/MWh) |

---

## Order Submission Format

Orders are submitted via `POST /exaa-trading-api/V1/auctions/{auction-id}/orders`.

**Critical: this is a full-replacement operation per account.** All existing orders for any
account included in the request are completely replaced. Orders for accounts NOT
mentioned in the request are untouched.

### Top-Level Structure

```json
{
  "units": {
    "price": "EUR",
    "volume": "MWh/h"
  },
  "orders": [
    {
      "accountID": "APTAP1",
      "isSpreadOrder": false,
      "accountIDSink": null,
      "hourlyProducts": { ... },
      "blockProducts": { ... },
      "15minProducts": { ... }
    }
  ]
}
```

The `units` object is fixed: `{"price": "EUR", "volume": "MWh/h"}`.

### Product Type Container

Each of `hourlyProducts`, `blockProducts`, and `15minProducts` shares this structure:

```json
{
  "typeOfOrder": "LINEAR",
  "products": [
    {
      "productID": "hEXA01",
      "fillOrKill": false,
      "priceVolumePairs": [
        {"price": 40.00, "volume": 250},
        {"price": 43.95, "volume": 150}
      ]
    }
  ]
}
```

If a product type container is `null` or absent, no products of that type are bid on.
**However, if the container is present with a null or empty products list, any existing
orders of that product type for the specified account are deleted.**

`typeOfOrder` is set at the product-type level and applies to ALL products within
that container. It cannot differ between products of the same type.

### Price/Volume Pairs

| Field | Type | Description |
|-------|------|-------------|
| price | number or "M" | EUR/MWh, 2 decimal places. Or string "M" for market orders. |
| volume | number | MWh/h, 1 decimal place. Positive = buy, negative = sell. |

### Market Orders

A market order has no specific price. Submitted as:
```json
{"price": "M", "volume": 100}
```

Only one market order is allowed per product.
Market orders cannot be used with LINEAR type (only STEP).

---

## Order Type Rules

`typeOfOrder` can be `LINEAR` or `STEP`:

- **STEP**: Volume is allocated at each price level independently (step function).
- **LINEAR**: Volume is interpolated linearly between price/volume points.

### Allowed Combinations by Auction Type

#### Classic Auction (10:15) - Normal Order Submission

| Product Type | Account Type | typeOfOrder | fillOrKill |
|-------------|--------------|-------------|------------|
| 15minProducts | grey | STEP or LINEAR | false only |
| hourlyProducts | grey or green | STEP or LINEAR | false only |
| blockProducts | grey or green | STEP or LINEAR | STEP: true or false; LINEAR: false only |
| blockProducts (location spread, BASE/PEAK only) | grey | STEP or LINEAR | STEP: true or false; LINEAR: false only |

#### Market Coupling Auction (12:00)

| Product Type | Account Type | typeOfOrder | fillOrKill |
|-------------|--------------|-------------|------------|
| hourlyProducts | grey | STEP or LINEAR | false only |
| blockProducts | grey | STEP only | true only |

#### Classic Auction - Post-Trading Order Submission

| Product Type | Account Type | typeOfOrder | fillOrKill |
|-------------|--------------|-------------|------------|
| hourlyProducts | grey | n/a | true or false |
| blockProducts | grey | n/a | true or false |

---

## Validation Rules

### Price Constraints

- Prices must be in range: -500 < price < 4000 EUR/MWh (exclusive on both ends).
- Orders submitted at exactly -500 or 4000 are rejected. Use market orders ("M") instead.
- Prices are EUR/MWh with exactly 2 decimal places.

### Volume Constraints

- Volumes are MWh/h with exactly 1 decimal place.
- Positive = buy, negative = sell.
- Zero-volume-only bids are invalid (error F034).
- Per-account constraints (maxVolume, maxPriceBuy, minPriceSell) are enforced server-side.

### Curve Rules

- **Monotonic rule (F010)**: Bids must be monotonic per direction (buy/sell) within a product.
- **Distinct prices (F013)**: All prices within a single product's price/volume pairs must be distinct.
- **Max pairs**: No more than 30,000 price/volume pairs per POST request.
- **Max body size**: 2 MB per request.

### Product Rules

- Duplicate product IDs within a product type are rejected (F020).
- Product IDs must match those returned by the auction (F015).
- Product types must be valid for the auction type (F015, F019).

---

## Location Spread Orders

Location spread orders trade between two control areas (e.g. AT <-> DE).

Submitted by setting:
```json
{
  "accountID": "ACCOUNT_AT",
  "isSpreadOrder": true,
  "accountIDSink": "ACCOUNT_DE"
}
```

Rules:
- First account (source) is always Austrian or Dutch leg.
- Second account (sink) is always the German leg.
- Only BASELOAD and PEAK block products are available.
- To delete, specify the source account only. Sink account in DELETE is rejected (F032).
- Source and sink must be different accounts (F017).

## Time Spread Orders

Time spread accounts follow normal Classic account submission rules, except:
- 15minProducts are NOT available.
- `isSpreadOrder` must be `false`.
- `accountIDSink` must be `null`.
- POST/DELETE with MC accounts in a time spread relationship are rejected.

---

## Post-Trading Orders

Post-trading is unique to the Classic (10:15) auction. After clearing, residual volume
becomes available at the clearing price.

### Post-Trading Info Response

Available once auction reaches `POSTTRADE_OPEN` state.

Per product: `productID`, `price` (clearing price), `volumeAvailable`
(positive = buy volume available, negative = sell volume available).

Products are grouped into hourlyProducts, blockProducts, 15minProducts.

### Post-Trading Order Format

Simpler than normal orders. No price (clearing price is used). No typeOfOrder.

```json
{
  "units": {"price": "EUR", "volume": "MWh/h"},
  "orders": [
    {
      "accountID": "APTAP1",
      "hourlyProducts": [
        {"productID": "hEXA01", "fillOrKill": false, "volume": 12}
      ],
      "blockProducts": [],
      "15minProducts": []
    }
  ]
}
```

Post-trading constraints:
- Grey accounts only (no green, no MC, no spread - F028).
- Volume must not exceed `volumeAvailable` (F024).
- Volume must not exceed user-specific limits (F025).
- Buy must be buy and sell must be sell - you cannot reverse direction (F027).
- fillOrKill: both true and false are allowed.

---

## Results Format

### Trade Results

Per-account results. Available from `AUCTIONED` (Classic) or `PRELIMINARY_RESULTS` (MC).
Final once auction reaches `FINALIZED`.

Per product:
```json
{"productID": "hEXA01", "price": 42.40, "volumeAwarded": 50.0}
```
`volumeAwarded`: positive = bought, negative = sold.

### Market Results

Market-wide results. Same availability timing as trade results.

Per product, per price zone:
```json
{
  "productID": "hEXA01",
  "originType": "GREY",
  "priceZones": [
    {"priceZoneID": "AT", "price": 40.00, "volume": 250},
    {"priceZoneID": "DE", "price": 43.95, "volume": 150}
  ]
}
```

Price zones are typically: AT, DE, NL (depending on auction configuration).

### Trade Confirmations

Final confirmations. Available only at `FINALIZED` / `FINALIZED_FALLBACK`.
Shows all trades for all accounts linked to the company.

Per confirmation:
```json
{
  "companyID": "Company1",
  "accountID": "APTAP1",
  "controlArea": "APG",
  "originType": "GREY",
  "productID": "bEXAbase (01-24)",
  "buyOrSell": "sell",
  "price": 43.01,
  "volume": 300,
  "referenceNumber": "0034402520191027"
}
```

---

## Auction Lifecycle States

### Classic Auction

```
TRADE_OPEN -> TRADE_CLOSED -> AUCTIONING -> AUCTIONED ->
POSTTRADE_OPEN -> POSTTRADE_CLOSED -> POSTAUCTIONING -> POSTAUCTIONED -> FINALIZED
```

| State | Orders | Post-Trading | Results | Confirmations |
|-------|--------|-------------|---------|---------------|
| TRADE_OPEN | read + write | - | - | - |
| TRADE_CLOSED | read only | - | - | - |
| AUCTIONING | read only | - | - | - |
| AUCTIONED | read only | - | preliminary | - |
| POSTTRADE_OPEN | read only | read + write | preliminary | - |
| POSTTRADE_CLOSED | read only | read only | preliminary | - |
| POSTAUCTIONING | read only | read only | preliminary | - |
| POSTAUCTIONED | read only | read only | preliminary | - |
| FINALIZED | read only | read only | final | available |

### Market Coupling Auction

Normal flow:
```
TRADE_OPEN -> TRADE_CLOSED -> AUCTIONING -> PRELIMINARY_RESULTS -> FINALIZED
```

Fallback flow (if SDAC coupling fails):
```
TRADE_OPEN_FALLBACK -> TRADE_CLOSED_FALLBACK -> AUCTIONING_FALLBACK ->
AUCTIONED_FALLBACK -> FINALIZED_FALLBACK
```

| State | Orders | Results | Confirmations |
|-------|--------|---------|---------------|
| TRADE_OPEN / _FALLBACK | read + write | - | - |
| TRADE_CLOSED / _FALLBACK | read only | - | - |
| AUCTIONING / _FALLBACK | read only | - | - |
| PRELIMINARY_RESULTS / AUCTIONED_FALLBACK | read only | preliminary | - |
| FINALIZED / FINALIZED_FALLBACK | read only | final | available |

---

## Error Codes

Errors are returned as:
```json
{
  "errors": [
    {"code": "F010", "message": "Monotonic rule is violated", "path": "[json path]"}
  ]
}
```

### Error Code Reference

**Authentication (Axxx) - HTTP 403:**
- A001: Username/PIN wrong
- A002: Passcode (RSA) wrong or expired
- A003: Passcode (RSA) missing
- A004: Forbidden (not authorised for function)

**Syntax (Sxxx) - HTTP 400:**
- S001: Unrecognized JSON field
- S002: Invalid value type
- S003: JSON parsing error
- S004: Type mismatch
- S005: Invalid query parameter format

**Functional (Fxxx) - HTTP 400/404/409:**
- F001: Post-trading not available (not Classic auction) [404]
- F002-F004: Results not yet available (auction state too early) [409]
- F005: Auction not yet in post-trading state [409]
- F006: Auction not found or closed [409]
- F007: Trade account not found or not accessible [400]
- F008: Auction not open for trading [409]
- F009: Invalid units [400]
- F010: Monotonic rule violated [400]
- F011: Account/auction spread mismatch [400]
- F012: Trade constraint violated [400]
- F013: Prices not distinct [400]
- F014: Invalid fillOrKill for auction/product/type combination [400]
- F015: Invalid product type or product ID [400]
- F016: Invalid typeOfOrder for auction/context [400]
- F017: Source and sink accounts must differ [400]
- F018: No trade account provided [400]
- F019: Product type not allowed in post-trading [400]
- F020: Duplicate products [400]
- F021: Volume or price exceeds global limit [400]
- F022: Values exceed auction-specific limits (use "M" for market orders at boundary) [400]
- F023: Too many price/volume pairs [400]
- F024: No volume available (post-trading) [400]
- F025: Post-trading volume exceeds user limits [400]
- F026: Trade zone not valid for auction [400]
- F027: Post-trading direction mismatch [400]
- F028: Spread accounts not allowed in post-trading [400]
- F029: Too many market orders (max 1 per product) [400]
- F030: Account origin type doesn't match auction [400]
- F031: Price zone mismatch [400]
- F032: Sink account not allowed (use source for DELETE) [400]
- F033: Internal error - too many trade relations [400]
- F034: Zero volume bids [400]

**Request (Rxxx):**
- R001: Method not allowed [405]
- R002: Resource not found [404]
- R003: Unsupported media type [415]
- R004: Request body too large [400]

**Value (Vxxx) - HTTP 400:**
- V001: Value must not be zero
- V002: Invalid decimal format
- V003: Value must not be null or empty
- V004: Value must not be null
- V005: Value must match pattern

**Unspecific (Uxxx):**
- U001: Unhandled server error [500]
- U002: Unhandled client error [400]

---

## Source Documents

This reference was compiled from:
- EXAA Trading API Technical Description v1.6 (July 2025)
- EXAA Trading API OpenAPI Specification (exaa-trading-api.yaml)
- EXAA Trading API General Information v1.1 (November 2023)
- EXAA Trading API 2-Factor Authentication Extension v3.2 (November 2025)
