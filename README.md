# Smart Cart Discount Engine

A modular Python shopping cart and discount engine built for an academic
OOP course. It shows the **Strategy**, **Factory Method** and **Composite**
design patterns and follows the SOLID principles.

No third-party packages are needed. Requires Python 3.10+.

## Project structure

```
Smart-Cart-Discount-Engine/
├── src/
│   ├── __init__.py      # Public API exports
│   ├── models.py        # Product, CartItem, Cart (+ money helpers)
│   ├── discounts.py     # IDiscountRule, PercentageDiscount, ThresholdDiscount,
│   │                    # CompositeDiscountRule, CompositionMode
│   ├── factory.py       # DiscountFactory, UnknownDiscountTypeError
│   └── processor.py     # DiscountProcessor, DiscountResult, RuleOutcome, RuleStatus
├── main.py              # Console demo + 49 self-checks
└── README.md
```

## Running

```bash
cd Smart-Cart-Discount-Engine
python main.py
```

The script prints formatted reports for seven scenarios and checks every
expected number. It exits with code `0` when all checks pass and `1`
otherwise, so it can also be used in CI.

## How discounts are applied

1. Each rule computes its discount for the cart, never more than the subtotal.
2. **Stackable** rules (`is_stackable=True`) are all applied and added together.
3. **Mutually exclusive** rules (`is_stackable=False`) compete. Only the one
   with the largest discount is applied; the others are marked *superseded*.
   Ties go to the rule registered first.
4. Total discount = stackable sum + best exclusive discount, capped at the
   subtotal so the final price is never negative.

Each rule's result is reported with a status (`applied`, `superseded` or
`not applicable`), a reason, and, for composites, a tree of its children.

## Design patterns

| Pattern | Where | Role |
|---|---|---|
| **Strategy** | `IDiscountRule` → `PercentageDiscount`, `ThresholdDiscount` | Each discount algorithm can be swapped for another. `DiscountProcessor` only knows the interface. |
| **Composite** | `CompositeDiscountRule` | A group of rules is itself an `IDiscountRule` and can contain other groups. `mode="sum"` adds the children together and `mode="best"` uses the largest. Cycles are rejected. |
| **Factory Method** | `DiscountFactory.create()` / `create_from_config()` | Builds rules from a type name or from a nested dictionary, so rules can be defined as data (JSON/YAML). New types are added with `register()`. |

Inside a composite, `mode` decides how the children combine and each
child's own `is_stackable` is ignored. The group's `is_stackable` flag
decides how the processor treats the group as a whole.

## SOLID

- **S**: Models store data, rules calculate discounts, the factory builds
  rules, the processor applies them, and `main.py` handles presentation.
- **O**: New rule types plug in through `DiscountFactory.register()`
  without editing existing code (`main.py` registers a `FreeShippingDiscount`).
- **L**: Every rule, including composites, can be used wherever an
  `IDiscountRule` is expected.
- **I**: The rule interface is small: `name`, `is_stackable`,
  `calculate_discount()` and `describe()`.
- **D**: `DiscountProcessor` and `CompositeDiscountRule` depend on the
  `IDiscountRule` abstraction, not on concrete classes.

## Usage example

```python
from src import Cart, DiscountFactory, DiscountProcessor, Product

cart = Cart()
cart.add_item(Product("P1", "Laptop", 1200.00, "Electronics"))
cart.add_item(Product("P2", "T-Shirt", 25.00, "Clothing"), quantity=3)

processor = DiscountProcessor([
    DiscountFactory.create("percentage", name="Clothing 20%", percentage=20,
                           category="Clothing"),
    DiscountFactory.create("percentage", name="Electronics 10%", percentage=10,
                           category="Electronics", is_stackable=False),
    DiscountFactory.create("threshold", name="$100 off $1000", threshold=1000,
                           amount=100, is_stackable=False),
    DiscountFactory.create_from_config({
        "type": "composite", "name": "Loyalty", "mode": "sum",
        "rules": [
            {"type": "percentage", "name": "Member 2%", "percentage": 2},
            {"type": "threshold", "name": "Member $10", "threshold": 100, "amount": 10},
        ],
    }),
])

result = processor.process(cart)
print("\n".join(result.log))
```

## Implementation notes

- Money is exposed as `float`, but all calculations use `Decimal` with
  half-up rounding to cents, so results like `10.7495 → 10.75` are exact.
- `Product` is immutable. Adding a product that is already in the cart
  increases its quantity.
- Category matching is case-insensitive.
- Invalid input raises `ValueError`, `TypeError`, `KeyError` or
  `UnknownDiscountTypeError` with a clear message.
