# drf-fastapi-003 synthetic fixture: nested writes, transactions, validation edges

A DRF order-management application exercising the validation and transaction
surface of the benchmark lane:

- writable nested serializers (`OrderSerializer` embeds `OrderItemSerializer`
  with `many=True`) with DRF's indexed nested error format;
- a transactional `create()`: the parent and children are written inside
  `transaction.atomic`, then a business rule (total quantity over 100) raises
  a validation error — the observable contract is a 400 with an unchanged
  database, which only holds when the write is atomic;
- `unique=True` field validation, `DecimalField(max_digits=8,
  decimal_places=2)` string representation and digit-limit errors,
  choice-field errors, and list-type errors for the nested payload.

Synthetic, Apache-2.0, written for Sanka Migration Bench.
