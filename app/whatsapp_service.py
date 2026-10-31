import json
import logging
import urllib.parse
import urllib.request
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)


def clean_phone_number(phone: str) -> str:
    """Strip spaces, dashes, parentheses and ensure country code for India if missing."""
    cleaned = "".join(filter(str.isdigit, phone.strip()))
    if len(cleaned) == 10:
        cleaned = "91" + cleaned
    return cleaned


def format_whatsapp_receipt_text(order: dict[str, Any]) -> str:
    """Create a formatted luxury receipt text suitable for WhatsApp."""
    order_id = order.get("id", "N/A")
    customer_name = order.get("customer_name", "Valued Customer")
    total_price = f"{float(order.get('total_price', 0)):,.2f}"
    payment_mode = order.get("payment_mode", "Cash")
    payment_status = order.get("payment_status", "success").capitalize()
    gst_no = getattr(settings, "gst_number", "27AABCM1234F1Z1")
    order_date = order.get("order_datetime")
    if hasattr(order_date, "strftime"):
        date_str = order_date.strftime("%d-%b-%Y %I:%M %p")
    else:
        date_str = str(order_date or "Today")

    items = order.get("items", [])
    item_lines = []
    for idx, itm in enumerate(items, start=1):
        p_name = itm.get("product_name") if isinstance(itm, dict) else getattr(itm, "product_name", "")
        qty = itm.get("quantity") if isinstance(itm, dict) else getattr(itm, "quantity", 1)
        tot = itm.get("total_price") if isinstance(itm, dict) else getattr(itm, "total_price", 0)
        item_lines.append(f"{idx}. *{p_name}* (x{qty}) - ₹{float(tot):,.2f}")

    items_text = "\n".join(item_lines) if item_lines else "Artisanal Fragrance"

    text = f"""⚜️ *MOHERA HAUTE PARFUMERIE* ⚜️
*Tax Invoice / Order Confirmation*

*Bill No:* #MOH-ORD-{order_id}
*Date:* {date_str}
*GSTIN:* {gst_no}
*Customer:* {customer_name}

------------------------------------
*ORDER DETAILS:*
{items_text}
------------------------------------
*Grand Total:* ₹{total_price}
*Payment:* {payment_mode} ({payment_status})

Thank you for selecting MOHERA. Your bespoke fragrance is being prepared with utmost artisanal precision.

For assistance or custom blends, reply to this message.
*www.mohera.in*"""
    return text


def build_whatsapp_web_url(phone: str, text: str) -> str:
    """Generate a direct WhatsApp link that can be opened in browser/app."""
    cleaned = clean_phone_number(phone)
    encoded = urllib.parse.quote(text)
    return f"https://wa.me/{cleaned}?text={encoded}"


def send_order_receipt_whatsapp(order: dict[str, Any]) -> bool:
    """
    Send WhatsApp message if whatsapp_api_key is set in environment.
    Supports Meta Cloud API / WhatsApp Business API.
    """
    phone = order.get("phone", "")
    if not phone:
        return False

    cleaned_phone = clean_phone_number(phone)
    message_text = format_whatsapp_receipt_text(order)

    api_key = getattr(settings, "whatsapp_api_key", "").strip()
    phone_number_id = getattr(settings, "whatsapp_phone_number_id", "").strip()

    if not api_key:
        logger.info(
            "WhatsApp API key not set in environment. Receipt prepared for direct WhatsApp link: %s",
            build_whatsapp_web_url(phone, message_text)
        )
        return False

    try:
        # Standard Meta Cloud API endpoint or custom endpoint
        base_url = getattr(settings, "whatsapp_api_url", "https://graph.facebook.com/v18.0").rstrip("/")
        if phone_number_id:
            url = f"{base_url}/{phone_number_id}/messages"
        else:
            url = f"{base_url}/messages"

        payload = {
            "messaging_product": "whatsapp",
            "to": cleaned_phone,
            "type": "text",
            "text": {"preview_url": False, "body": message_text},
        }

        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=10) as response:
            if response.status in (200, 201):
                logger.info("WhatsApp receipt successfully sent to %s", cleaned_phone)
                return True
    except Exception as exc:
        logger.warning("Could not send WhatsApp message via API: %s", exc)

    return False
