"""
Sector money-flow sentiment module.

This module turns board/sector capital-flow data into a compact signal that can
be used by the realtime decision engine. It is intentionally rule-based and
small: the goal is to confirm whether a hot sector has real capital support, not
to replace the existing limit-up and chip-quality checks.
"""

from typing import Dict, List, Optional


class SectorMoneyFlowAnalyzer:
    """Score whether a sector's limit-up effect is supported by capital flow."""

    HOT_THRESHOLD = 6
    WARM_THRESHOLD = 3
    COLD_THRESHOLD = -2

    def __init__(self, data_fetcher):
        self.data_fetcher = data_fetcher

    def analyze_sector(
        self,
        sector_name: str,
        zt_pool: Optional[List[Dict]] = None,
        money_flow_map: Optional[Dict[str, Dict]] = None,
    ) -> Dict:
        """Return a money-flow snapshot for one sector."""
        sector_name = str(sector_name or "").strip()
        zt_pool = zt_pool or []
        money_flow_map = (
            money_flow_map
            if money_flow_map is not None
            else self.data_fetcher.get_sector_money_flow_map()
        )

        sector_stocks = [
            stock for stock in zt_pool if str(stock.get("sector", "")).strip() == sector_name
        ]
        flow = self._lookup_flow(sector_name, money_flow_map)
        return self.score_sector_money(sector_name, flow, sector_stocks)

    @classmethod
    def score_sector_money(
        cls,
        sector_name: str,
        flow: Optional[Dict],
        sector_stocks: Optional[List[Dict]] = None,
    ) -> Dict:
        """Convert raw money-flow data plus limit-up breadth into a stable score."""
        sector_stocks = sector_stocks or []
        sector_zt_count = len(sector_stocks)

        if not flow:
            fallback_score = 1 if sector_zt_count >= 5 else 0
            return cls._result(
                sector_name=sector_name,
                score=fallback_score,
                temperature="unknown",
                source="limit_up_fallback",
                rank=None,
                net_inflow=0.0,
                net_inflow_pct=0.0,
                amount=0.0,
                reason=(
                    f"no money-flow data; fallback uses {sector_zt_count} sector limit-ups"
                ),
            )

        net_inflow = cls._to_float(flow.get("net_inflow"))
        net_inflow_pct = cls._to_float(flow.get("net_inflow_pct"))
        amount = cls._to_float(flow.get("amount"))
        rank = cls._to_int(flow.get("rank"))

        score = 0
        reasons = []

        if rank:
            if rank <= 5:
                score += 3
                reasons.append(f"money-flow rank #{rank}")
            elif rank <= 10:
                score += 2
                reasons.append(f"money-flow rank #{rank}")
            elif rank <= 20:
                score += 1
                reasons.append(f"money-flow rank #{rank}")

        if net_inflow >= 1_000_000_000:
            score += 3
            reasons.append(f"net inflow {net_inflow / 100_000_000:.1f}e")
        elif net_inflow >= 300_000_000:
            score += 2
            reasons.append(f"net inflow {net_inflow / 100_000_000:.1f}e")
        elif net_inflow > 0:
            score += 1
            reasons.append(f"net inflow {net_inflow / 100_000_000:.1f}e")
        elif net_inflow <= -300_000_000:
            score -= 3
            reasons.append(f"net outflow {abs(net_inflow) / 100_000_000:.1f}e")
        elif net_inflow < 0:
            score -= 1
            reasons.append(f"net outflow {abs(net_inflow) / 100_000_000:.1f}e")

        if net_inflow_pct >= 3:
            score += 2
            reasons.append(f"inflow pct {net_inflow_pct:.1f}%")
        elif net_inflow_pct >= 1:
            score += 1
            reasons.append(f"inflow pct {net_inflow_pct:.1f}%")
        elif net_inflow_pct <= -2:
            score -= 2
            reasons.append(f"outflow pct {net_inflow_pct:.1f}%")
        elif net_inflow_pct < 0:
            score -= 1
            reasons.append(f"outflow pct {net_inflow_pct:.1f}%")

        if sector_zt_count >= 5:
            score += 2
            reasons.append(f"{sector_zt_count} limit-ups")
        elif sector_zt_count >= 3:
            score += 1
            reasons.append(f"{sector_zt_count} limit-ups")
        elif sector_zt_count <= 1:
            score -= 1
            reasons.append(f"only {sector_zt_count} limit-up")

        if net_inflow < 0 and sector_zt_count <= 3:
            score -= 1
            reasons.append("thin breadth with outflow")

        temperature = cls._temperature(score)
        return cls._result(
            sector_name=sector_name,
            score=score,
            temperature=temperature,
            source=flow.get("source", "unknown"),
            rank=rank,
            net_inflow=net_inflow,
            net_inflow_pct=net_inflow_pct,
            amount=amount,
            reason="; ".join(reasons) if reasons else "neutral money flow",
        )

    @classmethod
    def should_block_entry(cls, sector_money: Dict, sector_limit_up_count: int) -> bool:
        """Use money flow as a gate only when breadth is barely acceptable."""
        temperature = sector_money.get("money_temperature")
        score = int(sector_money.get("money_score", 0) or 0)
        if temperature == "unknown":
            return False
        return sector_limit_up_count <= 3 and score <= cls.COLD_THRESHOLD

    @classmethod
    def confidence_adjustment(cls, sector_money: Optional[Dict]) -> int:
        """Small confidence adjustment used by the decision engine."""
        if not sector_money:
            return 0
        temperature = sector_money.get("money_temperature")
        score = int(sector_money.get("money_score", 0) or 0)
        if temperature == "hot" or score >= cls.HOT_THRESHOLD:
            return 1
        if temperature == "cold" or score <= cls.COLD_THRESHOLD:
            return -1
        return 0

    @staticmethod
    def _lookup_flow(sector_name: str, money_flow_map: Dict[str, Dict]) -> Optional[Dict]:
        if not sector_name:
            return None
        if sector_name in money_flow_map:
            return money_flow_map[sector_name]

        normalized = SectorMoneyFlowAnalyzer._normalize_name(sector_name)
        for name, flow in money_flow_map.items():
            if SectorMoneyFlowAnalyzer._normalize_name(name) == normalized:
                return flow
        return None

    @classmethod
    def _temperature(cls, score: int) -> str:
        if score >= cls.HOT_THRESHOLD:
            return "hot"
        if score >= cls.WARM_THRESHOLD:
            return "warm"
        if score <= cls.COLD_THRESHOLD:
            return "cold"
        return "neutral"

    @staticmethod
    def _normalize_name(value: str) -> str:
        text = str(value or "").strip().lower()
        for suffix in ("行业", "概念", "板块"):
            text = text.replace(suffix, "")
        return text.replace(" ", "")

    @staticmethod
    def _to_float(value) -> float:
        try:
            if value is None:
                return 0.0
            text = str(value).replace(",", "").replace("%", "").strip()
            if not text or text in ("-", "--", "nan", "None"):
                return 0.0
            multiplier = 1.0
            if text.endswith("亿"):
                multiplier = 100_000_000.0
                text = text[:-1]
            elif text.endswith("万"):
                multiplier = 10_000.0
                text = text[:-1]
            return float(text) * multiplier
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _to_int(value):
        try:
            if value is None or value == "":
                return None
            return int(float(str(value).replace(",", "").strip()))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _result(
        sector_name: str,
        score: int,
        temperature: str,
        source: str,
        rank,
        net_inflow: float,
        net_inflow_pct: float,
        amount: float,
        reason: str,
    ) -> Dict:
        return {
            "sector": sector_name,
            "money_score": int(score),
            "money_temperature": temperature,
            "net_inflow": float(net_inflow),
            "net_inflow_pct": float(net_inflow_pct),
            "amount": float(amount),
            "rank": rank,
            "source": source,
            "reason": reason,
        }
