"""Discount rules, built with the Strategy and Composite design patterns.

Strategy
    ``IDiscountRule`` is the strategy interface. ``PercentageDiscount`` and
    ``ThresholdDiscount`` are concrete strategies. Code that applies discounts
    (the ``DiscountProcessor``) depends only on the interface, so new kinds of
    discount can be added without changing it (Open/Closed and Dependency
    Inversion principles).

Composite
    ``CompositeDiscountRule`` is itself an ``IDiscountRule`` that holds other
    rules, which may be composites too. Clients treat a single rule and a
    whole tree of rules the same way.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from decimal import Decimal
from enum import Enum
from typing import NamedTuple

from .models import Cart, to_decimal, to_money


class RuleBreakdown(NamedTuple):
    """One line of a rule's explanation tree.

    Attributes:
        depth: Nesting level (0 for the rule itself, 1 for its children, ...).
        name: Rule name.
        description: Short human-readable description of the rule.
        amount: Discount this rule produces for the given cart.
    """

    depth: int
    name: str
    description: str
    amount: float


class IDiscountRule(ABC):
    """Interface that every discount rule implements (Strategy).

    Attributes:
        name: Unique, human-readable rule name.
        is_stackable: ``True`` if the rule can be combined with other rules;
            ``False`` if it competes in the mutually exclusive group, where
            only the best rule is applied.
    """

    def __init__(self, name: str, *, is_stackable: bool = True) -> None:
        """Initialise the shared rule attributes.

        Raises:
            ValueError: If ``name`` is blank.
            TypeError: If ``is_stackable`` is not a bool.
        """
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Discount rule name must be a non-empty string.")
        if not isinstance(is_stackable, bool):
            raise TypeError("is_stackable must be a bool.")
        self._name = name.strip()
        self._is_stackable = is_stackable

    @property
    def name(self) -> str:
        """Rule name."""
        return self._name

    @property
    def is_stackable(self) -> bool:
        """Whether the rule can be combined with other rules."""
        return self._is_stackable

    @abstractmethod
    def calculate_discount(self, cart: Cart) -> float:
        """Return the discount amount for ``cart``.

        Implementations must return a value between ``0`` and
        ``cart.subtotal``, rounded to cents.
        """

    @abstractmethod
    def describe(self) -> str:
        """Return a short description of what the rule does."""

    def explain(self, cart: Cart, depth: int = 0) -> list[RuleBreakdown]:
        """Return this rule's contribution as an explanation tree.

        A plain rule is a single line. ``CompositeDiscountRule`` overrides
        this to add a line for each child.
        """
        return [RuleBreakdown(depth, self.name, self.describe(), self.calculate_discount(cart))]

    @staticmethod
    def _bounded(amount: Decimal | float, cart: Cart) -> float:
        """Clamp ``amount`` to ``[0, cart.subtotal]`` and round it to cents."""
        value = to_decimal(amount)
        ceiling = to_decimal(cart.subtotal)
        return to_money(max(Decimal("0"), min(value, ceiling)))

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(name={self._name!r}, "
            f"is_stackable={self._is_stackable})"
        )


class PercentageDiscount(IDiscountRule):
    """Take a percentage off the whole cart, or off one product category."""

    def __init__(
        self,
        name: str,
        percentage: float,
        category: str | None = None,
        *,
        is_stackable: bool = True,
    ) -> None:
        """Create a percentage discount.

        Args:
            name: Rule name.
            percentage: Percent to take off; must be in ``(0, 100]``.
            category: If given, only products in this category are discounted.
                ``None`` discounts the whole cart.
            is_stackable: Whether the rule can be combined with others.

        Raises:
            ValueError: If ``percentage`` is out of range or ``category`` is blank.
        """
        super().__init__(name, is_stackable=is_stackable)
        if isinstance(percentage, bool) or not isinstance(percentage, (int, float)):
            raise TypeError("percentage must be a number.")
        if not 0 < percentage <= 100:
            raise ValueError("percentage must be greater than 0 and at most 100.")
        if category is not None and (not isinstance(category, str) or not category.strip()):
            raise ValueError("category must be a non-empty string or None.")
        self._percentage = float(percentage)
        self._category = category.strip() if category else None

    @property
    def percentage(self) -> float:
        """Percent taken off."""
        return self._percentage

    @property
    def category(self) -> str | None:
        """Target category, or ``None`` for the whole cart."""
        return self._category

    def calculate_discount(self, cart: Cart) -> float:
        """Return ``percentage`` percent of the eligible amount."""
        base = (
            cart.subtotal
            if self._category is None
            else cart.subtotal_for_category(self._category)
        )
        amount = to_decimal(base) * to_decimal(self._percentage) / Decimal("100")
        return self._bounded(amount, cart)

    def describe(self) -> str:
        target = f"'{self._category}' items" if self._category else "entire cart"
        return f"{self._percentage:g}% off {target}"


class ThresholdDiscount(IDiscountRule):
    """Take a fixed amount off when the subtotal reaches a threshold."""

    def __init__(
        self,
        name: str,
        threshold: float,
        amount: float,
        *,
        is_stackable: bool = True,
    ) -> None:
        """Create a threshold discount.

        Args:
            name: Rule name.
            threshold: Minimum subtotal (inclusive) needed for the discount.
            amount: Fixed amount taken off; must be positive.
            is_stackable: Whether the rule can be combined with others.

        Raises:
            ValueError: If ``threshold`` is negative or ``amount`` is not positive.
        """
        super().__init__(name, is_stackable=is_stackable)
        for label, value in (("threshold", threshold), ("amount", amount)):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{label} must be a number.")
        if threshold < 0:
            raise ValueError("threshold cannot be negative.")
        if amount <= 0:
            raise ValueError("amount must be greater than 0.")
        self._threshold = to_money(threshold)
        self._amount = to_money(amount)

    @property
    def threshold(self) -> float:
        """Minimum subtotal needed for the discount."""
        return self._threshold

    @property
    def amount(self) -> float:
        """Fixed amount taken off."""
        return self._amount

    def calculate_discount(self, cart: Cart) -> float:
        """Return ``amount`` if the subtotal meets the threshold, else ``0``.

        The discount never exceeds the subtotal.
        """
        if cart.is_empty or cart.subtotal < self._threshold:
            return 0.0
        return self._bounded(self._amount, cart)

    def describe(self) -> str:
        return f"${self._amount:,.2f} off orders of ${self._threshold:,.2f}+"


class CompositionMode(str, Enum):
    """How a ``CompositeDiscountRule`` combines its children."""

    SUM = "sum"
    """Add up every child's discount (a bundle of rules)."""

    BEST = "best"
    """Use only the child with the largest discount (pick the best)."""


class CompositeDiscountRule(IDiscountRule):
    """A rule made of other rules, which may themselves be composites.

    Inside a group, ``mode`` decides how the children combine and each
    child's own ``is_stackable`` flag is ignored. The group's
    ``is_stackable`` flag decides how the group as a whole is handled by
    the ``DiscountProcessor``.
    """

    def __init__(
        self,
        name: str,
        rules: Iterable[IDiscountRule] | None = None,
        mode: CompositionMode | str = CompositionMode.SUM,
        *,
        is_stackable: bool = True,
    ) -> None:
        """Create a group of rules.

        Args:
            name: Rule name.
            rules: Initial child rules.
            mode: ``"sum"`` to add the children up, ``"best"`` to use the largest.
            is_stackable: Whether the group can be combined with other rules.

        Raises:
            ValueError: If ``mode`` is unknown or a child is invalid.
        """
        super().__init__(name, is_stackable=is_stackable)
        try:
            self._mode = CompositionMode(mode)
        except ValueError:
            valid = ", ".join(m.value for m in CompositionMode)
            raise ValueError(f"Unknown composition mode {mode!r}; expected one of: {valid}.") from None
        self._children: list[IDiscountRule] = []
        for rule in rules or ():
            self.add(rule)

    @property
    def mode(self) -> CompositionMode:
        """How the children are combined."""
        return self._mode

    @property
    def children(self) -> tuple[IDiscountRule, ...]:
        """The direct child rules (read-only)."""
        return tuple(self._children)

    def add(self, rule: IDiscountRule) -> None:
        """Add a child rule.

        Raises:
            TypeError: If ``rule`` is not an ``IDiscountRule``.
            ValueError: If adding ``rule`` would create a cycle or a duplicate.
        """
        if not isinstance(rule, IDiscountRule):
            raise TypeError("Composite children must implement IDiscountRule.")
        if rule is self or (isinstance(rule, CompositeDiscountRule) and rule.contains(self)):
            raise ValueError(f"Adding {rule.name!r} to {self.name!r} would create a cycle.")
        if any(child is rule for child in self._children):
            raise ValueError(f"{rule.name!r} is already part of {self.name!r}.")
        self._children.append(rule)

    def remove(self, rule: IDiscountRule) -> None:
        """Remove a direct child rule.

        Raises:
            ValueError: If ``rule`` is not a direct child.
        """
        for index, child in enumerate(self._children):
            if child is rule:
                del self._children[index]
                return
        raise ValueError(f"{rule.name!r} is not a child of {self.name!r}.")

    def contains(self, rule: IDiscountRule) -> bool:
        """Return ``True`` if ``rule`` is anywhere in this group's tree."""
        for child in self._children:
            if child is rule:
                return True
            if isinstance(child, CompositeDiscountRule) and child.contains(rule):
                return True
        return False

    def calculate_discount(self, cart: Cart) -> float:
        """Combine the children's discounts according to ``mode``.

        The result never exceeds the cart subtotal. An empty group gives ``0``.
        """
        amounts = [to_decimal(child.calculate_discount(cart)) for child in self._children]
        if not amounts:
            return 0.0
        combined = sum(amounts, Decimal("0")) if self._mode is CompositionMode.SUM else max(amounts)
        return self._bounded(combined, cart)

    def describe(self) -> str:
        how = "sum of" if self._mode is CompositionMode.SUM else "best of"
        return f"Group: {how} {len(self._children)} rule(s)"

    def explain(self, cart: Cart, depth: int = 0) -> list[RuleBreakdown]:
        """Return this group's line followed by each child's tree, indented."""
        lines = [RuleBreakdown(depth, self.name, self.describe(), self.calculate_discount(cart))]
        for child in self._children:
            lines.extend(child.explain(cart, depth + 1))
        return lines
