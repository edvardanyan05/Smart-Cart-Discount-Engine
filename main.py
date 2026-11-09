"""Console demo and self-test for the Smart Cart Discount Engine.

Run from the project root directory::

    python main.py

The script builds a product catalogue and carts, creates discount rules
through ``DiscountFactory``, runs ``DiscountProcessor`` over several
scenarios and prints a report for each. Every scenario also checks its
expected numbers; the script exits with status 1 if any check fails.
"""

from __future__ import annotations

import math
import sys
from collections.abc import Callable
from typing import Any

from src import (
    Cart,
    CompositeDiscountRule,
    DiscountFactory,
    DiscountProcessor,
    DiscountResult,
    IDiscountRule,
    Product,
    RuleStatus,
    UnknownDiscountTypeError,
)

WIDTH = 78


# --------------------------------------------------------------------------- #
# Output helpers
# --------------------------------------------------------------------------- #
def money(value: float) -> str:
    """Format a number as dollars, e.g. ``$1,234.50``."""
    return f"${value:,.2f}"


def banner(title: str) -> None:
    """Print a section heading."""
    print()
    print("=" * WIDTH)
    print(f" {title}")
    print("=" * WIDTH)


def sub_heading(title: str) -> None:
    """Print a smaller heading."""
    print()
    print(f"--- {title} " + "-" * max(0, WIDTH - len(title) - 5))


def print_cart(cart: Cart) -> None:
    """Print the cart's lines and subtotal as a table."""
    if cart.is_empty:
        print("  (cart is empty)")
        return
    print(f"  {'Product':<22}{'Category':<14}{'Unit':>11}{'Qty':>6}{'Line total':>14}")
    print("  " + "-" * 67)
    for item in cart:
        p = item.product
        print(
            f"  {p.name:<22}{p.category:<14}{money(p.price):>11}"
            f"{item.quantity:>6}{money(item.total_price):>14}"
        )
    print("  " + "-" * 67)
    print(f"  {'Subtotal':<53}{money(cart.subtotal):>14}")


def print_result(result: DiscountResult) -> None:
    """Print every rule's outcome, then the totals."""
    labels = {
        RuleStatus.APPLIED: "APPLIED",
        RuleStatus.SUPERSEDED: "SKIPPED",
        RuleStatus.NOT_APPLICABLE: "N/A",
    }
    print(f"  {'Status':<9}{'Group':<11}{'Rule':<34}{'Amount':>12}")
    print("  " + "-" * 66)
    for outcome in result.outcomes:
        group = "stackable" if outcome.is_stackable else "exclusive"
        print(
            f"  {labels[outcome.status]:<9}{group:<11}{outcome.rule_name:<34}"
            f"{money(outcome.amount):>12}"
        )
        print(f"  {'':<20}{outcome.description}")
        # Show the children of composite rules as an indented tree.
        for line in outcome.breakdown[1:]:
            indent = "  " * line.depth
            label = f"{indent}+ {line.name}"
            print(f"  {'':<20}{label:<34}{money(line.amount):>12}")
        print(f"  {'':<20}-> {outcome.note}")
    print("  " + "-" * 66)
    print(f"  {'Subtotal':<54}{money(result.subtotal):>12}")
    print(f"  {'Total discount':<54}{'-' + money(result.total_discount):>12}")
    if result.capped:
        print("  (discounts exceeded the subtotal and were capped)")
    print(f"  {'FINAL PRICE':<54}{money(result.final_price):>12}")
    print(f"  You save {result.savings_percentage:g}% on this order.")


# --------------------------------------------------------------------------- #
# Self-checks
# --------------------------------------------------------------------------- #
class CheckRunner:
    """Records pass/fail checks and prints a summary at the end."""

    def __init__(self) -> None:
        self.passed = 0
        self.failed: list[str] = []

    def equal(self, label: str, actual: Any, expected: Any) -> None:
        """Check that ``actual`` equals ``expected`` (floats compared to the cent)."""
        if isinstance(expected, float) and isinstance(actual, (int, float)):
            ok = math.isclose(actual, expected, abs_tol=0.005)
        else:
            ok = actual == expected
        self._record(label, ok, f"expected {expected!r}, got {actual!r}")

    def raises(self, label: str, exc_type: type[BaseException], action: Callable[[], Any]) -> None:
        """Check that ``action()`` raises ``exc_type``, and print the message."""
        try:
            action()
        except exc_type as exc:
            print(f"  Rejected as expected ({type(exc).__name__}): {exc}")
            self._record(label, True, "")
        except Exception as exc:  # noqa: BLE001 - report any unexpected error
            self._record(label, False, f"raised {type(exc).__name__} instead: {exc}")
        else:
            self._record(label, False, f"no {exc_type.__name__} was raised")

    def _record(self, label: str, ok: bool, detail: str) -> None:
        if ok:
            self.passed += 1
            print(f"  [PASS] {label}")
        else:
            self.failed.append(f"{label}: {detail}")
            print(f"  [FAIL] {label} - {detail}")

    def summary(self) -> bool:
        """Print the summary and return ``True`` if every check passed."""
        banner("SELF-CHECK SUMMARY")
        total = self.passed + len(self.failed)
        print(f"  {self.passed}/{total} checks passed.")
        for failure in self.failed:
            print(f"  FAILED: {failure}")
        return not self.failed


# --------------------------------------------------------------------------- #
# Test data
# --------------------------------------------------------------------------- #
CATALOG: dict[str, Product] = {
    p.id: p
    for p in (
        Product("P001", "Laptop Pro 14", 1200.00, "Electronics"),
        Product("P002", "Wireless Headphones", 150.00, "Electronics"),
        Product("P003", "Cotton T-Shirt", 25.00, "Clothing"),
        Product("P004", "Denim Jeans", 60.00, "Clothing"),
        Product("P005", "Coffee Beans 1kg", 18.50, "Grocery"),
        Product("P006", "Paperback Novel", 14.99, "Books"),
    )
}


def build_cart(lines: dict[str, int]) -> Cart:
    """Build a cart from ``{product_id: quantity}``."""
    cart = Cart()
    for product_id, quantity in lines.items():
        cart.add_item(CATALOG[product_id], quantity)
    return cart


def build_main_cart() -> Cart:
    """The large cart used by several scenarios (subtotal $1,738.98)."""
    cart = build_cart({"P001": 1, "P002": 1, "P003": 3, "P004": 1, "P005": 4, "P006": 2})
    # Adding a product already in the cart increases its quantity.
    cart.add_item(CATALOG["P002"], 1)
    return cart


def build_standard_rules() -> list[IDiscountRule]:
    """Create the store's rules through the factory.

    Stackable: Clothing Sale (20% clothing) and Loyalty Bundle (2% + $10 off
    $100). Exclusive: Electronics Week (10% electronics), Big Spender ($100
    off $1,000) and Site-wide Sale (5% of everything).
    """
    clothing_sale = DiscountFactory.create(
        "percentage", name="Clothing Sale", percentage=20, category="Clothing"
    )
    # A composite rule defined as data, the way it might come from a config file.
    loyalty_bundle = DiscountFactory.create_from_config(
        {
            "type": "composite",
            "name": "Loyalty Bundle",
            "mode": "sum",
            "rules": [
                {"type": "percentage", "name": "Member 2%", "percentage": 2},
                {"type": "threshold", "name": "Member $10", "threshold": 100, "amount": 10},
            ],
        }
    )
    electronics_week = DiscountFactory.create(
        "percentage",
        name="Electronics Week",
        percentage=10,
        category="electronics",  # category matching is case-insensitive
        is_stackable=False,
    )
    big_spender = DiscountFactory.create(
        "threshold", name="Big Spender", threshold=1000, amount=100, is_stackable=False
    )
    site_wide = DiscountFactory.create(
        "percentage", name="Site-wide Sale", percentage=5, is_stackable=False
    )
    return [clothing_sale, loyalty_bundle, electronics_week, big_spender, site_wide]


def status_of(result: DiscountResult, rule_name: str) -> RuleStatus:
    """Return the status of the rule called ``rule_name``."""
    return next(o.status for o in result.outcomes if o.rule_name == rule_name)


# --------------------------------------------------------------------------- #
# Scenarios
# --------------------------------------------------------------------------- #
def scenario_models(checks: CheckRunner) -> None:
    banner("1. MODELS: PRODUCTS AND CART")
    sub_heading("Catalogue")
    for p in CATALOG.values():
        print(f"  {p.id}  {p.name:<22}{p.category:<14}{money(p.price):>10}")

    sub_heading("Main cart (Headphones added twice, merged into one line)")
    cart = build_main_cart()
    print_cart(cart)

    checks.equal("Cart merges repeated products into one line", len(cart), 6)
    checks.equal("Headphones quantity is 2", cart.items[1].quantity, 2)
    checks.equal("CartItem.total_price", cart.items[1].total_price, 300.00)
    checks.equal("Cart subtotal", cart.subtotal, 1738.98)
    checks.equal("Electronics subtotal", cart.subtotal_for_category("Electronics"), 1500.00)
    checks.equal("Total units", cart.total_quantity, 13)

    sub_heading("Removing items")
    cart.remove_item("P003", 1)
    print("  Removed 1 x Cotton T-Shirt; removed the Paperback Novel line.")
    cart.remove_item("P006")
    checks.equal("Partial removal reduces quantity", cart.items[2].quantity, 2)
    checks.equal("Full removal drops the line", "P006" in cart, False)
    checks.equal("Subtotal after removals", cart.subtotal, 1684.00)


def scenario_factory(checks: CheckRunner) -> None:
    banner("2. FACTORY METHOD: CREATING RULES BY TYPE NAME")
    print(f"  Registered types: {', '.join(DiscountFactory.available_types())}")
    sub_heading("Rules created for the store")
    for rule in build_standard_rules():
        group = "stackable" if rule.is_stackable else "exclusive"
        print(f"  {type(rule).__name__:<24}{group:<11}{rule.name:<20}{rule.describe()}")

    rule = DiscountFactory.create("PERCENTAGE", name="Case test", percentage=1)
    checks.equal("Type names are case-insensitive", type(rule).__name__, "PercentageDiscount")

    sub_heading("Extending the factory without modifying it (Open/Closed)")

    class FreeShippingDiscount(IDiscountRule):
        """Example plug-in rule: a flat shipping refund on any non-empty cart."""

        def __init__(self, name: str, fee: float, *, is_stackable: bool = True) -> None:
            super().__init__(name, is_stackable=is_stackable)
            self._fee = fee

        def calculate_discount(self, cart: Cart) -> float:
            return 0.0 if cart.is_empty else self._bounded(self._fee, cart)

        def describe(self) -> str:
            return f"Refunds {money(self._fee)} shipping"

    DiscountFactory.register("free_shipping", FreeShippingDiscount)
    try:
        shipping = DiscountFactory.create("free_shipping", name="Free Shipping", fee=7.99)
        print(f"  Registered 'free_shipping' -> {shipping!r}: {shipping.describe()}")
        checks.equal(
            "Custom rule works with the factory",
            shipping.calculate_discount(build_cart({"P006": 1})),
            7.99,
        )
    finally:
        DiscountFactory.unregister("free_shipping")


def scenario_full_cart(checks: CheckRunner) -> None:
    banner("3. PROCESSOR: MAIN CART WITH ALL STORE RULES")
    cart = build_main_cart()
    processor = DiscountProcessor(build_standard_rules())
    print(
        f"  {len(processor.stackable_rules)} stackable rule(s), "
        f"{len(processor.exclusive_rules)} mutually exclusive rule(s)."
    )
    print(f"  Cart subtotal: {money(cart.subtotal)}")
    sub_heading("Discount breakdown")
    result = processor.process(cart)
    print_result(result)

    # 20% of $135 clothing = $27.00; loyalty = 2% of $1,738.98 ($34.78) + $10
    # = $44.78; best exclusive = 10% of $1,500 electronics = $150.00.
    checks.equal("Stackable: Clothing Sale amount", result.outcomes[0].amount, 27.00)
    checks.equal("Composite SUM: Loyalty Bundle amount", result.outcomes[1].amount, 44.78)
    checks.equal("Exclusive winner is Electronics Week",
                 status_of(result, "Electronics Week"), RuleStatus.APPLIED)
    checks.equal("Big Spender is superseded",
                 status_of(result, "Big Spender"), RuleStatus.SUPERSEDED)
    checks.equal("Site-wide Sale is superseded",
                 status_of(result, "Site-wide Sale"), RuleStatus.SUPERSEDED)
    checks.equal("Total discount", result.total_discount, 221.78)
    checks.equal("Final price", result.final_price, 1517.20)

    sub_heading("Plain-text log (DiscountResult.log)")
    for line in result.log:
        print(f"  {line}")


def scenario_small_cart(checks: CheckRunner) -> None:
    banner("4. PROCESSOR: SMALL CART (THRESHOLD NOT MET)")
    cart = build_cart({"P003": 2, "P002": 1, "P006": 1})
    print_cart(cart)
    sub_heading("Discount breakdown")
    result = DiscountProcessor(build_standard_rules()).process(cart)
    print_result(result)

    checks.equal("Big Spender not applicable below $1,000",
                 status_of(result, "Big Spender"), RuleStatus.NOT_APPLICABLE)
    checks.equal("Electronics Week still wins",
                 status_of(result, "Electronics Week"), RuleStatus.APPLIED)
    checks.equal("Total discount", result.total_discount, 39.30)
    checks.equal("Final price", result.final_price, 175.69)


def scenario_winner_changes(checks: CheckRunner) -> None:
    banner("5. PROCESSOR: CART CHANGES, EXCLUSIVE WINNER CHANGES")
    cart = build_main_cart()
    cart.remove_item("P001")
    cart.remove_item("P002")
    print("  Removed every Electronics item from the main cart.")
    print_cart(cart)
    sub_heading("Discount breakdown")
    result = DiscountProcessor(build_standard_rules()).process(cart)
    print_result(result)

    checks.equal("Electronics Week no longer applies",
                 status_of(result, "Electronics Week"), RuleStatus.NOT_APPLICABLE)
    checks.equal("Site-wide Sale is now the winner",
                 status_of(result, "Site-wide Sale"), RuleStatus.APPLIED)
    checks.equal("Total discount", result.total_discount, 53.73)
    checks.equal("Final price", result.final_price, 185.25)


def scenario_nested_composite(checks: CheckRunner) -> None:
    banner("6. COMPOSITE: NESTED GROUPS ('BEST OF' CONTAINING A 'SUM OF')")
    vip = DiscountFactory.create_from_config(
        {
            "type": "composite",
            "name": "VIP Pick-Best",
            "mode": "best",
            "rules": [
                {"type": "percentage", "name": "VIP Electronics 15%",
                 "percentage": 15, "category": "Electronics"},
                {
                    "type": "composite",
                    "name": "VIP Lifestyle",
                    "mode": "sum",
                    "rules": [
                        {"type": "percentage", "name": "VIP Clothing 30%",
                         "percentage": 30, "category": "Clothing"},
                        {"type": "percentage", "name": "VIP Grocery 10%",
                         "percentage": 10, "category": "Grocery"},
                    ],
                },
            ],
        }
    )
    sub_heading("Rule tree for the main cart (IDiscountRule.explain)")
    cart = build_main_cart()
    for line in vip.explain(cart):
        print(f"  {'    ' * line.depth}{line.name:<24}{line.description:<34}{money(line.amount):>12}")

    result = DiscountProcessor([vip]).process(cart)
    # Electronics 15% = $225.00 beats Lifestyle ($40.50 + $7.40 = $47.90).
    checks.equal("Inner SUM group", vip.explain(cart)[2].amount, 47.90)
    checks.equal("Outer BEST group picks the larger child", result.total_discount, 225.00)

    sub_heading("Same rule tree on an electronics-free cart")
    small = build_cart({"P003": 2, "P005": 2})
    for line in vip.explain(small):
        print(f"  {'    ' * line.depth}{line.name:<24}{line.description:<34}{money(line.amount):>12}")
    # Clothing 30% of $50 = $15.00 + Grocery 10% of $37 = $3.70 -> $18.70.
    checks.equal("BEST switches to the Lifestyle group", vip.calculate_discount(small), 18.70)


def scenario_edge_cases(checks: CheckRunner) -> None:
    banner("7. EDGE CASES AND VALIDATION")

    sub_heading("Empty cart")
    result = DiscountProcessor(build_standard_rules()).process(Cart())
    print_result(result)
    checks.equal("Empty cart final price", result.final_price, 0.0)
    checks.equal("No rules applied to an empty cart", len(result.applied), 0)

    sub_heading("Discounts larger than the subtotal are capped")
    cart = build_cart({"P006": 1})
    processor = DiscountProcessor(
        [
            DiscountFactory.create("threshold", name="$20 Voucher", threshold=10, amount=20),
            DiscountFactory.create("percentage", name="Half Price", percentage=50),
        ]
    )
    result = processor.process(cart)
    print_result(result)
    checks.equal("Single rule clamped to the subtotal", result.outcomes[0].amount, 14.99)
    checks.equal("Total is capped", result.capped, True)
    checks.equal("Final price never goes negative", result.final_price, 0.0)

    sub_heading("Exclusive tie goes to the first registered rule")
    tie = DiscountProcessor(
        [
            DiscountFactory.create("threshold", name="First $5", threshold=0, amount=5,
                                   is_stackable=False),
            DiscountFactory.create("threshold", name="Second $5", threshold=0, amount=5,
                                   is_stackable=False),
        ]
    ).process(cart)
    for line in tie.log:
        print(f"  {line}")
    checks.equal("Tie: first rule applied", status_of(tie, "First $5"), RuleStatus.APPLIED)
    checks.equal("Tie: total counts one rule only", tie.total_discount, 5.00)

    sub_heading("Managing rules")
    processor = DiscountProcessor(build_standard_rules())
    checks.equal("remove_rule returns True for a known rule",
                 processor.remove_rule("big spender"), True)
    checks.equal("remove_rule returns False for an unknown rule",
                 processor.remove_rule("No Such Rule"), False)
    checks.equal("Rule count after removal", len(processor.rules), 4)

    sub_heading("Invalid input is rejected")
    checks.raises("Unknown discount type", UnknownDiscountTypeError,
                  lambda: DiscountFactory.create("bogo", name="Buy one get one"))
    checks.raises("Percentage above 100", ValueError,
                  lambda: DiscountFactory.create("percentage", name="Too much", percentage=150))
    checks.raises("Missing factory parameter", ValueError,
                  lambda: DiscountFactory.create("threshold", name="No amount", threshold=50))
    checks.raises("Config without a type", ValueError,
                  lambda: DiscountFactory.create_from_config({"name": "Typeless"}))
    checks.raises("Unknown composite mode", ValueError,
                  lambda: DiscountFactory.create("composite", name="Odd", mode="average"))
    checks.raises("Duplicate rule name in processor", ValueError,
                  lambda: DiscountProcessor(build_standard_rules() + build_standard_rules()))
    checks.raises("Negative product price", ValueError,
                  lambda: Product("X1", "Broken", -1.0, "Misc"))
    checks.raises("Zero quantity", ValueError,
                  lambda: Cart().add_item(CATALOG["P001"], 0))
    checks.raises("Removing a product not in the cart", KeyError,
                  lambda: Cart().remove_item("P999"))

    outer = CompositeDiscountRule("Outer")
    inner = CompositeDiscountRule("Inner", [outer])
    checks.raises("Composite cycle detection", ValueError, lambda: outer.add(inner))


def main() -> int:
    """Run every scenario and return the process exit code."""
    print("SMART CART DISCOUNT ENGINE - DEMO AND SELF-TEST")
    checks = CheckRunner()
    for scenario in (
        scenario_models,
        scenario_factory,
        scenario_full_cart,
        scenario_small_cart,
        scenario_winner_changes,
        scenario_nested_composite,
        scenario_edge_cases,
    ):
        scenario(checks)
    return 0 if checks.summary() else 1


if __name__ == "__main__":
    sys.exit(main())
