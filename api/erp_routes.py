"""Read-only ERP business data endpoints backed by Railway Postgres."""

from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Query, Request

from db import get_erp_pg_db
from skills.routes import _check_permission

router = APIRouter(prefix="/api/erp", tags=["erp-data"])

OVERDUE_INVOICE = """(status = 'overdue' OR (
    status IN ('submitted', 'partially_paid')
    AND NULLIF(due_date::text, '')::date < CURRENT_DATE
    AND outstanding_amount::numeric > 0
))"""

# Public route keys are fixed and map only to tables in the ERP schema.
ENTITY_TABLES = {
    "customer": "customer", "quotation": "quotation", "sales_order": "sales_order",
    "delivery_note": "delivery_note", "sales_invoice": "sales_invoice",
    "credit_note": "sales_invoice", "supplier": "supplier", "purchase_order": "purchase_order",
    "purchase_receipt": "purchase_receipt", "purchase_invoice": "purchase_invoice",
    "item": "item", "warehouse": "warehouse", "stock_entry": "stock_entry",
    "account": "account", "journal_entry": "journal_entry", "payment_entry": "payment_entry",
    "employee": "employee", "expense_claim": "expense_claim", "company": "company",
    "fiscal_year": "fiscal_year", "tax_template": "tax_template",
}

# Fields available to the GUI, kept intentionally narrow (especially for HR).
ENTITY_COLUMNS = {
    "customer": ("id", "name", "customer_type", "customer_group", "territory", "email", "phone", "status", "credit_limit", "created_at"),
    "quotation": ("id", "naming_series", "customer_id", "quotation_date", "valid_until", "grand_total", "status", "created_at"),
    "sales_order": ("id", "naming_series", "customer_id", "order_date", "delivery_date", "grand_total", "status", "created_at"),
    "delivery_note": ("id", "naming_series", "customer_id", "sales_order_id", "posting_date", "status", "created_at"),
    "sales_invoice": ("id", "naming_series", "customer_id", "posting_date", "due_date", "grand_total", "outstanding_amount", "status", "created_at"),
    "credit_note": ("id", "naming_series", "customer_id", "return_against", "posting_date", "grand_total", "status", "created_at"),
    "supplier": ("id", "name", "supplier_type", "supplier_group", "email", "phone", "status", "created_at"),
    "purchase_order": ("id", "naming_series", "supplier_id", "order_date", "required_date", "grand_total", "status", "created_at"),
    "purchase_receipt": ("id", "naming_series", "supplier_id", "purchase_order_id", "posting_date", "status", "created_at"),
    "purchase_invoice": ("id", "naming_series", "supplier_id", "posting_date", "due_date", "grand_total", "outstanding_amount", "status", "created_at"),
    "item": ("id", "item_code", "item_name", "item_group_id", "item_type", "stock_uom", "standard_rate", "status", "created_at"),
    "warehouse": ("id", "name", "warehouse_type", "address", "created_at"),
    "stock_entry": ("id", "naming_series", "stock_entry_type", "posting_date", "from_warehouse_id", "to_warehouse_id", "status", "created_at"),
    "account": ("id", "account_number", "name", "account_type", "root_type", "is_group", "disabled", "created_at"),
    "journal_entry": ("id", "naming_series", "entry_type", "posting_date", "total_debit", "status", "created_at"),
    "payment_entry": ("id", "naming_series", "party_type", "party_id", "payment_type", "posting_date", "paid_amount", "status", "created_at"),
    "employee": ("id", "full_name", "department_id", "designation_id", "status", "date_of_joining"),
    "expense_claim": ("id", "naming_series", "employee_id", "expense_date", "total_amount", "status", "created_at"),
    "company": ("id", "name", "abbr", "default_currency", "country", "created_at"),
    "fiscal_year": ("id", "name", "start_date", "end_date", "is_closed"),
    "tax_template": ("id", "name", "tax_type", "is_default"),
}

# Foreign-key labels used by the table and record views.
RELATED_LABELS = {
    "customer_id": ("customer", "name", "customer_name"),
    "supplier_id": ("supplier", "name", "supplier_name"),
    "sales_order_id": ("sales_order", "naming_series", "sales_order_name"),
    "purchase_order_id": ("purchase_order", "naming_series", "purchase_order_name"),
    "return_against": ("sales_invoice", "naming_series", "return_against_name"),
    "item_group_id": ("item_group", "name", "item_group_name"),
    "from_warehouse_id": ("warehouse", "name", "from_warehouse_name"),
    "to_warehouse_id": ("warehouse", "name", "to_warehouse_name"),
    "department_id": ("department", "name", "department_name"),
    "designation_id": ("designation", "name", "designation_name"),
    "employee_id": ("employee", "full_name", "employee_name"),
}


def _add_related_labels(cursor, rows):
    for field, (table, label, output) in RELATED_LABELS.items():
        ids = {row[field] for row in rows if row.get(field)}
        if not ids:
            continue
        cursor.execute(f'SELECT id, "{label}" FROM "{table}" WHERE id = ANY(%s)', (list(ids),))
        names = {row["id"]: row[label] for row in cursor.fetchall()}
        for row in rows:
            name = names.get(row.get(field))
            if name is not None:
                row[output] = name

def _db():
    try:
        return get_erp_pg_db()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _json_value(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _require_entity_permission(user, entity, action):
    """Apply the web app's ERP action permissions to data reads."""
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if "System Manager" in user.get("roles", []):
        return
    list_names = {
        "customer": "customers", "quotation": "quotations", "sales_order": "sales_orders",
        "delivery_note": "delivery_notes", "sales_invoice": "sales_invoices", "credit_note": "credit_notes",
        "supplier": "suppliers", "purchase_order": "purchase_orders", "purchase_receipt": "purchase_receipts",
        "purchase_invoice": "purchase_invoices", "item": "items", "warehouse": "warehouses",
        "stock_entry": "stock_entries", "account": "accounts", "journal_entry": "journal_entries",
        "payment_entry": "payment_entries", "employee": "employees", "expense_claim": "expense_claims",
        "company": "companies", "fiscal_year": "fiscal_years", "tax_template": "tax_templates",
    }
    action_name = f"{action}-{list_names.get(entity, entity.replace('_', '-')) if action == 'list' else entity.replace('_', '-')}"
    if not _check_permission(user, "erpclaw", action_name):
        raise HTTPException(status_code=403, detail="Permission denied")


@router.get("/overview")
def overview(request: Request):
    """Return live dashboard counts, recent activity, and attention items."""
    _require_entity_permission(getattr(request.state, "user", None), "sales_invoice", "list")
    _require_entity_permission(getattr(request.state, "user", None), "sales_order", "list")
    _require_entity_permission(getattr(request.state, "user", None), "purchase_order", "list")
    conn = _db()
    try:
        with conn.cursor() as cur:
            def scalar(sql, args=()):
                cur.execute(sql, args)
                return cur.fetchone()["n"]

            cur.execute("SELECT currency, COALESCE(SUM(grand_total::numeric), 0) AS n FROM sales_invoice WHERE status IN ('submitted','partially_paid','paid','overdue') AND posting_date::date >= date_trunc('month', CURRENT_DATE)::date GROUP BY currency ORDER BY currency")
            revenue = cur.fetchall()
            open_count = scalar("SELECT COUNT(*) AS n FROM sales_invoice WHERE status IN ('submitted','partially_paid','overdue')")
            cur.execute("SELECT currency, COALESCE(SUM(outstanding_amount::numeric), 0) AS n FROM sales_invoice WHERE status IN ('submitted','partially_paid','overdue') GROUP BY currency ORDER BY currency")
            outstanding = cur.fetchall()
            overdue = scalar(f"SELECT COUNT(*) AS n FROM sales_invoice WHERE is_return::integer = 0 AND {OVERDUE_INVOICE}")
            week_orders = scalar("SELECT COUNT(*) AS n FROM sales_order WHERE order_date::date >= CURRENT_DATE - INTERVAL '7 days' AND status NOT IN ('draft','cancelled')")
            pending_delivery = scalar("SELECT COUNT(*) AS n FROM sales_order WHERE status IN ('confirmed','partially_delivered')")
            workflows = []
            for key, label, table, status_values in [
                ("sales_order", "Sales Orders", "sales_order", ["draft", "confirmed", "partially_delivered", "fully_delivered"]),
                ("sales_invoice", "Sales Invoices", "sales_invoice", ["draft", "submitted", "partially_paid", "paid", "overdue"]),
                ("purchase_order", "Purchase Orders", "purchase_order", ["draft", "confirmed", "partially_received", "fully_received"]),
            ]:
                cur.execute(f'SELECT status, COUNT(*) AS n FROM "{table}" GROUP BY status')
                counts = {row["status"]: row["n"] for row in cur.fetchall()}
                workflows.append({"key": key, "label": label, "steps": [{"label": status.replace("_", " ").title(), "count": counts.get(status, 0)} for status in status_values]})
            attention = []
            if overdue:
                attention.append({"message": f"{overdue} overdue invoice(s) need follow-up", "severity": "warning", "href": "/sales_invoice?status=overdue"})
            activity = []
            for table, label, href in [("sales_invoice", "Sales invoice", "/sales_invoice"), ("sales_order", "Sales order", "/sales_order"), ("purchase_order", "Purchase order", "/purchase_order")]:
                cur.execute(f'SELECT id, naming_series, created_at FROM "{table}" ORDER BY created_at DESC LIMIT 10')
                activity.extend({"message": f"{label} {row['naming_series'] or row['id']} recorded", "timestamp": _json_value(row["created_at"]), "href": href} for row in cur.fetchall())
            activity.sort(key=lambda row: row["timestamp"] or "", reverse=True)
        return {
            "kpis": [
                {"label": "Revenue (MTD)", "value": _format_currency_totals(revenue), "sub": "Current month", "color": "#10b981"},
                {"label": "Open Invoices", "value": str(open_count), "sub": f"{_format_currency_totals(outstanding)} outstanding", "color": "#06b6d4"},
                {"label": "Overdue", "value": str(overdue), "sub": "Past due", "color": "#ef4444"},
                {"label": "Orders This Week", "value": str(week_orders), "sub": f"{pending_delivery} pending delivery", "color": "#f59e0b"},
            ], "workflows": workflows, "attention": attention, "activity": activity[:20],
        }
    finally:
        conn.close()


def _format_currency_totals(rows):
    """Keep dashboard amounts explicit when invoices use multiple currencies."""
    if not rows:
        return "0.00"
    return " · ".join(f"{row['currency']} {Decimal(str(row['n'])):,.2f}" for row in rows)


@router.get("/{entity}")
def list_entity(entity: str, request: Request, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0), search: str = "", status: str | None = None):
    """List rows for a known ERP entity with bounded pagination and search."""
    table = ENTITY_TABLES.get(entity)
    if table is None:
        raise HTTPException(status_code=404, detail="Unknown ERP entity")
    _require_entity_permission(getattr(request.state, "user", None), entity, "list")
    conn = _db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_schema = current_schema() AND table_name = %s ORDER BY ordinal_position", (table,))
            metadata = cur.fetchall()
            if not metadata:
                raise HTTPException(status_code=404, detail=f"ERP table '{table}' is not available")
            available = {row["column_name"]: row["data_type"] for row in metadata}
            columns = [column for column in ENTITY_COLUMNS[entity] if column in available]
            if not columns:
                raise HTTPException(status_code=404, detail=f"No supported fields are available for '{entity}'")
            text_columns = [column for column in columns if available[column] in ("text", "character varying", "character")]
            predicates = []
            params = []
            if entity == "credit_note" and "is_return" in available:
                predicates.append('"is_return" IS TRUE' if available["is_return"] == "boolean" else '"is_return" = 1')
            elif entity == "sales_invoice" and "is_return" in available:
                predicates.append('"is_return" IS FALSE' if available["is_return"] == "boolean" else '"is_return" = 0')
            if status is not None:
                if entity == "account" and "disabled" in available:
                    if status not in ("active", "disabled"):
                        raise HTTPException(status_code=400, detail="Account status must be 'active' or 'disabled'")
                    predicates.append('"disabled" = %s')
                    disabled = status == "disabled"
                    params.append(disabled if available["disabled"] == "boolean" else int(disabled))
                elif entity == "sales_invoice" and status == "overdue" and {"status", "due_date", "outstanding_amount"} <= available.keys():
                    predicates.append(OVERDUE_INVOICE)
                elif "status" in available:
                    predicates.append('"status" = %s')
                    params.append(status)
                else:
                    raise HTTPException(status_code=400, detail=f"'{entity}' does not support status filtering")
            if search.strip() and text_columns:
                predicates.append("(" + " OR ".join(f'"{column}" ILIKE %s' for column in text_columns) + ")")
                params.extend([f"%{search.strip()}%"] * len(text_columns))
            reserved = {"limit", "offset", "search", "status"}
            for field, value in request.query_params.multi_items():
                if field in reserved:
                    continue
                if field not in columns:
                    raise HTTPException(status_code=400, detail=f"Unsupported filter '{field}' for '{entity}'")
                predicates.append(f'"{field}" = %s')
                params.append(value)
            where = " WHERE " + " AND ".join(predicates) if predicates else ""
            cur.execute(f'SELECT COUNT(*) AS n FROM "{table}"{where}', params)
            total = cur.fetchone()["n"]
            order_column = "created_at" if "created_at" in columns else ("posting_date" if "posting_date" in columns else "id")
            order = f' ORDER BY "{order_column}" DESC, "id" DESC'
            selected = ", ".join(f'"{column}"' for column in columns)
            cur.execute(f'SELECT {selected} FROM "{table}"{where}{order} LIMIT %s OFFSET %s', [*params, limit, offset])
            rows = [{key: _json_value(value) for key, value in row.items()} for row in cur.fetchall()]
            _add_related_labels(cur, rows)
        return {"data": rows, "total_count": total, "has_more": offset + len(rows) < total}
    finally:
        conn.close()


@router.get("/{entity}/{entity_id}")
def get_entity(entity: str, entity_id: str, request: Request):
    """Return one allowlisted ERP record using the same field limits as lists."""
    table = ENTITY_TABLES.get(entity)
    if table is None:
        raise HTTPException(status_code=404, detail="Unknown ERP entity")
    _require_entity_permission(getattr(request.state, "user", None), entity, "get")
    conn = _db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT column_name, data_type FROM information_schema.columns WHERE table_schema = current_schema() AND table_name = %s",
                (table,),
            )
            available = {row["column_name"]: row["data_type"] for row in cur.fetchall()}
            if not available:
                raise HTTPException(status_code=404, detail=f"ERP table '{table}' is not available")
            columns = [column for column in ENTITY_COLUMNS[entity] if column in available]
            if not columns:
                raise HTTPException(status_code=404, detail=f"No supported fields are available for '{entity}'")
            select = ", ".join(f'"{column}"' for column in columns)
            predicates = ['"id" = %s']
            params = [entity_id]
            if entity == "credit_note" and "is_return" in available:
                predicates.append('"is_return" IS TRUE' if available["is_return"] == "boolean" else '"is_return" = 1')
            elif entity == "sales_invoice" and "is_return" in available:
                predicates.append('"is_return" IS FALSE' if available["is_return"] == "boolean" else '"is_return" = 0')
            cur.execute(f'SELECT {select} FROM "{table}" WHERE {" AND ".join(predicates)} LIMIT 1', params)
            row = cur.fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="ERP record not found")
            record = {key: _json_value(value) for key, value in row.items()}
            _add_related_labels(cur, [record])
            return {"data": record}
    finally:
        conn.close()
