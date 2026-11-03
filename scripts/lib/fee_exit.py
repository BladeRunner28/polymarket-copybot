#!/usr/bin/env python3
"""fee_exit — the ONE place that decides what PRICE a fee is charged at.

Card: `fee-exit-basis-instruments` (opened 2026-11-02 by the profit review, Lane B).
Two fee instruments were charging an early exit's taker fee at the leg's ENTRY price:

    scripts/c200-fee-reprice-archive.py   `ex_docs = entry_docs`  (exit := entry)
    scripts/fee-sign-flip-test.py         `cur *= 2.0`            (exit := entry)

The fee law the whole repo uses (confirmed against a live fill) is

    fee = shares * rate * p * (1 - p)

which goes to ZERO as p approaches 0 and as p approaches 1. An exit is a trade AT THE
EXIT PRICE, so charging it at the entry price overstates the bill exactly where most of
this book leaves: 83.4% of closed legs step out below 0.05 or above 0.80.

TWO EXIT-PRICE BASES, in order of preference:

  observed  PaperTrade.currentPrice — the exit price the paper engine actually wrote on
            the row (src/lib/paper.ts sets status='closed', currentPrice=exitPrice).
            Primary basis; needs no derivation.
  identity  c = p * (1 + realizedPnl / sizeUsd), exact from pnl = shares*(c - p).
            Used only when the stored price is missing or pinned at 0 or 1.
  undetermined  neither basis available. The caller must SAY SO, never fall back to the
            entry price silently, which is the defect this module exists to kill.

Stdlib only: these instruments also run under the venv python.
Self-test: `python3 scripts/lib/fee_exit.py` exits 1 if the module cannot tell a correct
exit basis from an entry-price one.
"""

EXIT_BASIS_OBSERVED = "observed"
EXIT_BASIS_IDENTITY = "identity"
EXIT_BASIS_UNDETERMINED = "undetermined"

# Float slack when comparing a stored exit price against the PnL identity: the paper
# engine rounds pnl to cents (computePnl), so agreement is never exact.
DISAGREE_TOL = 0.005


def pp(price):
    """The repo's taker law, per share: p * (1 - p). The caller supplies the rate."""
    if price is None or not (0.0 < price < 1.0):
        return 0.0
    return price * (1.0 - price)


def min_law(price):
    """The archive-era / venue-field law, per share: min(p, 1-p).

    Kept callable so `fee-sign-flip-test.py` prices its artifact line on the same basis
    as every other line instead of hard-coding a second law inline.
    """
    if price is None or not (0.0 < price < 1.0):
        return 0.0
    return min(price, 1.0 - price)


LAWS = {"pp": pp, "min": min_law}


def fee(shares, rate, price, law="pp"):
    """Fee in USD for `shares` traded at `price` under `law`."""
    fn = LAWS[law]
    return float(shares) * float(rate) * fn(price)


def observed_exit_price(current_price):
    """Exit price as written on the trade row, or None if the row carries no trade price.

    A stored 0 or 1 means the row was written off at settlement, not traded out, so it
    is not an exit PRICE — the identity basis (which clamps to the payoff range) owns
    those legs.
    """
    if current_price is None:
        return None
    try:
        cp = float(current_price)
    except (TypeError, ValueError):
        return None
    if 0.0 < cp < 1.0:
        return cp
    return None


def identity_exit_price(entry_price, size_usd, realized_pnl):
    """c = p*(1 + pnl/size), clamped to [0,1]. None when not computable."""
    try:
        p = float(entry_price)
        size = float(size_usd)
        pnl = float(realized_pnl)
    except (TypeError, ValueError):
        return None
    if p <= 0.0 or size <= 0.0:
        return None
    c = p * (1.0 + pnl / size)
    return max(0.0, min(1.0, c))


def resolve_exit_price(current_price, entry_price, size_usd, realized_pnl, tol=DISAGREE_TOL):
    """Pick the exit price for a leg and report WHICH basis produced it.

    Returns {basis, price, derived, disagree, delta}. `disagree` is None when only one
    basis exists: an absent cross-check is not agreement, so callers must count it
    separately rather than fold it into the agreement rate.
    """
    observed = observed_exit_price(current_price)
    derived = identity_exit_price(entry_price, size_usd, realized_pnl)
    if observed is not None:
        disagree = None if derived is None else abs(observed - derived) > tol
        delta = None if derived is None else observed - derived
        return {"basis": EXIT_BASIS_OBSERVED, "price": observed, "derived": derived,
                "disagree": disagree, "delta": delta}
    if derived is not None:
        return {"basis": EXIT_BASIS_IDENTITY, "price": derived, "derived": derived,
                "disagree": None, "delta": None}
    return {"basis": EXIT_BASIS_UNDETERMINED, "price": None, "derived": None,
            "disagree": None, "delta": None}


def leg_fees(shares, rate, entry_price, exit_price, early_exit, law="pp"):
    """(entry_fee, exit_fee) for one leg. A natural settlement is not a trade.

    `early_exit` is status=='closed'. A 'resolved' leg settles at 0/1 with no sale, so it
    carries the entry fee only — unchanged from both instruments' original behaviour.
    """
    entry = fee(shares, rate, entry_price, law)
    if not early_exit or exit_price is None:
        return entry, 0.0
    return entry, fee(shares, rate, exit_price, law)


class ExitBasisTally:
    """Counts where each exit price came from, plus the observed-vs-identity cross-check.

    Instruments print `tally.line()`, which states population, clock and level: a bare
    "exit priced at the exit price" would be the same class of lie as the bug.
    """

    def __init__(self, population="", clock="", level="leg"):
        self.population = population
        self.clock = clock
        self.level = level
        self.counts = {EXIT_BASIS_OBSERVED: 0, EXIT_BASIS_IDENTITY: 0, EXIT_BASIS_UNDETERMINED: 0}
        self.cross_checked = 0
        self.disagreements = 0
        self.max_abs_delta = 0.0

    def add(self, resolved):
        self.counts[resolved["basis"]] = self.counts.get(resolved["basis"], 0) + 1
        if resolved.get("disagree") is not None:
            self.cross_checked += 1
            if resolved["disagree"]:
                self.disagreements += 1
                self.max_abs_delta = max(self.max_abs_delta, abs(resolved["delta"] or 0.0))

    @property
    def total(self):
        return sum(self.counts.values())

    def line(self):
        out = [
            "EXIT PRICE BASIS: observed PaperTrade.currentPrice %d, identity fallback %d, "
            "undetermined %d (of %d %s; %s; level=%s)"
            % (self.counts[EXIT_BASIS_OBSERVED], self.counts[EXIT_BASIS_IDENTITY],
               self.counts[EXIT_BASIS_UNDETERMINED], self.total,
               self.population or "legs", self.clock or "clock unstated", self.level)
        ]
        if self.cross_checked:
            out.append(
                "identity cross-check on %d leg(s): %d disagree by more than %.3f "
                "(max |delta| %.4f) — the stored price wins and the disagreement is "
                "reported, never averaged"
                % (self.cross_checked, self.disagreements, DISAGREE_TOL, self.max_abs_delta))
        else:
            out.append("identity cross-check: 0 legs carried both bases — NOT a clean check")
        if self.counts[EXIT_BASIS_UNDETERMINED]:
            out.append(
                "%d leg(s) carried NO exit price and are excluded from every exit-fee figure "
                "rather than priced at entry" % self.counts[EXIT_BASIS_UNDETERMINED])
        return "\n".join("  " + b for b in out)


def self_test():
    """Prove the module (a) prices an exit at the exit and (b) can FAIL.

    The failure half is the point: a detector that cannot separate the entry-price basis
    from the exit-price one is exactly what shipped this bug twice.
    """
    fails = []

    def check(name, cond, detail=""):
        if not cond:
            fails.append(name + " " + detail)

    rate, shares = 0.05, 100.0
    p, c = 0.57, 0.02
    entry_fee = fee(shares, rate, p)
    exit_fee = fee(shares, rate, c)
    check("exit-at-exit must be far cheaper than exit-at-entry on a step-out leg",
          exit_fee < 0.25 * entry_fee, "(entry %.4f exit %.4f)" % (entry_fee, exit_fee))
    check("the old basis is exactly the entry fee",
          abs(fee(shares, rate, p) - entry_fee) < 1e-12)
    check("fee vanishes at the payoff extremes",
          fee(shares, rate, 0.0) == 0.0 and fee(shares, rate, 1.0) == 0.0)

    # identity: pnl = shares*(c-p), so c = p*(1 + pnl/size)
    size = 10.0
    pnl = (size / p) * (c - p)
    check("identity recovers a step-out exit",
          abs(identity_exit_price(p, size, pnl) - c) < 1e-9,
          "(got %r)" % (identity_exit_price(p, size, pnl),))
    check("identity tolerates cent-rounded pnl",
          abs(identity_exit_price(0.53, 5.0, round((5.0 / 0.53) * (0.90 - 0.53), 2)) - 0.90) < 1e-3)

    # the observed price wins, and a stored price that contradicts the identity is FLAGGED
    agree = resolve_exit_price(0.90, 0.53, 5.0, round((5.0 / 0.53) * (0.90 - 0.53), 2))
    check("observed basis is preferred and agrees",
          agree["basis"] == EXIT_BASIS_OBSERVED and agree["disagree"] is False,
          "(got %r)" % (agree,))
    lie = resolve_exit_price(0.30, 0.53, 5.0, round((5.0 / 0.53) * (0.90 - 0.53), 2))
    check("a stored price that lies about the exit is DETECTED", lie["disagree"] is True,
          "(got %r)" % (lie,))
    nope = resolve_exit_price(None, 0.0, 0.0, None)
    check("undetermined never silently becomes the entry price",
          nope["basis"] == EXIT_BASIS_UNDETERMINED and nope["price"] is None)

    # a natural settlement carries no exit fee; a closed leg pays it at the exit
    e, x = leg_fees(shares, rate, p, c, early_exit=False)
    check("resolved legs pay no exit fee", x == 0.0 and e == entry_fee)
    e, x = leg_fees(shares, rate, p, c, early_exit=True)
    check("closed legs pay the exit fee at the exit", abs(x - exit_fee) < 1e-12)
    check("min-law exit is priced at the exit",
          abs(fee(shares, 0.10, c, "min") - shares * 0.10 * c) < 1e-12)

    tally = ExitBasisTally(population="legs", clock="self-test")
    tally.add(agree)
    tally.add(lie)
    line = tally.line()
    check("tally line names both bases and the disagreement",
          "observed" in line and "1 disagree" in line, "(got %r)" % line)

    if fails:
        print("fee_exit SELF-TEST FAILED (%d):" % len(fails))
        for f in fails:
            print("  - " + f)
        return 1
    print("fee_exit self-test OK: 12 checks — an exit is priced at the exit, the identity "
          "recovers it, a stored price that lies is detected, undetermined stays "
          "undetermined, settlements pay no exit fee.")
    return 0


if __name__ == "__main__":
    raise SystemExit(self_test())
