"""Tests for nexa_bidkit.orders — order book/portfolio container."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from nexa_bidkit.bids import (
    BlockBid,
    ExclusiveGroupBid,
    LinkedBlockBid,
    SimpleBid,
    block_bid,
    exclusive_group,
    linked_block_bid,
    simple_bid_from_curve,
)
from nexa_bidkit.orders import (
    OrderBook,
    add_bid,
    add_bids,
    count_bids,
    create_order_book,
    filter_bids,
    get_bid_by_id,
    get_bids_by_direction,
    get_bids_by_status,
    get_bids_by_type,
    get_bids_by_zone,
    get_bids_in_period,
    get_order_book_summary,
    remove_bid,
    to_dataframe,
    total_volume_by_zone,
    update_all_statuses,
    update_bid_status,
)
from nexa_bidkit.types import (
    BiddingZone,
    BidStatus,
    BidType,
    CurveType,
    DeliveryPeriod,
    Direction,
    MTUDuration,
    MTUInterval,
    PriceQuantityCurve,
    PriceQuantityStep,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

T0 = datetime(2026, 4, 1, 10, 0, 0, tzinfo=UTC)


def step(price: str, volume: str) -> PriceQuantityStep:
    """Create a price-quantity step."""
    return PriceQuantityStep(price=Decimal(price), volume=Decimal(volume))


def quarter_interval(start: datetime = T0) -> MTUInterval:
    """Create a quarter-hourly MTU interval."""
    return MTUInterval.from_start(start, MTUDuration.QUARTER_HOURLY)


def hourly_interval(start: datetime = T0) -> MTUInterval:
    """Create an hourly MTU interval."""
    return MTUInterval.from_start(start, MTUDuration.HOURLY)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_mtu() -> MTUInterval:
    """Sample quarter-hourly MTU."""
    return quarter_interval()


@pytest.fixture
def sample_delivery_period() -> DeliveryPeriod:
    """Sample 4-hour delivery period."""
    return DeliveryPeriod(
        start=T0,
        end=T0 + timedelta(hours=4),
        duration=MTUDuration.QUARTER_HOURLY,
    )


@pytest.fixture
def sample_simple_bid(sample_mtu: MTUInterval) -> SimpleBid:
    """Sample SimpleBid."""
    curve = PriceQuantityCurve(
        curve_type=CurveType.SUPPLY,
        steps=[step("10.5", "50"), step("25.0", "100")],
        mtu=sample_mtu,
    )
    return simple_bid_from_curve(curve, BiddingZone.NO1, bid_id="simple_1")


@pytest.fixture
def sample_block_bid(sample_delivery_period: DeliveryPeriod) -> BlockBid:
    """Sample BlockBid."""
    return block_bid(
        bidding_zone=BiddingZone.NO1,
        direction=Direction.SELL,
        delivery_period=sample_delivery_period,
        price=Decimal("50.0"),
        volume=Decimal("100.0"),
        bid_id="block_1",
    )


@pytest.fixture
def sample_linked_bid(sample_delivery_period: DeliveryPeriod) -> LinkedBlockBid:
    """Sample LinkedBlockBid."""
    # Adjust delivery period to be after the parent
    later_period = DeliveryPeriod(
        start=sample_delivery_period.end,
        end=sample_delivery_period.end + timedelta(hours=2),
        duration=MTUDuration.QUARTER_HOURLY,
    )
    return linked_block_bid(
        parent_bid_id="block_1",
        bidding_zone=BiddingZone.NO1,
        direction=Direction.SELL,
        delivery_period=later_period,
        price=Decimal("55.0"),
        volume=Decimal("80.0"),
        bid_id="linked_1",
    )


@pytest.fixture
def sample_exclusive_group(sample_delivery_period: DeliveryPeriod) -> ExclusiveGroupBid:
    """Sample ExclusiveGroupBid."""
    block_1 = block_bid(
        bidding_zone=BiddingZone.NO2,
        direction=Direction.BUY,
        delivery_period=sample_delivery_period,
        price=Decimal("100.0"),
        volume=Decimal("50.0"),
        bid_id="group_member_1",
    )
    block_2 = block_bid(
        bidding_zone=BiddingZone.NO2,
        direction=Direction.BUY,
        delivery_period=sample_delivery_period,
        price=Decimal("90.0"),
        volume=Decimal("60.0"),
        bid_id="group_member_2",
    )
    return exclusive_group([block_1, block_2], group_id="exclusive_1")


@pytest.fixture
def empty_order_book() -> OrderBook:
    """Empty order book."""
    return create_order_book(order_book_id="test_book_empty")


@pytest.fixture
def sample_order_book(
    sample_simple_bid: SimpleBid,
    sample_block_bid: BlockBid,
    sample_linked_bid: LinkedBlockBid,
    sample_exclusive_group: ExclusiveGroupBid,
) -> OrderBook:
    """Order book with mixed bid types."""
    return create_order_book(
        bids=[
            sample_simple_bid,
            sample_block_bid,
            sample_linked_bid,
            sample_exclusive_group,
        ],
        order_book_id="test_book_sample",
    )


# ---------------------------------------------------------------------------
# Tests: OrderBook creation
# ---------------------------------------------------------------------------


class TestOrderBookCreation:
    """Tests for OrderBook creation and validation."""

    def test_create_empty_order_book(self) -> None:
        """Can create an empty order book."""
        book = create_order_book()
        assert book.order_book_id.startswith("book_")
        assert len(book.bids) == 0
        assert book.metadata == {}
        assert book.created_at.tzinfo is not None

    def test_create_with_explicit_id(self) -> None:
        """Can create with explicit order_book_id."""
        book = create_order_book(order_book_id="my_book")
        assert book.order_book_id == "my_book"

    def test_create_with_bids(self, sample_simple_bid: SimpleBid) -> None:
        """Can create with initial bids."""
        book = create_order_book(bids=[sample_simple_bid])
        assert len(book.bids) == 1
        assert book.bids[0] == sample_simple_bid

    def test_create_with_metadata(self) -> None:
        """Can create with metadata."""
        metadata = {"trader": "alice", "strategy": "test"}
        book = create_order_book(metadata=metadata)
        assert book.metadata == metadata

    def test_create_with_explicit_timestamp(self) -> None:
        """Can create with explicit timestamp."""
        ts = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        book = create_order_book(created_at=ts)
        assert book.created_at == ts

    def test_order_book_id_must_be_nonempty(self) -> None:
        """order_book_id must be non-empty."""
        with pytest.raises(ValidationError, match="order_book_id must be a non-empty string"):
            OrderBook(order_book_id="", bids=[], metadata={}, created_at=T0)

    def test_created_at_must_be_timezone_aware(self) -> None:
        """created_at must be timezone-aware."""
        naive_dt = datetime(2026, 1, 1, 12, 0, 0)
        with pytest.raises(ValidationError, match="timezone-aware datetime"):
            OrderBook(order_book_id="test", bids=[], metadata={}, created_at=naive_dt)

    def test_immutable_order_book(self, empty_order_book: OrderBook) -> None:
        """OrderBook is immutable."""
        with pytest.raises(ValidationError):
            empty_order_book.bids = []  # type: ignore


# ---------------------------------------------------------------------------
# Tests: Adding bids
# ---------------------------------------------------------------------------


class TestAddingBids:
    """Tests for adding bids to order books."""

    def test_add_single_bid(
        self, empty_order_book: OrderBook, sample_simple_bid: SimpleBid
    ) -> None:
        """Can add a single bid."""
        book = add_bid(empty_order_book, sample_simple_bid)
        assert len(book.bids) == 1
        assert book.bids[0] == sample_simple_bid

    def test_add_multiple_bids(
        self,
        empty_order_book: OrderBook,
        sample_simple_bid: SimpleBid,
        sample_block_bid: BlockBid,
    ) -> None:
        """Can add multiple bids at once."""
        book = add_bids(empty_order_book, [sample_simple_bid, sample_block_bid])
        assert len(book.bids) == 2

    def test_add_bid_is_immutable(
        self, empty_order_book: OrderBook, sample_simple_bid: SimpleBid
    ) -> None:
        """Adding a bid returns a new OrderBook."""
        book = add_bid(empty_order_book, sample_simple_bid)
        assert len(empty_order_book.bids) == 0
        assert len(book.bids) == 1

    def test_add_duplicate_bid_id_raises(
        self, empty_order_book: OrderBook, sample_simple_bid: SimpleBid
    ) -> None:
        """Adding a bid with duplicate ID raises."""
        book = add_bid(empty_order_book, sample_simple_bid)
        with pytest.raises(ValueError, match="Duplicate bid_ids"):
            add_bid(book, sample_simple_bid)

    def test_add_linked_bid_without_parent_raises(
        self, empty_order_book: OrderBook, sample_linked_bid: LinkedBlockBid
    ) -> None:
        """Adding a linked bid without parent raises."""
        with pytest.raises(ValueError, match="references non-existent parent"):
            add_bid(empty_order_book, sample_linked_bid)

    def test_add_linked_bid_with_parent_succeeds(
        self,
        empty_order_book: OrderBook,
        sample_block_bid: BlockBid,
        sample_linked_bid: LinkedBlockBid,
    ) -> None:
        """Adding a linked bid with parent succeeds."""
        book = add_bid(empty_order_book, sample_block_bid)
        book = add_bid(book, sample_linked_bid)
        assert len(book.bids) == 2


# ---------------------------------------------------------------------------
# Tests: Removing bids
# ---------------------------------------------------------------------------


class TestRemovingBids:
    """Tests for removing bids from order books."""

    def test_remove_bid_by_id(
        self, sample_order_book: OrderBook, sample_simple_bid: SimpleBid
    ) -> None:
        """Can remove a bid by ID."""
        book = remove_bid(sample_order_book, sample_simple_bid.bid_id)
        assert len(book.bids) == len(sample_order_book.bids) - 1
        assert get_bid_by_id(book, sample_simple_bid.bid_id) is None

    def test_remove_nonexistent_bid_raises(self, sample_order_book: OrderBook) -> None:
        """Removing nonexistent bid raises."""
        with pytest.raises(ValueError, match="No bid found with ID"):
            remove_bid(sample_order_book, "nonexistent")

    def test_remove_is_immutable(
        self, sample_order_book: OrderBook, sample_simple_bid: SimpleBid
    ) -> None:
        """Removing a bid returns a new OrderBook."""
        original_count = len(sample_order_book.bids)
        book = remove_bid(sample_order_book, sample_simple_bid.bid_id)
        assert len(sample_order_book.bids) == original_count
        assert len(book.bids) == original_count - 1

    def test_remove_exclusive_group_by_group_id(
        self, sample_order_book: OrderBook, sample_exclusive_group: ExclusiveGroupBid
    ) -> None:
        """Can remove ExclusiveGroupBid by group_id."""
        book = remove_bid(sample_order_book, sample_exclusive_group.group_id)
        assert get_bid_by_id(book, sample_exclusive_group.group_id) is None

    def test_filter_bids(self, sample_order_book: OrderBook) -> None:
        """Can filter bids with predicate."""
        book = filter_bids(sample_order_book, lambda b: b.direction == Direction.SELL)
        # Should have simple_bid, block_bid, linked_bid (all SELL)
        assert len(book.bids) == 3


# ---------------------------------------------------------------------------
# Tests: Querying bids
# ---------------------------------------------------------------------------


class TestQueryingBids:
    """Tests for querying bids in order books."""

    def test_get_bid_by_id(
        self, sample_order_book: OrderBook, sample_simple_bid: SimpleBid
    ) -> None:
        """Can retrieve bid by ID."""
        bid = get_bid_by_id(sample_order_book, sample_simple_bid.bid_id)
        assert bid == sample_simple_bid

    def test_get_bid_by_id_nonexistent(self, sample_order_book: OrderBook) -> None:
        """Returns None for nonexistent ID."""
        bid = get_bid_by_id(sample_order_book, "nonexistent")
        assert bid is None

    def test_get_bid_by_group_id(
        self, sample_order_book: OrderBook, sample_exclusive_group: ExclusiveGroupBid
    ) -> None:
        """Can retrieve ExclusiveGroupBid by group_id."""
        bid = get_bid_by_id(sample_order_book, sample_exclusive_group.group_id)
        assert bid == sample_exclusive_group

    def test_get_bid_by_member_id(
        self, sample_order_book: OrderBook, sample_exclusive_group: ExclusiveGroupBid
    ) -> None:
        """Can retrieve member bid from ExclusiveGroupBid."""
        member = sample_exclusive_group.block_bids[0]
        bid = get_bid_by_id(sample_order_book, member.bid_id)
        assert bid == member

    def test_get_bids_by_zone(self, sample_order_book: OrderBook) -> None:
        """Can filter by bidding zone."""
        no1_bids = get_bids_by_zone(sample_order_book, BiddingZone.NO1)
        # simple_bid, block_bid, linked_bid are NO1
        assert len(no1_bids) == 3

        no2_bids = get_bids_by_zone(sample_order_book, BiddingZone.NO2)
        # exclusive_group is NO2
        assert len(no2_bids) == 1

    def test_get_bids_by_direction(self, sample_order_book: OrderBook) -> None:
        """Can filter by direction."""
        sell_bids = get_bids_by_direction(sample_order_book, Direction.SELL)
        assert len(sell_bids) == 3

        buy_bids = get_bids_by_direction(sample_order_book, Direction.BUY)
        assert len(buy_bids) == 1

    def test_get_bids_by_status(self, sample_order_book: OrderBook) -> None:
        """Can filter by status."""
        draft_bids = get_bids_by_status(sample_order_book, BidStatus.DRAFT)
        assert len(draft_bids) == len(sample_order_book.bids)

        submitted = get_bids_by_status(sample_order_book, BidStatus.SUBMITTED)
        assert len(submitted) == 0

    def test_get_bids_by_type(self, sample_order_book: OrderBook) -> None:
        """Can filter by bid type."""
        simple = get_bids_by_type(sample_order_book, BidType.SIMPLE_HOURLY)
        assert len(simple) == 1

        block = get_bids_by_type(sample_order_book, BidType.BLOCK)
        assert len(block) == 1

        linked = get_bids_by_type(sample_order_book, BidType.LINKED_BLOCK)
        assert len(linked) == 1

        exclusive = get_bids_by_type(sample_order_book, BidType.EXCLUSIVE_GROUP)
        assert len(exclusive) == 1

    def test_get_bids_in_period(self, sample_order_book: OrderBook) -> None:
        """Can filter by time period."""
        # Period covering the sample MTU and delivery periods
        bids = get_bids_in_period(
            sample_order_book,
            T0 - timedelta(hours=1),
            T0 + timedelta(hours=5),
        )
        # All bids should overlap
        assert len(bids) == len(sample_order_book.bids)

    def test_get_bids_in_period_no_overlap(self, sample_order_book: OrderBook) -> None:
        """Returns empty list for non-overlapping period."""
        bids = get_bids_in_period(
            sample_order_book,
            T0 + timedelta(days=10),
            T0 + timedelta(days=11),
        )
        assert len(bids) == 0

    def test_get_bids_in_period_requires_timezone_aware(self, sample_order_book: OrderBook) -> None:
        """get_bids_in_period requires timezone-aware datetimes."""
        naive_dt = datetime(2026, 1, 1, 12, 0, 0)
        with pytest.raises(ValueError, match="timezone-aware datetimes"):
            get_bids_in_period(sample_order_book, naive_dt, T0)


# ---------------------------------------------------------------------------
# Tests: Aggregation
# ---------------------------------------------------------------------------


class TestAggregation:
    """Tests for aggregation functions."""

    def test_count_bids(self, sample_order_book: OrderBook) -> None:
        """Can count bids by type."""
        counts = count_bids(sample_order_book)
        assert counts["SIMPLE_HOURLY"] == 1
        assert counts["BLOCK"] == 1
        assert counts["LINKED_BLOCK"] == 1
        assert counts["EXCLUSIVE_GROUP"] == 1

    def test_count_bids_empty(self, empty_order_book: OrderBook) -> None:
        """Count returns zeros for empty book."""
        counts = count_bids(empty_order_book)
        assert all(count == 0 for count in counts.values())

    def test_total_volume_by_zone(
        self, sample_order_book: OrderBook, sample_simple_bid: SimpleBid
    ) -> None:
        """Can calculate total volume by zone."""
        volumes = total_volume_by_zone(sample_order_book)
        assert BiddingZone.NO1 in volumes
        assert BiddingZone.NO2 in volumes
        # Volumes should be positive
        assert volumes[BiddingZone.NO1] > 0
        assert volumes[BiddingZone.NO2] > 0

    def test_total_volume_by_zone_filtered(self, sample_order_book: OrderBook) -> None:
        """Can filter volume calculation by zone."""
        volumes = total_volume_by_zone(sample_order_book, zone=BiddingZone.NO1)
        assert BiddingZone.NO1 in volumes
        assert BiddingZone.NO2 not in volumes

    def test_total_volume_by_zone_empty(self, empty_order_book: OrderBook) -> None:
        """Returns empty dict for empty book."""
        volumes = total_volume_by_zone(empty_order_book)
        assert volumes == {}

    def test_get_order_book_summary(self, sample_order_book: OrderBook) -> None:
        """Can generate order book summary."""
        summary = get_order_book_summary(sample_order_book)
        assert summary["order_book_id"] == sample_order_book.order_book_id
        assert summary["total_bids"] == len(sample_order_book.bids)
        assert "bid_counts" in summary
        assert "zones" in summary
        assert "directions" in summary
        assert "statuses" in summary
        assert "total_volume_by_zone" in summary


# ---------------------------------------------------------------------------
# Tests: Status updates
# ---------------------------------------------------------------------------


class TestStatusUpdates:
    """Tests for status update functions."""

    def test_update_bid_status(
        self, sample_order_book: OrderBook, sample_simple_bid: SimpleBid
    ) -> None:
        """Can update single bid status."""
        book = update_bid_status(sample_order_book, sample_simple_bid.bid_id, BidStatus.VALIDATED)
        updated_bid = get_bid_by_id(book, sample_simple_bid.bid_id)
        assert updated_bid is not None
        assert updated_bid.status == BidStatus.VALIDATED

    def test_update_bid_status_nonexistent_raises(self, sample_order_book: OrderBook) -> None:
        """Updating nonexistent bid raises."""
        with pytest.raises(ValueError, match="No bid found with ID"):
            update_bid_status(sample_order_book, "nonexistent", BidStatus.VALIDATED)

    def test_update_bid_status_is_immutable(
        self, sample_order_book: OrderBook, sample_simple_bid: SimpleBid
    ) -> None:
        """Status update returns new OrderBook."""
        _ = update_bid_status(sample_order_book, sample_simple_bid.bid_id, BidStatus.VALIDATED)
        original_bid = get_bid_by_id(sample_order_book, sample_simple_bid.bid_id)
        assert original_bid is not None
        assert original_bid.status == BidStatus.DRAFT

    def test_update_exclusive_group_status(
        self, sample_order_book: OrderBook, sample_exclusive_group: ExclusiveGroupBid
    ) -> None:
        """Can update ExclusiveGroupBid status."""
        book = update_bid_status(
            sample_order_book, sample_exclusive_group.group_id, BidStatus.SUBMITTED
        )
        updated_group = get_bid_by_id(book, sample_exclusive_group.group_id)
        assert updated_group is not None
        assert updated_group.status == BidStatus.SUBMITTED

    def test_update_member_bid_status_in_group(
        self, sample_order_book: OrderBook, sample_exclusive_group: ExclusiveGroupBid
    ) -> None:
        """Can update member bid status within ExclusiveGroupBid."""
        member = sample_exclusive_group.block_bids[0]
        book = update_bid_status(sample_order_book, member.bid_id, BidStatus.VALIDATED)
        updated_member = get_bid_by_id(book, member.bid_id)
        assert updated_member is not None
        assert updated_member.status == BidStatus.VALIDATED

    def test_update_all_statuses(self, sample_order_book: OrderBook) -> None:
        """Can update all bid statuses."""
        book = update_all_statuses(sample_order_book, BidStatus.VALIDATED)
        for bid in book.bids:
            assert bid.status == BidStatus.VALIDATED

    def test_update_all_statuses_filtered(self, sample_order_book: OrderBook) -> None:
        """Can update statuses with filter."""
        # First update one bid to VALIDATED
        book = update_bid_status(sample_order_book, "simple_1", BidStatus.VALIDATED)
        # Then update only DRAFT bids to SUBMITTED
        book = update_all_statuses(book, BidStatus.SUBMITTED, filter_current_status=BidStatus.DRAFT)

        validated_bid = get_bid_by_id(book, "simple_1")
        assert validated_bid is not None
        assert validated_bid.status == BidStatus.VALIDATED

        # Other bids should be SUBMITTED
        draft_bids = get_bids_by_status(book, BidStatus.DRAFT)
        assert len(draft_bids) == 0

        submitted_bids = get_bids_by_status(book, BidStatus.SUBMITTED)
        assert len(submitted_bids) == 3


# ---------------------------------------------------------------------------
# Tests: DataFrame export
# ---------------------------------------------------------------------------


class TestDataFrameExport:
    """Tests for DataFrame export."""

    def test_to_dataframe_empty(self, empty_order_book: OrderBook) -> None:
        """Can export empty order book."""
        df = to_dataframe(empty_order_book)
        assert len(df) == 0

    def test_to_dataframe_mixed_types(self, sample_order_book: OrderBook) -> None:
        """Can export order book with mixed bid types."""
        df = to_dataframe(sample_order_book)
        assert len(df) == len(sample_order_book.bids)
        assert "bid_id" in df.columns
        assert "bid_type" in df.columns
        assert "bidding_zone" in df.columns
        assert "direction" in df.columns
        assert "status" in df.columns

    def test_to_dataframe_simple_bid_columns(
        self, empty_order_book: OrderBook, sample_simple_bid: SimpleBid
    ) -> None:
        """SimpleBid exports with correct columns."""
        book = add_bid(empty_order_book, sample_simple_bid)
        df = to_dataframe(book)
        row = df.iloc[0]
        assert row["bid_type"] == "SIMPLE_HOURLY"
        assert row["volume"] > 0
        assert row["min_price"] is not None
        assert row["max_price"] is not None
        assert row["num_steps"] == 2
        assert row["price"] is None
        assert row["parent_bid_id"] is None

    def test_to_dataframe_block_bid_columns(
        self, empty_order_book: OrderBook, sample_block_bid: BlockBid
    ) -> None:
        """BlockBid exports with correct columns."""
        book = add_bid(empty_order_book, sample_block_bid)
        df = to_dataframe(book)
        row = df.iloc[0]
        assert row["bid_type"] == "BLOCK"
        assert row["price"] > 0
        assert row["volume_per_mtu"] > 0
        assert row["total_volume"] > 0
        assert row["min_acceptance_ratio"] == 1.0
        assert row["mtu_count"] > 0
        assert row["volume"] is None
        assert row["parent_bid_id"] is None

    def test_to_dataframe_linked_bid_columns(
        self,
        empty_order_book: OrderBook,
        sample_block_bid: BlockBid,
        sample_linked_bid: LinkedBlockBid,
    ) -> None:
        """LinkedBlockBid exports with correct columns."""
        book = add_bids(empty_order_book, [sample_block_bid, sample_linked_bid])
        df = to_dataframe(book)
        linked_row = df[df["bid_id"] == "linked_1"].iloc[0]
        assert linked_row["bid_type"] == "LINKED_BLOCK"
        assert linked_row["parent_bid_id"] == "block_1"

    def test_to_dataframe_exclusive_group_columns(
        self, empty_order_book: OrderBook, sample_exclusive_group: ExclusiveGroupBid
    ) -> None:
        """ExclusiveGroupBid exports with correct columns."""
        book = add_bid(empty_order_book, sample_exclusive_group)
        df = to_dataframe(book)
        row = df.iloc[0]
        assert row["bid_type"] == "EXCLUSIVE_GROUP"
        assert row["group_id"] == sample_exclusive_group.group_id
        assert row["member_count"] == 2
        assert row["volume"] is None
        assert row["price"] is None
