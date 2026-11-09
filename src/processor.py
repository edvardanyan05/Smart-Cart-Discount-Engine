"""Applies a set of discount rules to a cart and explains the result.

Rules are split into two groups:

* **Stackable** rules (``is_stackable=True``) all apply, and their
  discounts are added together.
* **Mutually exclusive** rules (``is_stackable=False``) compete, and only
  the one with the largest discount is applied. Ties go to the rule that
  was registered first.

The total discount is the stackable sum plus the best exclusive discount,
capped at the subtotal so the final price is never negative.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from .discounts import IDiscountRule, RuleBreakdown
from .models import Cart, to_decimal, to_money


class RuleStatus(str, Enum):
    """What happened to a rule when the cart was processed."""

    APPLIED = "applied"
    """The rule's discount is part of the total."""

    SUPERSEDED = "superseded"
    """An exclusive rule that lost to a better exclusive rule."""

    NOT_APPLICABLE = "not applicable"
    """The rule gave no discount for this cart."""


@dataclass(frozen=True)
class RuleOutcome:
    """The result of evaluating one rule.

    Attributes:
        rule_name: Name of the rule.
        rule_type: Class name of the rule, e.g. ``"PercentageDiscount"``.
        description: Short description of the rule.
        is_stackable: Whether the rule was in the stackable group.
        amount: Discount the rule produced for the cart.
        status: Whether the rule was applied, superseded or not applicable.
        note: Plain-language reason for the status.
        breakdown: Explanation tree (more than one line for composites).
    """

    rule_name: str
    rule_type: str
    description: str
    is_stackable: bool
    amount: float
    status: RuleStatus
    note: str
    breakdown: tuple[RuleBreakdown, ...]

    @property
    def applied_amount(self) -> float:
        """The amount counted toward the total (``0`` unless applied)."""
        return self.amount if self.status is RuleStatus.APPLIED else 0.0


@dataclass(frozen=True)
class DiscountResult:
    """The full result of processing a cart.

    Attributes:
        subtotal: Cart total before discounts.
        total_discount: Discount actually taken off (after capping).
        final_price: ``subtotal - total_discount``.
        outcomes: One entry per rule, in registration order.
        capped: ``True`` if the discounts exceeded the subtotal and were capped.
    """

    subtotal: float
    total_discount: float
    final_price: float
    outcomes: tuple[RuleOutcome, ...]
    capped: bool = False

    @property
    def applied(self) -> list[RuleOutcome]:
        """The rules whose discount was applied."""
        return [o for o in self.outcomes if o.status is RuleStatus.APPLIED]

    @property
    def savings_percentage(self) -> float:
        """Total discount as a percentage of the subtotal."""
        if self.subtotal == 0:
            return 0.0
        return to_money(to_decimal(self.total_discount) / to_decimal(self.subtotal) * 100)

    @property
    def log(self) -> list[str]:
        """A plain-text, line-by-line account of how the total was reached."""
        lines = [f"Subtotal: ${self.subtotal:,.2f}"]
        for o in self.outcomes:
            group = "stackable" if o.is_stackable else "exclusive"
            lines.append(
                f"[{o.status.value.upper()}] {o.rule_name} ({group}): "
                f"${o.amount:,.2f} - {o.note}"
            )
        if self.capped:
            lines.append("Discounts exceeded the subtotal and were capped.")
        lines.append(f"Total discount: ${self.total_discount:,.2f}")
        lines.append(f"Final price: ${self.final_price:,.2f}")
        return lines


class DiscountProcessor:
    """Holds discount rules and applies them to carts.

    The processor depends only on ``IDiscountRule``, so any rule type,
    including composites, can be used without changing this class.
    """

    def __init__(self, rules: Iterable[IDiscountRule] = ()) -> None:
        """Create a processor with optional initial rules.

        Raises:
            ValueError: If two rules share a name.
        """
        self._rules: list[IDiscountRule] = []
        for rule in rules:
            self.add_rule(rule)

    @property
    def rules(self) -> tuple[IDiscountRule, ...]:
        """All rules, in registration order."""
        return tuple(self._rules)

    @property
    def stackable_rules(self) -> tuple[IDiscountRule, ...]:
        """Rules that are added together."""
        return tuple(r for r in self._rules if r.is_stackable)

    @property
    def exclusive_rules(self) -> tuple[IDiscountRule, ...]:
        """Rules that compete; only the best one is applied."""
        return tuple(r for r in self._rules if not r.is_stackable)

    def add_rule(self, rule: IDiscountRule) -> None:
        """Register a rule.

        Raises:
            TypeError: If ``rule`` is not an ``IDiscountRule``.
            ValueError: If a rule with the same name is already registered.
        """
        if not isinstance(rule, IDiscountRule):
            raise TypeError("Only IDiscountRule instances can be added.")
        if any(r.name.casefold() == rule.name.casefold() for r in self._rules):
            raise ValueError(f"A rule named {rule.name!r} is already registered.")
        self._rules.append(rule)

    def remove_rule(self, name: str) -> bool:
        """Remove the rule called ``name`` (case-insensitive).

        Returns:
            ``True`` if a rule was removed, ``False`` if none matched.
        """
        for index, rule in enumerate(self._rules):
            if rule.name.casefold() == name.casefold():
                del self._rules[index]
                return True
        return False

    def clear(self) -> None:
        """Remove all rules."""
        self._rules.clear()

    def process(self, cart: Cart) -> DiscountResult:
        """Apply the rules to ``cart``.

        Args:
            cart: The cart to price.

        Returns:
            The subtotal, total discount, final price and a per-rule breakdown.
        """
        subtotal = to_decimal(cart.subtotal)

        # Evaluate each rule once; the amounts are reused below.
        amounts: dict[int, float] = {id(r): r.calculate_discount(cart) for r in self._rules}

        # Pick the best exclusive rule. max() returns the first of equal
        # values, so ties go to the earliest registered rule.
        eligible_exclusive = [r for r in self.exclusive_rules if amounts[id(r)] > 0]
        best_exclusive = max(eligible_exclusive, key=lambda r: amounts[id(r)], default=None)

        outcomes: list[RuleOutcome] = []
        raw_total = Decimal("0")
        for rule in self._rules:
            amount = amounts[id(rule)]
            if amount <= 0:
                status, note = RuleStatus.NOT_APPLICABLE, "Conditions not met for this cart."
            elif rule.is_stackable:
                status, note = RuleStatus.APPLIED, "Stackable: added to the other discounts."
            elif rule is best_exclusive:
                others = len(eligible_exclusive) - 1
                status = RuleStatus.APPLIED
                note = (
                    f"Best of {others + 1} exclusive offers."
                    if others
                    else "Only eligible exclusive offer."
                )
            else:
                assert best_exclusive is not None  # an eligible rule exists
                status = RuleStatus.SUPERSEDED
                note = f"Exclusive: '{best_exclusive.name}' saves more."

            if status is RuleStatus.APPLIED:
                raw_total += to_decimal(amount)

            outcomes.append(
                RuleOutcome(
                    rule_name=rule.name,
                    rule_type=type(rule).__name__,
                    description=rule.describe(),
                    is_stackable=rule.is_stackable,
                    amount=amount,
                    status=status,
                    note=note,
                    breakdown=tuple(rule.explain(cart)),
                )
            )

        capped = raw_total > subtotal
        total_discount = min(raw_total, subtotal)
        return DiscountResult(
            subtotal=to_money(subtotal),
            total_discount=to_money(total_discount),
            final_price=to_money(subtotal - total_discount),
            outcomes=tuple(outcomes),
            capped=capped,
        )
