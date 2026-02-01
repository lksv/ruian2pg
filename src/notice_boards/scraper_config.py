"""Configuration for document scrapers."""

import os
from dataclasses import dataclass, field

# Support loading from .env file if python-dotenv is available
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


@dataclass
class EdeskyConfig:
    """Configuration for eDesky.cz API scraper."""

    # API key from https://edesky.cz
    api_key: str = field(default_factory=lambda: os.getenv("EDESKY_API_KEY", ""))

    # API base URL
    base_url: str = field(default_factory=lambda: os.getenv("EDESKY_BASE_URL", "https://edesky.cz"))

    # Request timeout in seconds
    request_timeout: int = field(
        default_factory=lambda: int(os.getenv("EDESKY_REQUEST_TIMEOUT", "30"))
    )

    # Number of retries for failed requests
    max_retries: int = field(default_factory=lambda: int(os.getenv("EDESKY_MAX_RETRIES", "3")))

    # Delay between retries in seconds
    retry_delay: float = field(
        default_factory=lambda: float(os.getenv("EDESKY_RETRY_DELAY", "1.0"))
    )

    # Maximum documents per API request
    page_size: int = field(default_factory=lambda: int(os.getenv("EDESKY_PAGE_SIZE", "50")))

    # User-Agent header for requests
    user_agent: str = field(
        default_factory=lambda: os.getenv(
            "EDESKY_USER_AGENT", "ruian2pg-scraper/1.0 (+https://github.com/lksv/ruian2pg)"
        )
    )

    @property
    def is_configured(self) -> bool:
        """Check if API key is configured."""
        return bool(self.api_key)


@dataclass
class OfnConfig:
    """Configuration for OFN (Open Formal Norm) scraper."""

    # Request timeout in seconds
    request_timeout: int = field(
        default_factory=lambda: int(os.getenv("OFN_REQUEST_TIMEOUT", "30"))
    )

    # Number of retries for failed requests
    max_retries: int = field(default_factory=lambda: int(os.getenv("OFN_MAX_RETRIES", "3")))

    # Delay between retries in seconds
    retry_delay: float = field(default_factory=lambda: float(os.getenv("OFN_RETRY_DELAY", "1.0")))

    # User-Agent header for requests
    user_agent: str = field(
        default_factory=lambda: os.getenv(
            "OFN_USER_AGENT", "ruian2pg-scraper/1.0 (+https://github.com/lksv/ruian2pg)"
        )
    )

    # Skip SSL verification (some OFN feeds have invalid certs)
    skip_ssl_verify: bool = field(
        default_factory=lambda: os.getenv("OFN_SKIP_SSL_VERIFY", "true").lower()
        in ("true", "1", "yes")
    )


@dataclass
class ScraperConfig:
    """General scraper configuration."""

    # Maximum number of documents to download per scrape session
    max_documents: int = field(
        default_factory=lambda: int(os.getenv("SCRAPER_MAX_DOCUMENTS", "100"))
    )

    # Download attachments or just metadata
    download_attachments: bool = field(
        default_factory=lambda: os.getenv("SCRAPER_DOWNLOAD_ATTACHMENTS", "true").lower()
        in ("true", "1", "yes")
    )

    # Maximum attachment file size in bytes (default: 50MB)
    max_attachment_size: int = field(
        default_factory=lambda: int(os.getenv("SCRAPER_MAX_ATTACHMENT_SIZE", str(50 * 1024 * 1024)))
    )

    # Skip already downloaded documents
    incremental: bool = field(
        default_factory=lambda: os.getenv("SCRAPER_INCREMENTAL", "true").lower()
        in ("true", "1", "yes")
    )

    # Verbose logging
    verbose: bool = False

    # eDesky-specific configuration
    edesky: EdeskyConfig = field(default_factory=EdeskyConfig)

    # OFN-specific configuration
    ofn: OfnConfig = field(default_factory=OfnConfig)
