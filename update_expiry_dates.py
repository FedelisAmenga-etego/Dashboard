import pandas as pd
from datetime import datetime, timedelta
import random
import os

# -------- CONFIG --------
INPUT_FILE = "biomedical_lab_inventory.xlsx"
OUTPUT_FILE = "biomedical_lab_inventory_updated.xlsx"
TODAY = datetime(2025, 10, 22)  # Use current date

# -------- FUNCTION TO GENERATE DATES --------
def random_date_within(days_past=180, days_future=365):
    """Generate a random date between -days_past and +days_future from today."""
    delta_days = random.randint(-days_past, days_future)
    return TODAY + timedelta(days=delta_days)

# -------- LOAD INVENTORY --------
if not os.path.exists(INPUT_FILE):
    raise FileNotFoundError(f"Could not find {INPUT_FILE}")

df = pd.read_excel(INPUT_FILE, engine="openpyxl")

# -------- UPDATE DATES --------
if "Last Restocked" in df.columns:
    df["Last Restocked"] = [
        random_date_within(90, 180).strftime("%Y-%m-%d") for _ in range(len(df))
    ]

if "Expiry Date" in df.columns:
    expiry_dates = []
    for _ in range(len(df)):
        # 20% expired, 30% expiring soon, 50% good
        chance = random.random()
        if chance < 0.2:
            expiry = TODAY - timedelta(days=random.randint(1, 90))  # expired
        elif chance < 0.5:
            expiry = TODAY + timedelta(days=random.randint(1, 90))  # soon to expire
        else:
            expiry = TODAY + timedelta(days=random.randint(120, 720))  # long shelf life
        expiry_dates.append(expiry.strftime("%Y-%m-%d"))
    df["Expiry Date"] = expiry_dates

# -------- SAVE UPDATED VERSION --------
df.to_excel(OUTPUT_FILE, index=False, engine="openpyxl")
print(f"✅ Updated inventory saved as {OUTPUT_FILE}")
