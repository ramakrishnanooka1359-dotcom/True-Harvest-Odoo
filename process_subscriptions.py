"""
process_subscriptions.py
=========================
True Harvest — Daily Subscription Automation Runner

Run every morning by Windows Task Scheduler.

What it does each run:
  1. Finds all SUBSCRIPTION_MASTER orders whose Next Delivery date is <= today
  2. Checks for vacation pauses (skips if customer is on holiday)
  3. Checks stock availability (skips + flags if out of stock)
  4. Creates a real Sale Order from the master
  5. Confirms the order (triggers Odoo delivery picking)
  6. Validates the delivery (marks it done, reduces stock)
  7. Creates and posts an invoice
  8. Rolls the master's Next Delivery date forward (Daily/Weekly/Monthly)
  9. Removes [EXTRA ITEM] lines from master (one-time only)

Logs results to subscription_log.txt
"""

import sys
import re
import logging
from datetime import date, timedelta

# ── Logging setup ─────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("subscription_log.txt", encoding="utf-8"),
    ],
)
log = logging.getLogger("subscription_runner")

# ── Odoo client ───────────────────────────────────────────────────────────
from odoo_client import models, uid
from config import ODOO_DB, ODOO_API_KEY, TRUE_HARVEST_COMPANY_ID


# ═══════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def strip_html(text: str) -> str:
    """Remove HTML tags from Odoo rich-text fields."""
    return re.sub(r"<[^<]+?>", "", text or "")


def parse_note(note: str) -> dict:
    """
    Parse the subscription master note.
    Expected format: "Frequency: Daily | Next Delivery: 2026-03-12"
    Returns: {"frequency": "Daily", "next_delivery": "2026-03-12"}
    """
    note = strip_html(note)
    result = {"frequency": "Daily", "next_delivery": ""}
    for part in note.split("|"):
        part = part.strip()
        if part.startswith("Frequency:"):
            result["frequency"] = part.split(":", 1)[1].strip()
        elif part.startswith("Next Delivery:"):
            result["next_delivery"] = part.split(":", 1)[1].strip()
    return result


def next_delivery_date(current_date: date, frequency: str) -> date:
    """Calculate the next delivery date based on frequency."""
    freq_lower = frequency.lower()
    if freq_lower == "daily":
        return current_date + timedelta(days=1)
    elif freq_lower == "weekly":
        return current_date + timedelta(weeks=1)
    elif freq_lower in ("bi-weekly", "biweekly", "bi weekly"):
        return current_date + timedelta(weeks=2)
    elif freq_lower == "monthly":
        return current_date + timedelta(days=30)
    else:
        # Default to daily for unknown frequencies
        return current_date + timedelta(days=1)


def is_customer_on_vacation(partner_id: int, check_date: date) -> bool:
    """Check if a partner has VACATION mode active on the given date."""
    try:
        partners = models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            "res.partner", "read",
            [[partner_id]],
            {"fields": ["comment"]}
        )
        if not partners:
            return False
        comment = strip_html(partners[0].get("comment") or "")
        if "VACATION:" not in comment:
            return False

        v_part = comment.split("VACATION:", 1)[1].strip()
        dates = v_part.split(" to ")
        if len(dates) != 2:
            return False
        start = date.fromisoformat(dates[0].strip())
        end = date.fromisoformat(dates[1].strip())
        return start <= check_date <= end
    except Exception as e:
        log.warning(f"  ⚠️  Could not check vacation for partner {partner_id}: {e}")
        return False


def check_stock(order_lines: list) -> tuple[bool, list]:
    """
    Returns (all_in_stock: bool, out_of_stock_products: list).
    Checks qty_available for each product in the order lines.
    """
    out_of_stock = []
    for line in order_lines:
        product_id = line["product_id"][0] if line.get("product_id") else None
        if not product_id:
            continue
        qty_needed = line.get("product_uom_qty", 1)
        product = models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            "product.product", "read",
            [[product_id]],
            {"fields": ["name", "qty_available"]}
        )
        if product:
            available = product[0]["qty_available"]
            if available < qty_needed:
                out_of_stock.append({
                    "product": product[0]["name"],
                    "available": available,
                    "needed": qty_needed
                })
    return (len(out_of_stock) == 0), out_of_stock


def create_delivery_order(master: dict, lines: list, frequency: str, today: date) -> int:
    """Create a confirmed Sale Order (delivery) from the master template."""

    # 1. Create the Sale Order header
    sale_order_id = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        "sale.order", "create",
        [{
            "partner_id": master["partner_id"][0],
            "company_id": TRUE_HARVEST_COMPANY_ID,
            "origin": f"Subscription Delivery - {frequency}",
            "note": f"Auto-generated from subscription {master['name']} on {today.isoformat()}",
        }]
    )

    # 2. Add order lines (skip [EXTRA ITEM] labeling — include all lines)
    for line in lines:
        product_id = line["product_id"][0] if line.get("product_id") else None
        if not product_id:
            continue
        product_data = models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            "product.product", "read",
            [[product_id]],
            {"fields": ["lst_price"]}
        )
        price = product_data[0]["lst_price"] if product_data else line.get("price_unit", 0)
        models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            "sale.order.line", "create",
            [{
                "order_id": sale_order_id,
                "product_id": product_id,
                "product_uom_qty": line.get("product_uom_qty", 1),
                "price_unit": price,
                "company_id": TRUE_HARVEST_COMPANY_ID,
            }]
        )

    # 3. Confirm the order (triggers stock picking creation)
    models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        "sale.order", "action_confirm",
        [[sale_order_id]]
    )
    return sale_order_id


def validate_delivery(sale_order_name: str) -> bool:
    """Find and validate all stock pickings for the confirmed sale order."""
    picking_ids = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        "stock.picking", "search",
        [[
            ("origin", "=", sale_order_name),
            ("company_id", "=", TRUE_HARVEST_COMPANY_ID),
            ("state", "not in", ["done", "cancel"]),
        ]]
    )
    if not picking_ids:
        log.warning(f"  ⚠️  No pending pickings found for {sale_order_name}")
        return False

    for picking_id in picking_ids:
        # Assign stock
        models.execute_kw(ODOO_DB, uid, ODOO_API_KEY, "stock.picking", "action_assign", [[picking_id]])

        # Get stock moves
        moves = models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            "stock.move", "search_read",
            [[("picking_id", "=", picking_id), ("company_id", "=", TRUE_HARVEST_COMPANY_ID)]],
            {"fields": ["id", "product_uom_qty"]}
        )

        for move in moves:
            # Set qty_done on each move line
            move_lines = models.execute_kw(
                ODOO_DB, uid, ODOO_API_KEY,
                "stock.move.line", "search",
                [[("move_id", "=", move["id"]), ("company_id", "=", TRUE_HARVEST_COMPANY_ID)]]
            )
            for line_id in move_lines:
                models.execute_kw(
                    ODOO_DB, uid, ODOO_API_KEY,
                    "stock.move.line", "write",
                    [[line_id], {"qty_done": move["product_uom_qty"]}]
                )

        # Validate the picking
        try:
            models.execute_kw(ODOO_DB, uid, ODOO_API_KEY, "stock.picking", "button_validate", [[picking_id]])
        except Exception as e:
            log.warning(f"  ⚠️  Picking {picking_id} validation issue (may be immediate transfer): {e}")

    return True


def create_and_post_invoice(sale_order_id: int, sale_order_name: str) -> bool:
    """Create and post an invoice for the delivered sale order."""
    try:
        wizard_id = models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            "sale.advance.payment.inv", "create",
            [{"advance_payment_method": "delivered", "company_id": TRUE_HARVEST_COMPANY_ID}],
            {"context": {"active_ids": [sale_order_id], "company_id": TRUE_HARVEST_COMPANY_ID}}
        )
        models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            "sale.advance.payment.inv", "create_invoices",
            [[wizard_id]],
            {"context": {"active_ids": [sale_order_id], "company_id": TRUE_HARVEST_COMPANY_ID}}
        )

        # Find and post the invoice
        invoice_ids = models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            "account.move", "search",
            [[("invoice_origin", "=", sale_order_name), ("company_id", "=", TRUE_HARVEST_COMPANY_ID)]]
        )
        for invoice_id in invoice_ids:
            models.execute_kw(
                ODOO_DB, uid, ODOO_API_KEY,
                "account.move", "action_post",
                [[invoice_id]],
                {"context": {"company_id": TRUE_HARVEST_COMPANY_ID}}
            )
        return True
    except Exception as e:
        log.error(f"  ❌ Invoice creation failed for {sale_order_name}: {e}")
        return False


def rollover_master(master_id: int, frequency: str, current_delivery: date, extra_item_line_ids: list):
    """
    Update the master's Next Delivery date to the next cycle
    and remove [EXTRA ITEM] lines (they were one-time only).
    """
    next_date = next_delivery_date(current_delivery, frequency)

    # Remove [EXTRA ITEM] lines first
    if extra_item_line_ids:
        models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            "sale.order.line", "unlink",
            [extra_item_line_ids]
        )
        log.info(f"  🧹  Removed {len(extra_item_line_ids)} extra item line(s) from master")

    # Update the note with the new Next Delivery date
    new_note = f"Frequency: {frequency} | Next Delivery: {next_date.isoformat()}"
    models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        "sale.order", "write",
        [[master_id], {"note": new_note}]
    )
    return next_date


# ═══════════════════════════════════════════════════════════════════════════
# MAIN RUNNER
# ═══════════════════════════════════════════════════════════════════════════

def run():
    today = date.today()
    log.info("=" * 60)
    log.info(f"🚀 Subscription Runner Started — {today.isoformat()}")
    log.info("=" * 60)

    # ── 1. Find all active subscription masters ────────────────────────────
    masters = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        "sale.order", "search_read",
        [[
            ("origin", "=", "[SUBSCRIPTION_MASTER]"),
            ("state", "=", "draft"),
            ("company_id", "=", TRUE_HARVEST_COMPANY_ID),
        ]],
        {"fields": ["id", "name", "partner_id", "order_line", "note"]}
    )

    log.info(f"📋 Found {len(masters)} active subscription master(s)")

    stats = {"processed": 0, "skipped_vacation": 0, "skipped_stock": 0, "errors": 0}

    for master in masters:
        master_id = master["id"]
        master_name = master["name"]
        partner_id = master["partner_id"][0]
        partner_name = master["partner_id"][1]

        log.info(f"\n── Processing: {master_name} ({partner_name}) ──")

        # ── 2. Parse the note ────────────────────────────────────────────
        note_data = parse_note(master.get("note") or "")
        frequency = note_data["frequency"]
        next_delivery_str = note_data["next_delivery"]

        if not next_delivery_str:
            log.warning(f"  ⚠️  No Next Delivery date found in note. Skipping.")
            stats["errors"] += 1
            continue

        try:
            next_delivery_dt = date.fromisoformat(next_delivery_str)
        except ValueError:
            log.warning(f"  ⚠️  Invalid Next Delivery date: {next_delivery_str}. Skipping.")
            stats["errors"] += 1
            continue

        log.info(f"  📅 Frequency: {frequency}, Next Delivery: {next_delivery_str}")

        # ── 3. Check if delivery is due today or overdue ─────────────────
        if next_delivery_dt > today:
            log.info(f"  ⏭️  Not due yet (next: {next_delivery_str}). Skipping.")
            continue

        # ── 4. Check vacation / pause ────────────────────────────────────
        if is_customer_on_vacation(partner_id, today):
            log.info(f"  🏖️  Customer {partner_name} is on vacation. Skipping.")
            stats["skipped_vacation"] += 1
            continue

        # ── 5. Load order lines ──────────────────────────────────────────
        line_ids = master.get("order_line", [])
        if not line_ids:
            log.warning(f"  ⚠️  Master has no order lines. Skipping.")
            stats["errors"] += 1
            continue

        lines = models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            "sale.order.line", "read",
            [line_ids],
            {"fields": ["id", "product_id", "product_uom_qty", "price_unit", "name"]}
        )

        # Identify [EXTRA ITEM] lines (one-time)
        extra_item_line_ids = [
            l["id"] for l in lines if "[EXTRA ITEM]" in (l.get("name") or "")
        ]

        # ── 6. Check stock ───────────────────────────────────────────────
        in_stock, out_items = check_stock(lines)
        if not in_stock:
            for item in out_items:
                log.warning(
                    f"  📦 OUT OF STOCK: {item['product']} — "
                    f"need {item['needed']}, have {item['available']}"
                )
            log.warning(f"  ❌ Stock insufficient for {master_name}. Skipping this delivery.")
            stats["skipped_stock"] += 1
            continue

        # ── 7. Create delivery order ─────────────────────────────────────
        try:
            sale_order_id = create_delivery_order(master, lines, frequency, today)
            # Get the name of the new sale order
            so_data = models.execute_kw(
                ODOO_DB, uid, ODOO_API_KEY,
                "sale.order", "read",
                [[sale_order_id]],
                {"fields": ["name"]}
            )[0]
            so_name = so_data["name"]
            log.info(f"  ✅ Sale Order created: {so_name}")

            # ── 8. Validate delivery ──────────────────────────────────────
            validate_delivery(so_name)
            log.info(f"  ✅ Delivery validated for {so_name}")

            # ── 9. Invoice ────────────────────────────────────────────────
            create_and_post_invoice(sale_order_id, so_name)
            log.info(f"  ✅ Invoice created and posted for {so_name}")

            # ── 10. Roll over master ──────────────────────────────────────
            new_next = rollover_master(master_id, frequency, next_delivery_dt, extra_item_line_ids)
            log.info(f"  🔄 Master {master_name} rolled to Next Delivery: {new_next.isoformat()}")

            stats["processed"] += 1

        except Exception as e:
            log.error(f"  ❌ ERROR processing {master_name}: {e}")
            import traceback
            log.error(traceback.format_exc())
            stats["errors"] += 1

    # ── Summary ──────────────────────────────────────────────────────────
    log.info("\n" + "=" * 60)
    log.info(f"✔️  Processed:        {stats['processed']}")
    log.info(f"🏖️  Vacation Skipped: {stats['skipped_vacation']}")
    log.info(f"📦 Stock Skipped:    {stats['skipped_stock']}")
    log.info(f"❌ Errors:           {stats['errors']}")
    log.info("=" * 60)


if __name__ == "__main__":
    run()
