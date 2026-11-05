"""
Mock data for the Factory Inventory Management System
This module loads sample data from JSON files for inventory items, orders, demand forecasts, and backlog items.
All data is from September 2025 and includes warehouse, category, and date fields for filtering.
"""

import json
import os

# Get the directory where this file is located
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')

def load_json_file(filename):
    """Load data from a JSON file in the data directory"""
    filepath = os.path.join(DATA_DIR, filename)
    with open(filepath, 'r') as f:
        return json.load(f)

# Load all datasets from JSON files
inventory_items = load_json_file('inventory.json')
orders = load_json_file('orders.json')
demand_forecasts = load_json_file('demand_forecasts.json')
backlog_items = load_json_file('backlog_items.json')

# Load spending data
spending_data = load_json_file('spending.json')
spending_summary = spending_data['spending_summary']
monthly_spending = spending_data['monthly_spending']
category_spending = spending_data['category_spending']

# Load transactions
recent_transactions = load_json_file('transactions.json')

# Load purchase orders
purchase_orders = load_json_file('purchase_orders.json')

# Restocking catalog: unit cost, stock and category for demand-forecast SKUs that
# are missing from inventory.json (only PSU-501 overlaps), plus per-category lead times.
# Kept separate so Inventory/Dashboard totals are unaffected by the Restocking feature.
restock_catalog = load_json_file('restock_catalog.json')

# Submitted restock orders. In-memory only: appended to by POST /api/restocking/orders
# and reset on server restart (matches the project's no-database design).
restock_orders = []

# All data is now loaded from JSON files in the data/ directory
# This allows for easier maintenance and updates of the sample data
