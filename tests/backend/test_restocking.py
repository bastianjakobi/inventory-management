"""
Tests for restocking API endpoints.
"""
from datetime import date, timedelta

import pytest

import mock_data


@pytest.fixture(autouse=True)
def clear_restock_orders():
    """Submitted restock orders live in an in-memory list that is never reset,
    so clear it (in place, main.py holds a reference to the same list) around each test."""
    mock_data.restock_orders.clear()
    yield
    mock_data.restock_orders.clear()


def recommend(client, budget):
    response = client.get(f"/api/restocking/recommendations?budget={budget}")
    assert response.status_code == 200
    return response.json()


def order_payload(recommendation, budget=None):
    """Build a POST body from a recommendations response."""
    return {
        "budget": recommendation["budget"] if budget is None else budget,
        "items": [
            {"sku": i["sku"], "quantity": i["recommended_qty"]}
            for i in recommendation["items"]
        ],
    }


class TestRestockRecommendations:
    """Test suite for GET /api/restocking/recommendations."""

    def test_recommendation_structure(self, client):
        """Test the response and item fields."""
        data = recommend(client, 15000)
        for field in ("budget", "items", "total_cost", "remaining_budget", "full_shortfall_cost"):
            assert field in data
        assert len(data["items"]) > 0

        item = data["items"][0]
        for field in ("sku", "name", "category", "current_stock", "forecasted_demand",
                      "shortfall", "unit_cost", "recommended_qty", "line_cost", "lead_time_days"):
            assert field in item
        assert isinstance(item["recommended_qty"], int)
        assert isinstance(item["unit_cost"], (int, float))

    def test_zero_budget_returns_no_items(self, client):
        """Test that a zero budget recommends nothing."""
        data = recommend(client, 0)
        assert data["items"] == []
        assert data["total_cost"] == 0
        assert data["remaining_budget"] == 0

    def test_negative_budget_rejected(self, client):
        """Test that a negative budget fails validation."""
        response = client.get("/api/restocking/recommendations?budget=-1")
        assert response.status_code == 422

    def test_missing_budget_rejected(self, client):
        """Test that budget is required."""
        response = client.get("/api/restocking/recommendations")
        assert response.status_code == 422

    @pytest.mark.parametrize("budget", [100, 5000, 15000, 40000, 1000000])
    def test_total_cost_never_exceeds_budget(self, client, budget):
        """Test that recommendations always fit inside the budget."""
        data = recommend(client, budget)
        assert data["total_cost"] <= budget
        assert abs(data["remaining_budget"] - (budget - data["total_cost"])) < 0.01

    def test_line_costs_add_up(self, client):
        """Test line_cost = qty * unit_cost and that the total is their sum."""
        data = recommend(client, 15000)
        for item in data["items"]:
            assert abs(item["line_cost"] - item["recommended_qty"] * item["unit_cost"]) < 0.01
        assert abs(data["total_cost"] - sum(i["line_cost"] for i in data["items"])) < 0.01

    def test_higher_budget_never_lowers_total_cost(self, client):
        """Test that spend is monotonic in the budget."""
        costs = [recommend(client, b)["total_cost"] for b in (0, 2000, 5000, 15000, 30000, 60000)]
        assert costs == sorted(costs)

    def test_items_sorted_by_shortfall_descending(self, client):
        """Test priority ordering when the budget covers every item."""
        data = recommend(client, 1000000)
        shortfalls = [i["shortfall"] for i in data["items"]]
        assert shortfalls == sorted(shortfalls, reverse=True)

    def test_only_items_with_shortfall_recommended(self, client):
        """Test that SKUs with enough stock are excluded and quantities never exceed the shortfall."""
        data = recommend(client, 1000000)
        skus = [i["sku"] for i in data["items"]]
        # MTR-304 is decreasing demand and CTL-330 / PSU-501 have stock above forecast
        for sku in ("MTR-304", "CTL-330", "PSU-501"):
            assert sku not in skus
        for item in data["items"]:
            assert item["shortfall"] > 0
            assert 0 < item["recommended_qty"] <= item["shortfall"]

    def test_large_budget_covers_full_shortfall(self, client):
        """Test that a big enough budget buys every shortfall in full."""
        data = recommend(client, 1000000)
        assert abs(data["total_cost"] - data["full_shortfall_cost"]) < 0.01
        for item in data["items"]:
            assert item["recommended_qty"] == item["shortfall"]

    def test_partial_fill_when_item_does_not_fit(self, client):
        """Test that an item that does not fully fit is bought in a reduced quantity."""
        data = recommend(client, 15000)
        partial = [i for i in data["items"] if i["recommended_qty"] < i["shortfall"]]
        assert len(partial) == 1
        # The partial item is the one that ran the budget down: not even one more unit fits
        assert data["remaining_budget"] < partial[0]["unit_cost"]

    def test_lead_time_matches_category(self, client):
        """Test that lead times are per category (same category, same lead time)."""
        data = recommend(client, 1000000)
        by_category = {}
        for item in data["items"]:
            by_category.setdefault(item["category"], set()).add(item["lead_time_days"])
        assert all(len(days) == 1 for days in by_category.values())
        assert all(days.pop() > 0 for days in by_category.values())


class TestRestockOrders:
    """Test suite for POST/GET /api/restocking/orders."""

    def test_place_order(self, client):
        """Test submitting a recommended order."""
        rec = recommend(client, 15000)
        response = client.post("/api/restocking/orders", json=order_payload(rec))
        assert response.status_code == 201

        order = response.json()
        assert order["id"].startswith("RST-")
        assert order["status"] == "Submitted"
        assert len(order["items"]) == len(rec["items"])
        assert abs(order["total_cost"] - rec["total_cost"]) < 0.01

    def test_order_lead_time_is_max_of_items(self, client):
        """Test that the order lead time is the slowest item, and delivery date follows from it."""
        rec = recommend(client, 1000000)
        # Make sure the test is meaningful: items must have differing lead times
        assert len({i["lead_time_days"] for i in rec["items"]}) > 1

        order = client.post("/api/restocking/orders", json=order_payload(rec)).json()
        assert order["lead_time_days"] == max(i["lead_time_days"] for i in rec["items"])
        expected = date.today() + timedelta(days=order["lead_time_days"])
        assert order["expected_delivery"] == expected.isoformat()

    def test_subset_of_items_can_be_ordered(self, client):
        """Test that unchecked items can be left out and the lead time reflects only the rest."""
        rec = recommend(client, 1000000)
        slowest = max(rec["items"], key=lambda i: i["lead_time_days"])
        payload = order_payload(rec)
        payload["items"] = [i for i in payload["items"] if i["sku"] != slowest["sku"]]

        order = client.post("/api/restocking/orders", json=payload).json()
        assert slowest["sku"] not in [i["sku"] for i in order["items"]]
        assert order["lead_time_days"] <= slowest["lead_time_days"]

    def test_server_ignores_client_prices(self, client):
        """Test that the total is computed server-side from the catalog."""
        rec = recommend(client, 15000)
        payload = order_payload(rec)
        payload["items"][0]["unit_cost"] = 0.01  # extra field must not affect pricing
        order = client.post("/api/restocking/orders", json=payload).json()
        assert abs(order["total_cost"] - rec["total_cost"]) < 0.01

    def test_empty_order_rejected(self, client):
        """Test that an order with no items is rejected."""
        response = client.post("/api/restocking/orders", json={"budget": 1000, "items": []})
        assert response.status_code == 400

    def test_unknown_sku_rejected(self, client):
        """Test that an unknown SKU is rejected."""
        response = client.post(
            "/api/restocking/orders",
            json={"budget": 1000, "items": [{"sku": "NOPE-999", "quantity": 1}]},
        )
        assert response.status_code == 400
        assert "unknown sku" in response.json()["detail"].lower()

    @pytest.mark.parametrize("quantity", [0, -5])
    def test_non_positive_quantity_rejected(self, client, quantity):
        """Test that zero or negative quantities are rejected."""
        rec = recommend(client, 15000)
        sku = rec["items"][0]["sku"]
        response = client.post(
            "/api/restocking/orders",
            json={"budget": 15000, "items": [{"sku": sku, "quantity": quantity}]},
        )
        assert response.status_code == 400

    def test_duplicate_sku_rejected(self, client):
        """Test that the same SKU cannot appear twice."""
        rec = recommend(client, 15000)
        sku = rec["items"][0]["sku"]
        response = client.post(
            "/api/restocking/orders",
            json={"budget": 15000, "items": [{"sku": sku, "quantity": 1}, {"sku": sku, "quantity": 1}]},
        )
        assert response.status_code == 400

    def test_order_over_budget_rejected(self, client):
        """Test that an order costing more than the budget is rejected and not stored."""
        rec = recommend(client, 15000)
        response = client.post("/api/restocking/orders", json=order_payload(rec, budget=100))
        assert response.status_code == 400
        assert "exceeds budget" in response.json()["detail"].lower()
        assert client.get("/api/restocking/orders").json() == []

    def test_invalid_body_rejected(self, client):
        """Test Pydantic validation of the request body."""
        response = client.post("/api/restocking/orders", json={"items": []})
        assert response.status_code == 422

    def test_get_orders_empty(self, client):
        """Test that no orders exist before one is placed."""
        response = client.get("/api/restocking/orders")
        assert response.status_code == 200
        assert response.json() == []

    def test_get_orders_newest_first(self, client):
        """Test that submitted orders are listed newest first with unique ids."""
        rec = recommend(client, 15000)
        first = client.post("/api/restocking/orders", json=order_payload(rec)).json()
        second = client.post("/api/restocking/orders", json=order_payload(rec)).json()
        assert first["id"] != second["id"]

        orders = client.get("/api/restocking/orders").json()
        assert [o["id"] for o in orders] == [second["id"], first["id"]]

    def test_restock_orders_do_not_leak_into_regular_orders(self, client):
        """Test that /api/orders is unaffected by submitted restock orders."""
        before = len(client.get("/api/orders").json())
        rec = recommend(client, 15000)
        client.post("/api/restocking/orders", json=order_payload(rec))
        assert len(client.get("/api/orders").json()) == before
