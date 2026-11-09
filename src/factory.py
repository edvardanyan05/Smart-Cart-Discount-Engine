"""Factory for creating discount rules from a type name (Factory Method).

Callers ask for a rule by name (``"percentage"``, ``"threshold"``,
``"composite"``) instead of importing and calling concrete classes. This
lets rules be defined in plain data, such as a JSON or YAML file.

New rule types are added with :meth:`DiscountFactory.register`, so the
factory itself never has to change (Open/Closed Principle).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, ClassVar

from .discounts import (
    CompositeDiscountRule,
    IDiscountRule,
    PercentageDiscount,
    ThresholdDiscount,
)

RuleCreator = Callable[..., IDiscountRule]
"""Anything that builds a rule from keyword arguments, such as a rule class."""


class UnknownDiscountTypeError(ValueError):
    """Raised when the factory is asked for a type that is not registered."""


class DiscountFactory:
    """Creates ``IDiscountRule`` objects from a type name and parameters."""

    _registry: ClassVar[dict[str, RuleCreator]] = {
        "percentage": PercentageDiscount,
        "threshold": ThresholdDiscount,
        "composite": CompositeDiscountRule,
    }

    @staticmethod
    def _normalise(rule_type: str) -> str:
        if not isinstance(rule_type, str) or not rule_type.strip():
            raise ValueError("Discount type must be a non-empty string.")
        return rule_type.strip().lower()

    @classmethod
    def register(cls, rule_type: str, creator: RuleCreator, *, replace: bool = False) -> None:
        """Register a new rule type.

        Args:
            rule_type: Name used to request the rule (case-insensitive).
            creator: A callable, usually a class, that returns an ``IDiscountRule``.
            replace: Allow overwriting an existing registration.

        Raises:
            ValueError: If the type is already registered and ``replace`` is False.
            TypeError: If ``creator`` is not callable.
        """
        key = cls._normalise(rule_type)
        if not callable(creator):
            raise TypeError("creator must be callable.")
        if key in cls._registry and not replace:
            raise ValueError(f"Discount type {key!r} is already registered.")
        cls._registry[key] = creator

    @classmethod
    def unregister(cls, rule_type: str) -> None:
        """Remove a registered rule type.

        Raises:
            UnknownDiscountTypeError: If the type is not registered.
        """
        key = cls._normalise(rule_type)
        if key not in cls._registry:
            raise UnknownDiscountTypeError(f"Unknown discount type {rule_type!r}.")
        del cls._registry[key]

    @classmethod
    def available_types(cls) -> list[str]:
        """Return the registered type names in alphabetical order."""
        return sorted(cls._registry)

    @classmethod
    def create(cls, rule_type: str, **params: Any) -> IDiscountRule:
        """Create a rule of type ``rule_type``.

        Args:
            rule_type: A registered type name, e.g. ``"percentage"``.
            **params: Keyword arguments for the rule's constructor.

        Returns:
            The new rule.

        Raises:
            UnknownDiscountTypeError: If ``rule_type`` is not registered.
            ValueError: If the parameters are missing or invalid.
        """
        key = cls._normalise(rule_type)
        creator = cls._registry.get(key)
        if creator is None:
            known = ", ".join(cls.available_types())
            raise UnknownDiscountTypeError(
                f"Unknown discount type {rule_type!r}. Available types: {known}."
            )
        try:
            rule = creator(**params)
        except TypeError as exc:
            raise ValueError(f"Invalid parameters for discount type {key!r}: {exc}") from exc
        if not isinstance(rule, IDiscountRule):
            raise TypeError(f"Creator for {key!r} did not return an IDiscountRule.")
        return rule

    @classmethod
    def create_from_config(cls, config: Mapping[str, Any]) -> IDiscountRule:
        """Create a rule, including nested groups, from a dictionary.

        The ``"type"`` key picks the rule type and the other keys are passed
        to its constructor. A ``"rules"`` key holding a list of dictionaries
        is built recursively, which is how nested composites are defined::

            {
                "type": "composite",
                "name": "Bundle",
                "mode": "sum",
                "rules": [
                    {"type": "percentage", "name": "5% off", "percentage": 5},
                    {"type": "threshold", "name": "$10 off $100",
                     "threshold": 100, "amount": 10},
                ],
            }

        Raises:
            ValueError: If ``"type"`` is missing or the config is invalid.
        """
        if not isinstance(config, Mapping):
            raise TypeError("Discount config must be a mapping.")
        params = dict(config)
        rule_type = params.pop("type", None)
        if rule_type is None:
            raise ValueError("Discount config is missing the 'type' key.")

        children = params.get("rules")
        if isinstance(children, (list, tuple)):
            params["rules"] = [
                cls.create_from_config(child) if isinstance(child, Mapping) else child
                for child in children
            ]
        return cls.create(rule_type, **params)
