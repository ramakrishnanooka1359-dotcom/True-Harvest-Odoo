# True Harvest API

A FastAPI-based integration for managing True Harvest orders, products, and variants in Odoo.

## 🚀 Features
- **Product Management**: Fetch products and variants filtered by True Harvest company.
- **Order Flow**: Automated Draft Order creation -> Payment Success -> Delivery Validation -> Invoice Posting.
- **Support for Partial Operations**:
  - **Return**: Return specific quantities of products to stock.
  - **Refund**: Create and post partial credit notes for specific items.
  - **Replace**: Single-API call to return an item and create a new replacement order.

---

## 📂 Project Structure

```text
true_harvest_api/
├── main.py             # Entry point (FastAPI initialization)
├── orders.py           # Core logic for Order, Return, Refund, and Replace
├── products.py         # Logic for fetching Products and Variants
├── odoo_client.py      # Odoo XML-RPC connection setup
├── config.py           # Configuration management and True Harvest constants
├── .env                # Environment variables (DB URL, API Key, etc.)
├── README.md           # Project documentation
└── .gitignore          # Git exclusion rules
```

---

## 🛠️ Installation & Setup

1. **Clone the repository**
2. **Setup Virtual Environment**:
   ```bash
   python -m venv venv
   source venv/Scripts/activate  # Windows
   ```
3. **Install Dependencies**:
   ```bash
   pip install fastapi uvicorn
   ```
4. **Configure Environment**:
   Create a `.env` file with your Odoo credentials:
   ```env
   ODOO_URL=http://your-odoo-url
   ODOO_DB=your-db
   ODOO_USERNAME=your-username
   ODOO_API_KEY=your-api-key
   ```
5. **Run the Server**:
   ```bash
   python -m uvicorn main:app --port 8001
   ```

---

## 🔌 API Documentation

Access the interactive Swagger UI at: `http://127.0.0.1:8001/docs`

### Key Endpoints:

#### 1. Orders
- `POST /orders`: Create a draft sale order.
- `POST /orders/{id}/payment-success`: Confirm order, validate delivery, and post invoice.
- `POST /orders/{id}/return`: Process full or partial returns.
- `POST /orders/{id}/refund`: Process full or partial financial refunds (Credit Notes).
- `POST /orders/{id}/replace`: Process a return and create a new replacement order in one call.

#### 2. Products
- `GET /products`: List all products.
- `GET /products/{id}`: Get details for a specific product and its variants.

---

## 🛡️ Company Isolation
This API is strictly locked to **True Harvest (Company ID: 3)**. 
- It will only fetch products belonging to True Harvest.
- It will only process orders/returns/refunds for True Harvest.
- Any attempt to access data from other companies (like Animal Kart) will result in a `403 Unauthorized` error.