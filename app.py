import os
import uuid

from dotenv import load_dotenv
from authlib.integrations.flask_client import OAuth
from flask import (
    Flask,
    render_template,
    redirect,
    url_for,
    session,
    request,
    flash,
    jsonify,
)

from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

from itsdangerous import (
    URLSafeTimedSerializer,
    BadSignature,
    SignatureExpired,
)

from models import db, Product, User, Order


# ==========================================
# APPLICATION CONFIGURATION
# ==========================================
load_dotenv()

app = Flask(__name__)

app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY")

if not app.config["SECRET_KEY"]:
    raise RuntimeError("SECRET_KEY is missing from your environment.")

database_url = os.environ.get("DATABASE_URL")

if database_url:
    if database_url.startswith("postgres://"):
        database_url = database_url.replace(
            "postgres://", "postgresql+psycopg2://", 1
        )
    elif database_url.startswith("postgresql://"):
        database_url = database_url.replace(
            "postgresql://", "postgresql+psycopg2://", 1
        )

    app.config["SQLALCHEMY_DATABASE_URI"] = database_url
else:
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///shop.db"

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False


app.config["ADMIN_EMAIL"] = os.environ.get(
    "ADMIN_EMAIL", ""
).strip().lower()

app.config["UPLOAD_FOLDER"] = os.path.join(
    app.root_path,
    "static",
    "images"
)

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}

db.init_app(app)
# Google OAuth configuration
oauth = OAuth(app)

google = oauth.register(
    name="google",
    client_id=os.environ.get("GOOGLE_CLIENT_ID"),
    client_secret=os.environ.get("GOOGLE_CLIENT_SECRET"),
    server_metadata_url=(
        "https://accounts.google.com/.well-known/openid-configuration"
    ),
    client_kwargs={
        "scope": "openid email profile"
    }
)


# ==========================================
# DATABASE INITIALIZATION
# ==========================================

with app.app_context():
    db.create_all()
    # Auto-fix old DB missing columns
    try:
        from sqlalchemy import inspect, text
        inspector = inspect(db.engine)
        if 'order' in inspector.get_table_names():
            cols = [c['name'] for c in inspector.get_columns('order')]
            if 'user_id' not in cols:
                with db.engine.connect() as conn:
                    conn.execute(text('ALTER TABLE "order" ADD COLUMN user_id INTEGER'))
                    conn.commit()
                print("FIXED: Added user_id column to order table")
            if 'status' not in cols:
                with db.engine.connect() as conn:
                    conn.execute(text('ALTER TABLE "order" ADD COLUMN status VARCHAR(20) DEFAULT "Pending"'))
                    conn.commit()
                print("FIXED: Added status column to order table")
    except Exception as e:
        print(f"Migration check failed: {e}")


# ==========================================
# HELPER FUNCTIONS
# ==========================================

def current_user():
    user_id = session.get("user_id")

    if not user_id:
        return None

    return db.session.get(User, user_id)


def is_admin():
    user = current_user()

    if user is None:
        return False

    return (
        user.email.lower()
        == app.config["ADMIN_EMAIL"].lower()
    )


@app.context_processor
def inject_admin_status():
    return {"is_admin": is_admin}

@app.route('/googledc57c5c4d08a9272.html')
def google_verify():
    return "google-site-verification: googledc57c5c4d08a9272.html"

def password_reset_serializer():
    return URLSafeTimedSerializer(
        app.config["SECRET_KEY"]
    )


def save_image(image):
    if not image or not image.filename:
        return None

    if "." not in image.filename:
        return None

    extension = image.filename.rsplit(".", 1)[1].lower()

    if extension not in ALLOWED_EXTENSIONS:
        return None

    os.makedirs(
        app.config["UPLOAD_FOLDER"],
        exist_ok=True
    )

    filename = secure_filename(
        f"{uuid.uuid4().hex}.{extension}"
    )

    image.save(
        os.path.join(
            app.config["UPLOAD_FOLDER"],
            filename
        )
    )

    return filename


def get_cart_products():
    cart_items = session.get("cart", {})
    products = []
    total = 0

    for product_id, quantity in cart_items.items():
        try:
            product_id = int(product_id)
            quantity = int(quantity)
        except (ValueError, TypeError):
            continue

        if quantity < 1:
            continue

        product = db.session.get(Product, product_id)

        if product:
            subtotal = product.price * quantity

            products.append({
                "product": product,
                "quantity": quantity,
                "subtotal": subtotal,
            })

            total += subtotal

    return products, total


# ==========================================
# HOME PAGE
# ==========================================

@app.route("/")
def home():
    products = Product.query.order_by(
        Product.id.desc()
    ).all()

    return render_template(
        "index.html",
        products=products
    )


# ==========================================
# SHOP PAGE
# ==========================================

@app.route("/shop")
def shop():
    search = request.args.get("q", "").strip()

    query = Product.query

    if search:
        query = query.filter(
            Product.name.ilike(f"%{search}%")
        )

    products = query.order_by(
        Product.id.desc()
    ).all()

    return render_template(
        "shop.html",
        products=products,
        search=search
    )


# ==========================================
# CATEGORIES
# ==========================================

@app.route("/categories")
def categories():
    products = Product.query.order_by(
        Product.id.desc()
    ).all()

    return render_template(
        "categories.html",
        products=products
    )


# ==========================================
# SHOPPING CART
# ==========================================

@app.route("/cart")
def cart():
    products, total = get_cart_products()

    return render_template(
        "cart.html",
        products=products,
        total=total
    )


@app.route(
    "/add-to-cart/<int:product_id>",
    methods=["POST", "GET"]
)
def add_to_cart(product_id):
    product = db.session.get(Product, product_id)

    is_ajax = (
        request.headers.get("X-Requested-With")
        == "XMLHttpRequest"
    )

    if not product:
        if is_ajax:
            return jsonify({
                "success": False,
                "message": "Product not found."
            }), 404

        flash("Product not found.")
        return redirect(url_for("shop"))

    cart_items = session.get("cart", {})
    key = str(product_id)

    try:
        quantity = int(cart_items.get(key, 0))
    except (ValueError, TypeError):
        quantity = 0

    cart_items[key] = max(0, quantity) + 1

    session["cart"] = cart_items
    session.modified = True

    if is_ajax:
        return jsonify({
            "success": True,
            "message": f"{product.name} added to your cart."
        })

    flash(f"{product.name} added to your cart.")

    return redirect(
        request.referrer or url_for("shop")
    )


@app.route(
    "/remove-from-cart/<int:product_id>",
    methods=["POST"]
)
def remove_from_cart(product_id):
    cart_items = session.get("cart", {})

    cart_items.pop(str(product_id), None)

    session["cart"] = cart_items
    session.modified = True

    flash("Item removed from cart.")

    return redirect(url_for("cart"))

# ==========================================
# CHECKOUT
# ==========================================

@app.route("/checkout", methods=["GET", "POST"])
def checkout():
    products, total = get_cart_products()

    if not products:
        flash("Your cart is empty.")
        return redirect(url_for("shop"))

    if request.method == "POST":
        name = (
            request.form.get("customer_name")
            or request.form.get("name")
            or ""
        ).strip()

        phone = request.form.get("phone", "").strip()
        address = request.form.get("address", "").strip()

        payment_method = request.form.get(
            "payment_method",
            "Pay on Delivery"
        ).strip()

        allowed_payment_methods = {
            "Pay on Delivery",
            "Bank Transfer",
        }

        if not name or not phone or not address:
            flash("Please complete all delivery details.")
            return render_template(
                "checkout.html",
                products=products,
                total=total
            )

        if payment_method not in allowed_payment_methods:
            flash("Please select a valid payment method.")
            return render_template(
                "checkout.html",
                products=products,
                total=total
            )

        # Link the order to the logged-in customer.
        user = current_user()

        order = Order(
            user_id=user.id if user else None,
            customer_name=name,
            phone=phone,
            address=address,
            payment_method=payment_method,
            items=str(session.get("cart", {})),
            total=total
        )

        try:
            db.session.add(order)
            db.session.commit()

            session["cart"] = {}
            session.modified = True

            return render_template(
                "order_success.html",
                order=order
            )

        except Exception:
            db.session.rollback()

            app.logger.exception(
                "Could not save customer order."
            )

            flash(
                "We could not place your order. Please try again."
            )

    return render_template(
        "checkout.html",
        products=products,
        total=total
    )


# ==========================================
# CUSTOMER REGISTRATION
# ==========================================

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get(
            "name", ""
        ).strip()

        email = request.form.get(
            "email", ""
        ).strip().lower()

        password = request.form.get(
            "password", ""
        )

        if not name or not email or not password:
            flash("Please complete every field.")
            return redirect(url_for("register"))

        if len(password) < 8:
            flash(
                "Your password must contain at least 8 characters."
            )
            return redirect(url_for("register"))

        existing_user = User.query.filter_by(
            email=email
        ).first()

        if existing_user:
            flash(
                "An account with this email already exists."
            )
            return redirect(url_for("register"))

        user = User(
            name=name,
            email=email,
            password=generate_password_hash(password)
        )

        try:
            db.session.add(user)
            db.session.commit()

            session["user_id"] = user.id

            flash("Your account was created successfully.")

            return redirect(url_for("account"))

        except Exception:
            db.session.rollback()

            app.logger.exception(
                "Customer registration failed."
            )

            flash("Registration failed. Please try again.")

    return render_template("register.html")


# ==========================================
# CUSTOMER LOGIN
# ==========================================

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get(
            "email", ""
        ).strip().lower()

        password = request.form.get(
            "password", ""
        )

        user = User.query.filter_by(
            email=email
        ).first()

        if user and check_password_hash(
            user.password, password
        ):
            session.clear()
            session["user_id"] = user.id

            flash("Login successful.")

            return redirect(url_for("account"))

        flash("Incorrect email or password.")

    return render_template("login.html")


# ==========================================
# FORGOT PASSWORD
# ==========================================

@app.route(
    "/forgot-password",
    methods=["GET", "POST"]
)
def forgot_password():
    if request.method == "POST":
        email = request.form.get(
            "email", ""
        ).strip().lower()

        user = User.query.filter_by(
            email=email
        ).first()

        # Do not reveal whether an email has an account.
        flash(
            "If an account exists for that email, "
            "recovery instructions can be provided."
        )

        if user:
            token = password_reset_serializer().dumps(
                user.email,
                salt="dk-password-reset"
            )

            reset_link = url_for(
                "reset_password",
                token=token,
                _external=True
            )

            # Local testing only. Configure email delivery
            # before allowing real customers to use this.
            app.logger.info(
                "Password reset link: %s",
                reset_link
            )

        return redirect(url_for("login"))

    return render_template("forgot_password.html")


# ==========================================
# RESET PASSWORD
# ==========================================

@app.route(
    "/reset-password/<token>",
    methods=["GET", "POST"]
)
def reset_password(token):
    try:
        email = password_reset_serializer().loads(
            token,
            salt="dk-password-reset",
            max_age=1800
        )

    except SignatureExpired:
        flash(
            "Your reset link has expired. Request a new one."
        )

        return redirect(url_for("forgot_password"))

    except BadSignature:
        flash("This reset link is invalid.")

        return redirect(url_for("forgot_password"))

    user = User.query.filter_by(
        email=email
    ).first()

    if not user:
        flash("Account not found.")

        return redirect(url_for("forgot_password"))

    if request.method == "POST":
        password = request.form.get(
            "password", ""
        )

        confirm_password = request.form.get(
            "confirm_password", ""
        )

        if len(password) < 8:
            flash(
                "Your password must contain at least 8 characters."
            )

        elif password != confirm_password:
            flash("The passwords do not match.")

        else:
            user.password = generate_password_hash(
                password
            )

            try:
                db.session.commit()

                flash(
                    "Password changed successfully. You can now log in."
                )

                return redirect(url_for("login"))

            except Exception:
                db.session.rollback()

                app.logger.exception(
                    "Password reset failed."
                )

                flash(
                    "Could not change your password. Please try again."
                )

    return render_template(
        "reset_password.html"
    )


# ==========================================
# CUSTOMER ACCOUNT
# ==========================================

@app.route("/account")
def account():
    user = current_user()

    if not user:
        return redirect(url_for("login"))

    customer_orders = Order.query.filter_by(
        user_id=user.id
    ).order_by(
        Order.id.desc()
    ).all()

    return render_template(
        "account.html",
        user=user,
        orders=customer_orders
    )

# ==========================================
# CUSTOMER PROFILE
# ==========================================

@app.route("/profile", methods=["GET", "POST"])
def profile():
    user = current_user()

    if not user:
        return redirect(url_for("login"))

    if request.method == "POST":
        name = request.form.get(
            "name", ""
        ).strip()

        if not name:
            flash("Name cannot be empty.")

        else:
            user.name = name

            try:
                db.session.commit()
                flash("Profile updated successfully.")

            except Exception:
                db.session.rollback()

                app.logger.exception(
                    "Profile update failed."
                )

                flash("Could not update your profile.")

        return redirect(url_for("profile"))

    return render_template(
        "profile.html",
        user=user
    )


# ==========================================
# LOGOUT
# ==========================================

@app.route("/logout")
def logout():
    session.clear()

    flash("You have logged out.")

    return redirect(url_for("home"))


# ==========================================
# CUSTOMER ORDER HISTORY
# ==========================================

@app.route("/orders")
def orders():
    user = current_user()

    if not user:
        return redirect(url_for("login"))

    # Administrators can view all orders.
    if is_admin():
        all_orders = Order.query.order_by(
            Order.id.desc()
        ).all()

    # Customers can view only their own orders.
    else:
        all_orders = Order.query.filter_by(
            user_id=user.id
        ).order_by(Order.id.desc()).all()

    return render_template(
        "orders.html",
        orders=all_orders
    )

# ==========================================
# ADMIN DASHBOARD
# ==========================================

@app.route("/admin", methods=["GET", "POST"])
def admin():
    if not is_admin():
        if not current_user():
            return redirect(url_for("login"))

        return "Access denied: administrators only.", 403

    if request.method == "POST":
        name = request.form.get(
            "name", ""
        ).strip()

        description = request.form.get(
            "description", ""
        ).strip()

        price_text = request.form.get(
            "price", ""
        ).strip()

        image = request.files.get("image")

        if not name or not price_text:
            flash("Product name and price are required.")
            return redirect(url_for("admin"))

        try:
            price = float(price_text)

            if price <= 0:
                raise ValueError

        except ValueError:
            flash(
                "Enter a valid price greater than zero."
            )

            return redirect(url_for("admin"))

        filename = save_image(image)

        if not filename:
            flash(
                "Upload a valid JPG, JPEG, PNG, or WEBP image."
            )

            return redirect(url_for("admin"))

        product = Product(
            name=name,
            description=description,
            price=price,
            image=filename
        )

        try:
            db.session.add(product)
            db.session.commit()

            flash("Product published successfully!")

        except Exception:
            db.session.rollback()

            app.logger.exception(
                "Product could not be saved."
            )

            flash("Product could not be saved.")

        return redirect(url_for("admin"))

    products = Product.query.order_by(
        Product.id.desc()
    ).all()

    return render_template(
        "admin.html",
        products=products
    )


# ==========================================
# EDIT PRODUCT
# ==========================================

@app.route(
    "/admin/edit/<int:product_id>",
    methods=["GET", "POST"]
)
def edit_product(product_id):
    if not is_admin():
        if not current_user():
            return redirect(url_for("login"))

        return "Access denied: administrators only.", 403

    product = db.session.get(
        Product, product_id
    )

    if not product:
        return "Product not found.", 404

    if request.method == "POST":
        name = request.form.get(
            "name", ""
        ).strip()

        description = request.form.get(
            "description", ""
        ).strip()

        price_text = request.form.get(
            "price", ""
        ).strip()

        image = request.files.get("image")

        if not name or not price_text:
            flash("Product name and price are required.")

            return redirect(
                url_for(
                    "edit_product",
                    product_id=product.id
                )
            )

        try:
            price = float(price_text)

            if price <= 0:
                raise ValueError

        except ValueError:
            flash(
                "Enter a valid price greater than zero."
            )

            return redirect(
                url_for(
                    "edit_product",
                    product_id=product.id
                )
            )

        product.name = name
        product.description = description
        product.price = price

        if image and image.filename:
            filename = save_image(image)

            if not filename:
                flash(
                    "Use a JPG, JPEG, PNG, or WEBP image."
                )

                return redirect(
                    url_for(
                        "edit_product",
                        product_id=product.id
                    )
                )

            product.image = filename

        try:
            db.session.commit()

            flash("Product updated successfully!")

            return redirect(url_for("admin"))

        except Exception:
            db.session.rollback()

            app.logger.exception(
                "Product update failed."
            )

            flash("Could not update the product.")

    return render_template(
        "edit_product.html",
        product=product
    )


# ==========================================
# DELETE PRODUCT
# ==========================================

@app.route(
    "/admin/delete/<int:product_id>",
    methods=["POST"]
)
def delete_product(product_id):
    if not is_admin():
        if not current_user():
            return redirect(url_for("login"))

        return "Access denied: administrators only.", 403

    product = db.session.get(
        Product, product_id
    )

    if not product:
        flash("Product not found.")
        return redirect(url_for("admin"))

    try:
        db.session.delete(product)
        db.session.commit()

        flash("Product deleted successfully!")

    except Exception:
        db.session.rollback()

        app.logger.exception(
            "Product deletion failed."
        )

        flash("Could not delete the product.")

    return redirect(url_for("admin"))


# ==========================================
# ADMIN ORDER MANAGEMENT
# ==========================================

@app.route("/admin/orders")
def admin_orders():
    if not is_admin():
        if not current_user():
            return redirect(url_for("login"))

        return "Access denied: administrators only.", 403

    all_orders = Order.query.order_by(
        Order.id.desc()
    ).all()

    return render_template(
        "admin_orders.html",
        orders=all_orders
    )


# ==========================================
# SOCIAL LOGIN PLACEHOLDERS
# ==========================================
# These routes prevent 404 errors from login-page buttons.
# Real Google, Facebook, and Apple authentication still
# requires provider registration and OAuth configuration.

@app.route("/login/google")
def google_login():
    if not os.environ.get("GOOGLE_CLIENT_ID") or not os.environ.get("GOOGLE_CLIENT_SECRET"):
        flash("Google Sign-In is not configured.")
        return redirect(url_for("login"))

    redirect_uri = url_for(
        "google_callback",
        _external=True
    )

    return google.authorize_redirect(redirect_uri)


@app.route("/login/google/callback")
def google_callback():
    try:
        token = google.authorize_access_token()
        user_info = token.get("userinfo")

        if not user_info:
            user_info = google.parse_id_token(
                token,
                nonce=None
            )

        email = (user_info.get("email") or "").strip().lower()
        name = user_info.get("name") or "DK Shoes Customer"
        email_verified = user_info.get("email_verified", False)

        if not email or email_verified is not True:
            flash("Google did not provide a verified email address.")
            return redirect(url_for("login"))

        user = User.query.filter_by(email=email).first()

        if user is None:
            user = User(
                name=name,
                email=email,
                password=generate_password_hash(
                    uuid.uuid4().hex + uuid.uuid4().hex
                )
            )

            db.session.add(user)
            db.session.commit()

        session.clear()
        session["user_id"] = user.id

        flash("You signed in with Google successfully.")
        return redirect(url_for("account"))

    except Exception:
        db.session.rollback()
        app.logger.exception("Google sign-in failed.")
        flash("Google sign-in failed. Please try again.")
        return redirect(url_for("login"))


@app.route("/login/apple")
def apple_login():
    flash(
        "Apple sign-in has not been configured yet."
    )

    return redirect(url_for("login"))

@app.route("/admin/orders/<int:order_id>/status", methods=["POST"])
def update_order_status(order_id):
    from flask import request, redirect, url_for, flash

    if not session.get("user_id"):
        flash("Please log in first.")
        return redirect(url_for("login"))

    user = User.query.get(session["user_id"])

    if not user or user.email.lower() != app.config["ADMIN_EMAIL"].lower():
        flash("Access denied. Administrator access required.")
        return redirect(url_for("home"))

    order = db.session.get(Order, order_id)

    if not order:
        flash("Order not found.")
        return redirect(url_for("admin_orders"))

    new_status = request.form.get("status", "").strip()
    allowed_statuses = ["Pending", "Processing", "Shipped", "Delivered", "Cancelled"]

    if new_status not in allowed_statuses:
        flash("Invalid order status.")
        return redirect(url_for("admin_orders"))

    order.status = new_status
    db.session.commit()

    flash(f"Order #{order.id} status updated to {new_status}.")
    return redirect(url_for("admin_orders"))


# ==========================================
# RUN WEBSITE
# ==========================================

if __name__ == "__main__":
  app.run(
    host="0.0.0.0",
    port=5000,
    debug=True
)