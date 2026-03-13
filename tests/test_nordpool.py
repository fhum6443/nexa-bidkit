"""Tests for nexa_bidkit.nordpool — Nord Pool market adapter."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from nexa_bidkit.bids import (
    BlockBid,
    ExclusiveGroupBid,
    LinkedBlockBid,
    SimpleBid,
    exclusive_group,
)
from nexa_bidkit.nordpool import (
    BlockListCreate,
    CurveOrderCreate,
    NordPoolSubmission,
    bidding_zone_to_area_code,
    block_bid_to_block_list,
    exclusive_group_to_block_list,
    linked_block_bid_to_block_list,
    order_book_to_nord_pool,
    simple_bid_to_curve_order,
)
from nexa_bidkit.orders import OrderBook, add_bid, create_order_book
from nexa_bidkit.types import (
    BiddingZone,
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
AUCTION_ID = "DA-2026-04-01"
PORTFOLIO = "test-portfolio"


def _mtu(start: datetime = T0, duration: MTUDuration = MTUDuration.HOURLY) -> MTUInterval:
    return MTUInterval.from_start(start, duration)


def _delivery_period(
    start: datetime = T0,
    hours: int = 2,
    duration: MTUDuration = MTUDuration.HOURLY,
) -> DeliveryPeriod:
    return DeliveryPeriod(start=start, end=start + timedelta(hours=hours), duration=duration)


def _supply_curve(start: datetime = T0) -> PriceQuantityCurve:
    return PriceQuantityCurve(
        curve_type=CurveType.SUPPLY,
        steps=[
            PriceQuantityStep(price=Decimal("10.00"), volume=Decimal("50")),
            PriceQuantityStep(price=Decimal("20.00"), volume=Decimal("100")),
        ],
        mtu=_mtu(start),
    )


def _demand_curve(start: datetime = T0) -> PriceQuantityCurve:
    return PriceQuantityCurve(
        curve_type=CurveType.DEMAND,
        steps=[
            PriceQuantityStep(price=Decimal("80.00"), volume=Decimal("30")),
            PriceQuantityStep(price=Decimal("40.00"), volume=Decimal("60")),
        ],
        mtu=_mtu(start),
    )


def _simple_sell_bid(start: datetime = T0) -> SimpleBid:
    return SimpleBid(
        bid_id="simple-sell-1",
        bidding_zone=BiddingZone.NO1,
        direction=Direction.SELL,
        curve=_supply_curve(start),
    )


def _simple_buy_bid(start: datetime = T0) -> SimpleBid:
    return SimpleBid(
        bid_id="simple-buy-1",
        bidding_zone=BiddingZone.NO1,
        direction=Direction.BUY,
        curve=_demand_curve(start),
    )


def _block_sell_bid(bid_id: str = "block-1", zone: BiddingZone = BiddingZone.NO1) -> BlockBid:
    return BlockBid(
        bid_id=bid_id,
        bidding_zone=zone,
        direction=Direction.SELL,
        delivery_period=_delivery_period(),
        price=Decimal("45.00"),
        volume=Decimal("100"),
        min_acceptance_ratio=Decimal("0.5"),
    )


def _block_buy_bid(bid_id: str = "block-buy-1") -> BlockBid:
    return BlockBid(
        bid_id=bid_id,
        bidding_zone=BiddingZone.NO1,
        direction=Direction.BUY,
        delivery_period=_delivery_period(),
        price=Decimal("60.00"),
        volume=Decimal("80"),
    )


def _contract_resolver(mtu: MTUInterval, zone: BiddingZone) -> str:
    """Simple resolver: zone-value + hour offset from T0."""
    offset_hours = int((mtu.start - T0).total_seconds() // 3600)
    return f"{zone.value}-{10 + offset_hours}"


# ---------------------------------------------------------------------------
# Tests: bidding_zone_to_area_code
# ---------------------------------------------------------------------------


class TestBiddingZoneToAreaCode:
    def test_nordic_zones_map_correctly(self) -> None:
        assert bidding_zone_to_area_code(BiddingZone.NO1) == "NO1"
        assert bidding_zone_to_area_code(BiddingZone.NO5) == "NO5"
        assert bidding_zone_to_area_code(BiddingZone.SE3) == "SE3"
        assert bidding_zone_to_area_code(BiddingZone.FI) == "FI"
        assert bidding_zone_to_area_code(BiddingZone.DK1) == "DK1"
        assert bidding_zone_to_area_code(BiddingZone.DK2) == "DK2"

    def test_baltic_zones_map_correctly(self) -> None:
        assert bidding_zone_to_area_code(BiddingZone.EE) == "EE"
        assert bidding_zone_to_area_code(BiddingZone.LV) == "LV"
        assert bidding_zone_to_area_code(BiddingZone.LT) == "LT"

    def test_pl_maps_correctly(self) -> None:
        assert bidding_zone_to_area_code(BiddingZone.PL) == "PL"

    def test_unsupported_cwe_de_lu_raises(self) -> None:
        with pytest.raises(ValueError, match="not supported by Nord Pool"):
            bidding_zone_to_area_code(BiddingZone.DE_LU)

    def test_unsupported_fr_raises(self) -> None:
        with pytest.raises(ValueError, match="not supported by Nord Pool"):
            bidding_zone_to_area_code(BiddingZone.FR)

    def test_unsupported_gb_raises(self) -> None:
        with pytest.raises(ValueError, match="not supported by Nord Pool"):
            bidding_zone_to_area_code(BiddingZone.GB)

    def test_unsupported_italian_zone_raises(self) -> None:
        with pytest.raises(ValueError, match="not supported by Nord Pool"):
            bidding_zone_to_area_code(BiddingZone.IT_NORD)

    def test_unsupported_iberian_zone_raises(self) -> None:
        with pytest.raises(ValueError, match="not supported by Nord Pool"):
            bidding_zone_to_area_code(BiddingZone.ES)


# ---------------------------------------------------------------------------
# Tests: simple_bid_to_curve_order
# ---------------------------------------------------------------------------


class TestSimpleBidToCurveOrder:
    def test_returns_curve_order_create(self) -> None:
        bid = _simple_sell_bid()
        result = simple_bid_to_curve_order(bid, AUCTION_ID, PORTFOLIO, _contract_resolver)
        assert isinstance(result, CurveOrderCreate)

    def test_auction_id_and_portfolio(self) -> None:
        bid = _simple_sell_bid()
        result = simple_bid_to_curve_order(bid, AUCTION_ID, PORTFOLIO, _contract_resolver)
        assert result.auction_id == AUCTION_ID
        assert result.portfolio == PORTFOLIO

    def test_area_code_set_from_zone(self) -> None:
        bid = _simple_sell_bid()
        result = simple_bid_to_curve_order(bid, AUCTION_ID, PORTFOLIO, _contract_resolver)
        assert result.area_code == "NO1"

    def test_contract_id_from_resolver(self) -> None:
        bid = _simple_sell_bid()
        result = simple_bid_to_curve_order(bid, AUCTION_ID, PORTFOLIO, _contract_resolver)
        assert len(result.curves) == 1
        assert result.curves[0].contract_id == "NO1-10"

    def test_sell_volumes_are_positive(self) -> None:
        bid = _simple_sell_bid()
        result = simple_bid_to_curve_order(bid, AUCTION_ID, PORTFOLIO, _contract_resolver)
        for point in result.curves[0].curve_points:
            assert point.volume > 0

    def test_buy_volumes_are_negative(self) -> None:
        bid = _simple_buy_bid()
        result = simple_bid_to_curve_order(bid, AUCTION_ID, PORTFOLIO, _contract_resolver)
        for point in result.curves[0].curve_points:
            assert point.volume < 0

    def test_curve_points_count_matches_steps(self) -> None:
        bid = _simple_sell_bid()
        result = simple_bid_to_curve_order(bid, AUCTION_ID, PORTFOLIO, _contract_resolver)
        assert len(result.curves[0].curve_points) == len(bid.curve.steps)

    def test_comment_passed_through(self) -> None:
        bid = _simple_sell_bid()
        result = simple_bid_to_curve_order(
            bid, AUCTION_ID, PORTFOLIO, _contract_resolver, comment="my comment"
        )
        assert result.comment == "my comment"

    def test_comment_none_by_default(self) -> None:
        bid = _simple_sell_bid()
        result = simple_bid_to_curve_order(bid, AUCTION_ID, PORTFOLIO, _contract_resolver)
        assert result.comment is None

    def test_unsupported_zone_raises(self) -> None:
        bid = SimpleBid(
            bid_id="cwe-bid",
            bidding_zone=BiddingZone.DE_LU,
            direction=Direction.SELL,
            curve=PriceQuantityCurve(
                curve_type=CurveType.SUPPLY,
                steps=[PriceQuantityStep(price=Decimal("10"), volume=Decimal("50"))],
                mtu=_mtu(),
            ),
        )
        with pytest.raises(ValueError, match="not supported by Nord Pool"):
            simple_bid_to_curve_order(bid, AUCTION_ID, PORTFOLIO, _contract_resolver)


# ---------------------------------------------------------------------------
# Tests: block_bid_to_block_list
# ---------------------------------------------------------------------------


class TestBlockBidToBlockList:
    def test_returns_block_list_create(self) -> None:
        bid = _block_sell_bid()
        result = block_bid_to_block_list(bid, AUCTION_ID, PORTFOLIO, _contract_resolver)
        assert isinstance(result, BlockListCreate)

    def test_area_code_set_from_zone(self) -> None:
        bid = _block_sell_bid()
        result = block_bid_to_block_list(bid, AUCTION_ID, PORTFOLIO, _contract_resolver)
        assert result.area_code == "NO1"

    def test_one_block_per_bid(self) -> None:
        bid = _block_sell_bid()
        result = block_bid_to_block_list(bid, AUCTION_ID, PORTFOLIO, _contract_resolver)
        assert len(result.blocks) == 1

    def test_block_name_is_bid_id(self) -> None:
        bid = _block_sell_bid(bid_id="my-block")
        result = block_bid_to_block_list(bid, AUCTION_ID, PORTFOLIO, _contract_resolver)
        assert result.blocks[0].name == "my-block"

    def test_block_price_converted_to_float(self) -> None:
        bid = _block_sell_bid()
        result = block_bid_to_block_list(bid, AUCTION_ID, PORTFOLIO, _contract_resolver)
        assert result.blocks[0].price == pytest.approx(45.0)

    def test_mar_converted_to_float(self) -> None:
        bid = _block_sell_bid()
        result = block_bid_to_block_list(bid, AUCTION_ID, PORTFOLIO, _contract_resolver)
        assert result.blocks[0].minimum_acceptance_ratio == pytest.approx(0.5)

    def test_periods_match_mtu_intervals(self) -> None:
        bid = _block_sell_bid()
        result = block_bid_to_block_list(bid, AUCTION_ID, PORTFOLIO, _contract_resolver)
        expected_count = bid.delivery_period.mtu_count
        assert len(result.blocks[0].periods) == expected_count

    def test_sell_periods_have_positive_volume(self) -> None:
        bid = _block_sell_bid()
        result = block_bid_to_block_list(bid, AUCTION_ID, PORTFOLIO, _contract_resolver)
        for period in result.blocks[0].periods:
            assert period.volume > 0

    def test_buy_periods_have_negative_volume(self) -> None:
        bid = _block_buy_bid()
        result = block_bid_to_block_list(bid, AUCTION_ID, PORTFOLIO, _contract_resolver)
        for period in result.blocks[0].periods:
            assert period.volume < 0

    def test_period_contract_ids_from_resolver(self) -> None:
        bid = _block_sell_bid()
        result = block_bid_to_block_list(bid, AUCTION_ID, PORTFOLIO, _contract_resolver)
        periods = result.blocks[0].periods
        assert periods[0].contract_id == "NO1-10"
        assert periods[1].contract_id == "NO1-11"

    def test_linked_to_not_set(self) -> None:
        bid = _block_sell_bid()
        result = block_bid_to_block_list(bid, AUCTION_ID, PORTFOLIO, _contract_resolver)
        assert result.blocks[0].linked_to is None

    def test_exclusive_group_not_set(self) -> None:
        bid = _block_sell_bid()
        result = block_bid_to_block_list(bid, AUCTION_ID, PORTFOLIO, _contract_resolver)
        assert result.blocks[0].exclusive_group is None


# ---------------------------------------------------------------------------
# Tests: linked_block_bid_to_block_list
# ---------------------------------------------------------------------------


class TestLinkedBlockBidToBlockList:
    def _linked_bid(self) -> LinkedBlockBid:
        return LinkedBlockBid(
            bid_id="linked-1",
            parent_bid_id="block-1",
            bidding_zone=BiddingZone.NO1,
            direction=Direction.SELL,
            delivery_period=_delivery_period(start=T0 + timedelta(hours=2)),
            price=Decimal("50.00"),
            volume=Decimal("75"),
            min_acceptance_ratio=Decimal("0.75"),
        )

    def test_linked_to_set_from_parent_bid_id(self) -> None:
        bid = self._linked_bid()
        result = linked_block_bid_to_block_list(bid, AUCTION_ID, PORTFOLIO, _contract_resolver)
        assert result.blocks[0].linked_to == "block-1"

    def test_returns_block_list_create(self) -> None:
        bid = self._linked_bid()
        result = linked_block_bid_to_block_list(bid, AUCTION_ID, PORTFOLIO, _contract_resolver)
        assert isinstance(result, BlockListCreate)

    def test_block_name_is_bid_id(self) -> None:
        bid = self._linked_bid()
        result = linked_block_bid_to_block_list(bid, AUCTION_ID, PORTFOLIO, _contract_resolver)
        assert result.blocks[0].name == "linked-1"

    def test_periods_match_mtu_count(self) -> None:
        bid = self._linked_bid()
        result = linked_block_bid_to_block_list(bid, AUCTION_ID, PORTFOLIO, _contract_resolver)
        assert len(result.blocks[0].periods) == bid.delivery_period.mtu_count

    def test_mar_carried_through(self) -> None:
        bid = self._linked_bid()
        result = linked_block_bid_to_block_list(bid, AUCTION_ID, PORTFOLIO, _contract_resolver)
        assert result.blocks[0].minimum_acceptance_ratio == pytest.approx(0.75)

    def test_exclusive_group_not_set(self) -> None:
        bid = self._linked_bid()
        result = linked_block_bid_to_block_list(bid, AUCTION_ID, PORTFOLIO, _contract_resolver)
        assert result.blocks[0].exclusive_group is None


# ---------------------------------------------------------------------------
# Tests: exclusive_group_to_block_list
# ---------------------------------------------------------------------------


class TestExclusiveGroupToBlockList:
    def _group(self) -> ExclusiveGroupBid:
        bid_a = BlockBid(
            bid_id="excl-a",
            bidding_zone=BiddingZone.NO2,
            direction=Direction.SELL,
            delivery_period=_delivery_period(),
            price=Decimal("40.00"),
            volume=Decimal("50"),
        )
        bid_b = BlockBid(
            bid_id="excl-b",
            bidding_zone=BiddingZone.NO2,
            direction=Direction.SELL,
            delivery_period=_delivery_period(start=T0 + timedelta(hours=4)),
            price=Decimal("45.00"),
            volume=Decimal("60"),
        )
        return exclusive_group([bid_a, bid_b], group_id="grp-1")

    def test_returns_block_list_create(self) -> None:
        grp = self._group()
        result = exclusive_group_to_block_list(grp, AUCTION_ID, PORTFOLIO, _contract_resolver)
        assert isinstance(result, BlockListCreate)

    def test_area_code_from_group_zone(self) -> None:
        grp = self._group()
        result = exclusive_group_to_block_list(grp, AUCTION_ID, PORTFOLIO, _contract_resolver)
        assert result.area_code == "NO2"

    def test_all_blocks_have_exclusive_group_set(self) -> None:
        grp = self._group()
        result = exclusive_group_to_block_list(grp, AUCTION_ID, PORTFOLIO, _contract_resolver)
        for block in result.blocks:
            assert block.exclusive_group == "grp-1"

    def test_block_count_matches_members(self) -> None:
        grp = self._group()
        result = exclusive_group_to_block_list(grp, AUCTION_ID, PORTFOLIO, _contract_resolver)
        assert len(result.blocks) == grp.member_count

    def test_block_names_from_member_bid_ids(self) -> None:
        grp = self._group()
        result = exclusive_group_to_block_list(grp, AUCTION_ID, PORTFOLIO, _contract_resolver)
        names = {b.name for b in result.blocks}
        assert names == {"excl-a", "excl-b"}

    def test_linked_to_not_set(self) -> None:
        grp = self._group()
        result = exclusive_group_to_block_list(grp, AUCTION_ID, PORTFOLIO, _contract_resolver)
        for block in result.blocks:
            assert block.linked_to is None


# ---------------------------------------------------------------------------
# Tests: order_book_to_nord_pool
# ---------------------------------------------------------------------------


class TestOrderBookToNordPool:
    def _mixed_order_book(self) -> OrderBook:
        parent_bid = _block_sell_bid(bid_id="parent-block")
        linked = LinkedBlockBid(
            bid_id="linked-x",
            parent_bid_id="parent-block",
            bidding_zone=BiddingZone.NO1,
            direction=Direction.SELL,
            delivery_period=_delivery_period(start=T0 + timedelta(hours=2)),
            price=Decimal("50.00"),
            volume=Decimal("50"),
        )
        excl_a = BlockBid(
            bid_id="excl-a",
            bidding_zone=BiddingZone.NO1,
            direction=Direction.SELL,
            delivery_period=_delivery_period(start=T0 + timedelta(hours=4)),
            price=Decimal("30.00"),
            volume=Decimal("40"),
        )
        excl_b = BlockBid(
            bid_id="excl-b",
            bidding_zone=BiddingZone.NO1,
            direction=Direction.SELL,
            delivery_period=_delivery_period(start=T0 + timedelta(hours=6)),
            price=Decimal("35.00"),
            volume=Decimal("45"),
        )
        grp = exclusive_group([excl_a, excl_b], group_id="grp-1")
        simple = _simple_sell_bid(start=T0 + timedelta(hours=8))

        ob = create_order_book()
        ob = add_bid(ob, simple)
        ob = add_bid(ob, parent_bid)
        ob = add_bid(ob, linked)
        ob = add_bid(ob, grp)
        return ob

    def test_returns_nord_pool_submission(self) -> None:
        ob = self._mixed_order_book()
        result = order_book_to_nord_pool(ob, AUCTION_ID, PORTFOLIO, _contract_resolver)
        assert isinstance(result, NordPoolSubmission)

    def test_simple_bids_go_to_curve_orders(self) -> None:
        ob = self._mixed_order_book()
        result = order_book_to_nord_pool(ob, AUCTION_ID, PORTFOLIO, _contract_resolver)
        assert len(result.curve_orders) == 1
        assert isinstance(result.curve_orders[0], CurveOrderCreate)

    def test_block_bids_go_to_block_orders(self) -> None:
        ob = self._mixed_order_book()
        result = order_book_to_nord_pool(ob, AUCTION_ID, PORTFOLIO, _contract_resolver)
        assert len(result.block_orders) == 1

    def test_linked_bids_go_to_linked_block_orders(self) -> None:
        ob = self._mixed_order_book()
        result = order_book_to_nord_pool(ob, AUCTION_ID, PORTFOLIO, _contract_resolver)
        assert len(result.linked_block_orders) == 1
        assert result.linked_block_orders[0].blocks[0].linked_to == "parent-block"

    def test_exclusive_groups_go_to_exclusive_group_orders(self) -> None:
        ob = self._mixed_order_book()
        result = order_book_to_nord_pool(ob, AUCTION_ID, PORTFOLIO, _contract_resolver)
        assert len(result.exclusive_group_orders) == 1

    def test_empty_order_book_returns_empty_submission(self) -> None:
        ob = create_order_book()
        result = order_book_to_nord_pool(ob, AUCTION_ID, PORTFOLIO, _contract_resolver)
        assert result.curve_orders == []
        assert result.block_orders == []
        assert result.linked_block_orders == []
        assert result.exclusive_group_orders == []


# ---------------------------------------------------------------------------
# Tests: Decimal → float conversion
# ---------------------------------------------------------------------------


class TestPriceVolumeDecimalToFloat:
    def test_curve_point_price_is_float(self) -> None:
        bid = _simple_sell_bid()
        result = simple_bid_to_curve_order(bid, AUCTION_ID, PORTFOLIO, _contract_resolver)
        for point in result.curves[0].curve_points:
            assert isinstance(point.price, float)

    def test_curve_point_volume_is_float(self) -> None:
        bid = _simple_sell_bid()
        result = simple_bid_to_curve_order(bid, AUCTION_ID, PORTFOLIO, _contract_resolver)
        for point in result.curves[0].curve_points:
            assert isinstance(point.volume, float)

    def test_block_price_is_float(self) -> None:
        bid = _block_sell_bid()
        result = block_bid_to_block_list(bid, AUCTION_ID, PORTFOLIO, _contract_resolver)
        assert isinstance(result.blocks[0].price, float)

    def test_block_period_volume_is_float(self) -> None:
        bid = _block_sell_bid()
        result = block_bid_to_block_list(bid, AUCTION_ID, PORTFOLIO, _contract_resolver)
        for period in result.blocks[0].periods:
            assert isinstance(period.volume, float)

    def test_decimal_precision_preserved_in_conversion(self) -> None:
        bid = _simple_sell_bid()
        result = simple_bid_to_curve_order(bid, AUCTION_ID, PORTFOLIO, _contract_resolver)
        prices = [pt.price for pt in result.curves[0].curve_points]
        assert prices[0] == pytest.approx(10.0)
        assert prices[1] == pytest.approx(20.0)
