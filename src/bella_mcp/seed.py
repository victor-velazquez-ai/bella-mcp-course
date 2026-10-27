"""Builds Brightline Outdoor's demo database (data/bella.db).

Brightline Outdoor is a fictional outdoor-gear retailer. The data is synthetic and
deterministic (fixed random seed), so every student gets exactly the same numbers
and the demo questions always have the same answers.
"""

from __future__ import annotations

import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path

START = date(2025, 1, 1)
AS_OF = date(2026, 9, 30)  # "today" inside the dataset

REGIONS = {
    "North America": {"United States": ["Denver", "Seattle", "Austin", "Boston"], "Canada": ["Vancouver", "Toronto", "Calgary"]},
    "Europe": {"Germany": ["Munich", "Berlin"], "France": ["Lyon", "Paris"], "Spain": ["Barcelona", "Madrid"],
               "United Kingdom": ["Manchester", "London"], "Italy": ["Turin", "Milan"]},
    "LATAM": {"Mexico": ["Mexico City", "Monterrey", "Guadalajara"], "Chile": ["Santiago"],
              "Colombia": ["Bogotá", "Medellín"], "Brazil": ["São Paulo", "Curitiba"]},
    "APAC": {"Japan": ["Tokyo", "Sapporo"], "Australia": ["Sydney", "Melbourne"], "New Zealand": ["Queenstown", "Auckland"]},
}
REGION_WEIGHTS = {"North America": 40, "Europe": 28, "LATAM": 20, "APAC": 12}

CATALOG = {
    "Tents": (["Summit 2P Tent", "Basecamp 4P Tent", "Ridgeline Ultralight Tent", "Storm Shelter 3P", "Family Dome 6P",
               "Bivy Pro", "Trailhead 1P Tent", "Expedition 4-Season Tent"], (149, 799)),
    "Backpacks": (["Trailblazer 45L", "Daypack 22L", "Ascent 65L", "Commuter 18L", "Thru-Hiker 55L", "Kids Explorer 15L",
                   "Hydration Vest 8L", "Alpine Attack 35L"], (49, 329)),
    "Footwear": (["Granite Mid Boot", "Trail Runner X", "Approach Shoe", "Winter Hiker GTX", "Camp Slide",
                  "Mountaineering Boot", "Fastpack Low", "Water Shoe"], (39, 389)),
    "Apparel": (["Storm Shell Jacket", "Down Puffy", "Merino Base Layer", "Softshell Pant", "Fleece Hoodie",
                 "Sun Hoodie", "Rain Pant", "Insulated Vest"], (35, 349)),
    "Climbing": (["Dynamic Rope 60m", "Harness Pro", "Quickdraw Set", "Helmet Shield", "Belay Device",
                  "Chalk Bag", "Crash Pad", "Climbing Shoe V2"], (19, 279)),
    "Camp Kitchen": (["Titan Stove", "Cookset Duo", "Insulated Mug", "Water Filter", "Camp Chair",
                      "Cooler 45QT", "Spork Set", "Lantern 400"], (12, 299)),
}
# Seasonality: spring/summer peak, holiday bump.
MONTH_WEIGHT = {1: 0.7, 2: 0.75, 3: 0.95, 4: 1.1, 5: 1.25, 6: 1.35, 7: 1.4, 8: 1.25, 9: 1.0, 10: 0.85, 11: 1.05, 12: 1.2}

FIRST = ["Ana", "Liam", "Sofía", "Noah", "Emma", "Mateo", "Olivia", "Lucas", "Mia", "Hiro", "Chloe", "Diego", "Isla",
         "Marco", "Yuki", "Elena", "Jack", "Valentina", "Leo", "Camila", "Finn", "Aiko", "Lena", "Tomás", "Grace", "Arjun"]
LAST = ["García", "Smith", "Müller", "Rossi", "Tanaka", "Martin", "López", "Brown", "Silva", "Dubois", "Walker",
        "Sato", "Fernández", "Taylor", "Schmidt", "Moreau", "Kelly", "Ramírez", "Nguyen", "Costa", "Wilson", "Ito"]
COMPANY_A = ["Alpine", "Summit", "Cascade", "Andes", "Fjord", "Sierra", "Granite", "Coastal", "Maple", "Aurora",
             "Pacific", "Highland", "Canyon", "Glacier", "Redwood", "Patagonia Trail"]
COMPANY_B = ["Outfitters", "Expeditions", "Logistics", "Adventure Co.", "Guides", "Supply", "Mountain School",
             "Rentals", "Tours", "Gear Hub"]

REPS = [("Hannah Cole", "North America"), ("Marcus Reed", "North America"), ("Clara Vogel", "Europe"),
        ("Julien Arnaud", "Europe"), ("Lucía Navarro", "LATAM"), ("Rafael Duarte", "LATAM"),
        ("Kenji Mori", "APAC"), ("Zoe Harper", "APAC")]

SCHEMA = """
CREATE TABLE sales_reps (
    rep_id      INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    region      TEXT NOT NULL,
    email       TEXT NOT NULL
);
CREATE TABLE customers (
    customer_id INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    email       TEXT NOT NULL UNIQUE,
    segment     TEXT NOT NULL CHECK (segment IN ('Consumer', 'SMB', 'Enterprise')),
    country     TEXT NOT NULL,
    city        TEXT NOT NULL,
    signup_date TEXT NOT NULL
);
CREATE TABLE products (
    product_id    INTEGER PRIMARY KEY,
    sku           TEXT NOT NULL UNIQUE,
    name          TEXT NOT NULL,
    category      TEXT NOT NULL,
    unit_price    REAL NOT NULL,
    unit_cost     REAL NOT NULL,
    stock_qty     INTEGER NOT NULL,
    reorder_level INTEGER NOT NULL
);
CREATE TABLE orders (
    order_id    INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(customer_id),
    rep_id      INTEGER NOT NULL REFERENCES sales_reps(rep_id),
    order_date  TEXT NOT NULL,
    status      TEXT NOT NULL CHECK (status IN ('completed', 'shipped', 'pending', 'cancelled', 'refunded')),
    channel     TEXT NOT NULL CHECK (channel IN ('web', 'store', 'partner'))
);
CREATE TABLE order_items (
    order_id   INTEGER NOT NULL REFERENCES orders(order_id),
    product_id INTEGER NOT NULL REFERENCES products(product_id),
    quantity   INTEGER NOT NULL,
    unit_price REAL NOT NULL,
    discount   REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (order_id, product_id)
);
CREATE TABLE dataset_info (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE INDEX idx_orders_date ON orders(order_date);
CREATE INDEX idx_orders_customer ON orders(customer_id);
CREATE INDEX idx_items_product ON order_items(product_id);

-- The semantic layer: the ONE agreed definition of revenue.
-- Only completed + shipped orders count; revenue is net of line discounts.
CREATE VIEW sales AS
SELECT o.order_id, o.order_date, substr(o.order_date, 1, 7) AS month,
       o.customer_id, c.segment, c.country, r.region, o.rep_id, o.channel,
       oi.product_id, p.category, oi.quantity,
       ROUND(oi.quantity * oi.unit_price * (1 - oi.discount), 2) AS revenue,
       ROUND(oi.quantity * p.unit_cost, 2) AS cost,
       ROUND(oi.quantity * oi.unit_price * (1 - oi.discount) - oi.quantity * p.unit_cost, 2) AS margin
FROM orders o
JOIN order_items oi ON oi.order_id = o.order_id
JOIN products p     ON p.product_id = oi.product_id
JOIN customers c    ON c.customer_id = o.customer_id
JOIN sales_reps r   ON r.rep_id = o.rep_id
WHERE o.status IN ('completed', 'shipped');
"""


def _slug(text: str) -> str:
    table = str.maketrans("áéíóúüñçãâ", "aeiouuncaa")
    return "".join(ch for ch in text.lower().translate(table) if ch.isalnum())


def build_database(path: Path, seed: int = 42) -> Path:
    """Create (or recreate) the demo database at `path`."""
    rnd = random.Random(seed)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)

    for i, (name, region) in enumerate(REPS, start=1):
        first, last = name.lower().split()
        conn.execute("INSERT INTO sales_reps VALUES (?,?,?,?)", (i, name, region, f"{_slug(first)}.{_slug(last)}@brightline.example"))
    reps_by_region = {r: [i for i, (_, reg) in enumerate(REPS, start=1) if reg == r] for r in REGIONS}

    # Products: prices inside each category's band, a handful deliberately below reorder level.
    product_rows = []
    pid = 0
    for category, (names, (lo, hi)) in CATALOG.items():
        for name in names:
            pid += 1
            price = round(rnd.uniform(lo, hi) / 5) * 5 - 0.01
            cost = round(price * rnd.uniform(0.42, 0.62), 2)
            reorder = rnd.choice([20, 25, 30, 40, 50])
            stock = rnd.randint(reorder + 15, 420)
            product_rows.append([pid, f"BL-{category[:3].upper()}-{pid:03d}", name, category, price, cost, stock, reorder])
    for row in rnd.sample(product_rows, 7):  # the inventory alerts the demo will find
        row[6] = rnd.randint(0, row[7])
    conn.executemany("INSERT INTO products VALUES (?,?,?,?,?,?,?,?)", product_rows)

    # Customers: people for Consumer, companies for SMB/Enterprise.
    customers = []
    used_emails: set[str] = set()
    for cid in range(1, 321):
        region = rnd.choices(list(REGION_WEIGHTS), weights=list(REGION_WEIGHTS.values()))[0]
        country = rnd.choice(list(REGIONS[region]))
        city = rnd.choice(REGIONS[region][country])
        segment = rnd.choices(["Consumer", "SMB", "Enterprise"], weights=[70, 22, 8])[0]
        if segment == "Consumer":
            name = f"{rnd.choice(FIRST)} {rnd.choice(LAST)}"
            local, domain = ".".join(_slug(p) for p in name.split()), rnd.choice(["example.com", "example.org", "example.net"])
        else:
            name = f"{rnd.choice(COMPANY_A)} {rnd.choice(COMPANY_B)}"
            if segment == "Enterprise":
                name += rnd.choice([" GmbH", " SA", " Inc.", " Ltd.", " S.A. de C.V.", " KK"])
            local, domain = rnd.choice(["purchasing", "orders", "ops", "hello"]), _slug(name)[:18] + ".example"
        email = f"{local}@{domain}"
        while email in used_emails:
            email = f"{local}{rnd.randint(2, 99)}@{domain}"
        used_emails.add(email)
        signup = START - timedelta(days=rnd.randint(0, 900)) if rnd.random() < 0.6 else START + timedelta(days=rnd.randint(0, 560))
        customers.append((cid, name, email, segment, country, city, signup.isoformat(), region))
    conn.executemany("INSERT INTO customers VALUES (?,?,?,?,?,?,?)", [c[:7] for c in customers])

    # Orders: seasonality, ~20% year-over-year growth, bigger baskets for business customers.
    prices = {r[0]: r[4] for r in product_rows}
    order_id = 0
    day = START
    while day <= AS_OF:
        growth = 1.0 + 0.2 * ((day - START).days / 365)
        n_orders = int(rnd.gauss(7.5 * MONTH_WEIGHT[day.month] * growth, 1.6))
        for _ in range(max(n_orders, 0)):
            cust = rnd.choice(customers)
            if date.fromisoformat(cust[6]) > day:
                continue
            order_id += 1
            segment, region = cust[3], cust[7]
            age = (AS_OF - day).days
            if age <= 10:
                status = rnd.choices(["pending", "shipped", "cancelled"], weights=[55, 40, 5])[0]
            elif age <= 25:
                status = rnd.choices(["shipped", "completed", "cancelled"], weights=[45, 50, 5])[0]
            else:
                status = rnd.choices(["completed", "cancelled", "refunded"], weights=[88, 7, 5])[0]
            channel = rnd.choices(["web", "store", "partner"],
                                  weights=[45, 15, 40] if segment == "Enterprise" else [58, 32, 10])[0]
            conn.execute("INSERT INTO orders VALUES (?,?,?,?,?,?)",
                         (order_id, cust[0], rnd.choice(reps_by_region[region]), day.isoformat(), status, channel))
            qty_range = {"Consumer": (1, 2), "SMB": (2, 8), "Enterprise": (6, 30)}[segment]
            for product_id in rnd.sample(list(prices), rnd.choice([1, 1, 2, 2, 3, 4])):
                discount = 0.0 if segment == "Consumer" else rnd.choice([0.0, 0.05, 0.1, 0.15])
                conn.execute("INSERT INTO order_items VALUES (?,?,?,?,?)",
                             (order_id, product_id, rnd.randint(*qty_range), prices[product_id], discount))
        day += timedelta(days=1)

    conn.executemany("INSERT INTO dataset_info VALUES (?,?)", [
        ("company", "Brightline Outdoor (fictional outdoor-gear retailer)"),
        ("as_of_date", AS_OF.isoformat()),
        ("data_from", START.isoformat()),
        ("currency", "USD"),
    ])
    conn.commit()
    conn.close()
    return path


def ensure_database(path: Path) -> Path:
    """Build the database on first use so `python -m bella_mcp` just works."""
    return path if path.exists() else build_database(path)
