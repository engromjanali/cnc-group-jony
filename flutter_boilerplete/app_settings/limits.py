"""How much an app setting may hold, in one place."""

# Long enough for a store link with tracking parameters, or a direct download
# link on a CDN, and short enough to be a link and not a document.
MAX_URL_LENGTH = 500

# An email address, phone number, or messaging username - all comfortably
# shorter than this.
MAX_CONTACT_LENGTH = 200
