"""Deterministic sample data generator for the fictional e-commerce database.

Populates customers, products, orders, and order_items with realistic,
reproducible data so the database is rich enough for meaningful SQL
analysis (revenue by category, top products, customer spending, monthly
trends, etc.) without requiring any external service or manual data entry.

Determinism
-----------
A fixed random seed (SEED) drives every random choice below, and orders are
spread across a fixed 12-month calendar window (YEAR) rather than relative
to "today". Re-running the generator therefore always produces byte-for-byte
identical rows, which keeps tests stable regardless of when they run.

Idempotency strategy
---------------------
Before inserting anything, the seeder checks whether the `customers` table
already has rows. If it does, seeding is skipped entirely and the function
returns without touching the database. This is intentionally simple: it
needs no extra bookkeeping table or "seed version" flag, and it is
sufficient because this seeder's only job is to populate a fresh database
once. To regenerate the dataset from scratch, delete the database file (or
delete rows from all four tables) and re-run the seeder.
"""

from __future__ import annotations

import calendar
import random
import sqlite3
from datetime import datetime

from database.init_db import get_connection, get_database_path, init_db

SEED = 42
YEAR = 2024

NUM_CUSTOMERS = 100
MIN_ORDERS = 500
MAX_ORDERS = 800

FIRST_NAMES = [
    "James", "Mary", "Robert", "Patricia", "John", "Jennifer", "Michael",
    "Linda", "William", "Elizabeth", "David", "Barbara", "Richard", "Susan",
    "Joseph", "Jessica", "Thomas", "Sarah", "Charles", "Karen", "Daniel",
    "Nancy", "Matthew", "Lisa", "Anthony", "Margaret", "Mark", "Betty",
    "Paul", "Sandra", "Steven", "Ashley", "Andrew", "Emily", "Kevin",
    "Kimberly", "Brian", "Donna", "George", "Michelle", "Edward", "Amanda",
    "Ronald", "Melissa", "Timothy", "Rebecca", "Jason", "Laura", "Jeffrey",
    "Stephanie",
]

LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
    "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez",
    "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin",
    "Lee", "Perez", "Thompson", "White", "Harris", "Sanchez", "Clark",
    "Ramirez", "Lewis", "Robinson", "Walker", "Young", "Allen", "King",
    "Wright", "Scott", "Torres", "Nguyen", "Hill", "Flores",
]

# (city, relative weight) — weights make some cities more common than
# others instead of an unrealistic uniform spread across customers.
CITIES = [
    ("New York", 14), ("Los Angeles", 12), ("Chicago", 10), ("Houston", 8),
    ("Phoenix", 6), ("Philadelphia", 6), ("San Antonio", 5), ("San Diego", 5),
    ("Dallas", 7), ("Austin", 6), ("Seattle", 8), ("Denver", 5),
    ("Boston", 6), ("Portland", 4), ("Miami", 7),
]

# (name, category, price, weight) — weight controls how often a product
# is picked for an order line, so some products clearly outsell others.
PRODUCTS = [
    ("Wireless Mouse", "Electronics", 24.99, 18),
    ("Mechanical Keyboard", "Electronics", 79.99, 10),
    ("USB-C Hub", "Electronics", 34.50, 14),
    ("Bluetooth Speaker", "Electronics", 49.99, 16),
    ("Noise Cancelling Headphones", "Electronics", 129.99, 20),
    ("1080p Webcam", "Electronics", 39.99, 7),
    ("Portable SSD 1TB", "Electronics", 89.99, 9),
    ("Ceramic Coffee Mug", "Home", 12.99, 12),
    ("Stainless Steel Water Bottle", "Home", 18.50, 15),
    ("LED Desk Lamp", "Home", 27.99, 9),
    ("Throw Blanket", "Home", 34.99, 6),
    ("Aroma Diffuser", "Home", 29.99, 8),
    ("Non-Stick Frying Pan", "Home", 42.00, 5),
    ("Notebook 3-Pack", "Office", 9.99, 11),
    ("Ergonomic Office Chair", "Office", 189.99, 17),
    ("Standing Desk Converter", "Office", 149.99, 13),
    ("Desk Organizer", "Office", 15.99, 7),
    ("Wireless Presenter", "Office", 22.50, 4),
    ("Whiteboard 24x36", "Office", 45.00, 3),
    ("Yoga Mat", "Sports", 21.99, 10),
    ("Adjustable Dumbbell Set", "Sports", 89.99, 15),
    ("Resistance Bands Set", "Sports", 15.99, 9),
    ("Running Shorts", "Sports", 19.99, 6),
    ("Water-Resistant Backpack", "Sports", 39.99, 8),
    ("Foam Roller", "Sports", 24.99, 4),
    ("Leather Wallet", "Accessories", 29.99, 8),
    ("Classic Sunglasses", "Accessories", 24.99, 9),
    ("Travel Duffel Bag", "Accessories", 54.99, 11),
    ("Phone Case", "Accessories", 14.99, 19),
    ("Analog Wrist Watch", "Accessories", 59.99, 12),
]

STATUSES = ["completed", "processing", "pending", "cancelled"]
STATUS_WEIGHTS = [62, 13, 12, 13]

# Relative order volume per calendar month (Jan..Dec) — a mild dip in
# late winter and a holiday-season spike in Nov/Dec, so monthly revenue
# is not flat.
MONTH_WEIGHTS = [7, 6, 7, 8, 8, 9, 8, 8, 9, 10, 13, 15]

ITEMS_PER_ORDER_CHOICES = [1, 2, 3, 4, 5]
ITEMS_PER_ORDER_WEIGHTS = [35, 30, 20, 10, 5]

QUANTITY_CHOICES = [1, 2, 3]
QUANTITY_WEIGHTS = [70, 22, 8]

# Small, simple discount model applied at the moment of sale so
# order_items.unit_price reflects realistic historical pricing without
# a full price-history table.
DISCOUNT_CHOICES = [1.0, 0.95, 0.90]
DISCOUNT_WEIGHTS = [80, 15, 5]


def _database_has_data(connection: sqlite3.Connection) -> bool:
    """Return True if the customers table already has at least one row."""
    row = connection.execute("SELECT COUNT(*) FROM customers").fetchone()
    return row[0] > 0


def _random_datetime(rng: random.Random, month: int) -> str:
    """Return a random 'YYYY-MM-DD HH:MM:SS' timestamp within YEAR/month."""
    last_day = calendar.monthrange(YEAR, month)[1]
    day = rng.randint(1, last_day)
    hour = rng.randint(8, 21)
    minute = rng.randint(0, 59)
    second = rng.randint(0, 59)
    return datetime(YEAR, month, day, hour, minute, second).strftime(
        "%Y-%m-%d %H:%M:%S"
    )


def _generate_customers(rng: random.Random) -> list[tuple[str, str, str, str]]:
    """Build NUM_CUSTOMERS (first_name, last_name, email, city) rows."""
    cities = [city for city, _ in CITIES]
    city_weights = [weight for _, weight in CITIES]

    customers = []
    for i in range(1, NUM_CUSTOMERS + 1):
        first = rng.choice(FIRST_NAMES)
        last = rng.choice(LAST_NAMES)
        city = rng.choices(cities, weights=city_weights, k=1)[0]
        # Index suffix guarantees uniqueness even when a name repeats,
        # which is expected and realistic with only ~90 unique names.
        email = f"{first.lower()}.{last.lower()}{i}@example.com"
        customers.append((first, last, email, city))
    return customers


def _generate_products() -> list[tuple[str, str, float, int]]:
    """Build (name, category, price, stock) rows from the PRODUCTS catalog.

    Stock is derived deterministically from each product's popularity
    weight (bestsellers keep more stock on hand) instead of pure
    randomness, which keeps the catalog simple and reproducible.
    """
    products = []
    for name, category, price, weight in PRODUCTS:
        stock = 20 + weight * 8
        products.append((name, category, price, stock))
    return products


def _weighted_sample_without_replacement(
    rng: random.Random, population: list, weights: list[int], k: int
) -> list:
    """Pick up to k distinct items from population, honoring weights.

    random.choices() samples with replacement, which would let the same
    product appear twice on one order and violate the
    UNIQUE (order_id, product_id) constraint on order_items. The pool is
    small (30 products, at most 5 picks), so removing the chosen item and
    re-drawing is simple and fast enough.
    """
    pool = list(zip(population, weights))
    chosen = []
    for _ in range(min(k, len(pool))):
        items, item_weights = zip(*pool)
        pick = rng.choices(items, weights=item_weights, k=1)[0]
        chosen.append(pick)
        pool = [(item, w) for item, w in pool if item is not pick]
    return chosen


def _generate_orders_and_items(
    rng: random.Random,
    customer_ids: list[int],
    product_rows: list[tuple[int, str, str, float, int]],
) -> tuple[list[tuple[int, str, str]], list[tuple[int, int, int, float]]]:
    """Build order rows and their order_items rows.

    product_rows is a list of (id, name, category, price, weight) so
    popularity weighting can drive which products get picked.
    """
    num_orders = rng.randint(MIN_ORDERS, MAX_ORDERS)

    # ~15% of customers are frequent buyers with a much higher chance of
    # being picked for any given order, so order counts per customer are
    # not uniform.
    customer_weights = []
    for _ in customer_ids:
        weight = 1.0
        if rng.random() < 0.15:
            weight *= rng.uniform(3, 6)
        customer_weights.append(weight)

    product_ids = [row[0] for row in product_rows]
    product_prices = {row[0]: row[3] for row in product_rows}
    product_weights = [row[4] for row in product_rows]

    orders = []
    order_items = []
    for order_id in range(1, num_orders + 1):
        customer_id = rng.choices(customer_ids, weights=customer_weights, k=1)[0]
        month = rng.choices(range(1, 13), weights=MONTH_WEIGHTS, k=1)[0]
        order_date = _random_datetime(rng, month)
        status = rng.choices(STATUSES, weights=STATUS_WEIGHTS, k=1)[0]
        orders.append((customer_id, order_date, status))

        num_items = rng.choices(
            ITEMS_PER_ORDER_CHOICES, weights=ITEMS_PER_ORDER_WEIGHTS, k=1
        )[0]
        chosen_product_ids = _weighted_sample_without_replacement(
            rng, product_ids, product_weights, num_items
        )
        for product_id in chosen_product_ids:
            quantity = rng.choices(
                QUANTITY_CHOICES, weights=QUANTITY_WEIGHTS, k=1
            )[0]
            discount = rng.choices(
                DISCOUNT_CHOICES, weights=DISCOUNT_WEIGHTS, k=1
            )[0]
            unit_price = round(product_prices[product_id] * discount, 2)
            order_items.append((order_id, product_id, quantity, unit_price))

    return orders, order_items


def seed_database(database_path: str | None = None, seed: int = SEED) -> bool:
    """Populate the database with deterministic sample data.

    Returns True if data was inserted, False if seeding was skipped
    because the database already contained data (see the idempotency
    strategy documented at the top of this module).
    """
    database_path = database_path or get_database_path()
    init_db(database_path)

    connection = get_connection(database_path)
    try:
        if _database_has_data(connection):
            return False

        rng = random.Random(seed)

        customers = _generate_customers(rng)
        connection.executemany(
            "INSERT INTO customers (first_name, last_name, email, city) "
            "VALUES (?, ?, ?, ?)",
            customers,
        )
        # Tables were confirmed empty above, so AUTOINCREMENT ids are
        # assigned sequentially starting at 1, matching insertion order.
        customer_ids = list(range(1, len(customers) + 1))

        products = _generate_products()
        connection.executemany(
            "INSERT INTO products (name, category, price, stock) "
            "VALUES (?, ?, ?, ?)",
            products,
        )
        product_rows = [
            (index, name, category, price, PRODUCTS[index - 1][3])
            for index, (name, category, price, _stock) in enumerate(products, start=1)
        ]

        orders, order_items = _generate_orders_and_items(
            rng, customer_ids, product_rows
        )
        connection.executemany(
            "INSERT INTO orders (customer_id, order_date, status) "
            "VALUES (?, ?, ?)",
            orders,
        )
        connection.executemany(
            "INSERT INTO order_items (order_id, product_id, quantity, unit_price) "
            "VALUES (?, ?, ?, ?)",
            order_items,
        )

        connection.commit()
        return True
    finally:
        connection.close()


if __name__ == "__main__":
    path = get_database_path()
    inserted = seed_database(path)
    if inserted:
        print(f"Seeded sample data into: {path}")
    else:
        print(f"Database already contains data; skipped seeding: {path}")
