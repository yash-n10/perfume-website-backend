import logging
import smtplib
import ssl
from email.message import EmailMessage
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)


def send_otp_email(recipient: str, code: str) -> None:
    if not settings.smtp_host or not settings.smtp_from_email:
        raise RuntimeError("SMTP_HOST and SMTP_FROM_EMAIL must be configured.")

    message = EmailMessage()
    message["Subject"] = "Your MOHERA verification code"
    message["From"] = settings.smtp_from_email
    message["To"] = recipient
    message.set_content(
        f"Your MOHERA verification code is {code}. "
        f"It expires in {settings.otp_expiration_minutes} minutes."
    )

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as server:
        if settings.smtp_use_tls:
            server.starttls(context=ssl.create_default_context())
        if settings.smtp_username:
            server.login(settings.smtp_username, settings.smtp_password)
        server.send_message(message)


def send_order_receipt_email(order: dict[str, Any]) -> bool:
    """Send luxury HTML order invoice / receipt to customer."""
    recipient = (order.get("email") or "").strip()
    if not recipient or "@" not in recipient or recipient.endswith("@mohera.com"):
        return False

    if not settings.smtp_host or not settings.smtp_from_email:
        logger.warning("SMTP host or from email not configured. Cannot send order receipt email.")
        return False

    order_id = order.get("id", "N/A")
    customer_name = order.get("customer_name", "Valued Patron")
    total_price = f"{float(order.get('total_price', 0)):,.2f}"
    payment_mode = order.get("payment_mode", "Cash")
    payment_status = str(order.get("payment_status", "success")).capitalize()
    gst_no = getattr(settings, "gst_number", "27AABCM1234F1Z1")
    order_date = order.get("order_datetime")
    if hasattr(order_date, "strftime"):
        date_str = order_date.strftime("%d %B %Y, %I:%M %p")
    else:
        date_str = str(order_date or "Today")

    items = order.get("items", [])
    items_rows_html = ""
    for idx, itm in enumerate(items, start=1):
        p_name = itm.get("product_name") if isinstance(itm, dict) else getattr(itm, "product_name", "")
        qty = itm.get("quantity") if isinstance(itm, dict) else getattr(itm, "quantity", 1)
        unit = itm.get("unit_price") if isinstance(itm, dict) else getattr(itm, "unit_price", 0)
        tot = itm.get("total_price") if isinstance(itm, dict) else getattr(itm, "total_price", 0)
        items_rows_html += f"""
        <tr>
            <td style="padding: 10px 12px; border-bottom: 1px solid #e8dfd3; color: #333;">{idx}</td>
            <td style="padding: 10px 12px; border-bottom: 1px solid #e8dfd3; color: #1a1a1a; font-weight: 600;">{p_name}</td>
            <td style="padding: 10px 12px; border-bottom: 1px solid #e8dfd3; color: #555; text-align: center;">{qty}</td>
            <td style="padding: 10px 12px; border-bottom: 1px solid #e8dfd3; color: #555; text-align: right;">₹{float(unit):,.2f}</td>
            <td style="padding: 10px 12px; border-bottom: 1px solid #e8dfd3; color: #b48c20; font-weight: 600; text-align: right;">₹{float(tot):,.2f}</td>
        </tr>
        """

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>MOHERA Tax Invoice #{order_id}</title>
    </head>
    <body style="margin: 0; padding: 20px; background-color: #f7f5f0; font-family: 'Helvetica Neue', Arial, sans-serif;">
        <table width="100%" cellpadding="0" cellspacing="0" style="max-width: 680px; margin: 0 auto; background: #ffffff; border: 1px solid #d4af37; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 20px rgba(0,0,0,0.06);">
            <!-- Header -->
            <tr>
                <td style="background: linear-gradient(135deg, #111111, #24211a); padding: 32px 30px; text-align: center; border-bottom: 3px solid #b48c20;">
                    <h1 style="margin: 0; color: #d4af37; font-size: 24px; letter-spacing: 0.25em; text-transform: uppercase;">MOHERA</h1>
                    <p style="margin: 6px 0 0; color: #e5d5be; font-size: 11px; letter-spacing: 0.15em; text-transform: uppercase;">Haute Parfumerie • Artisanal Scents</p>
                    <p style="margin: 8px 0 0; color: #b48c20; font-size: 11px;">GSTIN: {gst_no}</p>
                </td>
            </tr>

            <!-- Body -->
            <tr>
                <td style="padding: 30px;">
                    <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom: 24px;">
                        <tr>
                            <td valign="top">
                                <h2 style="margin: 0 0 8px; color: #1a1a1a; font-size: 18px; font-weight: 600;">Tax Invoice & Receipt</h2>
                                <p style="margin: 0; color: #666; font-size: 13px;">Invoice No: <strong style="color: #1a1a1a;">#MOH-ORD-{order_id}</strong></p>
                                <p style="margin: 4px 0 0; color: #666; font-size: 13px;">Date: {date_str}</p>
                            </td>
                            <td valign="top" style="text-align: right;">
                                <span style="display: inline-block; padding: 4px 12px; background: #ecfdf5; color: #065f46; border: 1px solid #a7f3d0; border-radius: 20px; font-size: 12px; font-weight: 600; text-transform: uppercase;">
                                    {payment_status}
                                </span>
                                <p style="margin: 6px 0 0; color: #777; font-size: 12px;">Paid via: {payment_mode}</p>
                            </td>
                        </tr>
                    </table>

                    <!-- Customer Info Box -->
                    <div style="background: #faf8f5; border: 1px solid #e8dfd3; border-radius: 8px; padding: 16px; margin-bottom: 24px;">
                        <h4 style="margin: 0 0 6px; color: #b48c20; font-size: 12px; letter-spacing: 0.1em; text-transform: uppercase;">Billed To:</h4>
                        <p style="margin: 0; color: #1a1a1a; font-size: 14px; font-weight: 600;">{customer_name}</p>
                        <p style="margin: 3px 0 0; color: #555; font-size: 13px;">Phone: {order.get('phone', '—')} | Email: {recipient}</p>
                        <p style="margin: 3px 0 0; color: #555; font-size: 13px;">Delivery: {order.get('address', '—')}</p>
                    </div>

                    <!-- Items Table -->
                    <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse: collapse; margin-bottom: 20px; font-size: 13px;">
                        <thead>
                            <tr style="background: #faf8f5;">
                                <th style="padding: 10px 12px; text-align: left; border-bottom: 2px solid #b48c20; color: #555; font-size: 11px; text-transform: uppercase;">#</th>
                                <th style="padding: 10px 12px; text-align: left; border-bottom: 2px solid #b48c20; color: #555; font-size: 11px; text-transform: uppercase;">Fragrance Description</th>
                                <th style="padding: 10px 12px; text-align: center; border-bottom: 2px solid #b48c20; color: #555; font-size: 11px; text-transform: uppercase;">Qty</th>
                                <th style="padding: 10px 12px; text-align: right; border-bottom: 2px solid #b48c20; color: #555; font-size: 11px; text-transform: uppercase;">Rate</th>
                                <th style="padding: 10px 12px; text-align: right; border-bottom: 2px solid #b48c20; color: #555; font-size: 11px; text-transform: uppercase;">Amount</th>
                            </tr>
                        </thead>
                        <tbody>
                            {items_rows_html}
                        </tbody>
                    </table>

                    <!-- Total Section -->
                    <table width="100%" cellpadding="0" cellspacing="0" style="margin-top: 10px;">
                        <tr>
                            <td width="55%"></td>
                            <td width="45%">
                                <table width="100%" cellpadding="0" cellspacing="0" style="font-size: 13px;">
                                    <tr>
                                        <td style="padding: 4px 0; color: #666;">Taxes (GST Included):</td>
                                        <td style="padding: 4px 0; color: #1a1a1a; text-align: right;">18% Included</td>
                                    </tr>
                                    <tr>
                                        <td style="padding: 8px 0; border-top: 2px solid #b48c20; font-size: 16px; font-weight: 700; color: #1a1a1a;">Grand Total:</td>
                                        <td style="padding: 8px 0; border-top: 2px solid #b48c20; font-size: 18px; font-weight: 700; color: #b48c20; text-align: right;">₹{total_price}</td>
                                    </tr>
                                </table>
                            </td>
                        </tr>
                    </table>

                    <!-- Note -->
                    <div style="margin-top: 30px; padding: 14px 18px; background: #fffcf5; border-left: 3px solid #b48c20; border-radius: 4px; font-size: 12px; color: #666;">
                        Thank you for your patronage. Every MOHERA bottle is bottled and packed with precision. Keep stored away from direct sunlight for supreme longevity.
                    </div>
                </td>
            </tr>

            <!-- Footer -->
            <tr>
                <td style="background: #faf8f5; padding: 18px 30px; text-align: center; border-top: 1px solid #e8dfd3; color: #888; font-size: 11px;">
                    MOHERA Haute Parfumerie • www.mohera.in • Inquiries: narayanyash10@gmail.com
                </td>
            </tr>
        </table>
    </body>
    </html>
    """

    message = EmailMessage()
    message["Subject"] = f"Tax Invoice & Order Confirmation #MOH-ORD-{order_id} | MOHERA Haute Parfumerie"
    message["From"] = settings.smtp_from_email
    message["To"] = recipient
    message.set_content(
        f"Dear {customer_name},\n\nThank you for choosing MOHERA Haute Parfumerie.\n"
        f"Your Order #MOH-ORD-{order_id} has been recorded.\n"
        f"Grand Total: INR {total_price} ({payment_mode} - {payment_status})\n\n"
        f"Warm regards,\nMOHERA Fragrances"
    )
    message.add_alternative(html_content, subtype="html")

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as server:
            if settings.smtp_use_tls:
                server.starttls(context=ssl.create_default_context())
            if settings.smtp_username:
                server.login(settings.smtp_username, settings.smtp_password)
            server.send_message(message)
        logger.info("Order receipt email sent to %s for Order #%s", recipient, order_id)
        return True
    except Exception as exc:
        logger.warning("Failed to send order receipt email to %s: %s", recipient, exc)
        return False
