"""Nord Pool market adapter for nexa-bidkit.

Converts internal bid objects into Nord Pool Auction API request schemas.
Supports curve orders (SimpleBid) and block/linked/exclusive-group orders.

Nord Pool operates in the Nordic and Baltic bidding zones. Unsupported zones
(CWE, Iberian, Italian, GB) raise ValueError.

Callers must supply a ``ContractIdResolver`` to map MTU intervals to Nord Pool
contract ID strings (e.g. ``"NO1-14"``), since these IDs require a call to
Nord Pool's products API and are not derivable from the bid data alone.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, Field

from nexa_bidkit.bids import BlockBid, ExclusiveGroupBid, LinkedBlockBid, SimpleBid
from nexa_bidkit.orders import OrderBook
from nexa_bidkit.types import BiddingZone, Direction, MTUInterval

# ---------------------------------------------------------------------------
# Type alias
# ---------------------------------------------------------------------------

ContractIdResolver = Callable[[MTUInterval, BiddingZone], str]
"""Callable that maps an MTU interval + bidding zone to a Nord Pool contract ID."""


# ---------------------------------------------------------------------------
# Nord Pool request Pydantic models
# ---------------------------------------------------------------------------


class CurvePoint(BaseModel):
    """A single point on a Nord Pool price-quantity curve.

    Attributes:
        price: Price in EUR/MWh (float, Nord Pool API convention).
        volume: Volume in MW. Positive = sell, negative = buy.
    """

    model_config = ConfigDict(populate_by_name=True)

    price: float
    volume: float


class Curve(BaseModel):
    """A price-quantity curve for a single Nord Pool contract.

    Attributes:
        contract_id: Nord Pool contract identifier (e.g. ``"NO1-14"``).
        curve_points: Ordered list of price-quantity points.
    """

    model_config = ConfigDict(populate_by_name=True)

    contract_id: str = Field(alias="contractId")
    curve_points: list[CurvePoint] = Field(alias="curvePoints")


class CurveOrderCreate(BaseModel):
    """Nord Pool API payload for submitting a curve (simple) order.

    Attributes:
        auction_id: Auction identifier.
        portfolio: Portfolio name.
        area_code: Nord Pool area code derived from the bidding zone.
        comment: Optional free-text comment.
        curves: List of per-contract curves.
    """

    model_config = ConfigDict(populate_by_name=True)

    auction_id: str = Field(alias="auctionId")
    portfolio: str
    area_code: str = Field(alias="areaCode")
    comment: str | None = Field(default=None)
    curves: list[Curve]


class BlockPeriod(BaseModel):
    """A single MTU period within a Nord Pool block order.

    Attributes:
        contract_id: Nord Pool contract identifier for this MTU.
        volume: Volume in MW. Positive = sell, negative = buy.
    """

    model_config = ConfigDict(populate_by_name=True)

    contract_id: str = Field(alias="contractId")
    volume: float


class Block(BaseModel):
    """A single block within a Nord Pool block list order.

    Attributes:
        name: Block identifier (typically the internal bid_id).
        price: Limit price in EUR/MWh.
        minimum_acceptance_ratio: Minimum partial fill ratio (0–1).
        periods: Per-MTU periods making up the block.
        linked_to: Parent block name for linked blocks.
        exclusive_group: Exclusive group identifier.
        is_spread_block: Whether this is a spread block (default False).
    """

    model_config = ConfigDict(populate_by_name=True)

    name: str
    price: float
    minimum_acceptance_ratio: float = Field(alias="minimumAcceptanceRatio")
    periods: list[BlockPeriod]
    linked_to: str | None = Field(default=None, alias="linkedTo")
    exclusive_group: str | None = Field(default=None, alias="exclusiveGroup")
    is_spread_block: bool = Field(default=False, alias="isSpreadBlock")


class BlockListCreate(BaseModel):
    """Nord Pool API payload for submitting a list of block orders.

    Attributes:
        auction_id: Auction identifier.
        portfolio: Portfolio name.
        area_code: Nord Pool area code derived from the bidding zone.
        comment: Optional free-text comment.
        blocks: List of block orders to submit.
    """

    model_config = ConfigDict(populate_by_name=True)

    auction_id: str = Field(alias="auctionId")
    portfolio: str
    area_code: str = Field(alias="areaCode")
    comment: str | None = Field(default=None)
    blocks: list[Block]


# ---------------------------------------------------------------------------
# Submission container
# ---------------------------------------------------------------------------


@dataclass
class NordPoolSubmission:
    """All Nord Pool API request payloads derived from an OrderBook.

    Attributes:
        curve_orders: One :class:`CurveOrderCreate` per :class:`SimpleBid`.
        block_orders: One :class:`BlockListCreate` per :class:`BlockBid`.
        linked_block_orders: One :class:`BlockListCreate` per :class:`LinkedBlockBid`.
        exclusive_group_orders: One :class:`BlockListCreate` per :class:`ExclusiveGroupBid`.
    """

    curve_orders: list[CurveOrderCreate] = field(default_factory=list)
    block_orders: list[BlockListCreate] = field(default_factory=list)
    linked_block_orders: list[BlockListCreate] = field(default_factory=list)
    exclusive_group_orders: list[BlockListCreate] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Bidding zone → Nord Pool area code
# ---------------------------------------------------------------------------

_AREA_CODE_MAP: dict[BiddingZone, str] = {
    BiddingZone.NO1: "NO1",
    BiddingZone.NO2: "NO2",
    BiddingZone.NO3: "NO3",
    BiddingZone.NO4: "NO4",
    BiddingZone.NO5: "NO5",
    BiddingZone.SE1: "SE1",
    BiddingZone.SE2: "SE2",
    BiddingZone.SE3: "SE3",
    BiddingZone.SE4: "SE4",
    BiddingZone.FI: "FI",
    BiddingZone.DK1: "DK1",
    BiddingZone.DK2: "DK2",
    BiddingZone.EE: "EE",
    BiddingZone.LV: "LV",
    BiddingZone.LT: "LT",
    BiddingZone.PL: "PL",
}


def bidding_zone_to_area_code(zone: BiddingZone) -> str:
    """Convert a BiddingZone to a Nord Pool area code string.

    Args:
        zone: The bidding zone to convert.

    Returns:
        The Nord Pool area code string (e.g. ``"NO1"``).

    Raises:
        ValueError: If the zone is not supported by Nord Pool
            (e.g. CWE, Iberian, Italian, or GB zones).
    """
    try:
        return _AREA_CODE_MAP[zone]
    except KeyError as exc:
        raise ValueError(
            f"Bidding zone {zone.value!r} is not supported by Nord Pool. "
            "Nord Pool operates Nordic (NO1-NO5, SE1-SE4, FI, DK1, DK2) "
            "and Baltic (EE, LV, LT) zones only."
        ) from exc


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _signed_volume(volume: float, direction: Direction) -> float:
    """Return volume with sign convention: SELL = positive, BUY = negative."""
    return volume if direction == Direction.SELL else -volume


# ---------------------------------------------------------------------------
# Conversion functions
# ---------------------------------------------------------------------------


def simple_bid_to_curve_order(
    bid: SimpleBid,
    auction_id: str,
    portfolio: str,
    contract_id_resolver: ContractIdResolver,
    comment: str | None = None,
) -> CurveOrderCreate:
    """Convert a :class:`SimpleBid` to a Nord Pool :class:`CurveOrderCreate`.

    One :class:`Curve` is created for the bid's MTU, with ``contractId``
    resolved via ``contract_id_resolver``. Volumes are signed per Nord Pool
    convention: positive for SELL, negative for BUY.

    Args:
        bid: The simple bid to convert.
        auction_id: Nord Pool auction identifier.
        portfolio: Portfolio name.
        contract_id_resolver: Callable mapping (MTUInterval, BiddingZone) → contract ID.
        comment: Optional free-text comment.

    Returns:
        A :class:`CurveOrderCreate` ready for submission.

    Raises:
        ValueError: If the bid's bidding zone is not supported by Nord Pool.
    """
    area_code = bidding_zone_to_area_code(bid.bidding_zone)
    contract_id = contract_id_resolver(bid.curve.mtu, bid.bidding_zone)

    curve_points = [
        CurvePoint(
            price=float(step.price),
            volume=_signed_volume(float(step.volume), bid.direction),
        )
        for step in bid.curve.steps
    ]

    curve = Curve.model_validate({"contractId": contract_id, "curvePoints": curve_points})

    return CurveOrderCreate.model_validate(
        {
            "auctionId": auction_id,
            "portfolio": portfolio,
            "areaCode": area_code,
            "comment": comment,
            "curves": [curve],
        }
    )


def block_bid_to_block_list(
    bid: BlockBid,
    auction_id: str,
    portfolio: str,
    contract_id_resolver: ContractIdResolver,
    comment: str | None = None,
) -> BlockListCreate:
    """Convert a :class:`BlockBid` to a Nord Pool :class:`BlockListCreate`.

    One :class:`Block` is created with one :class:`BlockPeriod` per MTU interval
    in the bid's delivery period. Volumes are signed per Nord Pool convention.

    Args:
        bid: The block bid to convert.
        auction_id: Nord Pool auction identifier.
        portfolio: Portfolio name.
        contract_id_resolver: Callable mapping (MTUInterval, BiddingZone) → contract ID.
        comment: Optional free-text comment.

    Returns:
        A :class:`BlockListCreate` ready for submission.

    Raises:
        ValueError: If the bid's bidding zone is not supported by Nord Pool.
    """
    area_code = bidding_zone_to_area_code(bid.bidding_zone)
    signed_vol = _signed_volume(float(bid.volume), bid.direction)

    periods = [
        BlockPeriod.model_validate(
            {"contractId": contract_id_resolver(mtu, bid.bidding_zone), "volume": signed_vol}
        )
        for mtu in bid.delivery_period.mtu_intervals()
    ]

    block = Block.model_validate(
        {
            "name": bid.bid_id,
            "price": float(bid.price),
            "minimumAcceptanceRatio": float(bid.min_acceptance_ratio),
            "periods": periods,
        }
    )

    return BlockListCreate.model_validate(
        {
            "auctionId": auction_id,
            "portfolio": portfolio,
            "areaCode": area_code,
            "comment": comment,
            "blocks": [block],
        }
    )


def linked_block_bid_to_block_list(
    bid: LinkedBlockBid,
    auction_id: str,
    portfolio: str,
    contract_id_resolver: ContractIdResolver,
    comment: str | None = None,
) -> BlockListCreate:
    """Convert a :class:`LinkedBlockBid` to a Nord Pool :class:`BlockListCreate`.

    Same as :func:`block_bid_to_block_list` but sets ``linkedTo`` on the block
    to reference the parent bid ID.

    Args:
        bid: The linked block bid to convert.
        auction_id: Nord Pool auction identifier.
        portfolio: Portfolio name.
        contract_id_resolver: Callable mapping (MTUInterval, BiddingZone) → contract ID.
        comment: Optional free-text comment.

    Returns:
        A :class:`BlockListCreate` with ``linkedTo`` populated, ready for submission.

    Raises:
        ValueError: If the bid's bidding zone is not supported by Nord Pool.
    """
    area_code = bidding_zone_to_area_code(bid.bidding_zone)
    signed_vol = _signed_volume(float(bid.volume), bid.direction)

    periods = [
        BlockPeriod.model_validate(
            {"contractId": contract_id_resolver(mtu, bid.bidding_zone), "volume": signed_vol}
        )
        for mtu in bid.delivery_period.mtu_intervals()
    ]

    block = Block.model_validate(
        {
            "name": bid.bid_id,
            "price": float(bid.price),
            "minimumAcceptanceRatio": float(bid.min_acceptance_ratio),
            "periods": periods,
            "linkedTo": bid.parent_bid_id,
        }
    )

    return BlockListCreate.model_validate(
        {
            "auctionId": auction_id,
            "portfolio": portfolio,
            "areaCode": area_code,
            "comment": comment,
            "blocks": [block],
        }
    )


def exclusive_group_to_block_list(
    group: ExclusiveGroupBid,
    auction_id: str,
    portfolio: str,
    contract_id_resolver: ContractIdResolver,
    comment: str | None = None,
) -> BlockListCreate:
    """Convert an :class:`ExclusiveGroupBid` to a Nord Pool :class:`BlockListCreate`.

    Each member :class:`BlockBid` becomes a :class:`Block` with ``exclusiveGroup``
    set to the group's ``group_id``. All blocks share the same ``areaCode``.

    Args:
        group: The exclusive group bid to convert.
        auction_id: Nord Pool auction identifier.
        portfolio: Portfolio name.
        contract_id_resolver: Callable mapping (MTUInterval, BiddingZone) → contract ID.
        comment: Optional free-text comment.

    Returns:
        A :class:`BlockListCreate` with all member blocks tagged with ``exclusiveGroup``.

    Raises:
        ValueError: If the group's bidding zone is not supported by Nord Pool.
    """
    area_code = bidding_zone_to_area_code(group.bidding_zone)

    blocks = []
    for member in group.block_bids:
        signed_vol = _signed_volume(float(member.volume), member.direction)
        periods = [
            BlockPeriod.model_validate(
                {"contractId": contract_id_resolver(mtu, member.bidding_zone), "volume": signed_vol}
            )
            for mtu in member.delivery_period.mtu_intervals()
        ]
        blocks.append(
            Block.model_validate(
                {
                    "name": member.bid_id,
                    "price": float(member.price),
                    "minimumAcceptanceRatio": float(member.min_acceptance_ratio),
                    "periods": periods,
                    "exclusiveGroup": group.group_id,
                }
            )
        )

    return BlockListCreate.model_validate(
        {
            "auctionId": auction_id,
            "portfolio": portfolio,
            "areaCode": area_code,
            "comment": comment,
            "blocks": blocks,
        }
    )


def order_book_to_nord_pool(
    order_book: OrderBook,
    auction_id: str,
    portfolio: str,
    contract_id_resolver: ContractIdResolver,
    comment: str | None = None,
) -> NordPoolSubmission:
    """Convert an :class:`OrderBook` into a :class:`NordPoolSubmission`.

    Iterates all bids in the order book and dispatches each to the appropriate
    conversion function, grouping outputs by bid type.

    Args:
        order_book: The order book to convert.
        auction_id: Nord Pool auction identifier.
        portfolio: Portfolio name.
        contract_id_resolver: Callable mapping (MTUInterval, BiddingZone) → contract ID.
        comment: Optional free-text comment attached to all generated requests.

    Returns:
        A :class:`NordPoolSubmission` containing all generated API payloads.

    Raises:
        ValueError: If any bid's bidding zone is not supported by Nord Pool.
    """
    submission = NordPoolSubmission()

    for bid in order_book.bids:
        if isinstance(bid, SimpleBid):
            submission.curve_orders.append(
                simple_bid_to_curve_order(bid, auction_id, portfolio, contract_id_resolver, comment)
            )
        elif isinstance(bid, LinkedBlockBid):
            submission.linked_block_orders.append(
                linked_block_bid_to_block_list(
                    bid, auction_id, portfolio, contract_id_resolver, comment
                )
            )
        elif isinstance(bid, BlockBid):
            submission.block_orders.append(
                block_bid_to_block_list(bid, auction_id, portfolio, contract_id_resolver, comment)
            )
        elif isinstance(bid, ExclusiveGroupBid):
            submission.exclusive_group_orders.append(
                exclusive_group_to_block_list(
                    group=bid,
                    auction_id=auction_id,
                    portfolio=portfolio,
                    contract_id_resolver=contract_id_resolver,
                    comment=comment,
                )
            )

    return submission


__all__ = [
    "ContractIdResolver",
    "CurvePoint",
    "Curve",
    "CurveOrderCreate",
    "BlockPeriod",
    "Block",
    "BlockListCreate",
    "NordPoolSubmission",
    "bidding_zone_to_area_code",
    "simple_bid_to_curve_order",
    "block_bid_to_block_list",
    "linked_block_bid_to_block_list",
    "exclusive_group_to_block_list",
    "order_book_to_nord_pool",
]
