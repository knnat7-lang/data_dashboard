
import os
from decimal import Decimal, InvalidOperation

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError


# ==================================================
# 1. LOAD ENVIRONMENT VARIABLES
# ==================================================

load_dotenv()


# ==================================================
# 2. DATABASE CONNECTION
# ==================================================

def get_engine():
    """
    Create and return a SQLAlchemy engine.
    Read DATABASE_URL from .env.
    """

    url = os.getenv("DATABASE_URL")

    if not url:
        raise ValueError(
            "DATABASE_URL not found. Check your .env file."
        )

    engine = create_engine(
        url,
        echo=False,
        pool_pre_ping=True
    )

    # Test database connection
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))

    print("Database connection successful!")

    return engine


# ==================================================
# 3. STORE REPORT
# ==================================================

def store_report(engine):
    """
    Display store statistics, catalog,
    and top 3 customers.
    """

    print("\n" + "=" * 45)
    print("           STORE DASHBOARD")
    print("=" * 45)

    with engine.connect() as conn:

        # ------------------------------------------
        # 3.1 COUNT USERS
        # ------------------------------------------

        users_count = conn.execute(
            text("SELECT COUNT(*) FROM users")
        ).scalar_one()

        # ------------------------------------------
        # 3.2 COUNT PRODUCTS
        # ------------------------------------------

        products_count = conn.execute(
            text("SELECT COUNT(*) FROM products")
        ).scalar_one()

        # ------------------------------------------
        # 3.3 COUNT ORDERS
        # ------------------------------------------

        orders_count = conn.execute(
            text("SELECT COUNT(*) FROM orders")
        ).scalar_one()

        print("\nSTORE STATISTICS")
        print("-" * 45)

        print(f"Users:    {users_count}")
        print(f"Products: {products_count}")
        print(f"Orders:   {orders_count}")

        # ------------------------------------------
        # 3.4 PRODUCT CATALOG
        # ------------------------------------------

        products = conn.execute(
            text("""
                SELECT name, category, price, stock
                FROM products
                ORDER BY name
            """)
        ).mappings().all()

        print("\nPRODUCT CATALOG")
        print("-" * 45)

        if products:
            for product in products:
                print(
                    f"{product['name']:<18} "
                    f"${product['price']:>8.2f} "
                    f"Stock: {product['stock']}"
                )
        else:
            print("No products found.")

        # ------------------------------------------
        # 3.5 TOP 3 CUSTOMERS
        # ------------------------------------------

        top_customers = conn.execute(
            text("""
                SELECT
                    users.email,
                    SUM(orders.quantity) AS total_items

                FROM users

                JOIN orders
                    ON users.id = orders.user_id

                GROUP BY users.id, users.email

                ORDER BY total_items DESC

                LIMIT 3
            """)
        ).mappings().all()

        print("\nTOP 3 CUSTOMERS")
        print("-" * 45)

        if top_customers:
            for customer in top_customers:
                print(
                    f"{customer['email']:<25}"
                    f"{customer['total_items']} items"
                )
        else:
            print("No orders found.")

        # ------------------------------------------
        # 3.6 LOW STOCK PRODUCTS
        # ------------------------------------------

        low_stock = conn.execute(
            text("""
                SELECT name, stock
                FROM products
                WHERE stock < 10
                ORDER BY stock ASC
            """)
        ).mappings().all()

        print("\nLOW STOCK PRODUCTS")
        print("-" * 45)

        if low_stock:
            for product in low_stock:
                print(
                    f"{product['name']}: "
                    f"{product['stock']} left"
                )
        else:
            print("All products have sufficient stock.")

        # ------------------------------------------
        # 3.7 REVENUE BY PRODUCT
        # ------------------------------------------

        revenue = conn.execute(
            text("""
                SELECT
                    products.name,
                    SUM(products.price * orders.quantity)
                        AS total_revenue

                FROM products

                JOIN orders
                    ON products.id = orders.product_id

                GROUP BY products.id, products.name

                ORDER BY total_revenue DESC
            """)
        ).mappings().all()

        print("\nREVENUE BY PRODUCT")
        print("-" * 45)

        if revenue:
            for item in revenue:
                print(
                    f"{item['name']:<20}"
                    f"${item['total_revenue']:,.2f}"
                )
        else:
            print("No revenue data found.")

        # ------------------------------------------
        # 3.8 USERS WITHOUT ORDERS
        # ------------------------------------------

        users_without_orders = conn.execute(
            text("""
                SELECT
                    users.id,
                    users.email

                FROM users

                LEFT JOIN orders
                    ON users.id = orders.user_id

                WHERE orders.id IS NULL

                ORDER BY users.id
            """)
        ).mappings().all()

        print("\nUSERS WITHOUT ORDERS")
        print("-" * 45)

        if users_without_orders:
            for user in users_without_orders:
                print(user["email"])
        else:
            print("All users have placed orders.")

    print("\n" + "=" * 45)


# ==================================================
# 4. ADD PRODUCT
# ==================================================

def add_product(engine, name, category, price, stock):
    """
    Insert a new product into the database.
    Return its generated ID.
    """

    with engine.begin() as conn:

        result = conn.execute(
            text("""
                INSERT INTO products
                    (name, category, price, stock)

                VALUES
                    (:name, :category, :price, :stock)

                RETURNING id
            """),
            {
                "name": name,
                "category": category,
                "price": price,
                "stock": stock
            }
        )

        product_id = result.scalar_one()

    print("\nProduct added successfully!")
    print(f"New product ID: {product_id}")

    return product_id


# ==================================================
# 5. PLACE ORDER
# ==================================================

def place_order(engine, email, product_name, quantity):
    """
    Create an order and decrease product stock.
    Both operations happen in one transaction.
    """

    if quantity <= 0:
        raise ValueError("Quantity must be greater than zero.")

    with engine.begin() as conn:

        # ------------------------------------------
        # 5.1 FIND USER
        # ------------------------------------------

        user = conn.execute(
            text("""
                SELECT id
                FROM users
                WHERE email = :email
            """),
            {
                "email": email
            }
        ).mappings().first()

        if user is None:
            raise ValueError("User not found.")

        user_id = user["id"]

        # ------------------------------------------
        # 5.2 FIND PRODUCT AND LOCK ITS ROW
        # ------------------------------------------

        product = conn.execute(
            text("""
                SELECT id, name, stock
                FROM products
                WHERE name = :product_name
                FOR UPDATE
            """),
            {
                "product_name": product_name
            }
        ).mappings().first()

        if product is None:
            raise ValueError("Product not found.")

        product_id = product["id"]
        current_stock = product["stock"]

        # ------------------------------------------
        # 5.3 CHECK STOCK
        # ------------------------------------------

        if current_stock < quantity:
            raise ValueError(
                f"Not enough stock! "
                f"Available: {current_stock}, "
                f"Requested: {quantity}"
            )

        # ------------------------------------------
        # 5.4 INSERT ORDER
        # ------------------------------------------

        result = conn.execute(
            text("""
                INSERT INTO orders
                    (user_id, product_id, quantity, status)

                VALUES
                    (:user_id, :product_id, :quantity, :status)

                RETURNING id
            """),
            {
                "user_id": user_id,
                "product_id": product_id,
                "quantity": quantity,
                "status": "pending"
            }
        )

        order_id = result.scalar_one()

        # ------------------------------------------
        # 5.5 DECREASE PRODUCT STOCK
        # ------------------------------------------

        conn.execute(
            text("""
                UPDATE products

                SET stock = stock - :quantity

                WHERE id = :product_id
            """),
            {
                "quantity": quantity,
                "product_id": product_id
            }
        )

    # Transaction commits automatically here.

    print("\nOrder created successfully!")
    print(f"Order ID: {order_id}")
    print(f"Customer: {email}")
    print(f"Product: {product_name}")
    print(f"Quantity: {quantity}")
    print(f"Remaining stock: {current_stock - quantity}")

    return order_id


# ==================================================
# 6. INPUT VALIDATION
# ==================================================

def get_price():
    """
    Ask the user for a valid positive price.
    """

    while True:
        try:
            price = Decimal(input("Enter price: "))

            if not price.is_finite() or price <= 0:
                print("Price must be a positive number.")
                continue

            return price

        except InvalidOperation:
            print("Please enter a valid price.")


def get_positive_integer(message):
    """
    Ask the user for a positive integer.
    """

    while True:
        try:
            value = int(input(message))

            if value <= 0:
                print("Enter a number greater than zero.")
                continue

            return value

        except ValueError:
            print("Please enter a valid integer.")


# ==================================================
# 7. ADD PRODUCT MENU
# ==================================================

def add_product_menu(engine):

    print("\nADD NEW PRODUCT")
    print("-" * 30)

    name = input("Product name: ").strip()

    category = input("Category: ").strip()

    if not name or not category:
        print("Name and category are required.")
        return

    price = get_price()

    stock = get_positive_integer("Stock: ")

    add_product(
        engine,
        name,
        category,
        price,
        stock
    )


# ==================================================
# 8. PLACE ORDER MENU
# ==================================================

def place_order_menu(engine):

    print("\nCREATE NEW ORDER")
    print("-" * 30)

    email = input("Customer email: ").strip()

    product_name = input("Product name: ").strip()

    quantity = get_positive_integer("Quantity: ")

    if not email or not product_name:
        print("Email and product name are required.")
        return

    place_order(
        engine,
        email,
        product_name,
        quantity
    )


# ==================================================
# 9. MAIN MENU
# ==================================================

def main():

    try:

        # Connect to database
        engine = get_engine()

        # Display initial report
        store_report(engine)

        while True:

            print("\n" + "=" * 35)
            print("          MAIN MENU")
            print("=" * 35)

            print("1. Show store report")
            print("2. Add product")
            print("3. Place order")
            print("4. Exit")

            choice = input("\nChoose an option: ").strip()

            try:

                if choice == "1":

                    store_report(engine)

                elif choice == "2":

                    add_product_menu(engine)

                elif choice == "3":

                    place_order_menu(engine)

                elif choice == "4":

                    print("Goodbye!")
                    break

                else:

                    print("Invalid option. Choose 1-4.")

            except (ValueError, SQLAlchemyError) as error:

                print(f"\nOperation failed: {error}")

    except (ValueError, SQLAlchemyError) as error:

        print(f"\nDatabase error: {error}")

    except KeyboardInterrupt:

        print("\nProgram interrupted.")

    finally:

        if "engine" in locals():
            engine.dispose()


# ==================================================
# 10. PROGRAM ENTRY POINT
# ==================================================

if __name__ == "__main__":
    main()
