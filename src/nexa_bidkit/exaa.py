"""EXAA market adapter for nexa-bidkit.

Converts internal bid objects into EXAA Trading API order submission payloads.
Supports Classic (10:15 CET) and Market Coupling (12:00 CET) auction types.

EXAA operates in Austria (AT), Germany (DE-LU), and the Netherlands (NL).
Unsupported bidding zones raise :class:`ValueError`.

The EXAA submission model groups bids by trade account. Callers supply an
``account_id`` string identifying the account to submit under. For portfolios
spanning multiple accounts, call :func:`order_book_to_exaa` once per account
with a filtered :class:`~nexa_bidkit.orders.OrderBook`.

Product IDs are exchange-assigned and returned dynamically per auction via
``GET /auctions/{auction-id}``. Callers must supply a :data:`ProductIdResolver`
to map MTU intervals to product ID strings. For convenience, the standard
helpers :func:`standard_hourly_product_id` and
:func:`standard_quarter_hourly_product_id` generate the well-known IDs
(``hEXA01``–``hEXA24`` and ``qEXA01_1``–``qEXA24_4``) directly from the MTU
start time — useful when the auction's product list follows the canonical
pattern.

.. note::
    EXAA volume sign convention is **opposite** to Nord Pool:
    positive volume = buy, negative volume = sell.

.. note::
    Linked block bids and exclusive groups are not supported by EXAA.
    Passing these bid types to :func:`order_book_to_exaa` raises
    :class:`ValueError`.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from nexa_bidkit.bids import BlockBid, ExclusiveGroupBid, LinkedBlockBid, SimpleBid
from nexa_bidkit.orders import OrderBook
from nexa_bidkit.types import BiddingZone, DeliveryPeriod, Direction, MTUDuration, MTUInterval

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

ProductIdResolver = Callable[[MTUInterval], str]
"""Callable that maps an MTU interval to an EXAA product ID string.

Used for hourly products (e.g. ``"hEXA01"``) and 15-minute products
(e.g. ``"qEXA01_1"``).
"""

BlockProductResolver = Callable[[DeliveryPeriod], str]
"""Callable that maps a delivery period to an EXAA block product ID string.

Used for block products (e.g. ``"bEXAbase (01-24)"``, ``"bEXApeak (09-20)"``).
"""


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ExaaOrderType(str, Enum):
    """Order type for EXAA price-volume pairs.

    Attributes:
        STEP: Volume is allocated at each price level independently.
        LINEAR: Volume is interpolated linearly between price/volume points.
    """

    STEP = "STEP"
    LINEAR = "LINEAR"


# ---------------------------------------------------------------------------
# EXAA request Pydantic models
# ---------------------------------------------------------------------------


class PriceVolumePair(BaseModel):
    """A single price-volume pair in an EXAA product order.

    Attributes:
        price: Price in EUR/MWh (2 decimal places), or ``"M"`` for a market order.
        volume: Volume in MWh/h. Positive = buy, negative = sell.
    """

    model_config = ConfigDict(populate_by_name=True)

    price: float | Literal["M"]
    volume: float


class ExaaProduct(BaseModel):
    """An EXAA product order (hourly, 15-minute, or block).

    Attributes:
        product_id: Exchange-assigned product identifier (e.g. ``"hEXA01"``).
        fill_or_kill: If ``True`` the order must be fully filled or not at all.
        price_volume_pairs: Ordered list of price-volume pairs.
    """

    model_config = ConfigDict(populate_by_name=True)

    product_id: str = Field(alias="productID")
    fill_or_kill: bool = Field(alias="fillOrKill")
    price_volume_pairs: list[PriceVolumePair] = Field(alias="priceVolumePairs")


class ExaaProductTypeContainer(BaseModel):
    """Container for a single product type (hourly, block, or 15-minute).

    ``typeOfOrder`` applies to **all** products within this container.

    Attributes:
        type_of_order: STEP or LINEAR interpolation for all products.
        products: List of product orders in this container.
    """

    model_config = ConfigDict(populate_by_name=True)

    type_of_order: ExaaOrderType = Field(alias="typeOfOrder")
    products: list[ExaaProduct]


class ExaaAccountOrder(BaseModel):
    """EXAA order submission for a single trade account.

    Omitting a product-type container (``None``) leaves existing orders of
    that type unchanged. Setting a container with an empty ``products`` list
    **deletes** all existing orders of that type for the account.

    Attributes:
        account_id: Trade account identifier (e.g. ``"APTAP1"``).
        is_spread_order: ``True`` for location spread orders.
        account_id_sink: Sink account for spread orders; ``None`` otherwise.
        hourly_products: Hourly product container, or ``None`` to leave unchanged.
        block_products: Block product container, or ``None`` to leave unchanged.
        fifteen_min_products: 15-minute product container, or ``None`` to leave unchanged.
    """

    model_config = ConfigDict(populate_by_name=True)

    account_id: str = Field(alias="accountID")
    is_spread_order: bool = Field(default=False, alias="isSpreadOrder")
    account_id_sink: str | None = Field(default=None, alias="accountIDSink")
    hourly_products: ExaaProductTypeContainer | None = Field(default=None, alias="hourlyProducts")
    block_products: ExaaProductTypeContainer | None = Field(default=None, alias="blockProducts")
    fifteen_min_products: ExaaProductTypeContainer | None = Field(
        default=None, alias="15minProducts"
    )


class ExaaUnits(BaseModel):
    """Fixed units object required by the EXAA API.

    Always ``{"price": "EUR", "volume": "MWh/h"}``.
    """

    model_config = ConfigDict(populate_by_name=True)

    price: str = "EUR"
    volume: str = "MWh/h"


class ExaaOrderRequest(BaseModel):
    """Top-level EXAA order submission payload.

    Serialise with ``model_dump(by_alias=True)`` to produce the wire format
    expected by ``POST /exaa-trading-api/V1/auctions/{auction-id}/orders``.

    Attributes:
        units: Fixed units declaration (always EUR / MWh/h).
        orders: Per-account order entries.
    """

    model_config = ConfigDict(populate_by_name=True)

    units: ExaaUnits = Field(default_factory=ExaaUnits)
    orders: list[ExaaAccountOrder]


# ---------------------------------------------------------------------------
# Bidding zone → control area
# ---------------------------------------------------------------------------

_CONTROL_AREA_MAP: dict[BiddingZone, str] = {
    BiddingZone.AT: "APG",
    BiddingZone.DE_LU: "Amprion",
    BiddingZone.NL: "TenneT",
}


def bidding_zone_to_control_area(zone: BiddingZone) -> str:
    """Convert a :class:`~nexa_bidkit.types.BiddingZone` to an EXAA control area string.

    Args:
        zone: The bidding zone to convert.

    Returns:
        The EXAA control area string (``"APG"``, ``"Amprion"``, or ``"TenneT"``).

    Raises:
        ValueError: If the zone is not supported by EXAA (AT, DE-LU, NL only).
    """
    try:
        return _CONTROL_AREA_MAP[zone]
    except KeyError as exc:
        raise ValueError(
            f"Bidding zone {zone.value!r} is not supported by EXAA. "
            "EXAA operates in Austria (AT), Germany (DE-LU), and the Netherlands (NL) only."
        ) from exc


# ---------------------------------------------------------------------------
# Standard product ID helpers
# ---------------------------------------------------------------------------


def standard_hourly_product_id(mtu: MTUInterval) -> str:
    """Generate the standard EXAA hourly product ID for a given MTU interval.

    Maps hour 00:00–01:00 → ``"hEXA01"``, 01:00–02:00 → ``"hEXA02"``, and so
    on through 23:00–24:00 → ``"hEXA24"``.

    The hour number is derived from ``mtu.start`` in whatever timezone it
    carries. For EXAA (CET/CEST) submissions, ensure the MTU uses a
    CET-aware datetime before calling this helper.

    Args:
        mtu: The MTU interval to derive the product ID from.

    Returns:
        Product ID string such as ``"hEXA01"``.
    """
    hour_num = mtu.start.hour + 1
    return f"hEXA{hour_num:02d}"


def standard_quarter_hourly_product_id(mtu: MTUInterval) -> str:
    """Generate the standard EXAA 15-minute product ID for a given MTU interval.

    Maps 00:00–00:15 → ``"qEXA01_1"``, 00:15–00:30 → ``"qEXA01_2"``, and so
    on through 23:45–24:00 → ``"qEXA24_4"``.

    The hour and quarter numbers are derived from ``mtu.start`` in whatever
    timezone it carries. For EXAA submissions, ensure the MTU uses a
    CET-aware datetime before calling this helper.

    Args:
        mtu: The MTU interval to derive the product ID from.

    Returns:
        Product ID string such as ``"qEXA01_1"``.
    """
    hour_num = mtu.start.hour + 1
    quarter_num = mtu.start.minute // 15 + 1
    return f"qEXA{hour_num:02d}_{quarter_num}"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _signed_volume(volume: float, direction: Direction) -> float:
    """Return volume with EXAA sign convention: BUY = positive, SELL = negative.

    Note: This is the **opposite** of the Nord Pool convention.
    """
    return volume if direction == Direction.BUY else -volume


# ---------------------------------------------------------------------------
# Conversion functions
# ---------------------------------------------------------------------------


def simple_bid_to_exaa_product(
    bid: SimpleBid,
    product_id_resolver: ProductIdResolver,
    fill_or_kill: bool = False,
) -> ExaaProduct:
    """Convert a :class:`~nexa_bidkit.bids.SimpleBid` to an :class:`ExaaProduct`.

    Each :class:`~nexa_bidkit.types.PriceQuantityStep` in the bid's curve
    becomes a :class:`PriceVolumePair`. Volumes are signed per EXAA convention:
    positive for BUY, negative for SELL.

    Args:
        bid: The simple bid to convert.
        product_id_resolver: Callable mapping the bid's MTU to an EXAA product ID.
        fill_or_kill: Whether this product must be fully filled or not at all.
            Per EXAA rules, hourly and 15-minute products should always use
            ``False``; this parameter is exposed for completeness.

    Returns:
        An :class:`ExaaProduct` ready to be placed in a product type container.
    """
    product_id = product_id_resolver(bid.curve.mtu)

    pairs = [
        PriceVolumePair(
            price=float(step.price),
            volume=_signed_volume(float(step.volume), bid.direction),
        )
        for step in bid.curve.steps
    ]

    return ExaaProduct.model_validate(
        {
            "productID": product_id,
            "fillOrKill": fill_or_kill,
            "priceVolumePairs": pairs,
        }
    )


def block_bid_to_exaa_product(
    bid: BlockBid,
    product_id: str,
) -> ExaaProduct:
    """Convert a :class:`~nexa_bidkit.bids.BlockBid` to an :class:`ExaaProduct`.

    Creates a single :class:`PriceVolumePair` from the bid's price and volume.
    ``fillOrKill`` is derived from :attr:`~nexa_bidkit.bids.BlockBid.is_indivisible`
    (i.e. ``True`` when ``min_acceptance_ratio == 1.0``).

    EXAA block products have exchange-defined delivery periods (e.g.
    ``"bEXAbase (01-24)"``, ``"bEXApeak (09-20)"``). Pass the correct product ID
    for the desired block product.

    Args:
        bid: The block bid to convert.
        product_id: EXAA block product identifier (e.g. ``"bEXAbase (01-24)"``).

    Returns:
        An :class:`ExaaProduct` ready to be placed in a block product container.
    """
    pair = PriceVolumePair(
        price=float(bid.price),
        volume=_signed_volume(float(bid.volume), bid.direction),
    )

    return ExaaProduct.model_validate(
        {
            "productID": product_id,
            "fillOrKill": bid.is_indivisible,
            "priceVolumePairs": [pair],
        }
    )


def order_book_to_exaa(
    order_book: OrderBook,
    account_id: str,
    product_id_resolver: ProductIdResolver,
    block_product_resolver: BlockProductResolver | None = None,
    order_type: ExaaOrderType = ExaaOrderType.STEP,
) -> ExaaOrderRequest:
    """Convert an :class:`~nexa_bidkit.orders.OrderBook` into an :class:`ExaaOrderRequest`.

    Dispatches each bid to the appropriate product type container:

    - :class:`~nexa_bidkit.bids.SimpleBid` with :attr:`~nexa_bidkit.types.MTUDuration.HOURLY`
      duration → ``hourlyProducts``
    - :class:`~nexa_bidkit.bids.SimpleBid` with
      :attr:`~nexa_bidkit.types.MTUDuration.QUARTER_HOURLY` duration → ``15minProducts``
    - :class:`~nexa_bidkit.bids.BlockBid` → ``blockProducts``
      (requires ``block_product_resolver``)

    Product type containers with no products are set to ``None`` (omitted when
    serialising with ``model_dump(by_alias=True)``).

    All containers use the same ``order_type`` (LINEAR or STEP).

    Args:
        order_book: The order book to convert.
        account_id: EXAA trade account identifier for the submission.
        product_id_resolver: Callable mapping an MTU interval to an EXAA
            hourly or 15-minute product ID string.
        block_product_resolver: Callable mapping a
            :class:`~nexa_bidkit.types.DeliveryPeriod` to an EXAA block
            product ID string. Required if the order book contains any
            :class:`~nexa_bidkit.bids.BlockBid` entries.
        order_type: STEP or LINEAR interpolation applied to all product
            type containers. Defaults to :attr:`ExaaOrderType.STEP`.

    Returns:
        An :class:`ExaaOrderRequest` ready for submission to the EXAA API.

    Raises:
        ValueError: If the order book contains
            :class:`~nexa_bidkit.bids.LinkedBlockBid` or
            :class:`~nexa_bidkit.bids.ExclusiveGroupBid` entries, which are
            not supported by EXAA.
        ValueError: If the order book contains
            :class:`~nexa_bidkit.bids.BlockBid` entries but
            ``block_product_resolver`` is ``None``.
    """
    hourly: list[ExaaProduct] = []
    fifteen_min: list[ExaaProduct] = []
    blocks: list[ExaaProduct] = []

    for bid in order_book.bids:
        if isinstance(bid, LinkedBlockBid):
            raise ValueError(
                f"Bid {bid.bid_id!r} is a LinkedBlockBid, which is not supported by EXAA. "
                "EXAA does not have a linked block concept."
            )
        if isinstance(bid, ExclusiveGroupBid):
            raise ValueError(
                f"Bid {bid.group_id!r} is an ExclusiveGroupBid, which is not supported by EXAA. "
                "EXAA does not have an exclusive group concept."
            )
        if isinstance(bid, SimpleBid):
            product = simple_bid_to_exaa_product(bid, product_id_resolver)
            if bid.curve.mtu.duration == MTUDuration.HOURLY:
                hourly.append(product)
            else:
                fifteen_min.append(product)
        elif isinstance(bid, BlockBid):
            if block_product_resolver is None:
                raise ValueError(
                    "order_book contains BlockBid entries but block_product_resolver is None. "
                    "Provide a BlockProductResolver to map delivery periods to block product IDs."
                )
            product_id = block_product_resolver(bid.delivery_period)
            blocks.append(block_bid_to_exaa_product(bid, product_id))

    hourly_container = (
        ExaaProductTypeContainer.model_validate({"typeOfOrder": order_type, "products": hourly})
        if hourly
        else None
    )
    fifteen_min_container = (
        ExaaProductTypeContainer.model_validate(
            {"typeOfOrder": order_type, "products": fifteen_min}
        )
        if fifteen_min
        else None
    )
    block_container = (
        ExaaProductTypeContainer.model_validate({"typeOfOrder": order_type, "products": blocks})
        if blocks
        else None
    )

    account_order = ExaaAccountOrder.model_validate(
        {
            "accountID": account_id,
            "hourlyProducts": hourly_container,
            "blockProducts": block_container,
            "15minProducts": fifteen_min_container,
        }
    )

    return ExaaOrderRequest(orders=[account_order])


__all__ = [
    "ProductIdResolver",
    "BlockProductResolver",
    "ExaaOrderType",
    "PriceVolumePair",
    "ExaaProduct",
    "ExaaProductTypeContainer",
    "ExaaAccountOrder",
    "ExaaUnits",
    "ExaaOrderRequest",
    "bidding_zone_to_control_area",
    "standard_hourly_product_id",
    "standard_quarter_hourly_product_id",
    "simple_bid_to_exaa_product",
    "block_bid_to_exaa_product",
    "order_book_to_exaa",
]
