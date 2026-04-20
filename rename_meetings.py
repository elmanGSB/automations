#!/usr/bin/env python3
"""Batch rename Fireflies meetings with generic names."""

import asyncio
import os
import sys

# Add vm-api to path (works on both local and VM)
vm_api_path = os.path.expanduser("~/vm-api") if os.path.exists(os.path.expanduser("~/vm-api")) else "/Users/elmanamador/coding/automations/vm-api"
sys.path.insert(0, vm_api_path)

from fireflies import FirefliesClient

RENAMES = [
    ("01KP7BMMXF2FPY6C0764WZPHC5", "Humor Class: Comedy Fundamentals - Finding Truth & Misdirection"),
    ("01KP6T9J0ETZ4EZFQ6KYAEJN6B", "Art of Leading: Coinbase Case Study - Mission vs. Politics in Corporate Leadership"),
    ("01KNSK4QQ9FMKSVVPEYWARJQPV", "Conversations in Management: Difficult Conversations - When to Ask vs. When to Tell"),
    ("01KNSCE1KET7V769THR6SNNJ8H", "Policy Proposals Seminar: Debating Immigration & National Security"),
    ("01KNQ849Y6BNXH8J768G2D3J2Q", "Doss: Composable Enterprise Platforms - AI-Enabled Custom Business Applications"),
]

async def rename_meetings():
    api_key = os.environ.get("FIREFLIES_API_KEY")
    if not api_key:
        raise ValueError("FIREFLIES_API_KEY not set")

    client = FirefliesClient(api_key)
    try:
        for meeting_id, new_title in RENAMES:
            result = await client.update_meeting_title(meeting_id, new_title)
            print(f"✓ {meeting_id}: '{result}'")
    finally:
        await client.aclose()

if __name__ == "__main__":
    asyncio.run(rename_meetings())
