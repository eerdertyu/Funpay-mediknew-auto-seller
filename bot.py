"""FunPay Medik bot entry point.

This is a safe starter scaffold. Connect the account only after verifying
the installed FunPayAPI version and its current event/order interfaces.
"""

from __future__ import annotations

import logging
import os

from dotenv import load_dotenv


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


def main() -> None:
    load_dotenv()
    configure_logging()
    logger = logging.getLogger("funpay-medik")

    golden_key = os.getenv("FUNPAY_GOLDEN_KEY", "").strip()
    phpsessid = os.getenv("FUNPAY_PHPSESSID", "").strip()

    if not golden_key or not phpsessid:
        logger.error(
            "Missing FunPay session settings. Fill FUNPAY_GOLDEN_KEY "
            "and FUNPAY_PHPSESSID in your local .env file."
        )
        raise SystemExit(1)

    logger.info("Configuration loaded. FunPay event integration is not wired yet.")
    logger.info(
        "Next step: connect the verified FunPayAPI client and implement "
        "safe new-order handling."
    )


if __name__ == "__main__":
    main()
