"""
Daily Email Report Service
Sends daily summary emails to tenants with chat analytics
"""
import logging
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from typing import List

logger = logging.getLogger(__name__)


def generate_daily_report_html(
    tenant_name: str,
    sessions: int,
    messages: int,
    leads: List[dict],
    positive_feedback: int,
    negative_feedback: int,
    top_topics: List[dict],
) -> str:
    """Generate HTML email content for daily report."""
    
    leads_html = ""
    if leads:
        for lead in leads:
            leads_html += f"""
            <tr>
                <td style="padding:8px;border-bottom:1px solid #eee">{lead.get('name', '-')}</td>
                <td style="padding:8px;border-bottom:1px solid #eee">{lead.get('email', '-')}</td>
                <td style="padding:8px;border-bottom:1px solid #eee">{lead.get('phone', '-')}</td>
                <td style="padding:8px;border-bottom:1px solid #eee">{lead.get('collected_at', '-')}</td>
            </tr>
            """
    else:
        leads_html = "<tr><td colspan='4' style='padding:8px;color:#888'>No new leads today</td></tr>"
    
    topics_html = ""
    if top_topics:
        for topic in top_topics[:5]:
            topics_html += f"<li>{topic.get('topic', '-')} ({topic.get('count', 0)})</li>"
    else:
        topics_html = "<li>No topics recorded</li>"
    
    alerts_html = ""
    if negative_feedback > 0:
        alerts_html = f"""
        <div style="background:#fee;padding:12px;border-radius:8px;margin:10px 0;">
            ⚠️ <strong>{negative_feedback} negative feedback</strong> - Check for quality issues
        </div>
        """
    
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Daily Report - {tenant_name}</title>
    </head>
    <body style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:20px;background:#f5f5f5;">
        <div style="background:white;padding:20px;border-radius:8px;">
            <h1 style="color:#2563eb;margin:0 0 20px 0;">📊 {tenant_name} - Daily Chat Report</h1>
            <p style="color:#666;">Report for {datetime.now().strftime('%B %d, %Y')}</p>
            
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:15px;margin:20px 0;">
                <div style="background:#f0f9ff;padding:15px;border-radius:8px;text-align:center;">
                    <div style="font-size:24px;font-weight:bold;color:#2563eb;">{sessions}</div>
                    <div style="color:#666;font-size:12px;">Chat Sessions</div>
                </div>
                <div style="background:#f0fdf4;padding:15px;border-radius:8px;text-align:center;">
                    <div style="font-size:24px;font-weight:bold;color:#16a34a;">{messages}</div>
                    <div style="color:#666;font-size:12px;">Messages</div>
                </div>
            </div>
            
            <div style="background:#faf5ff;padding:15px;border-radius:8px;margin:20px 0;">
                <h3 style="margin:0 0 10px 0;">📋 New Leads ({len(leads)})</h3>
                <table style="width:100%;border-collapse:collapse;">
                    <thead>
                        <tr style="background:#f5f5f5;">
                            <th style="padding:8px;text-align:left;">Name</th>
                            <th style="padding:8px;text-align:left;">Email</th>
                            <th style="padding:8px;text-align:left;">Phone</th>
                            <th style="padding:8px;text-align:left;">Collected</th>
                        </tr>
                    </thead>
                    <tbody>{leads_html}</tbody>
                </table>
            </div>
            
            <div style="background:#fffbeb;padding:15px;border-radius:8px;margin:20px 0;">
                <h3 style="margin:0 0 10px 0;">📈 Quality Metrics</h3>
                <div style="display:flex;gap:20px;">
                    <div>✅ Positive: <strong style="color:#16a34a;">{positive_feedback}</strong></div>
                    <div>❌ Negative: <strong style="color:#dc2626;">{negative_feedback}</strong></div>
                </div>
                {alerts_html}
            </div>
            
            <div style="background:#f9fafb;padding:15px;border-radius:8px;margin:20px 0;">
                <h3 style="margin:0 0 10px 0;">💬 Top Topics Discussed</h3>
                <ul style="margin:0;padding-left:20px;">{topics_html}</ul>
            </div>
            
            <p style="color:#888;font-size:12px;margin-top:30px;border-top:1px solid #eee;padding-top:15px;">
                This is an automated daily report from your Chatbot Platform.<br>
                To update settings, login to your dashboard.
            </p>
        </div>
    </body>
    </html>
    """


def generate_daily_report_text(
    tenant_name: str,
    sessions: int,
    messages: int,
    leads: List[dict],
    positive_feedback: int,
    negative_feedback: int,
    top_topics: List[dict],
) -> str:
    """Generate plain text email content for daily report."""
    
    leads_text = "\n".join([
        f"  - {l.get('name', '-')} | {l.get('email', '-')} | {l.get('phone', '-')}"
        for l in leads
    ]) if leads else "  No new leads today"
    
    topics_text = "\n".join([
        f"  - {t.get('topic', '-')} ({t.get('count', 0)})"
        for t in top_topics[:5]
    ]) if top_topics else "  No topics recorded"
    
    return f"""
{tenant_name} - Daily Chat Report
{datetime.now().strftime('%B %d, %Y')}
{'='*50}

SUMMARY
  Sessions: {sessions}
  Messages: {messages}
  New Leads: {len(leads)}

LEADS
{leads_text}

QUALITY METRICS
  Positive Feedback: {positive_feedback}
  Negative Feedback: {negative_feedback}

TOP TOPICS
{topics_text}

{'='*50}
This is an automated daily report from your Chatbot Platform.
"""


async def send_daily_reports(db: Session) -> dict:
    """Send daily reports to all enabled tenants."""
    from app.models import Tenant, ChatSession, ChatMessage
    
    results = {"sent": 0, "skipped": 0, "errors": 0}
    
    # Get all tenants with daily reports enabled
    tenants = db.query(Tenant).filter(
        Tenant.daily_report_enabled == True,
        Tenant.daily_report_email.isnot(None)
    ).all()
    
    today = datetime.now(timezone.utc).date()
    yesterday_start = datetime.combine(today - timedelta(days=1), datetime.min.time()).replace(tzinfo=timezone.utc)
    today_end = datetime.combine(today, datetime.max.time()).replace(tzinfo=timezone.utc)
    
    for tenant in tenants:
        try:
            # Get stats for yesterday
            sessions = db.query(ChatSession).filter(
                ChatSession.tenant_id == tenant.id,
                ChatSession.created_at >= yesterday_start,
                ChatSession.created_at <= today_end
            ).count()
            
            messages = db.query(ChatMessage).filter(
                ChatMessage.tenant_id == tenant.id,
                ChatMessage.role == "user",
                ChatMessage.created_at >= yesterday_start,
                ChatMessage.created_at <= today_end
            ).count()
            
            leads_sessions = db.query(ChatSession).filter(
                ChatSession.tenant_id == tenant.id,
                ChatSession.lead_name.isnot(None),
                ChatSession.lead_collected_at >= yesterday_start,
                ChatSession.lead_collected_at <= today_end
            ).all()
            
            leads = [{
                "name": s.lead_name,
                "email": s.lead_email,
                "phone": s.lead_phone,
                "collected_at": s.lead_collected_at.strftime("%Y-%m-%d %H:%M") if s.lead_collected_at else "-"
            } for s in leads_sessions]
            
            pos_feedback = db.query(ChatMessage).filter(
                ChatMessage.tenant_id == tenant.id,
                ChatMessage.role == "assistant",
                ChatMessage.feedback_score == 1,
                ChatMessage.created_at >= yesterday_start,
                ChatMessage.created_at <= today_end
            ).count()
            
            neg_feedback = db.query(ChatMessage).filter(
                ChatMessage.tenant_id == tenant.id,
                ChatMessage.role == "assistant",
                ChatMessage.feedback_score == -1,
                ChatMessage.created_at >= yesterday_start,
                ChatMessage.created_at <= today_end
            ).count()
            
            # Get top topics
            user_msgs = db.query(ChatMessage).filter(
                ChatMessage.tenant_id == tenant.id,
                ChatMessage.role == "user",
                ChatMessage.created_at >= yesterday_start,
                ChatMessage.created_at <= today_end
            ).all()
            
            topic_words = {}
            stop_words = {'the', 'a', 'an', 'is', 'are', 'was', 'i', 'you', 'we', 'it', 'to', 'of', 'my', 'and', 'or', 'but', 'how', 'what', 'can', 'do', 'hi', 'hello', 'thanks', 'please'}
            for msg in user_msgs:
                words = msg.content.lower().split()
                for w in words:
                    if len(w) > 4 and w not in stop_words:
                        topic_words[w] = topic_words.get(w, 0) + 1
            
            top_topics = sorted(topic_words.items(), key=lambda x: x[1], reverse=True)[:5]
            top_topics = [{"topic": t[0], "count": t[1]} for t in top_topics]
            
            # Generate email content
            html_body = generate_daily_report_html(
                tenant.name, sessions, messages, leads, pos_feedback, neg_feedback, top_topics
            )
            text_body = generate_daily_report_text(
                tenant.name, sessions, messages, leads, pos_feedback, neg_feedback, top_topics
            )
            
            # Send email
            from app.services.email_service import send_email
            subject = f"📊 Daily Report: {tenant.name} - {datetime.now().strftime('%b %d')}"
            
            email_result = await send_email(
                to=tenant.daily_report_email,
                subject=subject,
                html_body=html_body,
                text_body=text_body
            )
            
            if email_result:
                results["sent"] += 1
                logger.info(f"[DailyReport] Sent to {tenant.name} ({tenant.daily_report_email})")
            else:
                results["skipped"] += 1
                
        except Exception as e:
            results["errors"] += 1
            logger.error(f"[DailyReport] Error for {tenant.name}: {e}")
    
    return results