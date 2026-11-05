import math
from datetime import date, datetime, timedelta
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional
from pydantic import BaseModel
from mock_data import inventory_items, orders, demand_forecasts, backlog_items, spending_summary, monthly_spending, category_spending, recent_transactions, purchase_orders, restock_catalog, restock_orders

app = FastAPI(title="Factory Inventory Management System")

# Quarter mapping for date filtering
QUARTER_MAP = {
    'Q1-2025': ['2025-01', '2025-02', '2025-03'],
    'Q2-2025': ['2025-04', '2025-05', '2025-06'],
    'Q3-2025': ['2025-07', '2025-08', '2025-09'],
    'Q4-2025': ['2025-10', '2025-11', '2025-12']
}

def filter_by_month(items: list, month: Optional[str]) -> list:
    """Filter items by month/quarter based on order_date field"""
    if not month or month == 'all':
        return items

    if month.startswith('Q'):
        # Handle quarters
        if month in QUARTER_MAP:
            months = QUARTER_MAP[month]
            return [item for item in items if any(m in item.get('order_date', '') for m in months)]
    else:
        # Direct month match
        return [item for item in items if month in item.get('order_date', '')]

    return items

def apply_filters(items: list, warehouse: Optional[str] = None, category: Optional[str] = None,
                 status: Optional[str] = None) -> list:
    """Apply common filters to a list of items"""
    filtered = items

    if warehouse and warehouse != 'all':
        filtered = [item for item in filtered if item.get('warehouse') == warehouse]

    if category and category != 'all':
        filtered = [item for item in filtered if item.get('category', '').lower() == category.lower()]

    if status and status != 'all':
        filtered = [item for item in filtered if item.get('status', '').lower() == status.lower()]

    return filtered

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Data models
class InventoryItem(BaseModel):
    id: str
    sku: str
    name: str
    category: str
    warehouse: str
    quantity_on_hand: int
    reorder_point: int
    unit_cost: float
    location: str
    last_updated: str

class Order(BaseModel):
    id: str
    order_number: str
    customer: str
    items: List[dict]
    status: str
    order_date: str
    expected_delivery: str
    total_value: float
    actual_delivery: Optional[str] = None
    warehouse: Optional[str] = None
    category: Optional[str] = None

class DemandForecast(BaseModel):
    id: str
    item_sku: str
    item_name: str
    current_demand: int
    forecasted_demand: int
    trend: str
    period: str

class BacklogItem(BaseModel):
    id: str
    order_id: str
    item_sku: str
    item_name: str
    quantity_needed: int
    quantity_available: int
    days_delayed: int
    priority: str
    has_purchase_order: Optional[bool] = False

class PurchaseOrder(BaseModel):
    id: str
    backlog_item_id: str
    supplier_name: str
    quantity: int
    unit_cost: float
    expected_delivery_date: str
    status: str
    created_date: str
    notes: Optional[str] = None

class CreatePurchaseOrderRequest(BaseModel):
    backlog_item_id: str
    supplier_name: str
    quantity: int
    unit_cost: float
    expected_delivery_date: str
    notes: Optional[str] = None

class RestockRecommendation(BaseModel):
    sku: str
    name: str
    category: str
    current_stock: int
    forecasted_demand: int
    shortfall: int
    unit_cost: float
    recommended_qty: int
    line_cost: float
    lead_time_days: int

class RestockRecommendationsResponse(BaseModel):
    budget: float
    items: List[RestockRecommendation]
    total_cost: float
    remaining_budget: float
    # Cost to cover every shortfall in full, so the UI can show how far the budget goes
    full_shortfall_cost: float

class RestockOrderItem(BaseModel):
    sku: str
    quantity: int

class CreateRestockOrderRequest(BaseModel):
    budget: float
    items: List[RestockOrderItem]

class RestockOrderLine(BaseModel):
    sku: str
    name: str
    category: str
    quantity: int
    unit_cost: float
    line_cost: float
    lead_time_days: int

class RestockOrder(BaseModel):
    id: str
    submitted_at: str
    items: List[RestockOrderLine]
    total_cost: float
    lead_time_days: int
    expected_delivery: str
    status: str

# API endpoints
@app.get("/")
def root():
    return {"message": "Factory Inventory Management System API", "version": "1.0.0"}

@app.get("/api/inventory", response_model=List[InventoryItem])
def get_inventory(
    warehouse: Optional[str] = None,
    category: Optional[str] = None
):
    """Get all inventory items with optional filtering"""
    return apply_filters(inventory_items, warehouse, category)

@app.get("/api/inventory/{item_id}", response_model=InventoryItem)
def get_inventory_item(item_id: str):
    """Get a specific inventory item"""
    item = next((item for item in inventory_items if item["id"] == item_id), None)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    return item

@app.get("/api/orders", response_model=List[Order])
def get_orders(
    warehouse: Optional[str] = None,
    category: Optional[str] = None,
    status: Optional[str] = None,
    month: Optional[str] = None
):
    """Get all orders with optional filtering"""
    filtered_orders = apply_filters(orders, warehouse, category, status)
    filtered_orders = filter_by_month(filtered_orders, month)
    return filtered_orders

@app.get("/api/orders/{order_id}", response_model=Order)
def get_order(order_id: str):
    """Get a specific order"""
    order = next((order for order in orders if order["id"] == order_id), None)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order

@app.get("/api/demand", response_model=List[DemandForecast])
def get_demand_forecasts():
    """Get demand forecasts"""
    return demand_forecasts

@app.get("/api/backlog", response_model=List[BacklogItem])
def get_backlog():
    """Get backlog items with purchase order status"""
    # Add has_purchase_order flag to each backlog item
    result = []
    for item in backlog_items:
        item_dict = dict(item)
        # Check if this backlog item has a purchase order
        has_po = any(po["backlog_item_id"] == item["id"] for po in purchase_orders)
        item_dict["has_purchase_order"] = has_po
        result.append(item_dict)
    return result

@app.get("/api/dashboard/summary")
def get_dashboard_summary(
    warehouse: Optional[str] = None,
    category: Optional[str] = None,
    status: Optional[str] = None,
    month: Optional[str] = None
):
    """Get summary statistics for dashboard with optional filtering"""
    # Filter inventory
    filtered_inventory = apply_filters(inventory_items, warehouse, category)

    # Filter orders
    filtered_orders = apply_filters(orders, warehouse, category, status)
    filtered_orders = filter_by_month(filtered_orders, month)

    total_inventory_value = sum(item["quantity_on_hand"] * item["unit_cost"] for item in filtered_inventory)
    low_stock_items = len([item for item in filtered_inventory if item["quantity_on_hand"] <= item["reorder_point"]])
    pending_orders = len([order for order in filtered_orders if order["status"] in ["Processing", "Backordered"]])
    total_backlog_items = len(backlog_items)

    return {
        "total_inventory_value": round(total_inventory_value, 2),
        "low_stock_items": low_stock_items,
        "pending_orders": pending_orders,
        "total_backlog_items": total_backlog_items,
        "total_orders_value": sum(order["total_value"] for order in filtered_orders)
    }

@app.get("/api/spending/summary")
def get_spending_summary():
    """Get spending summary statistics"""
    return spending_summary

@app.get("/api/spending/monthly")
def get_monthly_spending():
    """Get monthly spending breakdown"""
    return monthly_spending

@app.get("/api/spending/categories")
def get_category_spending():
    """Get spending by category"""
    return category_spending

@app.get("/api/spending/transactions")
def get_recent_transactions():
    """Get recent transactions"""
    return recent_transactions

@app.get("/api/reports/quarterly")
def get_quarterly_reports():
    """Get quarterly performance reports"""
    # Calculate quarterly statistics from orders
    quarters = {}

    for order in orders:
        order_date = order.get('order_date', '')
        # Determine quarter
        if '2025-01' in order_date or '2025-02' in order_date or '2025-03' in order_date:
            quarter = 'Q1-2025'
        elif '2025-04' in order_date or '2025-05' in order_date or '2025-06' in order_date:
            quarter = 'Q2-2025'
        elif '2025-07' in order_date or '2025-08' in order_date or '2025-09' in order_date:
            quarter = 'Q3-2025'
        elif '2025-10' in order_date or '2025-11' in order_date or '2025-12' in order_date:
            quarter = 'Q4-2025'
        else:
            continue

        if quarter not in quarters:
            quarters[quarter] = {
                'quarter': quarter,
                'total_orders': 0,
                'total_revenue': 0,
                'delivered_orders': 0,
                'avg_order_value': 0
            }

        quarters[quarter]['total_orders'] += 1
        quarters[quarter]['total_revenue'] += order.get('total_value', 0)
        if order.get('status') == 'Delivered':
            quarters[quarter]['delivered_orders'] += 1

    # Calculate averages and fulfillment rate
    result = []
    for q, data in quarters.items():
        if data['total_orders'] > 0:
            data['avg_order_value'] = round(data['total_revenue'] / data['total_orders'], 2)
            data['fulfillment_rate'] = round((data['delivered_orders'] / data['total_orders']) * 100, 1)
        result.append(data)

    # Sort by quarter
    result.sort(key=lambda x: x['quarter'])
    return result

@app.get("/api/reports/monthly-trends")
def get_monthly_trends():
    """Get month-over-month trends"""
    months = {}

    for order in orders:
        order_date = order.get('order_date', '')
        if not order_date:
            continue

        # Extract month (format: YYYY-MM-DD)
        month = order_date[:7]  # Gets YYYY-MM

        if month not in months:
            months[month] = {
                'month': month,
                'order_count': 0,
                'revenue': 0,
                'delivered_count': 0
            }

        months[month]['order_count'] += 1
        months[month]['revenue'] += order.get('total_value', 0)
        if order.get('status') == 'Delivered':
            months[month]['delivered_count'] += 1

    # Convert to list and sort
    result = list(months.values())
    result.sort(key=lambda x: x['month'])
    return result

# ---------------------------------------------------------------------------
# Restocking
# ---------------------------------------------------------------------------

def get_restock_candidates() -> dict:
    """Join each demand forecast with cost/stock/category/lead-time data, keyed by SKU.

    Non-obvious: only PSU-501 exists in inventory.json, so for most forecast SKUs the
    data comes from restock_catalog.json. Inventory wins when a SKU is in both, because
    it is the live source of stock levels. SKUs with no data in either place are skipped
    (they cannot be priced, so they cannot be ordered).
    """
    lead_times = restock_catalog["category_lead_times_days"]
    catalog_by_sku = {c["item_sku"]: c for c in restock_catalog["items"]}
    inventory_by_sku = {i["sku"]: i for i in inventory_items}

    candidates = {}
    for forecast in demand_forecasts:
        sku = forecast["item_sku"]
        source = inventory_by_sku.get(sku)
        if source:
            stock, unit_cost, category = source["quantity_on_hand"], source["unit_cost"], source["category"]
        elif sku in catalog_by_sku:
            entry = catalog_by_sku[sku]
            stock, unit_cost, category = entry["stock_on_hand"], entry["unit_cost"], entry["category"]
        else:
            continue

        candidates[sku] = {
            "sku": sku,
            "name": forecast["item_name"],
            "category": category,
            "current_stock": stock,
            "forecasted_demand": forecast["forecasted_demand"],
            # Shortfall is clamped at 0: surplus stock never produces a negative order
            "shortfall": max(0, forecast["forecasted_demand"] - stock),
            "unit_cost": unit_cost,
            "lead_time_days": lead_times.get(category, max(lead_times.values())),
        }
    return candidates

@app.get("/api/restocking/recommendations", response_model=RestockRecommendationsResponse)
def get_restock_recommendations(budget: float = Query(..., ge=0)):
    """Recommend items to restock for a budget, prioritised by demand shortfall."""
    candidates = [c for c in get_restock_candidates().values() if c["shortfall"] > 0]
    # Largest shortfall first; SKU as a tiebreaker keeps the ordering deterministic
    candidates.sort(key=lambda c: (-c["shortfall"], c["sku"]))

    remaining = budget
    items = []
    for c in candidates:
        # Greedy fill with partial quantities: if the full shortfall does not fit in the
        # remaining budget, buy as many units as still fit, then keep going so cheaper
        # lower-priority items can use whatever budget is left.
        qty = min(c["shortfall"], math.floor(remaining / c["unit_cost"]))
        if qty <= 0:
            continue
        line_cost = round(qty * c["unit_cost"], 2)
        remaining = round(remaining - line_cost, 2)
        items.append({**c, "recommended_qty": qty, "line_cost": line_cost})

    total_cost = round(sum(i["line_cost"] for i in items), 2)
    return {
        "budget": budget,
        "items": items,
        "total_cost": total_cost,
        "remaining_budget": round(budget - total_cost, 2),
        "full_shortfall_cost": round(sum(c["shortfall"] * c["unit_cost"] for c in candidates), 2),
    }

@app.post("/api/restocking/orders", response_model=RestockOrder, status_code=201)
def create_restock_order(request: CreateRestockOrderRequest):
    """Submit a restocking order. Stored in memory only."""
    if not request.items:
        raise HTTPException(status_code=400, detail="Order must contain at least one item")

    skus = [i.sku for i in request.items]
    if len(set(skus)) != len(skus):
        raise HTTPException(status_code=400, detail="Duplicate SKUs in order")

    candidates = get_restock_candidates()
    lines = []
    for item in request.items:
        if item.quantity <= 0:
            raise HTTPException(status_code=400, detail=f"Quantity for {item.sku} must be greater than 0")
        candidate = candidates.get(item.sku)
        if not candidate:
            raise HTTPException(status_code=400, detail=f"Unknown SKU: {item.sku}")
        # Prices come from the server, never the client, so the client cannot
        # understate the cost of an order to get under its budget.
        lines.append({
            "sku": item.sku,
            "name": candidate["name"],
            "category": candidate["category"],
            "quantity": item.quantity,
            "unit_cost": candidate["unit_cost"],
            "line_cost": round(item.quantity * candidate["unit_cost"], 2),
            "lead_time_days": candidate["lead_time_days"],
        })

    total_cost = round(sum(l["line_cost"] for l in lines), 2)
    if total_cost > round(request.budget, 2):
        raise HTTPException(
            status_code=400,
            detail=f"Order total {total_cost:.2f} exceeds budget {request.budget:.2f}"
        )

    # The order ships as one delivery, so it arrives when its slowest item does:
    # order lead time is the max across items, not the sum or average.
    lead_time_days = max(l["lead_time_days"] for l in lines)
    order = {
        "id": f"RST-{len(restock_orders) + 1:04d}",
        "submitted_at": datetime.now().isoformat(timespec="seconds"),
        "items": lines,
        "total_cost": total_cost,
        "lead_time_days": lead_time_days,
        "expected_delivery": (date.today() + timedelta(days=lead_time_days)).isoformat(),
        "status": "Submitted",
    }
    restock_orders.append(order)
    return order

@app.get("/api/restocking/orders", response_model=List[RestockOrder])
def get_restock_orders():
    """Get submitted restock orders, newest first"""
    return list(reversed(restock_orders))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
