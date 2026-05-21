import argparse
import csv
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

TRADES_FILE = "btc_5m_trades.csv"
DECISIONS_FILE = "btc_5m_decisions.csv"

CLOSED_ACTIONS = {
    "CASHOUT",
    "STOPLOSS",
    "TIME_EXIT",
    "TRAIL_EXIT",
    "PROTECT_EXIT",
    "RECONCILED_EXIT",
    "SETTLE",
}
UNFILLED_ACTIONS = {"ORDER_UNFILLED_CANCELLED"}


def parse_time(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def parse_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def read_csv(path: str) -> list[dict[str, str]]:
    try:
        with open(path, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))
    except FileNotFoundError:
        return []


def add_dt(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        row2: dict[str, Any] = dict(row)
        row2["_dt"] = parse_time(row.get("timestamp", ""))
        out.append(row2)
    return out


def short_reason(reason: str, max_len: int = 130) -> str:
    reason = (reason or "").replace("\n", " ")
    return reason if len(reason) <= max_len else reason[: max_len - 3] + "..."


def trade_label(row: dict[str, Any]) -> str:
    return (
        f"{row.get('timestamp','')} | {row.get('market_id','')} | "
        f"{row.get('side','')} {row.get('outcome','')} "
        f"price={row.get('price','')} size={row.get('size','')} pnl={row.get('pnl','')}"
    )


def select_trade_window(trades_all: list[dict[str, Any]], decisions_all: list[dict[str, Any]], hours: Optional[float]) -> list[dict[str, Any]]:
    if hours is None:
        return trades_all

    dts = [row["_dt"] for row in (trades_all + decisions_all) if row.get("_dt") is not None]
    if not dts:
        return trades_all

    end_time = max(dts)
    start_time = end_time - timedelta(hours=hours)
    print(f"Window start: {start_time.isoformat()}")
    print(f"Window end:   {end_time.isoformat()}")

    return [
        row for row in trades_all
        if row.get("_dt") is not None and start_time <= row["_dt"] <= end_time
    ]


def print_summary(rows: list[dict[str, Any]], title: str) -> None:
    actions = Counter(row.get("side", "") for row in rows)
    closed = [row for row in rows if row.get("side") in CLOSED_ACTIONS]
    pnls = [parse_float(row.get("pnl")) for row in closed]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]

    print(f"=== BTC5M RUN SUMMARY ({title}) ===")
    print("Rows:", len(rows))
    print("Actions:", dict(actions))
    print("Closed trades:", len(closed))
    print("Total PnL:", round(sum(pnls), 4))
    print("Wins:", len(wins), "Losses:", len(losses))
    print("Win rate:", round(len(wins) / len(closed) * 100, 2) if closed else 0, "%")
    print("Avg win:", round(sum(wins) / len(wins), 4) if wins else 0)
    print("Avg loss:", round(sum(losses) / len(losses), 4) if losses else 0)
    print("Largest win:", round(max(wins), 4) if wins else 0)
    print("Largest loss:", round(min(losses), 4) if losses else 0)

    avg_win = (sum(wins) / len(wins)) if wins else 0.0
    avg_loss_abs = abs(sum(losses) / len(losses)) if losses else 0.0
    if avg_win > 0 and avg_loss_abs > 0:
        breakeven_wr = avg_loss_abs / (avg_loss_abs + avg_win)
        print("Breakeven win rate:", round(breakeven_wr * 100, 2), "%")
    else:
        print("Breakeven win rate:", 0, "%")

    print()
    print("Exit/action PnL breakdown:")
    by_action: dict[str, list[float]] = defaultdict(list)
    for row in closed:
        by_action[row.get("side", "")].append(parse_float(row.get("pnl")))

    if by_action:
        for action, values in sorted(by_action.items()):
            print(
                f"  {action}: count={len(values)} total={round(sum(values), 4)} "
                f"avg={round(sum(values) / len(values), 4)} "
                f"best={round(max(values), 4)} worst={round(min(values), 4)}"
            )
    else:
        print("  none")

    posted = [row for row in rows if row.get("side") == "ORDER_POSTED"]
    filled_buys = [row for row in rows if row.get("side") == "BUY"]
    unfilled = [row for row in rows if row.get("side") in UNFILLED_ACTIONS]
    exits_posted = [row for row in rows if row.get("side") == "EXIT_ORDER_POSTED"]
    exit_incomplete = [row for row in rows if row.get("side") == "EXIT_INCOMPLETE"]

    print()
    print("Execution:")
    print("  ORDER_POSTED:", len(posted))
    print("  BUY filled:", len(filled_buys))
    print("  ORDER_UNFILLED_CANCELLED:", len(unfilled))
    print("  EXIT_ORDER_POSTED:", len(exits_posted))
    print("  EXIT_INCOMPLETE:", len(exit_incomplete))
    print("  Fill rate:", round(len(filled_buys) / len(posted) * 100, 2) if posted else 0, "%")


def find_entry_trade_for_close(close: dict[str, Any], trades_all: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    close_dt = close.get("_dt")
    market_id = close.get("market_id")
    if close_dt is None or not market_id:
        return None

    candidates = [
        row for row in trades_all
        if row.get("market_id") == market_id
        and row.get("side") == "BUY"
        and row.get("_dt") is not None
        and row["_dt"] <= close_dt
    ]
    if not candidates:
        return None

    return max(candidates, key=lambda r: r["_dt"])


def find_decision_context(entry_trade: Optional[dict[str, Any]], close: dict[str, Any], decisions_all: list[dict[str, Any]], context_rows: int) -> list[dict[str, Any]]:
    market_id = close.get("market_id")
    market_decisions = [
        row for row in decisions_all
        if row.get("market_id") == market_id and row.get("_dt") is not None
    ]
    if not market_decisions:
        return []

    target_dt = entry_trade.get("_dt") if entry_trade else close.get("_dt")
    if target_dt is None:
        return market_decisions[:context_rows]

    buy_indices = [i for i, row in enumerate(market_decisions) if row.get("action") == "BUY"]
    if buy_indices:
        target_idx = min(buy_indices, key=lambda i: abs((market_decisions[i]["_dt"] - target_dt).total_seconds()))
    else:
        target_idx = min(range(len(market_decisions)), key=lambda i: abs((market_decisions[i]["_dt"] - target_dt).total_seconds()))

    before = context_rows // 2
    start = max(0, target_idx - before)
    end = min(len(market_decisions), start + context_rows)
    start = max(0, end - context_rows)
    return market_decisions[start:end]


def print_worst_and_best(rows_window: list[dict[str, Any]], n: int = 5) -> None:
    closed = [row for row in rows_window if row.get("side") in CLOSED_ACTIONS]
    closed_with_pnl = [(parse_float(row.get("pnl")), row) for row in closed]
    if not closed_with_pnl:
        return

    print()
    print(f"=== WORST {n} CLOSED TRADES ===")
    for pnl, row in sorted(closed_with_pnl, key=lambda x: x[0])[:n]:
        print(f"{round(pnl, 4)} | {trade_label(row)} | {short_reason(row.get('reason',''), 170)}")

    print()
    print(f"=== BEST {n} CLOSED TRADES ===")
    for pnl, row in sorted(closed_with_pnl, key=lambda x: x[0], reverse=True)[:n]:
        print(f"{round(pnl, 4)} | {trade_label(row)} | {short_reason(row.get('reason',''), 170)}")


def print_trade_details(rows_window: list[dict[str, Any]], trades_all: list[dict[str, Any]], decisions_all: list[dict[str, Any]], context_rows: int, max_trades: int) -> None:
    closed = [row for row in rows_window if row.get("side") in CLOSED_ACTIONS]
    closed.sort(key=lambda r: r.get("_dt") or datetime.min.replace(tzinfo=timezone.utc))

    if max_trades > 0:
        closed = closed[-max_trades:]

    print()
    print(f"=== CLOSED TRADE DETAILS + {context_rows} DECISION ROWS AROUND ENTRY ===")
    if not closed:
        print("No closed trades in selected window.")
        return

    for idx, close in enumerate(closed, start=1):
        entry = find_entry_trade_for_close(close, trades_all)
        pnl = parse_float(close.get("pnl"))
        print()
        print("-" * 110)
        print(f"Trade {idx}: {close.get('side')} {close.get('outcome')} pnl={round(pnl, 4)}")
        print("Close:", trade_label(close))
        if entry:
            print("Entry:", trade_label(entry))
            try:
                hold_sec = int((close["_dt"] - entry["_dt"]).total_seconds())
                print("Hold seconds:", hold_sec)
            except Exception:
                pass
        else:
            print("Entry: not found in trades CSV")

        print("Close reason:", short_reason(close.get("reason", ""), 220))

        context = find_decision_context(entry, close, decisions_all, context_rows)
        if not context:
            print("Decision context: none found")
            continue

        print("Decision context:")
        print("  timestamp | t | btc | strike | yes_bid/ask | no_bid/ask | model | market | edge | action | reason")
        for d in context:
            print(
                "  "
                f"{d.get('timestamp','')} | "
                f"{d.get('seconds_to_expiry','')} | "
                f"{d.get('btc_price','')} | "
                f"{d.get('strike','')} | "
                f"{d.get('yes_bid','')}/{d.get('yes_ask','')} | "
                f"{d.get('no_bid','')}/{d.get('no_ask','')} | "
                f"{d.get('model_probability','')} | "
                f"{d.get('market_probability','')} | "
                f"{d.get('edge','')} | "
                f"{d.get('action','')} | "
                f"{d.get('reason','')}"
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize BTC5M run results and print decision timelines around entries.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--hours", type=float, help="Summarize the last N hours based on latest trade/decision timestamp.")
    group.add_argument("--last-3h", action="store_true", help="Summarize the last 3 hours.")
    group.add_argument("--last-10h", action="store_true", help="Summarize the last 10 hours.")
    group.add_argument("--all", action="store_true", help="Summarize all rows.")

    parser.add_argument("--trades", default=TRADES_FILE, help="Trades CSV path.")
    parser.add_argument("--decisions", default=DECISIONS_FILE, help="Decisions CSV path.")
    parser.add_argument("--decision-context", type=int, default=10, help="Decision rows to print around each entry.")
    parser.add_argument("--max-trades", type=int, default=30, help="Max closed trades to print details for. 0 means all.")
    parser.add_argument("--worst-best", type=int, default=5, help="How many worst/best trades to print.")

    args = parser.parse_args()

    if args.last_3h:
        hours = 3.0
        title = "last 3 hours"
    elif args.last_10h:
        hours = 10.0
        title = "last 10 hours"
    elif args.all:
        hours = None
        title = "all"
    elif args.hours is not None:
        hours = args.hours
        title = f"last {args.hours:g} hours"
    else:
        hours = 3.0
        title = "last 3 hours"

    trades_all = add_dt(read_csv(args.trades))
    decisions_all = add_dt(read_csv(args.decisions))
    trades_window = select_trade_window(trades_all, decisions_all, hours)

    print_summary(trades_window, title)
    print_worst_and_best(trades_window, n=args.worst_best)
    print_trade_details(
        rows_window=trades_window,
        trades_all=trades_all,
        decisions_all=decisions_all,
        context_rows=args.decision_context,
        max_trades=args.max_trades,
    )


if __name__ == "__main__":
    main()
