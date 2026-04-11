"""
Domain entity dataclasses.

Each module in this package defines one aggregate root or value object cluster.
Entities use stdlib types only. Frozen dataclasses are used for value objects
and immutable records (AuditEvent, LedgerEntry). Mutable aggregates use
regular dataclasses.
"""
