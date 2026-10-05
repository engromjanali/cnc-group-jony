"""How much one notification may hold, in one place.

A push carries at most 4 KB, so both stay well under it."""

MAX_TITLE_LENGTH = 100

# Plain text. The phone shows the start of it; the details screen all of it.
MAX_BODY_LENGTH = 1_000
