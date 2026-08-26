"""Product identity and compatibility settings for PLATA."""

PRODUCT_NAME = "PLATA"
PRODUCT_FULL_NAME = "PLATA FunPay Automation"
PRODUCT_VERSION = "0.1.1"

# Public PLATA releases are read from this repository's version tags.
UPDATE_REPOSITORY = "hambinoWW/FunPay-PlataBot"

# Existing Cardinal configuration files remain supported during migration.
CONFIG_DIRECTORY = "configs"
STORAGE_DIRECTORY = "storage"
PLUGINS_DIRECTORY = "plugins"

# Public names that must remain importable for unmodified Cardinal plugins.
LEGACY_PLUGIN_MODULE = "cardinal"
LEGACY_PLUGIN_CLASS = "Cardinal"

# Read-only central PLATA announcement feed embedded in the public build.
DEFAULT_ANNOUNCEMENTS_GIST_ID = "8a32dc28ef2d33fa21ed67fd8edab486"
ANNOUNCEMENTS_ENABLED_ENV = "PLATA_ENABLE_GIST_ANNOUNCEMENTS"

# The public build has one fixed owner. This value is intentionally not
# inferred from the first authorized user.
PLATA_OWNER_TELEGRAM_ID = 5264940850
