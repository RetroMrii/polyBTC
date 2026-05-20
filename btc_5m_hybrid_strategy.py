from dataclasses import dataclass
from typing import Optional


@dataclass
class BTC5MDecision:
    action: str
    outcome: Optional[str]
    side: Optional[str]
    price: Optional[float]
    size: float
    model_probability: Optional[float]
    market_probability: Optional[float]
    edge: Optional[float]
    reason: str


class BTC5MHybridStrategy:
    def __init__(
        self,
        min_edge: float = 0.05,
        max_spread: float = 0.08,
        order_size: float = 5.0,
        no_trade_last_seconds: int = 45,
        min_seconds_to_expiry: int = 120,
        max_seconds_to_expiry: int = 270,
        min_distance_from_strike: float = 0.00008,
        late_distance_seconds: int = 150,
        late_min_distance_from_strike: float = 0.00018,
        require_momentum_confirmation: bool = True,
    ):
        self.min_edge = min_edge
        self.max_spread = max_spread
        self.order_size = order_size
        self.no_trade_last_seconds = no_trade_last_seconds
        self.min_seconds_to_expiry = min_seconds_to_expiry
        self.max_seconds_to_expiry = max_seconds_to_expiry
        self.min_distance_from_strike = min_distance_from_strike
        self.late_distance_seconds = late_distance_seconds
        self.late_min_distance_from_strike = late_min_distance_from_strike
        self.require_momentum_confirmation = require_momentum_confirmation

    def estimate_probability(
        self,
        btc_price: float,
        strike: float,
        seconds_to_expiry: int,
        momentum_60s: float = 0.0,
        volatility_60s: float = 0.0,
    ) -> float:
        if strike <= 0:
            return 0.5

        distance = (btc_price - strike) / strike

        prob = 0.5
        prob += distance * 120
        prob += momentum_60s * 40

        if seconds_to_expiry < 120:
            prob += distance * 80

        if volatility_60s > 0.002:
            prob = 0.5 + (prob - 0.5) * 0.75

        return max(0.01, min(0.99, prob))

    @staticmethod
    def _skip(reason: str) -> BTC5MDecision:
        return BTC5MDecision(
            action="SKIP",
            outcome=None,
            side=None,
            price=None,
            size=0.0,
            model_probability=None,
            market_probability=None,
            edge=None,
            reason=reason,
        )

    def decide(
        self,
        btc_price: float,
        strike: float,
        seconds_to_expiry: int,
        yes_bid: Optional[float],
        yes_ask: Optional[float],
        no_bid: Optional[float],
        no_ask: Optional[float],
        momentum_60s: float = 0.0,
        volatility_60s: float = 0.0,
    ) -> BTC5MDecision:
        if seconds_to_expiry <= self.no_trade_last_seconds:
            return self._skip("too_close_to_expiry")

        if seconds_to_expiry < self.min_seconds_to_expiry:
            return self._skip("below_min_seconds_to_expiry")

        if seconds_to_expiry > self.max_seconds_to_expiry:
            return self._skip("too_early_in_market")

        if yes_bid is None or yes_ask is None:
            return self._skip("missing_yes_book")

        if no_bid is None or no_ask is None:
            return self._skip("missing_no_book")

        distance_from_strike = (btc_price - strike) / strike if strike > 0 else 0.0

        required_distance_from_strike = self.min_distance_from_strike
        if seconds_to_expiry <= self.late_distance_seconds:
            required_distance_from_strike = self.late_min_distance_from_strike

        if abs(distance_from_strike) < required_distance_from_strike:
            return self._skip("too_close_to_strike")

        if self.require_momentum_confirmation:
            if btc_price > strike and momentum_60s <= 0:
                return self._skip("yes_momentum_not_confirmed")

            if btc_price < strike and momentum_60s >= 0:
                return self._skip("no_momentum_not_confirmed")

        yes_spread = yes_ask - yes_bid
        if yes_spread > self.max_spread:
            return self._skip("yes_spread_too_wide")

        no_spread = no_ask - no_bid
        if no_spread > self.max_spread:
            return self._skip("no_spread_too_wide")

        model_prob = self.estimate_probability(
            btc_price=btc_price,
            strike=strike,
            seconds_to_expiry=seconds_to_expiry,
            momentum_60s=momentum_60s,
            volatility_60s=volatility_60s,
        )

        yes_market_prob = yes_ask
        yes_edge = model_prob - yes_market_prob

        no_model_prob = 1 - model_prob
        no_market_prob = no_ask
        no_edge = no_model_prob - no_market_prob

        if btc_price > strike:
            if yes_edge >= self.min_edge:
                return BTC5MDecision(
                    action="BUY",
                    outcome="YES",
                    side="BUY",
                    price=yes_ask,
                    size=self.order_size,
                    model_probability=model_prob,
                    market_probability=yes_market_prob,
                    edge=yes_edge,
                    reason="yes_positive_edge_with_trend",
                )

            return BTC5MDecision(
                action="SKIP",
                outcome=None,
                side=None,
                price=None,
                size=0.0,
                model_probability=model_prob,
                market_probability=yes_market_prob,
                edge=yes_edge,
                reason="yes_allowed_but_edge_too_small",
            )

        if btc_price < strike:
            if no_edge >= self.min_edge:
                return BTC5MDecision(
                    action="BUY",
                    outcome="NO",
                    side="BUY",
                    price=no_ask,
                    size=self.order_size,
                    model_probability=no_model_prob,
                    market_probability=no_market_prob,
                    edge=no_edge,
                    reason="no_positive_edge_with_trend",
                )

            return BTC5MDecision(
                action="SKIP",
                outcome=None,
                side=None,
                price=None,
                size=0.0,
                model_probability=no_model_prob,
                market_probability=no_market_prob,
                edge=no_edge,
                reason="no_allowed_but_edge_too_small",
            )

        return BTC5MDecision(
            action="SKIP",
            outcome=None,
            side=None,
            price=None,
            size=0.0,
            model_probability=model_prob,
            market_probability=yes_market_prob,
            edge=0.0,
            reason="btc_equal_to_strike",
        )
