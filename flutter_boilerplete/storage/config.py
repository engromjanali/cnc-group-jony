"""Every storage policy knob in one place: allowlists, size limits, URL
lifetimes and where objects live. Views, validators and services import from
here rather than defining their own."""

# --- Upload limits ------------------------------------------------------------

# File bytes now pass through this backend (one multipart request adds a whole
# design), and Vercel rejects any request body over 4.5 MB with a 413 before
# Django ever sees it. The image and design file together must fit, so this is
# checked here first - with a readable message, and the same way locally as in
# production - and leaves headroom for the multipart framing and form fields.
MAX_DESIGN_UPLOAD_BYTES = 4 * 1024 * 1024

# --- Public preview images (Cloudinary) -------------------------------------

# Pillow's names for the image's real format (not the client-sent MIME type).
ALLOWED_IMAGE_FORMATS = frozenset({'jpg', 'jpeg', 'png', 'webp', 'gif'})

# Delivery transformation applied when building display URLs.
IMAGE_DELIVERY_TRANSFORMATION = 'f_auto,q_auto'

# Cloudinary folders
CLOUDINARY_DESIGN_FOLDER = 'cnc/designs'
CLOUDINARY_BANNER_FOLDER = 'cnc/banners'
CLOUDINARY_CATEGORY_FOLDER = 'cnc/categories'
CLOUDINARY_USER_PROFILE_FOLDER = 'cnc/user/profiles'
CLOUDINARY_WALLET_FOLDER = 'cnc/wallet'


def image_folder(user_id=None, folder=None):
    if folder:
        return folder
    if user_id is not None:
        return f'users/{user_id}/images'
    return CLOUDINARY_DESIGN_FOLDER


# --- Private files (R2) -----------------------------------------------------

# `application/octet-stream` is included because CNC toolpath files
# (.dxf/.dwg/.nc) are commonly sent with no specific type, so the extension
# allowlist below is what actually constrains those uploads.
ALLOWED_FILE_CONTENT_TYPES = frozenset({
    'application/pdf',
    'application/zip',
    'application/x-zip-compressed',
    'image/svg+xml',
    'image/vnd.dxf',
    'application/dxf',
    'application/x-dxf',
    'image/vnd.dwg',
    'application/acad',
    'application/postscript',
    'application/illustrator',
    'application/octet-stream',
})

ALLOWED_FILE_EXTENSIONS = frozenset({
    'pdf', 'zip', 'svg', 'dxf', 'dwg', 'nc', 'tap', 'gcode', 'cnc', 'plt', 'ai', 'eps',
})

# Downloads are presigned GETs that stop working after this long.
DOWNLOAD_URL_TTL_SECONDS = 5 * 60

# Cloudflare R2 object key prefix for design files
R2_DESIGN_FILE_PREFIX = 'designs-files/'


def file_key_prefix(user_id=None, prefix=None):
    if prefix:
        return prefix if prefix.endswith('/') else f'{prefix}/'
    if user_id is not None:
        return f'users/{user_id}/'
    return R2_DESIGN_FILE_PREFIX


# --- Cleanup ------------------------------------------------------------------
#
# Uploads are undone automatically when a design save fails, and replaced or
# deleted designs remove their own files. This is only the safety net for
# whatever slips through (e.g. a request killed mid-way): a file this old that
# no design points at is safe to reclaim.
CLEANUP_MAX_AGE_MINUTES = 60
