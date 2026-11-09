"""Domain models for the shopping cart: ``Product``, ``CartItem`` and ``Cart``.

The models only hold and aggregate data. They know nothing about discounts,
which keeps them focused on one job (Single Responsibility Principle).

Monetary values are exposed as ``float`` for a simple public API, but every
calculation is done with :class:`decimal.Decimal` and rounded half-up to
cents, so the usual binary floating-point drift (e.g. ``0.1 + 0.2``) never
reaches the user.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

_CENT = Decimal("0.01")


def to_decimal(value: float | int | Decimal) -> Decimal:
    """Convert a number to ``Decimal`` without inheriting binary float error.

    Args:
        value: The number to convert.

    Returns:
        The exact decimal representation of the number's shortest repr.
    """
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def to_money(value: float | int | Decimal) -> float:
    """Round a number to two decimal places (half-up) and return a float.

    Args:
        value: The amount to round.

    Returns:
        The amount rounded to whole cents.
    """
    return float(to_decimal(value).quantize(_CENT, rounding=ROUND_HALF_UP))


def _require_text(value: str, field_name: str) -> str:
    """Validate that ``value`` is a non-blank string and return it stripped."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string.")
    return value.strip()


@dataclass(frozen=True)
class Product:
    """An immutable item that can be sold.

    Attributes:
        id: Unique product identifier (e.g. a SKU).
        name: Human-readable product name.
        price: Unit price; must be zero or positive.
        category: Category used by category-specific discounts.
    """

    id: str
    name: str
    price: float
    category: str

    def __post_init__(self) -> None:
        # ``frozen=True`` blocks normal assignment, so use object.__setattr__
        # to store the normalised values.
        object.__setattr__(self, "id", _require_text(self.id, "Product id"))
        object.__setattr__(self, "name", _require_text(self.name, "Product name"))
        object.__setattr__(
            self, "category", _require_text(self.category, "Product category")
        )
        if isinstance(self.price, bool) or not isinstance(self.price, (int, float)):
            raise TypeError("Product price must be a number.")
        if self.price < 0:
            raise ValueError("Product price cannot be negative.")
        object.__setattr__(self, "price", to_money(self.price))

    def in_category(self, category: str) -> bool:
        """Return ``True`` if the product belongs to ``category`` (case-insensitive)."""
        return self.category.casefold() == category.strip().casefold()


class CartItem:
    """A product together with the quantity placed in the cart."""

    def __init__(self, product: Product, quantity: int = 1) -> None:
        """Create a cart line.

        Args:
            product: The product being purchased.
            quantity: Number of units; must be a positive integer.

        Raises:
            TypeError: If ``product`` is not a ``Product`` or quantity is not an int.
            ValueError: If ``quantity`` is not positive.
        """
        if not isinstance(product, Product):
            raise TypeError("CartItem.product must be a Product instance.")
        self._product = product
        self._quantity = 0
        self.quantity = quantity  # validated by the property setter

    @property
    def product(self) -> Product:
        """The product on this line."""
        return self._product

    @property
    def quantity(self) -> int:
        """Number of units of the product."""
        return self._quantity

    @quantity.setter
    def quantity(self, value: int) -> None:
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError("Quantity must be an integer.")
        if value <= 0:
            raise ValueError("Quantity must be a positive integer.")
        self._quantity = value

    @property
    def total_price(self) -> float:
        """Unit price multiplied by quantity, rounded to cents."""
        return to_money(to_decimal(self._product.price) * self._quantity)

    def __repr__(self) -> str:
        return f"CartItem(product={self._product.name!r}, quantity={self._quantity})"


class Cart:
    """A shopping cart made of ``CartItem`` lines.

    Adding a product that is already in the cart increases its quantity
    instead of creating a second line.
    """

    def __init__(self) -> None:
        """Create an empty cart."""
        # A dict keyed by product id keeps insertion order and gives O(1) lookups.
        self._items: dict[str, CartItem] = {}

    @property
    def items(self) -> list[CartItem]:
        """A copy of the cart lines, in the order they were added."""
        return list(self._items.values())

    def add_item(self, product: Product, quantity: int = 1) -> CartItem:
        """Add ``quantity`` units of ``product`` to the cart.

        Args:
            product: The product to add.
            quantity: Number of units to add; must be positive.

        Returns:
            The cart line that now holds the product.

        Raises:
            ValueError: If the quantity is invalid, or a different product
                with the same id is already in the cart.
        """
        existing = self._items.get(product.id)
        if existing is None:
            item = CartItem(product, quantity)
            self._items[product.id] = item
            return item

        if existing.product != product:
            raise ValueError(
                f"A different product with id {product.id!r} is already in the cart."
            )
        if isinstance(quantity, bool) or not isinstance(quantity, int):
            raise TypeError("Quantity must be an integer.")
        if quantity <= 0:
            raise ValueError("Quantity must be a positive integer.")
        existing.quantity += quantity
        return existing

    def remove_item(self, product_id: str, quantity: int | None = None) -> None:
        """Remove a product, or reduce its quantity.

        Args:
            product_id: Id of the product to remove.
            quantity: Units to remove. ``None`` (or a value at least equal to
                the current quantity) removes the whole line.

        Raises:
            KeyError: If the product is not in the cart.
            ValueError: If ``quantity`` is not positive.
        """
        item = self._items.get(product_id)
        if item is None:
            raise KeyError(f"Product {product_id!r} is not in the cart.")
        if quantity is None or quantity >= item.quantity:
            del self._items[product_id]
            return
        if quantity <= 0:
            raise ValueError("Quantity to remove must be a positive integer.")
        item.quantity -= quantity

    def clear(self) -> None:
        """Remove every item from the cart."""
        self._items.clear()

    @property
    def subtotal(self) -> float:
        """Sum of every line total, before discounts."""
        return to_money(sum((to_decimal(i.total_price) for i in self), Decimal("0")))

    def subtotal_for_category(self, category: str) -> float:
        """Sum of the line totals for products in ``category`` (case-insensitive)."""
        return to_money(
            sum(
                (to_decimal(i.total_price) for i in self if i.product.in_category(category)),
                Decimal("0"),
            )
        )

    @property
    def total_quantity(self) -> int:
        """Total number of units across all lines."""
        return sum(item.quantity for item in self)

    @property
    def is_empty(self) -> bool:
        """``True`` when the cart has no items."""
        return not self._items

    def __iter__(self) -> Iterator[CartItem]:
        return iter(self._items.values())

    def __len__(self) -> int:
        return len(self._items)

    def __contains__(self, product_id: object) -> bool:
        return product_id in self._items

    def __repr__(self) -> str:
        return f"Cart(lines={len(self)}, subtotal={self.subtotal:.2f})"
