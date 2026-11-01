"""Backward-compatible launcher. Run: python main.py"""
from main import main
import asyncio

if __name__ == "__main__":
    asyncio.run(main())
