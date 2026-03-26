"""Tests for nexa_bidkit.exaa — EXAA market adapter."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from nexa_bidkit.bids import (
    BlockBid,
    LinkedBlockBid,
    SimpleBid,
    exclusive_group,
)
from nexa_bidkit.exaa import (
    ExaaOrderRequest,
    ExaaOrderType,
    ExaaProduct,
    ExaaProductTypeContainer,
    bidding_zone_to_control_area,
    block_bid_to_exaa_product,
    order_book_to_exaa,
    simple_bid_to_exaa_product,
    standard_hourly_product_id,
    standard_quarter_hourly_product_id,
)
from nexa_bidkit.orders import add_bid, create_order_book
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
ACCOUNT_ID = "APTAP1"


def _mtu(start: datetime = T0, duration: MTUDuration = MTUDuration.HOURLY) -> MTUInterval:
    return MTUInterval.from_start(start, duration)


def _delivery_period(
    start: datetime = T0,
    hours: int = 2,
    duration: MTUDuration = MTUDuration.HOURLY,
) -> DeliveryPeriod:
    return DeliveryPeriod(start=start, end=start + timedelta(hours=hours), duration=duration)


def _supply_curve(
    start: datetime = T0, duration: MTUDuration = MTUDuration.HOURLY
) -> PriceQuantityCurve:
    return PriceQuantityCurve(
        curve_type=CurveType.SUPPLY,
        steps=[
            PriceQuantityStep(price=Decimal("10.00"), volume=Decimal("50")),
            PriceQuantityStep(price=Decimal("20.00"), volume=Decimal("100")),
        ],
        mtu=_mtu(start, duration),
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


def _simple_sell_bid(
    start: datetime = T0, duration: MTUDuration = MTUDuration.HOURLY
) -> SimpleBid:
    return SimpleBid(
        bid_id="simple-sell-1",
        bidding_zone=BiddingZone.AT,
        direction=Direction.SELL,
        curve=_supply_curve(start, duration),
    )


def _simple_buy_bid(start: datetime = T0) -> SimpleBid:
    return SimpleBid(
        bid_id="simple-buy-1",
        bidding_zone=BiddingZone.AT,
        direction=Direction.BUY,
        curve=_demand_curve(start),
    )


def _block_sell_bid(bid_id: str = "block-1", indivisible: bool = False) -> BlockBid:
    mar = Decimal("1.0") if indivisible else Decimal("0.5")
    return BlockBid(
        bid_id=bid_id,
        bidding_zone=BiddingZone.AT,
        direction=Direction.SELL,
        delivery_period=_delivery_period(),
        price=Decimal("45.00"),
        volume=Decimal("100"),
        min_acceptance_ratio=mar,
    )


def _block_buy_bid(bid_id: str = "block-buy-1") -> BlockBid:
    return BlockBid(
        bid_id=bid_id,
        bidding_zone=BiddingZone.AT,
        direction=Direction.BUY,
        delivery_period=_delivery_period(),
        price=Decimal("60.00"),
        volume=Decimal("80"),
    )


def _product_id_resolver(mtu: MTUInterval) -> str:
    """Return "hEXA{hour+1:02d}" for hourly, "qEXA{hour+1:02d}_{q}" for 15-min."""
    if mtu.duration == MTUDuration.HOURLY:
        return f"hEXA{mtu.start.hour + 1:02d}"
    quarter = mtu.start.minute // 15 + 1
    return f"qEXA{mtu.start.hour + 1:02d}_{quarter}"


def _block_product_resolver(period: DeliveryPeriod) -> str:
    return "bEXAbase (01-24)"


# ---------------------------------------------------------------------------
# Tests: bidding_zone_to_control_area
# ---------------------------------------------------------------------------


class TestBiddingZoneToControlArea:
    def test_at_maps_to_apg(self) -> None:
        assert bidding_zone_to_control_area(BiddingZone.AT) == "APG"

    def test_de_lu_maps_to_amprion(self) -> None:
        assert bidding_zone_to_control_area(BiddingZone.DE_LU) == "Amprion"

    def test_nl_maps_to_tennet(self) -> None:
        assert bidding_zone_to_control_area(BiddingZone.NL) == "TenneT"

    def test_unsupported_nordic_zone_raises(self) -> None:
        with pytest.raises(ValueError, match="not supported by EXAA"):
            bidding_zone_to_control_area(BiddingZone.NO1)

    def test_unsupported_fr_raises(self) -> None:
        with pytest.raises(ValueError, match="not supported by EXAA"):
            bidding_zone_to_control_area(BiddingZone.FR)

    def test_unsupported_gb_raises(self) -> None:
        with pytest.raises(ValueError, match="not supported by EXAA"):
            bidding_zone_to_control_area(BiddingZone.GB)


# ---------------------------------------------------------------------------
# Tests: standard product ID helpers
# ---------------------------------------------------------------------------


class TestStandardProductIdHelpers:
    def test_hourly_midnight_hour(self) -> None:
        mtu = _mtu(datetime(2026, 4, 1, 0, 0, tzinfo=UTC))
        assert standard_hourly_product_id(mtu) == "hEXA01"

    def test_hourly_midday_hour(self) -> None:
        mtu = _mtu(datetime(2026, 4, 1, 11, 0, tzinfo=UTC))
        assert standard_hourly_product_id(mtu) == "hEXA12"

    def test_hourly_last_hour(self) -> None:
        mtu = _mtu(datetime(2026, 4, 1, 23, 0, tzinfo=UTC))
        assert standard_hourly_product_id(mtu) == "hEXA24"

    def test_quarter_hourly_first_quarter(self) -> None:
        mtu = _mtu(datetime(2026, 4, 1, 0, 0, tzinfo=UTC), MTUDuration.QUARTER_HOURLY)
        assert standard_quarter_hourly_product_id(mtu) == "qEXA01_1"

    def test_quarter_hourly_second_quarter(self) -> None:
        mtu = _mtu(datetime(2026, 4, 1, 0, 15, tzinfo=UTC), MTUDuration.QUARTER_HOURLY)
        assert standard_quarter_hourly_product_id(mtu) == "qEXA01_2"

    def test_quarter_hourly_fourth_quarter(self) -> None:
        mtu = _mtu(datetime(2026, 4, 1, 0, 45, tzinfo=UTC), MTUDuration.QUARTER_HOURLY)
        assert standard_quarter_hourly_product_id(mtu) == "qEXA01_4"

    def test_quarter_hourly_last_interval(self) -> None:
        mtu = _mtu(datetime(2026, 4, 1, 23, 45, tzinfo=UTC), MTUDuration.QUARTER_HOURLY)
        assert standard_quarter_hourly_product_id(mtu) == "qEXA24_4"


# ---------------------------------------------------------------------------
# Tests: simple_bid_to_exaa_product
# ---------------------------------------------------------------------------


class TestSimpleBidToExaaProduct:
    def test_returns_exaa_product(self) -> None:
        bid = _simple_sell_bid()
        result = simple_bid_to_exaa_product(bid, _product_id_resolver)
        assert isinstance(result, ExaaProduct)

    def test_product_id_from_resolver(self) -> None:
        bid = _simple_sell_bid()
        result = simple_bid_to_exaa_product(bid, _product_id_resolver)
        assert result.product_id == "hEXA11"  # T0 = hour 10, so hEXA11

    def test_fill_or_kill_false_by_default(self) -> None:
        bid = _simple_sell_bid()
        result = simple_bid_to_exaa_product(bid, _product_id_resolver)
        assert result.fill_or_kill is False

    def test_fill_or_kill_can_be_set_true(self) -> None:
        bid = _simple_sell_bid()
        result = simple_bid_to_exaa_product(bid, _product_id_resolver, fill_or_kill=True)
        assert result.fill_or_kill is True

    def test_pair_count_matches_curve_steps(self) -> None:
        bid = _simple_sell_bid()
        result = simple_bid_to_exaa_product(bid, _product_id_resolver)
        assert len(result.price_volume_pairs) == len(bid.curve.steps)

    def test_sell_volumes_are_negative(self) -> None:
        bid = _simple_sell_bid()
        result = simple_bid_to_exaa_product(bid, _product_id_resolver)
        for pair in result.price_volume_pairs:
            assert isinstance(pair.volume, float)
            assert pair.volume < 0

    def test_buy_volumes_are_positive(self) -> None:
        bid = _simple_buy_bid()
        result = simple_bid_to_exaa_product(bid, _product_id_resolver)
        for pair in result.price_volume_pairs:
            assert pair.volume > 0

    def test_price_values_converted_to_float(self) -> None:
        bid = _simple_sell_bid()
        result = simple_bid_to_exaa_product(bid, _product_id_resolver)
        for pair in result.price_volume_pairs:
            assert isinstance(pair.price, float)

    def test_quarter_hourly_resolver_called_with_correct_mtu(self) -> None:
        bid = _simple_sell_bid(duration=MTUDuration.QUARTER_HOURLY)
        result = simple_bid_to_exaa_product(bid, _product_id_resolver)
        assert result.product_id.startswith("qEXA")


# ---------------------------------------------------------------------------
# Tests: block_bid_to_exaa_product
# ---------------------------------------------------------------------------


class TestBlockBidToExaaProduct:
    def test_returns_exaa_product(self) -> None:
        bid = _block_sell_bid()
        result = block_bid_to_exaa_product(bid, "bEXAbase (01-24)")
        assert isinstance(result, ExaaProduct)

    def test_product_id_passed_through(self) -> None:
        bid = _block_sell_bid()
        result = block_bid_to_exaa_product(bid, "bEXApeak (09-20)")
        assert result.product_id == "bEXApeak (09-20)"

    def test_single_price_volume_pair(self) -> None:
        bid = _block_sell_bid()
        result = block_bid_to_exaa_product(bid, "bEXAbase (01-24)")
        assert len(result.price_volume_pairs) == 1

    def test_price_converted_to_float(self) -> None:
        bid = _block_sell_bid()
        result = block_bid_to_exaa_product(bid, "bEXAbase (01-24)")
        assert isinstance(result.price_volume_pairs[0].price, float)
        assert result.price_volume_pairs[0].price == pytest.approx(45.0)

    def test_sell_volume_is_negative(self) -> None:
        bid = _block_sell_bid()
        result = block_bid_to_exaa_product(bid, "bEXAbase (01-24)")
        assert result.price_volume_pairs[0].volume == pytest.approx(-100.0)

    def test_buy_volume_is_positive(self) -> None:
        bid = _block_buy_bid()
        result = block_bid_to_exaa_product(bid, "bEXAbase (01-24)")
        assert result.price_volume_pairs[0].volume == pytest.approx(80.0)

    def test_fill_or_kill_false_for_divisible_bid(self) -> None:
        bid = _block_sell_bid(indivisible=False)
        result = block_bid_to_exaa_product(bid, "bEXAbase (01-24)")
        assert result.fill_or_kill is False

    def test_fill_or_kill_true_for_indivisible_bid(self) -> None:
        bid = _block_sell_bid(indivisible=True)
        result = block_bid_to_exaa_product(bid, "bEXAbase (01-24)")
        assert result.fill_or_kill is True


# ---------------------------------------------------------------------------
# Tests: order_book_to_exaa
# ---------------------------------------------------------------------------


class TestOrderBookToExaa:
    def test_returns_exaa_order_request(self) -> None:
        ob = create_order_book()
        ob = add_bid(ob, _simple_sell_bid())
        result = order_book_to_exaa(ob, ACCOUNT_ID, _product_id_resolver)
        assert isinstance(result, ExaaOrderRequest)

    def test_account_id_set_correctly(self) -> None:
        ob = create_order_book()
        ob = add_bid(ob, _simple_sell_bid())
        result = order_book_to_exaa(ob, ACCOUNT_ID, _product_id_resolver)
        assert result.orders[0].account_id == ACCOUNT_ID

    def test_hourly_simple_bids_go_to_hourly_container(self) -> None:
        ob = create_order_book()
        ob = add_bid(ob, _simple_sell_bid(duration=MTUDuration.HOURLY))
        result = order_book_to_exaa(ob, ACCOUNT_ID, _product_id_resolver)
        assert result.orders[0].hourly_products is not None
        assert len(result.orders[0].hourly_products.products) == 1

    def test_quarter_hourly_simple_bids_go_to_fifteen_min_container(self) -> None:
        ob = create_order_book()
        ob = add_bid(ob, _simple_sell_bid(duration=MTUDuration.QUARTER_HOURLY))
        result = order_book_to_exaa(ob, ACCOUNT_ID, _product_id_resolver)
        assert result.orders[0].fifteen_min_products is not None
        assert len(result.orders[0].fifteen_min_products.products) == 1

    def test_block_bids_go_to_block_container(self) -> None:
        ob = create_order_book()
        ob = add_bid(ob, _block_sell_bid())
        result = order_book_to_exaa(
            ob, ACCOUNT_ID, _product_id_resolver, _block_product_resolver
        )
        assert result.orders[0].block_products is not None
        assert len(result.orders[0].block_products.products) == 1

    def test_empty_containers_are_none(self) -> None:
        ob = create_order_book()
        ob = add_bid(ob, _simple_sell_bid(duration=MTUDuration.HOURLY))
        result = order_book_to_exaa(ob, ACCOUNT_ID, _product_id_resolver)
        assert result.orders[0].block_products is None
        assert result.orders[0].fifteen_min_products is None

    def test_empty_order_book_returns_all_none_containers(self) -> None:
        ob = create_order_book()
        result = order_book_to_exaa(ob, ACCOUNT_ID, _product_id_resolver)
        assert result.orders[0].hourly_products is None
        assert result.orders[0].block_products is None
        assert result.orders[0].fifteen_min_products is None

    def test_order_type_applied_to_containers(self) -> None:
        ob = create_order_book()
        ob = add_bid(ob, _simple_sell_bid())
        result = order_book_to_exaa(
            ob, ACCOUNT_ID, _product_id_resolver, order_type=ExaaOrderType.LINEAR
        )
        assert result.orders[0].hourly_products is not None
        assert result.orders[0].hourly_products.type_of_order == ExaaOrderType.LINEAR

    def test_default_order_type_is_step(self) -> None:
        ob = create_order_book()
        ob = add_bid(ob, _simple_sell_bid())
        result = order_book_to_exaa(ob, ACCOUNT_ID, _product_id_resolver)
        assert result.orders[0].hourly_products is not None
        assert result.orders[0].hourly_products.type_of_order == ExaaOrderType.STEP

    def test_linked_block_bid_raises_value_error(self) -> None:
        # OrderBook requires the parent to exist before adding a LinkedBlockBid.
        parent = _block_sell_bid(bid_id="parent-1")
        linked = LinkedBlockBid(
            bid_id="linked-1",
            parent_bid_id="parent-1",
            bidding_zone=BiddingZone.AT,
            direction=Direction.SELL,
            delivery_period=_delivery_period(start=T0 + timedelta(hours=2)),
            price=Decimal("40.00"),
            volume=Decimal("50"),
        )
        ob = create_order_book()
        ob = add_bid(ob, parent)
        ob = add_bid(ob, linked)
        with pytest.raises(ValueError, match="LinkedBlockBid"):
            order_book_to_exaa(ob, ACCOUNT_ID, _product_id_resolver, _block_product_resolver)

    def test_exclusive_group_bid_raises_value_error(self) -> None:
        ob = create_order_book()
        bid_a = _block_sell_bid(bid_id="excl-a")
        bid_b = _block_sell_bid(bid_id="excl-b")
        grp = exclusive_group([bid_a, bid_b])
        ob = add_bid(ob, grp)
        with pytest.raises(ValueError, match="ExclusiveGroupBid"):
            order_book_to_exaa(ob, ACCOUNT_ID, _product_id_resolver)

    def test_block_bids_without_resolver_raises_value_error(self) -> None:
        ob = create_order_book()
        ob = add_bid(ob, _block_sell_bid())
        with pytest.raises(ValueError, match="block_product_resolver"):
            order_book_to_exaa(ob, ACCOUNT_ID, _product_id_resolver)

    def test_multiple_bids_dispatched_to_correct_containers(self) -> None:
        hourly_bid = SimpleBid(
            bid_id="hourly-bid",
            bidding_zone=BiddingZone.AT,
            direction=Direction.SELL,
            curve=_supply_curve(T0, MTUDuration.HOURLY),
        )
        qh_bid = SimpleBid(
            bid_id="qh-bid",
            bidding_zone=BiddingZone.AT,
            direction=Direction.SELL,
            curve=_supply_curve(T0, MTUDuration.QUARTER_HOURLY),
        )
        ob = create_order_book()
        ob = add_bid(ob, hourly_bid)
        ob = add_bid(ob, qh_bid)
        ob = add_bid(ob, _block_sell_bid())
        result = order_book_to_exaa(
            ob, ACCOUNT_ID, _product_id_resolver, _block_product_resolver
        )
        assert result.orders[0].hourly_products is not None
        assert len(result.orders[0].hourly_products.products) == 1
        assert result.orders[0].fifteen_min_products is not None
        assert len(result.orders[0].fifteen_min_products.products) == 1
        assert result.orders[0].block_products is not None
        assert len(result.orders[0].block_products.products) == 1

    def test_units_always_eur_mwh(self) -> None:
        ob = create_order_book()
        result = order_book_to_exaa(ob, ACCOUNT_ID, _product_id_resolver)
        assert result.units.price == "EUR"
        assert result.units.volume == "MWh/h"


# ---------------------------------------------------------------------------
# Tests: volume sign convention
# ---------------------------------------------------------------------------


class TestVolumeSignConvention:
    """EXAA convention: BUY = positive, SELL = negative (opposite of Nord Pool)."""

    def test_sell_simple_bid_produces_negative_volumes(self) -> None:
        bid = _simple_sell_bid()
        result = simple_bid_to_exaa_product(bid, _product_id_resolver)
        for pair in result.price_volume_pairs:
            assert pair.volume < 0, f"Expected negative volume for SELL, got {pair.volume}"

    def test_buy_simple_bid_produces_positive_volumes(self) -> None:
        bid = _simple_buy_bid()
        result = simple_bid_to_exaa_product(bid, _product_id_resolver)
        for pair in result.price_volume_pairs:
            assert pair.volume > 0, f"Expected positive volume for BUY, got {pair.volume}"

    def test_sell_block_bid_produces_negative_volume(self) -> None:
        bid = _block_sell_bid()
        result = block_bid_to_exaa_product(bid, "bEXAbase (01-24)")
        assert result.price_volume_pairs[0].volume < 0

    def test_buy_block_bid_produces_positive_volume(self) -> None:
        bid = _block_buy_bid()
        result = block_bid_to_exaa_product(bid, "bEXAbase (01-24)")
        assert result.price_volume_pairs[0].volume > 0


# ---------------------------------------------------------------------------
# Tests: Decimal → float conversion
# ---------------------------------------------------------------------------


class TestDecimalToFloat:
    def test_simple_bid_price_is_float(self) -> None:
        bid = _simple_sell_bid()
        result = simple_bid_to_exaa_product(bid, _product_id_resolver)
        for pair in result.price_volume_pairs:
            assert isinstance(pair.price, float)

    def test_simple_bid_volume_is_float(self) -> None:
        bid = _simple_sell_bid()
        result = simple_bid_to_exaa_product(bid, _product_id_resolver)
        for pair in result.price_volume_pairs:
            assert isinstance(pair.volume, float)

    def test_block_bid_price_is_float(self) -> None:
        bid = _block_sell_bid()
        result = block_bid_to_exaa_product(bid, "bEXAbase (01-24)")
        assert isinstance(result.price_volume_pairs[0].price, float)

    def test_block_bid_volume_is_float(self) -> None:
        bid = _block_sell_bid()
        result = block_bid_to_exaa_product(bid, "bEXAbase (01-24)")
        assert isinstance(result.price_volume_pairs[0].volume, float)

    def test_decimal_precision_preserved_in_conversion(self) -> None:
        bid = _simple_sell_bid()
        result = simple_bid_to_exaa_product(bid, _product_id_resolver)
        prices = [p.price for p in result.price_volume_pairs]
        assert prices[0] == pytest.approx(10.0)
        assert prices[1] == pytest.approx(20.0)


# ---------------------------------------------------------------------------
# Tests: JSON serialisation (alias round-trip)
# ---------------------------------------------------------------------------


class TestJsonSerialisation:
    def test_product_id_serialised_as_camel_case(self) -> None:
        bid = _simple_sell_bid()
        product = simple_bid_to_exaa_product(bid, _product_id_resolver)
        dumped = product.model_dump(by_alias=True)
        assert "productID" in dumped
        assert "fillOrKill" in dumped
        assert "priceVolumePairs" in dumped

    def test_fifteen_min_products_key_in_account_order(self) -> None:
        ob = create_order_book()
        ob = add_bid(ob, _simple_sell_bid(duration=MTUDuration.QUARTER_HOURLY))
        result = order_book_to_exaa(ob, ACCOUNT_ID, _product_id_resolver)
        dumped = result.orders[0].model_dump(by_alias=True)
        assert "15minProducts" in dumped

    def test_account_id_serialised_as_camel_case(self) -> None:
        ob = create_order_book()
        result = order_book_to_exaa(ob, ACCOUNT_ID, _product_id_resolver)
        dumped = result.orders[0].model_dump(by_alias=True)
        assert "accountID" in dumped
        assert dumped["accountID"] == ACCOUNT_ID

    def test_container_type_of_order_key(self) -> None:
        container = ExaaProductTypeContainer.model_validate(
            {"typeOfOrder": ExaaOrderType.STEP, "products": []}
        )
        dumped = container.model_dump(by_alias=True)
        assert "typeOfOrder" in dumped
