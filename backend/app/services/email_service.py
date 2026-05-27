"""
Email Service - Supports SMTP sending
"""
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional

logger = logging.getLogger(__name__)


class EmailConfig:
    """Email configuration from environment"""
    
    # SMTP Settings
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""  # Your email
    SMTP_PASSWORD: str = ""  # Your app password
    SMTP_FROM: str = ""  # From email address
    SMTP_FROM_NAME: str = "ChatBot Platform"
    
    # Or use environment variables
    @classmethod
    def load_from_env(cls):
        import os
        cls.SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
        cls.SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
        cls.SMTP_USER = os.getenv("SMTP_USER", "")
        cls.SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
        cls.SMTP_FROM = os.getenv("SMTP_FROM", cls.SMTP_USER)
        cls.SMTP_FROM_NAME = os.getenv("SMTP_FROM_NAME", "ChatBot Platform")


async def send_email(
    to: str,
    subject: str,
    html_body: str,
    text_body: Optional[str] = None,
) -> bool:
    """
    Send email via SMTP
    
    Args:
        to: Recipient email address
        subject: Email subject
        html_body: HTML email body
        text_body: Plain text fallback body
    
    Returns:
        True if sent successfully, False otherwise
    """
    EmailConfig.load_from_env()
    
    # Check if SMTP is configured
    if not EmailConfig.SMTP_USER or not EmailConfig.SMTP_PASSWORD:
        logger.warning(f"[Email] SMTP not configured. Would send to {to}: {subject}")
        logger.info(f"[Email] Configure SMTP_HOST, SMTP_USER, SMTP_PASSWORD in .env to enable")
        return True  # Return True so it doesn't retry
    
    if text_body is None:
        text_body = html_body.replace("<br>", "\n").replace("<p>", "").replace("</p>", "\n")
    
    try:
        # Create message
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = f"{EmailConfig.SMTP_FROM_NAME} <{EmailConfig.SMTP_FROM}>"
        msg['To'] = to
        
        # Attach plain text
        text_part = MIMEText(text_body, 'plain')
        msg.attach(text_part)
        
        # Attach HTML
        html_part = MIMEText(html_body, 'html')
        msg.attach(html_part)
        
        # Send via SMTP
        server = smtplib.SMTP(EmailConfig.SMTP_HOST, EmailConfig.SMTP_PORT)
        server.starttls()
        server.login(EmailConfig.SMTP_USER, EmailConfig.SMTP_PASSWORD)
        server.sendmail(EmailConfig.SMTP_FROM, to, msg.as_string())
        server.quit()
        
        logger.info(f"[Email] Sent to {to}: {subject}")
        return True
        
    except smtplib.SMTPAuthenticationError:
        logger.error(f"[Email] SMTP authentication failed for {to}")
        return False
    except Exception as e:
        logger.error(f"[Email] Failed to send to {to}: {e}")
        return False


async def send_daily_report(
    to: str,
    tenant_name: str,
    sessions: int,
    messages: int,
    leads: list,
    positive_feedback: int,
    negative_feedback: int,
    top_topics: list,
) -> bool:
    """Send daily report email."""
    from app.services.daily_report import generate_daily_report_html, generate_daily_report_text
    
    import datetime
    subject = f"📊 Daily Report: {tenant_name} - {datetime.datetime.now().strftime('%b %d')}"
    
    html_body = generate_daily_report_html(
        tenant_name, sessions, messages, leads, positive_feedback, negative_feedback, top_topics
    )
    text_body = generate_daily_report_text(
        tenant_name, sessions, messages, leads, positive_feedback, negative_feedback, top_topics
    )
    
    return await send_email(to, subject, html_body, text_body)
