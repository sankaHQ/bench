# Local-time reservation API

Migrate a tenant-scoped reservation API to native Flask while retaining Django ORM models and domain logic. Interpret local times in the supplied IANA timezone. Reject nonexistent spring-transition times; require fold for ambiguous autumn times. Validate resource IDs and seat counts with DRF semantics. Preserve half-open reservation intervals, peak capacity across adjacent bookings, owner isolation, cancellation replay and atomic booking events. Return normalized UTC timestamps and preserve status/body/Allow/WWW-Authenticate behavior.

The source is an independently authored synthetic application. Public scenarios sample the contract; grading adds boundary and sequence cases.
