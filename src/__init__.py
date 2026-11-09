"""Smart Cart Discount Engine.

A shopping cart and discount system that demonstrates the Strategy,
Factory Method and Composite design patterns.
"""

from .discounts import (
    CompositeDiscountRule,
    CompositionMode,
    IDiscountRule,
    PercentageDiscount,
    RuleBreakdown,
    ThresholdDiscount,
)
from .factory import DiscountFactory, UnknownDiscountTypeError
from .models import Cart, CartItem, Product, to_money
from .processor import DiscountProcessor, DiscountResult, RuleOutcome, RuleStatus

__all__ = [
    "Cart",
    "CartItem",
    "CompositeDiscountRule",
    "CompositionMode",
    "DiscountFactory",
    "DiscountProcessor",
    "DiscountResult",
    "IDiscountRule",
    "PercentageDiscount",
    "Product",
    "RuleBreakdown",
    "RuleOutcome",
    "RuleStatus",
    "ThresholdDiscount",
    "UnknownDiscountTypeError",
    "to_money",
]

__version__ = "1.0.0"
