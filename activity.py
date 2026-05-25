from fastapi import APIRouter, HTTPException, Query
from odoo_client import models, uid
from config import ODOO_DB, ODOO_API_KEY, TRUE_HARVEST_COMPANY_ID
from datetime import date, datetime, timedelta
import calendar

router = APIRouter()

@router.get("/dashboard/product-activity")
def get_product_activity(
    period: str = Query("day", description="day, month, year"),
    target_date: str = Query("today", description="YYYY-MM-DD, YYYY-MM, or YYYY")
):
    """
    Fetches per-product stock additions and sales for a day, month, or year.
    """
    # 1. Determine date range
    try:
        if period == "day":
            if target_date == "today":
                d = date.today()
            elif target_date == "yesterday":
                d = date.today() - timedelta(days=1)
            else:
                d = date.fromisoformat(target_date)
            start_dt = f"{d.isoformat()} 00:00:00"
            end_dt = f"{d.isoformat()} 23:59:59"
            display_date = d.strftime("%B %d, %Y")
        
        elif period == "month":
            # Expect YYYY-MM
            if target_date == "today" or target_date == "current":
                d = date.today()
            else:
                parts = target_date.split("-")
                d = date(int(parts[0]), int(parts[1]), 1)
            
            last_day = calendar.monthrange(d.year, d.month)[1]
            start_dt = f"{d.year}-{d.month:02d}-01 00:00:00"
            end_dt = f"{d.year}-{d.month:02d}-{last_day:02d} 23:59:59"
            display_date = d.strftime("%B %Y")

        elif period == "year":
            # Expect YYYY
            if target_date == "today" or target_date == "current":
                year = date.today().year
            else:
                year = int(target_date)
            start_dt = f"{year}-01-01 00:00:00"
            end_dt = f"{year}-12-31 23:59:59"
            display_date = str(year)
        
        else:
            raise HTTPException(status_code=400, detail="Invalid period. Use day, month, or year.")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid date format for period {period}: {e}")

    # 2. Fetch Sales (sale.order.line)
    sales_lines = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'sale.order.line', 'search_read',
        [[
            ('company_id', '=', TRUE_HARVEST_COMPANY_ID),
            ('order_id.state', 'in', ['sale', 'done', 'closed']),
            ('order_id.date_order', '>=', start_dt),
            ('order_id.date_order', '<=', end_dt)
        ]],
        {'fields': ['product_id', 'product_uom_qty', 'price_subtotal']}
    )

    # 3. Fetch Stock Additions (stock.move)
    stock_moves = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'stock.move', 'search_read',
        [[
            ('company_id', '=', TRUE_HARVEST_COMPANY_ID),
            ('state', '=', 'done'),
            ('date', '>=', start_dt),
            ('date', '<=', end_dt),
            ('location_dest_id.usage', '=', 'internal'),
            ('location_id.usage', '!=', 'internal')
        ]],
        {'fields': ['product_id', 'product_uom_qty']}
    )

    # 4. Aggregate by Product
    activity_map = {}

    def get_entry(p_id, p_name):
        if p_id not in activity_map:
            activity_map[p_id] = {
                "id": p_id,
                "name": p_name,
                "additions": 0,
                "sales_qty": 0,
                "sales_value": 0
            }
        return activity_map[p_id]

    for s in sales_lines:
        pid, pname = s['product_id']
        entry = get_entry(pid, pname)
        entry['sales_qty'] += s['product_uom_qty']
        entry['sales_value'] += s['price_subtotal']

    for m in stock_moves:
        pid, pname = m['product_id']
        entry = get_entry(pid, pname)
        entry['additions'] += m['product_uom_qty']

    result = sorted(activity_map.values(), key=lambda x: x['sales_qty'], reverse=True)

    return {
        "period": period,
        "date_label": display_date,
        "raw_date": target_date,
        "summary": {
            "total_additions": sum(x['additions'] for x in result),
            "total_sales_qty": sum(x['sales_qty'] for x in result),
            "total_sales_value": sum(x['sales_value'] for x in result)
        },
        "items": result
    }
