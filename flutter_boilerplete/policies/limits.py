"""How much a privacy policy may hold, in one place."""

MAX_TITLE_LENGTH = 200

# Characters of HTML, not of visible text: the rich-text editor wraps every
# paragraph and run of styled text in tags, so this is generous for what is
# still a page or two of prose.
MAX_CONTENT_LENGTH = 100_000
