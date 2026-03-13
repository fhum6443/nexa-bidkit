"""Order book/portfolio container for European power market auction bids.

Provides a collection container (OrderBook) for managing portfolios of bids,
with immutable operations, querying, aggregation, and pandas export capabilities.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from typing import Any

import pandas as pd
from pydantic import BaseModel, Field, field_validator, model_validator

from nexa_bidkit.bids import (
    BlockBid,
    ExclusiveGroupBid,
    LinkedBlockBid,
    SimpleBid,
    validate_bid_collection,
    with_status,
)
from nexa_bidkit.types import BiddingZone, BidStatus, BidType, Direction

# ---------------------------------------------------------------------------
# Type union for all bid types
# ---------------------------------------------------------------------------

BidUnion = SimpleBid | BlockBid | LinkedBlockBid | ExclusiveGroupBid


# ---------------------------------------------------------------------------
# OrderBook - immutable portfolio of bids
# ---------------------------------------------------------------------------


class OrderBook(BaseModel):
    """Collection of bids forming a market order portfolio.

    Immutable container for managing collections of SimpleBid, BlockBid,
    LinkedBlockBid, and ExclusiveGroupBid instances. All mutations return
    new OrderBook instances (copy-on-write pattern).

    Attributes:
        order_book_id: Unique identifier for this order book.
        bids: List of bids in this portfolio.
        metadata: Optional arbitrary metadata for tracking.
        created_at: Timestamp when this order book was created (timezone-aware).
    """

    order_book_id: str
    bids: list[BidUnion] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime

    model_config = {"frozen": True}

    @field_validator("order_book_id")
    @classmethod
    def validate_order_book_id(cls, v: str) -> str:
        """Ensure order_book_id is non-empty."""
        if not v or not v.strip():
            raise ValueError("order_book_id must be a non-empty string")
        return v

    @field_validator("created_at", mode="before")
    @classmethod
    def require_timezone(cls, v: datetime) -> datetime:
        """Reject naive datetimes."""
        if isinstance(v, datetime) and v.tzinfo is None:
            raise ValueError("OrderBook.created_at requires timezone-aware datetime")
        return v

    @model_validator(mode="after")
    def validate_bids_collection(self) -> OrderBook:
        """Validate bid collection for consistency."""
        # Flatten ExclusiveGroupBids to extract member bids for validation
        flattened_bids: list[SimpleBid | BlockBid | LinkedBlockBid] = []
        for bid in self.bids:
            if isinstance(bid, ExclusiveGroupBid):
                flattened_bids.extend(bid.block_bids)
            else:
                flattened_bids.append(bid)

        # Validate the flattened collection
        validate_bid_collection(flattened_bids)
        return self


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def generate_order_book_id(prefix: str = "book") -> str:
    """Generate a unique order book ID using UUID4.

    Args:
        prefix: Optional prefix for the ID (default: "book").

    Returns:
        Unique order book ID string in the format "{prefix}_{uuid}".
    """
    return f"{prefix}_{uuid.uuid4()}"


def create_order_book(
    bids: list[BidUnion] | None = None,
    order_book_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    created_at: datetime | None = None,
) -> OrderBook:
    """Create an OrderBook with sensible defaults.

    Auto-generates order_book_id if not provided. Uses current UTC timestamp
    if created_at is not specified.

    Args:
        bids: Optional list of bids to include.
        order_book_id: Optional explicit order book ID (auto-generated if None).
        metadata: Optional metadata dict.
        created_at: Optional creation timestamp (defaults to datetime.now(UTC)).

    Returns:
        Validated OrderBook instance.
    """
    from datetime import UTC

    return OrderBook(
        order_book_id=order_book_id or generate_order_book_id(),
        bids=bids or [],
        metadata=metadata or {},
        created_at=created_at or datetime.now(UTC),
    )


# ---------------------------------------------------------------------------
# Collection management functions
# ---------------------------------------------------------------------------


def add_bid(order_book: OrderBook, bid: BidUnion) -> OrderBook:
    """Add a single bid to the order book.

    Returns a new OrderBook instance with the bid added. Validates the
    resulting collection for consistency.

    Args:
        order_book: Original order book.
        bid: Bid to add.

    Returns:
        New OrderBook instance with the bid added.

    Raises:
        ValueError: If adding the bid would violate collection constraints.
    """
    new_bids = [*order_book.bids, bid]
    # Use model_validate to force revalidation
    return OrderBook.model_validate(
        {
            "order_book_id": order_book.order_book_id,
            "bids": new_bids,
            "metadata": order_book.metadata,
            "created_at": order_book.created_at,
        }
    )


def add_bids(order_book: OrderBook, bids: list[BidUnion]) -> OrderBook:
    """Add multiple bids to the order book.

    Returns a new OrderBook instance with all bids added. Validates the
    resulting collection for consistency.

    Args:
        order_book: Original order book.
        bids: List of bids to add.

    Returns:
        New OrderBook instance with the bids added.

    Raises:
        ValueError: If adding the bids would violate collection constraints.
    """
    new_bids = [*order_book.bids, *bids]
    # Use model_validate to force revalidation
    return OrderBook.model_validate(
        {
            "order_book_id": order_book.order_book_id,
            "bids": new_bids,
            "metadata": order_book.metadata,
            "created_at": order_book.created_at,
        }
    )


def remove_bid(order_book: OrderBook, bid_id: str) -> OrderBook:
    """Remove a bid from the order book by ID.

    Returns a new OrderBook instance with the bid removed. For ExclusiveGroupBid,
    the entire group is removed if the group_id matches.

    Args:
        order_book: Original order book.
        bid_id: ID of the bid to remove (bid_id or group_id).

    Returns:
        New OrderBook instance with the bid removed.

    Raises:
        ValueError: If no bid with the given ID is found.
    """
    new_bids: list[BidUnion] = []
    found = False

    for bid in order_book.bids:
        bid_identifier = bid.group_id if isinstance(bid, ExclusiveGroupBid) else bid.bid_id
        if bid_identifier == bid_id:
            found = True
            continue
        new_bids.append(bid)

    if not found:
        raise ValueError(f"No bid found with ID {bid_id}")

    return order_book.model_copy(update={"bids": new_bids})


def filter_bids(
    order_book: OrderBook,
    predicate: Callable[[BidUnion], bool],
) -> OrderBook:
    """Filter bids using a predicate function.

    Returns a new OrderBook instance containing only bids for which the
    predicate returns True.

    Args:
        order_book: Original order book.
        predicate: Function that returns True for bids to keep.

    Returns:
        New OrderBook instance with filtered bids.
    """
    new_bids = [bid for bid in order_book.bids if predicate(bid)]
    return order_book.model_copy(update={"bids": new_bids})


# ---------------------------------------------------------------------------
# Querying functions
# ---------------------------------------------------------------------------


def get_bid_by_id(order_book: OrderBook, bid_id: str) -> BidUnion | None:
    """Retrieve a bid by its ID.

    For ExclusiveGroupBid, searches both the group_id and member bid_ids.

    Args:
        order_book: Order book to search.
        bid_id: ID to search for.

    Returns:
        The bid if found, None otherwise.
    """
    for bid in order_book.bids:
        if isinstance(bid, ExclusiveGroupBid):
            if bid.group_id == bid_id:
                return bid
            # Search member bids
            for member in bid.block_bids:
                if member.bid_id == bid_id:
                    return member
        else:
            if bid.bid_id == bid_id:
                return bid
    return None


def get_bids_by_zone(order_book: OrderBook, zone: BiddingZone) -> list[BidUnion]:
    """Retrieve all bids for a specific bidding zone.

    Args:
        order_book: Order book to search.
        zone: Bidding zone to filter by.

    Returns:
        List of bids in the specified zone.
    """
    return [bid for bid in order_book.bids if bid.bidding_zone == zone]


def get_bids_by_direction(order_book: OrderBook, direction: Direction) -> list[BidUnion]:
    """Retrieve all bids with a specific direction.

    Args:
        order_book: Order book to search.
        direction: Direction to filter by (BUY or SELL).

    Returns:
        List of bids with the specified direction.
    """
    return [bid for bid in order_book.bids if bid.direction == direction]


def get_bids_by_status(order_book: OrderBook, status: BidStatus) -> list[BidUnion]:
    """Retrieve all bids with a specific status.

    Args:
        order_book: Order book to search.
        status: Status to filter by.

    Returns:
        List of bids with the specified status.
    """
    return [bid for bid in order_book.bids if bid.status == status]


def get_bids_by_type(order_book: OrderBook, bid_type: BidType) -> list[BidUnion]:
    """Retrieve all bids of a specific type.

    Args:
        order_book: Order book to search.
        bid_type: Bid type to filter by.

    Returns:
        List of bids of the specified type.
    """
    return [bid for bid in order_book.bids if bid.bid_type == bid_type]


def get_bids_in_period(
    order_book: OrderBook,
    start: datetime,
    end: datetime,
) -> list[BidUnion]:
    """Retrieve all bids that overlap with a time period.

    For SimpleBid: checks if the MTU falls within [start, end).
    For BlockBid/LinkedBlockBid/ExclusiveGroupBid: checks if delivery period
    overlaps with [start, end).

    Args:
        order_book: Order book to search.
        start: Start of the period (inclusive, timezone-aware).
        end: End of the period (exclusive, timezone-aware).

    Returns:
        List of bids that overlap with the specified period.

    Raises:
        ValueError: If start or end are naive datetimes.
    """
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("get_bids_in_period requires timezone-aware datetimes")

    result: list[BidUnion] = []
    for bid in order_book.bids:
        if isinstance(bid, SimpleBid):
            # Check if MTU overlaps
            mtu_start = bid.curve.mtu.start
            mtu_end = bid.curve.mtu.end
            if mtu_start < end and mtu_end > start:
                result.append(bid)
        elif isinstance(bid, BlockBid | LinkedBlockBid):
            # Check if delivery period overlaps
            dp_start = bid.delivery_period.start
            dp_end = bid.delivery_period.end
            if dp_start < end and dp_end > start:
                result.append(bid)
        elif isinstance(bid, ExclusiveGroupBid):
            # Check if any member's delivery period overlaps
            for member in bid.block_bids:
                dp_start = member.delivery_period.start
                dp_end = member.delivery_period.end
                if dp_start < end and dp_end > start:
                    result.append(bid)
                    break

    return result


# ---------------------------------------------------------------------------
# Aggregation functions
# ---------------------------------------------------------------------------


def count_bids(order_book: OrderBook) -> dict[str, int]:
    """Count bids by type.

    Args:
        order_book: Order book to analyse.

    Returns:
        Dictionary mapping bid type names to counts.
    """
    counts: dict[str, int] = {
        "SIMPLE_HOURLY": 0,
        "BLOCK": 0,
        "LINKED_BLOCK": 0,
        "EXCLUSIVE_GROUP": 0,
    }

    for bid in order_book.bids:
        counts[bid.bid_type.value] += 1

    return counts


def total_volume_by_zone(
    order_book: OrderBook,
    zone: BiddingZone | None = None,
) -> dict[BiddingZone, Decimal]:
    """Calculate total volume by bidding zone.

    For SimpleBid: uses curve.total_volume.
    For BlockBid/LinkedBlockBid: uses bid.total_volume.
    For ExclusiveGroupBid: sums all member volumes (note: only one can be accepted).

    Args:
        order_book: Order book to analyse.
        zone: Optional zone filter. If provided, only returns volume for that zone.

    Returns:
        Dictionary mapping bidding zones to total volumes in MW.
    """
    volumes: dict[BiddingZone, Decimal] = {}

    for bid in order_book.bids:
        # Skip if zone filter is set and doesn't match
        if zone is not None and bid.bidding_zone != zone:
            continue

        bid_zone = bid.bidding_zone
        if bid_zone not in volumes:
            volumes[bid_zone] = Decimal("0")

        if isinstance(bid, SimpleBid):
            volumes[bid_zone] += bid.curve.total_volume
        elif isinstance(bid, BlockBid | LinkedBlockBid):
            volumes[bid_zone] += bid.total_volume
        elif isinstance(bid, ExclusiveGroupBid):
            # Sum all member volumes
            for member in bid.block_bids:
                volumes[bid_zone] += member.total_volume

    return volumes


def get_order_book_summary(order_book: OrderBook) -> dict[str, Any]:
    """Generate comprehensive summary statistics for the order book.

    Args:
        order_book: Order book to analyse.

    Returns:
        Dictionary with summary statistics including:
        - order_book_id: The order book ID
        - created_at: Creation timestamp
        - total_bids: Total number of bids
        - bid_counts: Count by bid type
        - zones: List of unique bidding zones
        - directions: Count by direction
        - statuses: Count by status
        - total_volume_by_zone: Volume aggregated by zone
    """
    bid_counts = count_bids(order_book)
    volumes = total_volume_by_zone(order_book)

    # Count by direction
    direction_counts = {"BUY": 0, "SELL": 0}
    for bid in order_book.bids:
        direction_counts[bid.direction.value] += 1

    # Count by status
    status_counts: dict[str, int] = {}
    for bid in order_book.bids:
        status_name = bid.status.value
        status_counts[status_name] = status_counts.get(status_name, 0) + 1

    # Unique zones
    zones = sorted({bid.bidding_zone.value for bid in order_book.bids})

    return {
        "order_book_id": order_book.order_book_id,
        "created_at": order_book.created_at.isoformat(),
        "total_bids": len(order_book.bids),
        "bid_counts": bid_counts,
        "zones": zones,
        "directions": direction_counts,
        "statuses": status_counts,
        "total_volume_by_zone": {zone.value: float(vol) for zone, vol in volumes.items()},
    }


# ---------------------------------------------------------------------------
# Status management functions
# ---------------------------------------------------------------------------


def update_bid_status(
    order_book: OrderBook,
    bid_id: str,
    new_status: BidStatus,
) -> OrderBook:
    """Update the status of a single bid.

    For ExclusiveGroupBid, updates the group status if the group_id matches.
    To update a member bid within an exclusive group, use the member's bid_id.

    Args:
        order_book: Order book containing the bid.
        bid_id: ID of the bid to update (bid_id or group_id).
        new_status: New status to apply.

    Returns:
        New OrderBook instance with the updated bid.

    Raises:
        ValueError: If no bid with the given ID is found.
    """
    new_bids: list[BidUnion] = []
    found = False

    for bid in order_book.bids:
        if isinstance(bid, ExclusiveGroupBid):
            if bid.group_id == bid_id:
                # Update the group status
                new_bids.append(bid.model_copy(update={"status": new_status}))
                found = True
            else:
                # Check if we need to update a member bid
                updated_members = []
                member_found = False
                for member in bid.block_bids:
                    if member.bid_id == bid_id:
                        updated_members.append(with_status(member, new_status))
                        member_found = True
                        found = True
                    else:
                        updated_members.append(member)

                if member_found:
                    new_bids.append(bid.model_copy(update={"block_bids": updated_members}))
                else:
                    new_bids.append(bid)
        else:
            if bid.bid_id == bid_id:
                new_bids.append(with_status(bid, new_status))
                found = True
            else:
                new_bids.append(bid)

    if not found:
        raise ValueError(f"No bid found with ID {bid_id}")

    return order_book.model_copy(update={"bids": new_bids})


def update_all_statuses(
    order_book: OrderBook,
    new_status: BidStatus,
    filter_current_status: BidStatus | None = None,
) -> OrderBook:
    """Update the status of all bids in the order book.

    Optionally filters by current status before updating.

    Args:
        order_book: Order book to update.
        new_status: New status to apply to all matching bids.
        filter_current_status: If provided, only update bids with this current status.

    Returns:
        New OrderBook instance with updated bid statuses.
    """
    new_bids: list[BidUnion] = []

    for bid in order_book.bids:
        should_update = filter_current_status is None or bid.status == filter_current_status

        if should_update:
            if isinstance(bid, ExclusiveGroupBid):
                new_bids.append(bid.model_copy(update={"status": new_status}))
            else:
                new_bids.append(with_status(bid, new_status))
        else:
            new_bids.append(bid)

    return order_book.model_copy(update={"bids": new_bids})


# ---------------------------------------------------------------------------
# DataFrame export
# ---------------------------------------------------------------------------


def to_dataframe(order_book: OrderBook) -> pd.DataFrame:
    """Export order book to a pandas DataFrame.

    Creates a wide-format DataFrame with common fields for all bid types
    and type-specific columns. Empty cells for type-specific fields are
    filled with None.

    Common columns:
    - bid_id: Unique identifier (group_id for ExclusiveGroupBid)
    - bid_type: Type of bid
    - bidding_zone: Market zone
    - direction: BUY or SELL
    - status: Lifecycle status

    SimpleBid columns:
    - volume: Total curve volume
    - min_price: Minimum price on curve
    - max_price: Maximum price on curve
    - num_steps: Number of curve steps
    - mtu_start: MTU start timestamp
    - mtu_end: MTU end timestamp

    BlockBid/LinkedBlockBid columns:
    - price: Limit price
    - volume_per_mtu: Volume per MTU
    - total_volume: Total volume across all MTUs
    - min_acceptance_ratio: Minimum fill ratio
    - delivery_start: Delivery period start
    - delivery_end: Delivery period end
    - mtu_count: Number of MTUs in delivery period
    - parent_bid_id: Parent reference (LinkedBlockBid only)

    ExclusiveGroupBid columns:
    - group_id: Group identifier
    - member_count: Number of member bids

    Args:
        order_book: Order book to export.

    Returns:
        pandas DataFrame with one row per bid.
    """
    rows = []

    for bid in order_book.bids:
        row: dict[str, Any] = {
            "bid_type": bid.bid_type.value,
            "bidding_zone": bid.bidding_zone.value,
            "direction": bid.direction.value,
            "status": bid.status.value,
        }

        if isinstance(bid, SimpleBid):
            row["bid_id"] = bid.bid_id
            row["volume"] = float(bid.curve.total_volume)
            row["min_price"] = float(bid.curve.min_price) if bid.curve.min_price else None
            row["max_price"] = float(bid.curve.max_price) if bid.curve.max_price else None
            row["num_steps"] = len(bid.curve.steps)
            row["mtu_start"] = bid.curve.mtu.start
            row["mtu_end"] = bid.curve.mtu.end
            row["price"] = None
            row["volume_per_mtu"] = None
            row["total_volume"] = None
            row["min_acceptance_ratio"] = None
            row["delivery_start"] = None
            row["delivery_end"] = None
            row["mtu_count"] = None
            row["parent_bid_id"] = None
            row["group_id"] = None
            row["member_count"] = None

        elif isinstance(bid, BlockBid):
            row["bid_id"] = bid.bid_id
            row["price"] = float(bid.price)
            row["volume_per_mtu"] = float(bid.volume)
            row["total_volume"] = float(bid.total_volume)
            row["min_acceptance_ratio"] = float(bid.min_acceptance_ratio)
            row["delivery_start"] = bid.delivery_period.start
            row["delivery_end"] = bid.delivery_period.end
            row["mtu_count"] = bid.delivery_period.mtu_count
            row["volume"] = None
            row["min_price"] = None
            row["max_price"] = None
            row["num_steps"] = None
            row["mtu_start"] = None
            row["mtu_end"] = None
            row["parent_bid_id"] = None
            row["group_id"] = None
            row["member_count"] = None

        elif isinstance(bid, LinkedBlockBid):
            row["bid_id"] = bid.bid_id
            row["price"] = float(bid.price)
            row["volume_per_mtu"] = float(bid.volume)
            row["total_volume"] = float(bid.total_volume)
            row["min_acceptance_ratio"] = float(bid.min_acceptance_ratio)
            row["delivery_start"] = bid.delivery_period.start
            row["delivery_end"] = bid.delivery_period.end
            row["mtu_count"] = bid.delivery_period.mtu_count
            row["parent_bid_id"] = bid.parent_bid_id
            row["volume"] = None
            row["min_price"] = None
            row["max_price"] = None
            row["num_steps"] = None
            row["mtu_start"] = None
            row["mtu_end"] = None
            row["group_id"] = None
            row["member_count"] = None

        elif isinstance(bid, ExclusiveGroupBid):
            row["bid_id"] = bid.group_id
            row["group_id"] = bid.group_id
            row["member_count"] = bid.member_count
            row["volume"] = None
            row["min_price"] = None
            row["max_price"] = None
            row["num_steps"] = None
            row["mtu_start"] = None
            row["mtu_end"] = None
            row["price"] = None
            row["volume_per_mtu"] = None
            row["total_volume"] = None
            row["min_acceptance_ratio"] = None
            row["delivery_start"] = None
            row["delivery_end"] = None
            row["mtu_count"] = None
            row["parent_bid_id"] = None

        rows.append(row)

    return pd.DataFrame(rows)


__all__ = [
    "BidUnion",
    "OrderBook",
    "generate_order_book_id",
    "create_order_book",
    "add_bid",
    "add_bids",
    "remove_bid",
    "filter_bids",
    "get_bid_by_id",
    "get_bids_by_zone",
    "get_bids_by_direction",
    "get_bids_by_status",
    "get_bids_by_type",
    "get_bids_in_period",
    "count_bids",
    "total_volume_by_zone",
    "get_order_book_summary",
    "update_bid_status",
    "update_all_statuses",
    "to_dataframe",
]
