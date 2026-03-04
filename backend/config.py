import os
from dataclasses import dataclass


@dataclass
class Settings:
    port: int = int(os.getenv("PORT", "8000"))
    db_path: str = os.getenv("DB_PATH", "data/freeroomfinder.db")
    current_term: str = os.getenv("YEAR_TERM", "20261")  # Winter 2026
    discovery_semaphore: int = int(os.getenv("DISCOVERY_SEMAPHORE", "15"))
    crawl_delay: float = float(os.getenv("CRAWL_DELAY", "0.5"))  # seconds between requests
    room_range_start: int = 1
    room_range_end: int = 499
    byu_url: str = "https://y.byu.edu/class_schedule/cgi/classRoom.cgi"
    request_timeout: float = 15.0


settings = Settings()
