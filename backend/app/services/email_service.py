import logging
import smtplib
import ssl
from html import escape
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session

from app.config.settings import settings

logger = logging.getLogger(__name__)

class EmailService:
    @staticmethod
    def _dispatch_smtp(to_email: str, subject: str, text_content: str, html_content: str) -> bool:
        """
        Sends an email using configured SMTP credentials (e.g. Gmail SMTP).
        """
        clean_email = to_email.strip().lower()
        smtp_user = settings.SMTP_USER.strip()
        smtp_password = settings.SMTP_PASSWORD.replace(" ", "").strip()
        smtp_host = settings.SMTP_HOST.strip() or "smtp.gmail.com"
        smtp_port = int(settings.SMTP_PORT or 587)
        from_email = settings.SMTP_FROM_EMAIL.strip() or smtp_user
        from_name = settings.SMTP_FROM_NAME.strip() or "Achuppori Cloud Print"

        if not (smtp_user and smtp_password):
            logger.warning("[EMAIL] SMTP credentials incomplete; email was not sent.")
            return False

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"{from_name} <{from_email}>"
        msg["To"] = clean_email

        part1 = MIMEText(text_content, "plain", "utf-8")
        part2 = MIMEText(html_content, "html", "utf-8")
        msg.attach(part1)
        msg.attach(part2)

        try:
            context = ssl.create_default_context()
            with smtplib.SMTP(smtp_host, smtp_port, timeout=12.0) as server:
                server.ehlo()
                server.starttls(context=context)
                server.ehlo()
                server.login(smtp_user, smtp_password)
                server.sendmail(from_email, [clean_email], msg.as_string())
            logger.info(f"[EMAIL] Email successfully sent to {clean_email} (Subject: {subject})")
            return True
        except Exception as e:
            logger.exception(f"[EMAIL] Failed to send email to {clean_email} via SMTP: {e}")
            return False

    @staticmethod
    def send_otp(email: str, otp: str, purpose: str = "login") -> bool:
        """
        Dispatches OTP code to the given email address using Gmail SMTP or configured provider.
        """
        clean_email = email.strip().lower()
        provider = (settings.EMAIL_PROVIDER or "smtp").lower().strip()

        if provider == "smtp":
            return EmailService._send_smtp(clean_email, otp, purpose)
        else:
            logger.info(f"[EMAIL MOCK] To: {clean_email} | Code: {otp} | Purpose: {purpose}")
            print(f"\n=======================================================", flush=True)
            print(f"[ACHUPPORI EMAIL OTP] Email: {clean_email} | Code: {otp} | Purpose: {purpose}", flush=True)
            print(f"=======================================================\n", flush=True)
            return True

    @staticmethod
    def _send_smtp(to_email: str, otp: str, purpose: str = "login") -> bool:
        clean_email = to_email.strip().lower()
        subject = f"Your Achuppori Verification Code: {otp}"
        action_text = "register your student account" if purpose == "signup" else "sign in to your student account"

        text_content = (
            f"Achuppori Cloud Print Verification\n\n"
            f"Your one-time verification code is: {otp}\n\n"
            f"Use this code to {action_text}. This code will expire in 5 minutes.\n"
            f"If you did not request this verification code, please ignore this email.\n\n"
            f"-- Achuppori Support"
        )

        html_content = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Verification Code</title>
</head>
<body style="margin: 0; padding: 0; background-color: #F8FAFC; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background-color: #F8FAFC; padding: 30px 15px;">
    <tr>
      <td align="center">
        <table role="presentation" width="100%" style="max-width: 500px; background-color: #FFFFFF; border-radius: 16px; border: 1px solid #E2E8F0; overflow: hidden; box-shadow: 0 4px 12px rgba(15, 23, 42, 0.04);">
          <tr>
            <td style="background-color: #2563EB; padding: 24px 30px; text-align: center;">
              <h1 style="margin: 0; color: #FFFFFF; font-size: 20px; font-weight: 700; letter-spacing: 0.5px;">Achuppori Cloud Print</h1>
            </td>
          </tr>
          <tr>
            <td style="padding: 30px;">
              <h2 style="margin: 0 0 12px 0; color: #0F172A; font-size: 18px; font-weight: 600;">Verification Code</h2>
              <p style="margin: 0 0 20px 0; color: #475569; font-size: 14px; line-height: 1.5;">
                Use the one-time code below to {action_text}:
              </p>
              <div style="background-color: #EFF6FF; border: 1.5px dashed #3B82F6; border-radius: 12px; padding: 18px; text-align: center; margin-bottom: 24px;">
                <span style="font-size: 32px; font-weight: 800; letter-spacing: 8px; color: #1D4ED8; font-family: monospace;">{otp}</span>
              </div>
              <p style="margin: 0 0 8px 0; color: #64748B; font-size: 13px;">
                • Code expires in <strong>5 minutes</strong>.
              </p>
              <p style="margin: 0 0 24px 0; color: #64748B; font-size: 13px;">
                • Never share this code with anyone.
              </p>
              <hr style="border: none; border-top: 1px solid #E2E8F0; margin: 20px 0;">
              <p style="margin: 0; color: #94A3B8; font-size: 12px; line-height: 1.4;">
                If you did not request this verification code, you can safely disregard this email.
              </p>
            </td>
          </tr>
          <tr>
            <td style="background-color: #F8FAFC; padding: 16px 30px; text-align: center; border-top: 1px solid #E2E8F0;">
              <p style="margin: 0; color: #94A3B8; font-size: 11px;">
                © {settings.APP_NAME} Cloud Print Platform. All rights reserved.
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""
        return EmailService._dispatch_smtp(clean_email, subject, text_content, html_content)

    @staticmethod
    def send_order_status_notification(
        to_email: str,
        order_id: str,
        status: str,
        recipient_name: Optional[str] = None,
        otp_code: Optional[str] = None,
        station_name: Optional[str] = None,
        printer_name: Optional[str] = None,
        document_name: Optional[str] = None,
        total_pages: Optional[int] = None,
        copies: Optional[int] = None,
        amount: Optional[float] = None,
        currency: str = "INR",
        error_message: Optional[str] = None,
        refund_status: Optional[str] = None,
    ) -> bool:
        """
        Sends an order/print status notification email to the customer.
        """
        clean_email = to_email.strip().lower()
        if not clean_email:
            return False

        clean_status = (status or "").upper().strip()
        status_badges = {
            "WAITING_FOR_OTP": {
                "title": "Print Order Ready for Release",
                "badge_bg": "#EFF6FF",
                "badge_color": "#1D4ED8",
                "badge_text": "Ready for Release",
                "subject": f"Print Order Confirmed - Release Code: {otp_code or order_id} | {order_id}",
                "message": "Your print order has been confirmed and is waiting to be printed. Enter your release code at the station kiosk touchscreen to release and print your pages.",
            },
            "PRINTING": {
                "title": "Printing in Progress",
                "badge_bg": "#FEF3C7",
                "badge_color": "#B45309",
                "badge_text": "Printing in Progress",
                "subject": f"Printing Started - Order #{order_id}",
                "message": "Your print job has started. Please stand by at the printer tray to collect your printed pages.",
            },
            "COMPLETED": {
                "title": "Print Job Completed",
                "badge_bg": "#DCFCE7",
                "badge_color": "#15803D",
                "badge_text": "Completed",
                "subject": f"Print Completed - Order #{order_id}",
                "message": "Your document has been successfully printed. Please collect your pages from the printer tray.",
            },
            "FAILED": {
                "title": "Print Job Failed",
                "badge_bg": "#FEE2E2",
                "badge_color": "#B91C1C",
                "badge_text": "Failed",
                "subject": f"Print Failed - Order #{order_id}",
                "message": f"Your print job could not be completed. {error_message or 'The printer reported an error.'} Check your order for the current refund status.",
            },
            "REFUNDED": {
                "title": "Refund Processed",
                "badge_bg": "#F3E8FF",
                "badge_color": "#6B21A8",
                "badge_text": "Refunded",
                "subject": f"Refund Processed - Order #{order_id}",
                "message": f"A refund has been issued for your print order #{order_id}.",
            },
            "CANCELLED": {
                "title": "Order Cancelled",
                "badge_bg": "#F1F5F9",
                "badge_color": "#475569",
                "badge_text": "Cancelled",
                "subject": f"Order Cancelled - #{order_id}",
                "message": f"Your print order #{order_id} has been cancelled.",
            },
        }

        meta = status_badges.get(clean_status, {
            "title": f"Order Status Update: {clean_status}",
            "badge_bg": "#F1F5F9",
            "badge_color": "#334155",
            "badge_text": clean_status,
            "subject": f"Order Update: {clean_status} - #{order_id}",
            "message": f"Your print order #{order_id} status is now {clean_status}.",
        })

        name_greeting = f"Hello {recipient_name}," if recipient_name else "Hello,"

        # Build Plain text representation
        text_lines = [
            f"Achuppori Cloud Print - {meta['title']}",
            "",
            name_greeting,
            "",
            meta["message"],
            "",
        ]
        if clean_status == "WAITING_FOR_OTP" and otp_code:
            text_lines.extend([
                f"RELEASE CODE: {otp_code}",
                "Enter this code on the station touchscreen to start printing.",
                "",
            ])
        text_lines.extend([
            "Order Details:",
            f"- Order ID: {order_id}",
            f"- Status: {meta['badge_text']}",
        ])
        if station_name:
            text_lines.append(f"- Station: {station_name}")
        if printer_name:
            text_lines.append(f"- Printer: {printer_name}")
        if document_name:
            text_lines.append(f"- Document: {document_name}")
        if total_pages is not None:
            text_lines.append(f"- Total Pages: {total_pages} (Copies: {copies or 1})")
        if amount is not None:
            text_lines.append(f"- Amount: {currency} {amount:.2f}")
        if error_message and clean_status == "FAILED":
            text_lines.append(f"- Reason: {error_message}")
        if refund_status:
            text_lines.append(f"- Refund Status: {refund_status}")
        text_lines.extend([
            "",
            "-- Achuppori Cloud Print Support"
        ])
        text_content = "\n".join(text_lines)

        subject = meta["subject"]
        # Escape every dynamic string used in HTML; plain text above stays intact.
        meta = {key: escape(str(value), quote=True) for key, value in meta.items()}
        name_greeting = escape(name_greeting, quote=True)
        order_id = escape(order_id, quote=True)
        otp_code = escape(otp_code, quote=True) if otp_code else None
        station_name = escape(station_name, quote=True) if station_name else None
        printer_name = escape(printer_name, quote=True) if printer_name else None
        document_name = escape(document_name, quote=True) if document_name else None
        error_message = escape(error_message, quote=True) if error_message else None
        refund_status = escape(refund_status, quote=True) if refund_status else None
        currency = escape(currency, quote=True)

        # Build OTP Box HTML if applicable
        otp_box_html = ""
        if clean_status == "WAITING_FOR_OTP" and otp_code:
            otp_box_html = f"""
              <div style="background-color: #EFF6FF; border: 1.5px dashed #3B82F6; border-radius: 12px; padding: 20px; text-align: center; margin: 20px 0 24px 0;">
                <div style="font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 1px; color: #1D4ED8; margin-bottom: 6px;">Kiosk Release Code</div>
                <div style="font-size: 32px; font-weight: 800; letter-spacing: 8px; color: #1D4ED8; font-family: monospace;">{otp_code}</div>
                <p style="margin: 8px 0 0 0; color: #475569; font-size: 13px;">Enter this 6-digit code on the station touchscreen to print.</p>
              </div>
            """

        # Build summary table rows
        rows_html = f"""
          <tr>
            <td style="padding: 8px 0; color: #64748B; font-size: 13px; width: 140px;">Order ID</td>
            <td style="padding: 8px 0; color: #0F172A; font-size: 13px; font-weight: 600; font-family: monospace;">{order_id}</td>
          </tr>
          <tr>
            <td style="padding: 8px 0; color: #64748B; font-size: 13px;">Status</td>
            <td style="padding: 8px 0;">
              <span style="display: inline-block; background-color: {meta['badge_bg']}; color: {meta['badge_color']}; font-size: 12px; font-weight: 600; padding: 3px 10px; border-radius: 6px;">
                {meta['badge_text']}
              </span>
            </td>
          </tr>
        """
        if station_name:
            rows_html += f"""
              <tr>
                <td style="padding: 8px 0; color: #64748B; font-size: 13px;">Station</td>
                <td style="padding: 8px 0; color: #0F172A; font-size: 13px; font-weight: 500;">{station_name}</td>
              </tr>
            """
        if printer_name:
            rows_html += f"""
              <tr>
                <td style="padding: 8px 0; color: #64748B; font-size: 13px;">Printer</td>
                <td style="padding: 8px 0; color: #0F172A; font-size: 13px; font-weight: 500;">{printer_name}</td>
              </tr>
            """
        if document_name:
            rows_html += f"""
              <tr>
                <td style="padding: 8px 0; color: #64748B; font-size: 13px;">Document</td>
                <td style="padding: 8px 0; color: #0F172A; font-size: 13px; font-weight: 500;">{document_name}</td>
              </tr>
            """
        if total_pages is not None:
            rows_html += f"""
              <tr>
                <td style="padding: 8px 0; color: #64748B; font-size: 13px;">Pages & Copies</td>
                <td style="padding: 8px 0; color: #0F172A; font-size: 13px; font-weight: 500;">{total_pages} page(s) × {copies or 1} copy</td>
              </tr>
            """
        if amount is not None:
            rows_html += f"""
              <tr>
                <td style="padding: 8px 0; color: #64748B; font-size: 13px;">Total Amount</td>
                <td style="padding: 8px 0; color: #0F172A; font-size: 13px; font-weight: 600;">{currency} {amount:.2f}</td>
              </tr>
            """
        if error_message and clean_status == "FAILED":
            rows_html += f"""
              <tr>
                <td style="padding: 8px 0; color: #B91C1C; font-size: 13px;">Failure Reason</td>
                <td style="padding: 8px 0; color: #B91C1C; font-size: 13px; font-weight: 500;">{error_message}</td>
              </tr>
            """
        if refund_status:
            rows_html += f"""
              <tr>
                <td style="padding: 8px 0; color: #6B21A8; font-size: 13px;">Refund Status</td>
                <td style="padding: 8px 0; color: #6B21A8; font-size: 13px; font-weight: 500;">{refund_status}</td>
              </tr>
            """

        html_content = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{meta['title']}</title>
</head>
<body style="margin: 0; padding: 0; background-color: #F8FAFC; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background-color: #F8FAFC; padding: 30px 15px;">
    <tr>
      <td align="center">
        <table role="presentation" width="100%" style="max-width: 520px; background-color: #FFFFFF; border-radius: 16px; border: 1px solid #E2E8F0; overflow: hidden; box-shadow: 0 4px 12px rgba(15, 23, 42, 0.04);">
          <!-- Header -->
          <tr>
            <td style="background-color: #2563EB; padding: 22px 28px; text-align: center;">
              <h1 style="margin: 0; color: #FFFFFF; font-size: 19px; font-weight: 700; letter-spacing: 0.5px;">Achuppori Cloud Print</h1>
            </td>
          </tr>
          <!-- Body -->
          <tr>
            <td style="padding: 28px;">
              <p style="margin: 0 0 14px 0; color: #334155; font-size: 14px; font-weight: 500;">
                {name_greeting}
              </p>
              <h2 style="margin: 0 0 10px 0; color: #0F172A; font-size: 18px; font-weight: 700;">
                {meta['title']}
              </h2>
              <p style="margin: 0 0 18px 0; color: #475569; font-size: 14px; line-height: 1.5;">
                {meta['message']}
              </p>

              {otp_box_html}

              <div style="background-color: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 12px; padding: 18px; margin: 18px 0;">
                <div style="font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; color: #64748B; margin-bottom: 12px;">Order Summary</div>
                <table role="presentation" width="100%" cellspacing="0" cellpadding="0">
                  {rows_html}
                </table>
              </div>

              <hr style="border: none; border-top: 1px solid #E2E8F0; margin: 20px 0;">

              <p style="margin: 0; color: #94A3B8; font-size: 12px; line-height: 1.4;">
                This is an automated status notification regarding order {order_id}. If you have questions, contact station attendants.
              </p>
            </td>
          </tr>
          <!-- Footer -->
          <tr>
            <td style="background-color: #F8FAFC; padding: 16px 28px; text-align: center; border-top: 1px solid #E2E8F0;">
              <p style="margin: 0; color: #94A3B8; font-size: 11px;">
                © {settings.APP_NAME} Autonomous Cloud Print. All rights reserved.
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""

        provider = (settings.EMAIL_PROVIDER or "smtp").lower().strip()
        if provider == "smtp":
            return EmailService._dispatch_smtp(clean_email, subject, text_content, html_content)
        else:
            logger.info(f"[EMAIL MOCK] To: {clean_email} | Subject: {meta['subject']} | Status: {clean_status}")
            print(f"\n=======================================================", flush=True)
            print(f"[ACHUPPORI EMAIL STATUS] To: {clean_email} | Order: {order_id} | Status: {clean_status}", flush=True)
            if otp_code:
                print(f"[ACHUPPORI EMAIL STATUS] Release Code: {otp_code}", flush=True)
            print(f"=======================================================\n", flush=True)
            return True

    @staticmethod
    def notify_order_status(
        db: Session,
        order: Any,
        new_status: Any,
        extra_info: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Extracts order and recipient metadata, resolves email address, and dispatches
        status notification email. Fails safely without raising exceptions.
        """
        try:
            if not getattr(settings, "ENABLE_EMAIL_STATUS_NOTIFICATIONS", True):
                return False

            if not order:
                return False

            settings_dict = dict(order.print_settings or {})
            recipient_email = settings_dict.get("notification_email") or settings_dict.get("email")
            recipient_name = None

            if order.user_id:
                from app.db.models.user import User
                user = db.get(User, order.user_id)
                if user:
                    if not recipient_email and user.email:
                        recipient_email = user.email
                    recipient_name = user.full_name or (user.email.split("@")[0] if user.email else None)

            if not recipient_email and order.document_id:
                from app.db.models.document import Document
                doc = db.get(Document, order.document_id)
                if doc and doc.user_id:
                    from app.db.models.user import User
                    u = db.get(User, doc.user_id)
                    if u and u.email:
                        recipient_email = u.email
                        recipient_name = recipient_name or u.full_name

            if not recipient_email:
                logger.debug(f"[EMAIL] No recipient email found for order {order.id}; status email skipped.")
                return False

            status_str = new_status.value if hasattr(new_status, "value") else str(new_status)

            station_name = None
            if order.print_server_id:
                from app.db.models.print_server import PrintServer
                server = db.get(PrintServer, order.print_server_id)
                if server:
                    station_name = server.name or server.location or server.id

            printer_name = settings_dict.get("printer_name") or settings_dict.get("cups_printer_name")

            otp_code = None
            if status_str == "WAITING_FOR_OTP":
                try:
                    from app.services.otp_service import otp_service
                    otp_code, _, _ = otp_service.get_otp_for_order(db, order.id)
                except Exception:
                    pass

            document_name = None
            if order.document_id:
                from app.db.models.document import Document
                doc = db.get(Document, order.document_id)
                if doc:
                    document_name = doc.original_filename

            error_message = (extra_info or {}).get("error_message")
            refund_status = (extra_info or {}).get("refund_status")

            from app.services.notification_service import enqueue_notification
            return enqueue_notification(db, dict(
                to_email=recipient_email,
                order_id=order.id,
                status=status_str,
                recipient_name=recipient_name,
                otp_code=otp_code,
                station_name=station_name,
                printer_name=printer_name,
                document_name=document_name,
                total_pages=order.total_pages,
                copies=order.copies,
                amount=float(order.amount) if order.amount is not None else None,
                currency=order.currency or "INR",
                error_message=error_message,
                refund_status=refund_status,
            ))
        except Exception as e:
            db.rollback()
            logger.warning(f"[EMAIL] Error in notify_order_status for order {getattr(order, 'id', 'unknown')}: {e}")
            return False

email_service = EmailService()
