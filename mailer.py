import smtplib
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, date, timedelta


def send_reminder_email(to_email: str, username: str, events: list):
    """
    Send a reminder email listing tomorrow's learning events.

    Args:
        to_email:  recipient email address
        username:  student's Elentra username
        events:    list of formatted event dicts (from format_events)
    """
    mail_address = os.getenv("MAIL_ADDRESS")
    mail_password = os.getenv("MAIL_PASSWORD")
    smtp_server   = os.getenv("MAIL_SMTP",    "smtp.gmail.com")
    smtp_port     = int(os.getenv("MAIL_PORT", 587))

    tomorrow = events[0]["date"] if events else "tomorrow"

    # ── Plain text version ──────────────────────
    if not events:
        text_body = f"Hi {username},\n\nYou have no learning events scheduled for tomorrow."
    else:
        lines = [f"Hi {username},\n",
                 f"Here are your learning events for {tomorrow}:\n"]
        for e in events:
            lines.append(f"• {e['title']}")
            lines.append(f"  Time:     {e['time']}")
            lines.append(f"  Location: {e['location']}")
            lines.append(f"  Course:   {e['course_code']}")
            if e['attendance'] == "Required":
                lines.append(f"  ⚠️  Attendance required")
            lines.append("")
        lines.append("Have a good time and see you tomorrow!")
        text_body = "\n".join(lines)

    # ── HTML version ────────────────────────────
    if not events:
        events_html = """
        <div style="padding:20px;background:#f8f9fa;border-radius:8px;text-align:center;color:#6c757d;">
            No learning events scheduled for tomorrow.
        </div>"""
    else:
        cards = ""
        for e in events:
            attendance_badge = ""
            if e['attendance'] == "Required":
                attendance_badge = """
                <span style="display:inline-block;margin-top:8px;padding:3px 10px;
                             background:#fff3cd;border:1px solid #ffc107;border-radius:99px;
                             font-size:12px;color:#856404;">
                    ⚠️ Attendance Required
                </span>"""
            else:
                attendance_badge = """
                <span style="display:inline-block;margin-top:8px;padding:3px 10px;
                             background:#f0f0f0;border:1px solid #cccccc;border-radius:99px;
                             font-size:12px;color:#666666;">
                    ✅ Optional
                </span>"""

            cards += f"""
            <div style="background:#fff;border:1px solid #e9ecef;border-radius:10px;
                        padding:16px 20px;margin-bottom:12px;">
                <div style="font-size:16px;font-weight:600;color:#1a1a2e;margin-bottom:8px;">
                    {e['title']}
                </div>
                <table style="font-size:13px;color:#495057;border-collapse:collapse;">
                    <tr>
                        <td style="padding:2px 12px 2px 0;color:#868e96;">🕐 Time</td>
                        <td style="padding:2px 0;font-weight:500;">{e['time']}</td>
                    </tr>
                    <tr>
                        <td style="padding:2px 12px 2px 0;color:#868e96;">📍 Location</td>
                        <td style="padding:2px 0;">{e['location'] or 'TBC'}</td>
                    </tr>
                    <tr>
                        <td style="padding:2px 12px 2px 0;color:#868e96;">📚 Course</td>
                        <td style="padding:2px 0;">{e['course_code']}</td>
                    </tr>
                    
                    <tr>
                        <td style="padding:3px 12px 3px 0;color:#868e96;">📋 Attendance</td>
                        <td style="padding:3px 0;">
                            <span style="display:inline-block;padding:2px 10px;
                                         background:#fff3cd;
                                         border:1px solid #ffc107;
                                         border-radius:99px;font-size:12px;
                                         color:#666666;font-weight:500;">
                                 {e['attendance']}
                            </span>
                        </td>
                    </tr>
                </table>
                {attendance_badge}
            </div>"""

        events_html = cards

    html_body = f"""
<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"/></head>
<body style="margin:0;padding:0;background:#f0f2f5;font-family:'Segoe UI',Arial,sans-serif;">
    <div style="max-width:560px;margin:32px auto;background:#fff;border:1px solid #e0e0e0;">

    <!-- Header -->
    <div style="background-color:#4a1259;padding:32px 32px 24px;">
      <div style="font-size:13px;color:rgba(255,255,255,0.7);letter-spacing:0.08em;
                  text-transform:uppercase;margin-bottom:6px;">NTU Medicine</div>
      <div style="font-size:24px;font-weight:700;color:#fff;">Tomorrow's Schedule</div>
      <div style="font-size:14px;color:rgba(255,255,255,0.8);margin-top:4px;">{tomorrow}</div>
    </div>

    <!-- Body -->
    <div style="padding:28px 32px;">
      <p style="margin:0 0 20px;font-size:15px;color:#495057;">
        Hi <strong>{username}</strong>, here's what's coming up for you tomorrow:
      </p>

      {events_html}

      <p style="margin:24px 0 0;font-size:13px;color:#868e96;line-height:1.6;">
        This reminder was sent automatically from the NTU MBBS Learning Assistant.<br>
        Log in to the assistant to view your full upcoming schedule.
      </p>
    </div>

    <!-- Footer -->
    <div style="background:#2d1b4e;padding:14px 32px;">
      <p style="margin:0;font-size:12px;color:rgba(255,255,255,0.5);text-align:center;">
        NTU Lee Kong Chian School of Medicine · Sent at 7:00 PM SGT
      </p>
    </div>

  </div>
</body>
</html>"""

    # ── Build and send email ─────────────────────
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f" Tomorrow's Learning Events — {tomorrow}"
    msg["From"]    = mail_address
    msg["To"]      = to_email

    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP(smtp_server, smtp_port) as server:
        server.ehlo()
        server.starttls()
        server.login(mail_address, mail_password)
        server.sendmail(mail_address, to_email, msg.as_string())

    print(f"[MAILER] Reminder sent to {to_email} ({len(events)} events)")


def send_weekly_summary_email(to_email: str, username: str, events: list):
    """
    Send a Monday morning weekly summary email.
    Groups events by day and shows totals.
    """
    mail_address  = os.getenv("MAIL_ADDRESS")
    mail_password = os.getenv("MAIL_PASSWORD")
    smtp_server   = os.getenv("MAIL_SMTP",  "smtp.gmail.com")
    smtp_port     = int(os.getenv("MAIL_PORT", 587))
 
    LKC_PURPLE       = "#4a1259"
    LKC_PURPLE_LIGHT = "#6b2180"
 
    from collections import OrderedDict
 
    # ── Group events by date ─────────────────────
    days = OrderedDict()
    for e in events:
        days.setdefault(e["date"], []).append(e)
 
    # ── Stats ────────────────────────────────────
    total_events   = len(events)
    total_hours    = sum(e["duration_hours"] for e in events)
    required_count = sum(1 for e in events if e["attendance"] == "Required")
 
    # ── Plain text ───────────────────────────────
    if not events:
        text_body = (f"Hi {username},\n\nYou have no learning events scheduled "
                     f"this week.\n\nHave a great week!")
    else:
        lines = [f"Hi {username},\n",
                 f"Here is your learning schedule for this week:\n",
                 f"Total: {total_events} events | "
                 f"{total_hours:.1f} hours | "
                 f"{required_count} attendance required\n"]
        for day, day_events in days.items():
            lines.append(f"\n── {day} ──")
            for e in day_events:
                lines.append(f"  • {e['title']}")
                lines.append(f"    {e['time']} | {e['location'] or 'TBC'} | "
                              f"Attendance: {e['attendance']}")
        lines.append("\nHave a productive week!")
        text_body = "\n".join(lines)
 
    # ── HTML ─────────────────────────────────────
    if not events:
        days_html = """
        <div style="padding:20px;background:#f8f9fa;border-radius:8px;
                    text-align:center;color:#6c757d;">
            No learning events scheduled this week.
        </div>"""
    else:
        days_html = ""
        for day, day_events in days.items():
            day_hours    = sum(e["duration_hours"] for e in day_events)
            day_required = sum(1 for e in day_events if e["attendance"] == "Required")
 
            # Build event rows for this day
            event_rows = ""
            for e in day_events:
                if e["attendance"] == "Required":
                    badge_bg = "#fff3cd"; badge_border = "#ffc107"
                    badge_color = "#856404"; badge_icon = "⚠️"
                else:
                    badge_bg = "#f0f0f0"; badge_border = "#cccccc"
                    badge_color = "#666666"; badge_icon = "✅"
 
                event_rows += f"""
                <tr style="border-bottom:1px solid #f0f0f0;">
                    <td style="padding:10px 12px;font-size:13px;
                               font-weight:500;color:#1a1a2e;width:40%;">
                        {e['title']}
                    </td>
                    <td style="padding:10px 12px;font-size:12px;color:#495057;">
                        🕐 {e['time']}
                    </td>
                    <td style="padding:10px 12px;font-size:12px;color:#495057;">
                        📍 {e['location'] or 'TBC'}
                    </td>
                    <td style="padding:10px 12px;">
                        <span style="display:inline-block;padding:2px 8px;
                                     background:{badge_bg};border:1px solid {badge_border};
                                     border-radius:99px;font-size:11px;
                                     color:{badge_color};white-space:nowrap;">
                            {badge_icon} {e['attendance']}
                        </span>
                    </td>
                </tr>"""
 
            days_html += f"""
            <div style="margin-bottom:20px;border-radius:10px;overflow:hidden;
                        border:1px solid #e9ecef;">
 
                <!-- Day header -->
                <div style="background:{LKC_PURPLE};padding:10px 16px;
                            display:flex;justify-content:space-between;align-items:center;">
                    <span style="font-size:14px;font-weight:600;color:#fff;">
                        {day}
                    </span>
                    <span style="font-size:12px;color:rgba(255,255,255,0.75);">
                        {len(day_events)} event{'s' if len(day_events)>1 else ''} ·
                        {day_hours:.1f}h
                        {f'· {day_required} required' if day_required else ''}
                    </span>
                </div>
 
                <!-- Events table -->
                <table style="width:100%;border-collapse:collapse;background:#fff;">
                    {event_rows}
                </table>
            </div>"""
 
    # Stats bar
    stats_html = f"""
    <div style="display:flex;gap:0;margin-bottom:24px;
                border:1px solid #e9ecef;border-radius:10px;overflow:hidden;">
        <div style="flex:1;padding:14px;text-align:center;background:#fafafa;
                    border-right:1px solid #e9ecef;">
            <div style="font-size:22px;font-weight:700;color:{LKC_PURPLE};">
                {total_events}
            </div>
            <div style="font-size:11px;color:#868e96;margin-top:2px;">EVENTS</div>
        </div>
        <div style="flex:1;padding:14px;text-align:center;background:#fafafa;
                    border-right:1px solid #e9ecef;">
            <div style="font-size:22px;font-weight:700;color:{LKC_PURPLE};">
                {total_hours:.1f}h
            </div>
            <div style="font-size:11px;color:#868e96;margin-top:2px;">TOTAL HOURS</div>
        </div>
        <div style="flex:1;padding:14px;text-align:center;background:#fafafa;">
            <div style="font-size:22px;font-weight:700;color:#e05c5c;">
                {required_count}
            </div>
            <div style="font-size:11px;color:#868e96;margin-top:2px;">ATTENDANCE REQ.</div>
        </div>
    </div>""" if events else ""
 
    # Get week range string e.g. "28 Apr – 04 May 2026"
    today       = date.today()
    monday      = today - timedelta(days=today.weekday())
    sunday      = monday + timedelta(days=6)
    week_range  = f"{monday.strftime('%d %b')} – {sunday.strftime('%d %b %Y')}"
 
    html_body = f"""
<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"/></head>
<body style="margin:0;padding:0;background:#f0f2f5;
             font-family:'Segoe UI',Arial,sans-serif;">
    <div style="max-width:620px;margin:32px auto;background:#fff;border:1px solid #e0e0e0;">
 
    <!-- Header -->
    <div style="background-color:{LKC_PURPLE};padding:32px 32px 24px;">
      <div style="font-size:12px;color:rgba(255,255,255,0.65);
                  letter-spacing:0.1em;text-transform:uppercase;margin-bottom:6px;">
          NTU Lee Kong Chian School of Medicine
      </div>
      <div style="font-size:26px;font-weight:700;color:#fff;margin-bottom:4px;">
           Your Week Ahead
      </div>
      <div style="font-size:14px;color:rgba(255,255,255,0.8);">
          {week_range}
      </div>
    </div>
 
    <!-- Body -->
    <div style="padding:28px 32px;">
      <p style="margin:0 0 20px;font-size:15px;color:#495057;">
          Good morning <strong>{username}</strong>!
          Here's everything scheduled for you this week:
      </p>
 
      {stats_html}
      {days_html}
 
      <p style="margin:24px 0 0;font-size:13px;color:#868e96;line-height:1.6;">
          This summary was sent automatically every Monday at 8:00 AM SGT.<br>
          Log in to the assistant to ask questions about your schedule.
      </p>
    </div>
 
    <!-- Footer -->
    <div style="background:{LKC_PURPLE};padding:16px 32px;">
      <p style="margin:0;font-size:12px;color:rgba(255,255,255,0.6);text-align:center;">
          NTU Lee Kong Chian School of Medicine · Sent every Monday at 8:00 AM SGT
      </p>
    </div>
 
  </div>
</body>
</html>"""
 
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f" Your Week Ahead — {week_range}"
    msg["From"]    = mail_address
    msg["To"]      = to_email
 
    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))
 
    with smtplib.SMTP(smtp_server, smtp_port) as server:
        server.ehlo()
        server.starttls()
        server.login(mail_address, mail_password)
        server.sendmail(mail_address, to_email, msg.as_string())
 
    print(f"[MAILER] Weekly summary sent to {to_email} ({total_events} event(s))")


def send_attendance_alert_email(to_email: str, username: str, events: list):
    """Send an attendance alert email for events starting now."""
    mail_address = os.getenv("MAIL_ADDRESS")
    mail_password = os.getenv("MAIL_PASSWORD")
    smtp_server   = os.getenv("MAIL_SMTP", "smtp.gmail.com")
    smtp_port     = int(os.getenv("MAIL_PORT", 587))

    GREEN = "#4caf7d"
    PURPLE = "#4a1259"
    DARK_FOOTER = "#2d1b4e"
    
    if not events:
        return
    
    event = events[0]
    
    # Use the actual attendance value from the event
    attendance_display = event['attendance']
    attendance_badge_color = "#fff3cd" if attendance_display == "Required" else "#f0f0f0"
    attendance_border_color = "#ffc107" if attendance_display == "Required" else "#cccccc"
    attendance_text_color = "#856404" if attendance_display == "Required" else "#666666"
    attendance_icon = "⚠️" if attendance_display == "Required" else "✅"
    
    subject = f" Attendance {attendance_display} — {event['course_code']}"
    
    text_body = f"""Hi {username},

{attendance_icon} Your class is starting now and attendance is {attendance_display}!

📌 {event['title']}
🕐 {event['time']}
📍 {event['location']}
📖 Course: {event['course_code']}
📋 Attendance: {attendance_display}

Please mark your attendance now.

This is an automated reminder from your NTU Learning Assistant."""
    
    html_body = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"/></head>
<body style="margin:0;padding:0;background:#f0f2f5;font-family:'Segoe UI',Arial,sans-serif;">
<div style="max-width:560px;margin:32px auto;background:#fff;border:1px solid #e0e0e0;">
    <div style="background-color:{GREEN};padding:28px 32px 20px;">
        <div style="font-size:12px;color:rgba(255,255,255,0.75);letter-spacing:0.1em;text-transform:uppercase;margin-bottom:6px;">NTU Lee Kong Chian School of Medicine</div>
        <div style="font-size:22px;font-weight:700;color:#fff;margin-bottom:2px;"> Class Starting Now — {'Mark Attendance!' if attendance_display == 'Required' else 'Class Starting'}</div>
        <div style="font-size:13px;color:rgba(255,255,255,0.85);">1 class starting now</div>
    </div>
    <div style="padding:28px 32px;">
        <p style="margin:0 0 20px;font-size:15px;color:#495057;">Hi <strong>{username}</strong>, your class is starting now:</p>
        <div style="background:#fff;border:1px solid #e9ecef;border-left:4px solid {GREEN};padding:16px 20px;margin-bottom:12px;">
            <div style="font-size:16px;font-weight:600;color:#1a1a2e;margin-bottom:10px;">📌 {event['title']}</div>
            <table style="font-size:13px;color:#495057;border-collapse:collapse;width:100%;">
                <tr><td style="padding:3px 12px 3px 0;color:#868e96;width:90px;">🕐 Time</td><td style="padding:3px 0;font-weight:600;color:{PURPLE};">{event['time']}</td></tr>
                <tr><td style="padding:3px 12px 3px 0;color:#868e96;">📍 Location</td><td style="padding:3px 0;">{event['location'] or 'TBC'}</td></tr>
                <tr><td style="padding:3px 12px 3px 0;color:#868e96;">📖 Course</td><td style="padding:3px 0;">{event['course_code']}</td></tr>
                <tr><td style="padding:3px 12px 3px 0;color:#868e96;">📋 Attendance</td>
                    <td style="padding:3px 0;"><span style="display:inline-block;padding:2px 10px;background:{attendance_badge_color};border:1px solid {attendance_border_color};font-size:12px;color:{attendance_text_color};font-weight:500;">{attendance_icon} {attendance_display}</span></td>
                </tr>
            </table>
            <a href="https://ntu.elentra.cloud/" style="display:inline-block;margin-top:10px;padding:6px 14px;background:{PURPLE};color:#fff;text-decoration:none;font-size:12px;font-weight:500;"> Go to Dashboard →</a>
        </div>
        <div style="background:#e8f5e9;border:1px solid #a5d6a7;padding:12px 16px;margin-top:20px;">
            <p style="margin:0;font-size:13px;color:#2e7d32;"><strong> Class is starting!</strong> {'Mark your attendance now on the Elentra dashboard.' if attendance_display == 'Required' else 'You can join the session.'}</p>
        </div>
        <p style="margin:24px 0 0;font-size:13px;color:#868e96;line-height:1.6;">This reminder was sent automatically when your class started.<br>Log in to the assistant to manage your reminders.</p>
    </div>
    <div style="background:{DARK_FOOTER};padding:14px 32px;">
        <p style="margin:0;font-size:12px;color:rgba(255,255,255,0.5);text-align:center;">NTU Lee Kong Chian School of Medicine · Class Start Reminder</p>
    </div>
</div>
</body></html>"""
    
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = mail_address
    msg["To"]      = to_email
    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))
    
    with smtplib.SMTP(smtp_server, smtp_port) as server:
        server.ehlo()
        server.starttls()
        server.login(mail_address, mail_password)
        server.sendmail(mail_address, to_email, msg.as_string())
    
    print(f"[MAILER] Attendance alert sent to {to_email}")


def send_mc_reminder_email(to_email: str, username: str, events: list):
    """Send MC reminder when attendance wasn't marked for completed events."""
    mail_address = os.getenv("MAIL_ADDRESS")
    mail_password = os.getenv("MAIL_PASSWORD")
    smtp_server   = os.getenv("MAIL_SMTP", "smtp.gmail.com")
    smtp_port     = int(os.getenv("MAIL_PORT", 587))

    ORANGE = "#f0ad4e"
    PURPLE = "#4a1259"
    DARK_FOOTER = "#2d1b4e"
    
    if not events:
        return
    
    lines = [f"Hi {username},\n", "You did not mark attendance for these events today:\n"]
    for event in events:
        lines.append(f"📌 {event['title']}")
        lines.append(f"   🕐 {event['time']}")
        lines.append(f"   📍 {event['location']}")
        lines.append(f"   📖 Course: {event['course_code']}")
        lines.append(f"   🔗 https://ntu.elentra.cloud/")
        lines.append("")
    lines.append("✅ If you attended — mark your attendance now.")
    lines.append("🏥 If you were absent — submit your MC/LOA here:")
    lines.append("   https://ntu.elentra.cloud/profile/absences")
    lines.append("\nThis is an automated reminder from your NTU Learning Assistant.")
    text_body = "\n".join(lines)

    event_cards = ""
    for event in events:
        event_cards += f"""
        <div style="background:#fff;border:1px solid #e9ecef;border-left:4px solid {ORANGE};padding:16px 20px;margin-bottom:12px;">
            <div style="font-size:16px;font-weight:600;color:#1a1a2e;margin-bottom:10px;">📌 {event['title']}</div>
            <table style="font-size:13px;color:#495057;border-collapse:collapse;width:100%;">
                <tr><td style="padding:3px 12px 3px 0;color:#868e96;width:90px;">🕐 Time</td><td style="padding:3px 0;">{event['time']}</td></tr>
                <tr><td style="padding:3px 12px 3px 0;color:#868e96;">📍 Location</td><td style="padding:3px 0;">{event['location'] or 'TBC'}</td></tr>
                <tr><td style="padding:3px 12px 3px 0;color:#868e96;">📖 Course</td><td style="padding:3px 0;">{event['course_code']}</td></tr>
            </table>
            <a href="https://ntu.elentra.cloud/" style="display:inline-block;margin-top:10px;padding:6px 14px;background:{PURPLE};color:#fff;text-decoration:none;font-size:12px;font-weight:500;"> Go to Dashboard →</a>
        </div>"""

    subject = f" Missed Attendance? — {len(events)} event(s) today"
    if len(events) == 1:
        subject = f" Missed Attendance? — {events[0]['course_code']}"

    html_body = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"/></head>
<body style="margin:0;padding:0;background:#f0f2f5;font-family:'Segoe UI',Arial,sans-serif;">
<div style="max-width:540px;margin:32px auto;background:#fff;border:1px solid #e0e0e0;">
    <div style="background-color:{ORANGE};padding:28px 32px 20px;">
        <div style="font-size:12px;color:rgba(255,255,255,0.75);letter-spacing:0.1em;text-transform:uppercase;margin-bottom:6px;">NTU Lee Kong Chian School of Medicine</div>
        <div style="font-size:22px;font-weight:700;color:#fff;margin-bottom:2px;"> Missed Attendance — Action Required</div>
        <div style="font-size:13px;color:rgba(255,255,255,0.85);margin-top:4px;">{len(events)} event{'s' if len(events) > 1 else ''} today without attendance marked</div>
    </div>
    <div style="padding:28px 32px;">
        <p style="margin:0 0 20px;font-size:15px;color:#495057;">Hi <strong>{username}</strong>, attendance was not marked for:</p>
        {event_cards}
        <div style="background:#fff3cd;border:1px solid #ffc107;padding:12px 16px;margin-bottom:20px;">
            <p style="margin:0;font-size:13px;color:#856404;"><strong> If you were absent:</strong> <a href="https://ntu.elentra.cloud/profile/absences" style="color:#856404;font-weight:600;">Submit your MC/LOA here</a> within 7 term days.</p>
        </div>
        <p style="margin:24px 0 0;font-size:13px;color:#868e96;line-height:1.6;">This reminder was sent automatically after your classes ended.<br>Log in to the assistant to manage your reminder preferences.</p>
    </div>
    <div style="background:{DARK_FOOTER};padding:14px 32px;">
        <p style="margin:0;font-size:12px;color:rgba(255,255,255,0.5);text-align:center;">NTU Lee Kong Chian School of Medicine · Post-Class MC Reminder</p>
    </div>
</div>
</body></html>"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = mail_address
    msg["To"]      = to_email
    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))
    
    with smtplib.SMTP(smtp_server, smtp_port) as server:
        server.ehlo()
        server.starttls()
        server.login(mail_address, mail_password)
        server.sendmail(mail_address, to_email, msg.as_string())
    
    print(f"[MAILER] MC reminder sent to {to_email} ({len(events)} event(s))")

def send_event_reminder_email(to_email: str, username: str, event: dict):
    """Send a 1-hour-before reminder for a specific learning event."""
    mail_address  = os.getenv("MAIL_ADDRESS")
    mail_password = os.getenv("MAIL_PASSWORD")
    smtp_server   = os.getenv("MAIL_SMTP", "smtp.gmail.com")
    smtp_port     = int(os.getenv("MAIL_PORT", 587))

    PURPLE = "#4a1259"
    DARK_FOOTER = "#2d1b4e"

    bb, bbd, bc, bi = ("#fff3cd", "#ffc107", "#856404", "⚠️") if event["attendance"] == "Required" else ("#f0f0f0", "#cccccc", "#666666", "✅")

    text_body = f"""Hi {username},

⏰ Reminder: Your session starts in 1 hour!

📚 {event['title']}
🕐 Time:       {event['time']}
📍 Location:   {event['location'] or 'TBC'}
📖 Course:     {event['course_code']}
📋 Attendance: {event['attendance']}

See you there!"""

    html_body = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"/></head>
<body style="margin:0;padding:0;background:#f0f2f5;font-family:'Segoe UI',Arial,sans-serif;">
<div style="max-width:520px;margin:32px auto;background:#fff;border:1px solid #e0e0e0;">
    <div style="background-color:{PURPLE};padding:28px 32px 20px;">
        <div style="font-size:12px;color:rgba(255,255,255,0.65);letter-spacing:0.1em;text-transform:uppercase;margin-bottom:6px;">NTU Lee Kong Chian School of Medicine</div>
        <div style="font-size:22px;font-weight:700;color:#fff;margin-bottom:2px;"> Starting in 1 Hour</div>
        <div style="font-size:13px;color:rgba(255,255,255,0.8);">{event['date']}</div>
    </div>
    <div style="padding:28px 32px;">
        <p style="margin:0 0 20px;font-size:15px;color:#495057;">Hi <strong>{username}</strong>, your upcoming session starts in 1 hour:</p>
        <div style="background:#fff;border:1px solid #e9ecef;border-left:4px solid {PURPLE};padding:18px 20px;">
            <div style="font-size:17px;font-weight:600;color:#1a1a2e;margin-bottom:12px;">{event['title']}</div>
            <table style="font-size:13px;color:#495057;border-collapse:collapse;width:100%;">
                <tr><td style="padding:4px 12px 4px 0;color:#868e96;width:90px;">🕐 Time</td><td style="padding:4px 0;font-weight:600;font-size:15px;color:{PURPLE};">{event['time']}</td></tr>
                <tr><td style="padding:4px 12px 4px 0;color:#868e96;">📍 Location</td><td style="padding:4px 0;">{event['location'] or 'TBC'}</td></tr>
                <tr><td style="padding:4px 12px 4px 0;color:#868e96;">📖 Course</td><td style="padding:4px 0;">{event['course_code']}</td></tr>
                <tr><td style="padding:4px 12px 4px 0;color:#868e96;">📋 Attendance</td><td style="padding:4px 0;"><span style="display:inline-block;padding:2px 10px;background:{bb};border:1px solid {bbd};font-size:12px;color:{bc};font-weight:500;">{bi} {event['attendance']}</span></td></tr>
            </table>
        </div>
        <p style="margin:24px 0 0;font-size:13px;color:#868e96;line-height:1.6;">This reminder was sent automatically 1 hour before your session.<br>Good luck and have a great session!</p>
    </div>
    <div style="background:{PURPLE};padding:14px 32px;">
        <p style="margin:0;font-size:12px;color:rgba(255,255,255,0.6);text-align:center;">NTU Lee Kong Chian School of Medicine · 1-Hour Session Reminder</p>
    </div>
</div>
</body></html>"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f" Starting in 1 Hour: {event['title']}"
    msg["From"]    = mail_address
    msg["To"]      = to_email
    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP(smtp_server, smtp_port) as server:
        server.ehlo()
        server.starttls()
        server.login(mail_address, mail_password)
        server.sendmail(mail_address, to_email, msg.as_string())

    print(f"[MAILER] 1h reminder sent to {to_email} for: {event['title']}")

def send_ending_class_reminder(to_email: str, username: str, events: list):
    """
    Send email reminder that class is ending soon and attendance needs marking.
    
    Args:
        to_email: recipient email address
        username: student's Elentra username
        events: list of event dicts with added 'minutes_until_end' and 'event_end_time' keys
    """
    mail_address  = os.getenv("MAIL_ADDRESS")
    mail_password = os.getenv("MAIL_PASSWORD")
    smtp_server   = os.getenv("MAIL_SMTP",  "smtp.gmail.com")
    smtp_port     = int(os.getenv("MAIL_PORT", 587))

    LKC_PURPLE       = "#4a1259"
    LKC_PURPLE_LIGHT = "#6b2180"
    
    # ── Plain text version ──────────────────────
    lines = [f"Hi {username},\n",
             " Class Ending Soon — Remember to Mark Attendance!\n"]
    
    for event in events:
        end_time = event.get("event_end_time", event["time"].split("–")[-1].strip())
        mins_left = event.get("minutes_until_end", "?")
        
        lines.append(f"📌 {event['title']}")
        lines.append(f"   Ends at: {end_time} (in ~{mins_left} min)")
        lines.append(f"   Location: {event['location']}")
        lines.append(f"   Course: {event['course_code']}")
        lines.append(f"   Attendance: {event['attendance']}")
        lines.append(f"   Mark on Elentra dashboard")
        lines.append("")
    
    lines.append("⚠️ Don't forget to mark your attendance before class ends!")
    lines.append("\nThis is an automated reminder from your NTU Learning Assistant.")
    
    text_body = "\n".join(lines)
    
    # ── HTML version ────────────────────────────
    event_cards = ""
    for event in events:
        end_time = event.get("event_end_time", event["time"].split("–")[-1].strip())
        mins_left = event.get("minutes_until_end", "?")
        
        # Urgency color based on minutes left
        if mins_left != "?" and mins_left <= 5:
            border_color = "#e05c5c"
            bg_color = "#fff5f5"
            urgency_text = "ENDING NOW"
        elif mins_left != "?" and mins_left <= 10:
            border_color = "#f0ad4e"
            bg_color = "#fffaf0"
            urgency_text = "ENDING SOON"
        else:
            border_color = "#ffc107"
            bg_color = "#fffdf5"
            urgency_text = "APPROACHING END"
        
        event_cards += f"""
        <div style="background:{bg_color};border:1px solid #e9ecef;
                    border-left:4px solid {border_color};border-radius:10px;
                    padding:16px 20px;margin-bottom:12px;">
            <div style="display:flex;justify-content:space-between;align-items:start;margin-bottom:8px;">
                <div style="font-size:16px;font-weight:600;color:#1a1a2e;">
                    {event['title']}
                </div>
                <span style="font-size:11px;font-weight:600;color:{border_color};
                             background:#fff;padding:3px 10px;border-radius:99px;
                             border:1px solid {border_color};white-space:nowrap;">
                    ⏰ {urgency_text}
                </span>
            </div>
            <table style="font-size:13px;color:#495057;border-collapse:collapse;width:100%;">
                <tr>
                    <td style="padding:3px 12px 3px 0;color:#868e96;width:90px;">🕐 Ends at</td>
                    <td style="padding:3px 0;font-weight:600;color:{LKC_PURPLE};">
                        {end_time} (in ~{mins_left} min)
                    </td>
                </tr>
                <tr>
                    <td style="padding:3px 12px 3px 0;color:#868e96;">📍 Location</td>
                    <td style="padding:3px 0;">{event['location'] or 'TBC'}</td>
                </tr>
                <tr>
                    <td style="padding:3px 12px 3px 0;color:#868e96;">📖 Course</td>
                    <td style="padding:3px 0;">{event['course_code']}</td>
                </tr>
                <tr>
                    <td style="padding:3px 12px 3px 0;color:#868e96;">📋 Attendance</td>
                    <td style="padding:3px 0;">
                        <span style="display:inline-block;padding:2px 10px;
                                     background:#fff3cd;border:1px solid #ffc107;
                                     border-radius:99px;font-size:12px;
                                     color:#856404;font-weight:500;">
                            ⚠️ {event['attendance']}
                        </span>
                    </td>
                </tr>
            </table>
            <a href="https://ntu.elentra.cloud/"
            style="display:inline-block;margin-top:10px;padding:6px 14px;
                    background:{LKC_PURPLE};color:#fff;text-decoration:none;
                    border-radius:6px;font-size:12px;font-weight:500;">
                 Go to Dashboard →
            </a>
        </div>"""
    
    html_body = f"""
<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"/></head>
<body style="margin:0;padding:0;background:#f0f2f5;
             font-family:'Segoe UI',Arial,sans-serif;">
    <div style="max-width:560px;margin:32px auto;background:#fff;border:1px solid #e0e0e0;">

    <!-- Header -->
    <div style="background-color:#e05c5c;padding:28px 32px 20px;">
      <div style="font-size:12px;color:rgba(255,255,255,0.75);
                  letter-spacing:0.1em;text-transform:uppercase;margin-bottom:6px;">
        NTU Lee Kong Chian School of Medicine
      </div>
      <div style="font-size:22px;font-weight:700;color:#fff;margin-bottom:2px;">
         Class Ending Soon — Mark Attendance!
      </div>
      <div style="font-size:13px;color:rgba(255,255,255,0.85);">
        {len(events)} class{'es' if len(events) > 1 else ''} ending in ~15 minutes
      </div>
    </div>

    <!-- Body -->
    <div style="padding:28px 32px;">
      <p style="margin:0 0 20px;font-size:15px;color:#495057;">
        Hi <strong>{username}</strong>, don't forget to mark your attendance before class ends:
      </p>

      {event_cards}

      <div style="background:#fff3cd;border:1px solid #ffc107;
                  border-radius:8px;padding:12px 16px;margin-top:20px;">
        <p style="margin:0;font-size:13px;color:#856404;">
          <strong>⚠️ Important:</strong> Attendance must be marked for each class. 
          If you attended, please mark it now before the class ends.
        </p>
      </div>

      <p style="margin:24px 0 0;font-size:13px;color:#868e96;line-height:1.6;">
        This reminder was sent automatically 15 minutes before class ends.<br>
        Log in to the assistant to manage your reminders.
      </p>
    </div>

    <!-- Footer -->
    <div style="background:#2d1b4e;padding:14px 32px;">
      <p style="margin:0;font-size:12px;
                color:rgba(255,255,255,0.5);text-align:center;">
        NTU Lee Kong Chian School of Medicine · Class End Reminder
      </p>
    </div>

  </div>
</body>
</html>"""

    # ── Build and send email ─────────────────────
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f" Class Ending Soon — Remember to Mark Attendance!"
    msg["From"]    = mail_address
    msg["To"]      = to_email

    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP(smtp_server, smtp_port) as server:
        server.ehlo()
        server.starttls()
        server.login(mail_address, mail_password)
        server.sendmail(mail_address, to_email, msg.as_string())

    print(f"[MAILER] Ending class reminder sent to {to_email} ({len(events)} event(s))")

def send_preferences_confirmation(to_email, username, preferences, bus_config=None, selected_modules=None):
    """
    Send a confirmation email showing which reminders are enabled/disabled,
    which modules are selected, bus configuration, and optional events setting.
    """
    mail_address  = os.getenv("MAIL_ADDRESS")
    mail_password = os.getenv("MAIL_PASSWORD")
    smtp_server   = os.getenv("MAIL_SMTP", "smtp.gmail.com")
    smtp_port     = int(os.getenv("MAIL_PORT", 587))

    PURPLE = "#4a1259"
    
    # Module names mapping
    module_names = {
        "1.01": "Foundations of Medicine",
        "1.02": "Cardiorespiratory System",
        "1.03": "Endocrine System",
        "1.04": "Renal and Urinary System",
        "1.05": "Gastrointestinal System",
        "1.06": "Anatomy and Pathology",
        "1.07": "Clinical Pharmacology and Therapeutics",
        "1.08": "Clinical Practice and Patient Safety",
        "1.09": "Digital Health and Precision Medicine",
        "1.10": "Medical Humanities",
        "1.11": "Professionalism, Ethics, Law and Leadership",
        "1.12": "Public and Population Health",
        "1.13": "Research and Scientific Enquiry",
        "1.14": "Professional Growth",
        "O-Wk": "Orientation",
        "Assessment": "Year 1 Examinations and Assessments Hub"
    }
    
    # ── Include Optional Events status ──
    include_optional = preferences.get("include_optional", True)
    optional_status = "✅ ENABLED (you'll receive reminders for optional sessions)" if include_optional else "❌ DISABLED (only required sessions)"
    
    # ── Build module list string ──
    module_list_str = ""
    if selected_modules and len(selected_modules) > 0:
        if len(selected_modules) <= 10:
            for code in selected_modules:
                name = module_names.get(code, code)
                module_list_str += f'<div style="padding:4px 0;">• <strong>{code}</strong> - {name}</div>'
        else:
            for code in selected_modules[:8]:
                name = module_names.get(code, code)
                module_list_str += f'<div style="padding:4px 0;">• <strong>{code}</strong> - {name}</div>'
            module_list_str += f'<div style="padding:4px 0;">• ... and {len(selected_modules) - 8} more modules</div>'
    else:
        module_list_str = '<div style="padding:4px 0;">• All modules selected</div>'
    
    # Bus description
    if bus_config and bus_config.get("active", False):
        remind_before = bus_config.get("remind_before_minutes", 5)
        direction = bus_config.get("direction", "both")
        dir_map = {"to_novena": "Yunnan → Novena", "to_ntu": "Novena → Yunnan", "both": "Both directions"}
        times = bus_config.get("preferred_times", [])
        if times:
            bus_desc = f"{remind_before} min before • {dir_map.get(direction, direction)} • {', '.join(times)}"
        else:
            bus_desc = f"{remind_before} min before • {dir_map.get(direction, direction)} • All times"
        bus_status = "✅ ENABLED"
        bus_status_color = "#4caf7d"
    else:
        bus_desc = "Email reminders before each shuttle bus"
        bus_status = "❌ DISABLED"
        bus_status_color = "#e05c5c"
    
    # Build HTML rows for each preference
    pref_items = [
        ("daily_tonight",      "🌙 Daily Tonight Reminder",       "7pm — Tomorrow's learning events"),
        ("weekly_monday",      "📅 Weekly Monday Summary",        "8am Monday — Full week ahead"),
        ("one_hour_before",    "⏰ 1 Hour Before Reminder",       "Sent 1 hour before each session"),
        ("attendance_alert",   "✅ Attendance Alert",             "Class starts — remind to mark attendance"),
        ("missing_attendance", "🚨 Missing Attendance Alert",     "After class — if attendance not marked"),
        ("loa_rejection",      "📋 LOA Rejection Alert",          "Email when an absence application is rejected"),
        ("ending_reminder",    "🔴 Class Ending Reminder",        "15 min before class ends — remind to mark attendance"),
    ]
    
    pref_rows = ""
    for key, name, desc in pref_items:
        enabled = preferences.get(key, False)
        status_color = "#4caf7d" if enabled else "#e05c5c"
        status_text = "✅ ENABLED" if enabled else "❌ DISABLED"
        pref_rows += f"""
        <tr style="border-bottom:1px solid #e9ecef;">
            <td style="padding:10px 12px;font-size:13px;font-weight:500;">{name}</td>
            <td style="padding:10px 12px;font-size:12px;color:#666;">{desc}</td>
            <td style="padding:10px 12px;text-align:right;">
                <span style="font-size:12px;font-weight:600;color:{status_color};">{status_text}</span>
            </td>
        </tr>"""
    
    # Optional Events row
    optional_row = f"""
    <tr style="border-bottom:1px solid #e9ecef;">
        <td style="padding:10px 12px;font-size:13px;font-weight:500;">📋 Include Optional Events</td>
        <td style="padding:10px 12px;font-size:12px;color:#666;">Send reminders for optional attendance sessions</td>
        <td style="padding:10px 12px;text-align:right;">
            <span style="font-size:12px;font-weight:600;color:{'#4caf7d' if include_optional else '#e05c5c'};">{'✅ ENABLED' if include_optional else '❌ DISABLED'}</span>
        </td>
    </tr>"""
    
    # Bus row
    bus_row = f"""
    <tr style="border-bottom:1px solid #e9ecef;">
        <td style="padding:10px 12px;font-size:13px;font-weight:500;">🚌 Bus Departure Reminder</td>
        <td style="padding:10px 12px;font-size:12px;color:#666;">{bus_desc}</td>
        <td style="padding:10px 12px;text-align:right;">
            <span style="font-size:12px;font-weight:600;color:{bus_status_color};">{bus_status}</span>
        </td>
    </tr>"""
    
    html_body = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"/></head>
<body style="margin:0;padding:0;background:#f0f2f5;font-family:'Segoe UI',Arial,sans-serif;">
<div style="max-width:560px;margin:32px auto;background:#fff;border:1px solid #e0e0e0;">
    <div style="background-color:{PURPLE};padding:28px 32px 20px;">
        <div style="font-size:12px;color:rgba(255,255,255,0.65);letter-spacing:0.1em;text-transform:uppercase;margin-bottom:6px;">NTU Lee Kong Chian School of Medicine</div>
        <div style="font-size:22px;font-weight:700;color:#fff;">✅ Preferences Saved</div>
        <div style="font-size:13px;color:rgba(255,255,255,0.8);margin-top:4px;">Your reminder settings have been updated</div>
    </div>
    <div style="padding:24px 28px;">
        <p style="margin:0 0 16px;font-size:14px;color:#333;">Hi <strong>{username}</strong>, here's a summary of your reminder preferences:</p>
        
        <table style="width:100%;border-collapse:collapse;border:1px solid #e9ecef;border-radius:8px;overflow:hidden;margin-bottom:16px;">
            {pref_rows}
            {optional_row}
            {bus_row}
        </table>
        
        <div style="margin-bottom:16px;">
            <div style="font-size:14px;font-weight:600;color:#1a1a2e;margin-bottom:8px;">📚 Selected Modules ({len(selected_modules) if selected_modules else 0})</div>
            <div style="background:#f9fafb;border:1px solid #e9ecef;border-radius:8px;padding:12px 16px; max-height:200px; overflow-y:auto;">
                {module_list_str}
            </div>
        </div>
        
        <p style="margin:16px 0 0;font-size:12px;color:#888;">You can update your preferences anytime by clicking the ⚙️ Settings button in the Learning Assistant.</p>
    </div>
    <div style="background:#2d1b4e;padding:12px 24px;">
        <p style="margin:0;font-size:11px;color:rgba(255,255,255,0.5);text-align:center;">NTU Lee Kong Chian School of Medicine · Learning Assistant</p>
    </div>
</div>
</body></html>"""

    # Plain text version
    text_body = f"""Hi {username},

Your reminder preferences have been saved.

─ REMINDER STATUS ─────────────────
"""
    for key, name, desc in pref_items:
        status = "ENABLED" if preferences.get(key, False) else "DISABLED"
        text_body += f"{status}  {name} - {desc}\n"
    
    text_body += f"""
📋 OPTIONAL EVENTS: {optional_status}

─ BUS REMINDER ────────────────────
{bus_status} - {bus_desc}

─ SELECTED MODULES ({len(selected_modules) if selected_modules else 0}) ──
"""
    if selected_modules and len(selected_modules) > 0:
        for code in selected_modules:
            name = module_names.get(code, code)
            text_body += f"  • {code} - {name}\n"
    else:
        text_body += "  • All modules selected\n"
    
    text_body += """
You can update your preferences anytime in the Learning Assistant settings."""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Reminder Preferences Saved - LKCMedicine Learning Assistant"
    msg["From"]    = mail_address
    msg["To"]      = to_email
    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP(smtp_server, smtp_port) as server:
        server.ehlo()
        server.starttls()
        server.login(mail_address, mail_password)
        server.sendmail(mail_address, to_email, msg.as_string())

    print(f"[MAILER] Preferences confirmation sent to {to_email}")
    
def send_bus_reminder_email(to_email, username, bus_time, remind_before, direction, from_location, to_location):
    """Send a bus reminder email."""
    mail_address = os.getenv("MAIL_ADDRESS")
    mail_password = os.getenv("MAIL_PASSWORD")
    smtp_server = os.getenv("MAIL_SMTP", "smtp.gmail.com")
    smtp_port = int(os.getenv("MAIL_PORT", 587))
    
    PURPLE = "#4a1259"
    DARK_FOOTER = "#2d1b4e"
    
    direction_icon = "🟢" if direction == "to_novena" else "🔵"
    direction_label = "Yunnan → Novena" if direction == "to_novena" else "Novena → Yunnan"
    
    text_body = f"""Hi {username},

🚌 Your shuttle bus is leaving in {remind_before} minutes!

⏰ Departure: {bus_time}
📍 From: {from_location}
📍 To: {to_location}
{direction_icon} Direction: {direction_label}

Please head to the pickup point now.
Arrive 5 minutes before departure.

This is an automated reminder from your NTU Learning Assistant."""
    
    html_body = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"/></head>
<body style="margin:0;padding:0;background:#f0f2f5;font-family:'Segoe UI',Arial,sans-serif;">
<div style="max-width:540px;margin:32px auto;background:#fff;border:1px solid #e0e0e0;">
    <div style="background-color:{PURPLE};padding:28px 32px 20px;">
        <div style="font-size:12px;color:rgba(255,255,255,0.65);letter-spacing:0.1em;text-transform:uppercase;margin-bottom:6px;">NTU Lee Kong Chian School of Medicine</div>
        <div style="font-size:22px;font-weight:700;color:#fff;margin-bottom:2px;">🚌 Bus Leaving Soon</div>
        <div style="font-size:13px;color:rgba(255,255,255,0.8);margin-top:4px;">Departure in {remind_before} minutes</div>
    </div>
    <div style="padding:28px 32px;">
        <p style="margin:0 0 20px;font-size:15px;color:#495057;">Hi <strong>{username}</strong>, your shuttle bus is about to leave:</p>
        <div style="background:#fff;border:1px solid #e9ecef;border-left:4px solid {PURPLE};padding:18px 20px;margin-bottom:12px;">
            <div style="font-size:28px;font-weight:700;color:{PURPLE};margin-bottom:12px;">⏰ {bus_time}</div>
            <table style="font-size:13px;color:#495057;border-collapse:collapse;width:100%;">
                <tr><td style="padding:3px 12px 3px 0;color:#868e96;width:30px;">📍</td><td style="padding:3px 0;"><strong>From:</strong> {from_location}</td></tr>
                <tr><td style="padding:3px 12px 3px 0;color:#868e96;">📍</td><td style="padding:3px 0;"><strong>To:</strong> {to_location}</td></tr>
                <tr><td style="padding:3px 12px 3px 0;color:#868e96;">{direction_icon}</td><td style="padding:3px 0;"><strong>Direction:</strong> {direction_label}</td></tr>
            </table>
        </div>
        <div style="background:#FFF3E0;border:1px solid #FFE0B2;padding:12px 16px;margin-top:16px;">
            <p style="margin:0;font-size:13px;color:#E65100;">⚠️ Please arrive 5 minutes before departure. Head to the pickup point now!</p>
        </div>
        <p style="margin:24px 0 0;font-size:13px;color:#868e96;line-height:1.6;">This reminder was sent automatically.<br>Configure your bus preferences in the Learning Assistant ⚙️ Settings.</p>
    </div>
    <div style="background:{DARK_FOOTER};padding:14px 32px;">
        <p style="margin:0;font-size:12px;color:rgba(255,255,255,0.5);text-align:center;">NTU Lee Kong Chian School of Medicine · Shuttle Bus Reminder</p>
    </div>
</div>
</body></html>"""
    
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"🚌 Bus Reminder — {bus_time} ({direction_label})"
    msg["From"] = mail_address
    msg["To"] = to_email
    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))
    
    with smtplib.SMTP(smtp_server, smtp_port) as server:
        server.ehlo()
        server.starttls()
        server.login(mail_address, mail_password)
        server.sendmail(mail_address, to_email, msg.as_string())
    
    print(f"[MAILER] Bus reminder sent to {to_email} for {bus_time}")

def send_loa_rejection_email(to_email, username, reference, from_date, reason):
    """Send email when an absence application is rejected."""
    mail_address = os.getenv("MAIL_ADDRESS")
    mail_password = os.getenv("MAIL_PASSWORD")
    smtp_server   = os.getenv("MAIL_SMTP", "smtp.gmail.com")
    smtp_port     = int(os.getenv("MAIL_PORT", 587))
   
    PURPLE = "#4a1259"
    DARK_FOOTER = "#2d1b4e"
   
    subject = "Your Absence Application Has Been Rejected"
   
    text_body = f"""Hi {username},
 
Your recent absence application has been REJECTED:
 
Reference: #{reference}
Date(s): {from_date}
Reason submitted: {reason}
 
Please log in to Elentra to review the rejection reason and resubmit if needed:
https://ntu.elentra.cloud/profile/absences#/dashboard
 
This is an automated notification from your NTU Learning Assistant."""
   
    html_body = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"/></head>
<body style="margin:0;padding:0;background:#f0f2f5;font-family:'Segoe UI',Arial,sans-serif;">
<div style="max-width:540px;margin:32px auto;background:#fff;border:1px solid #e0e0e0;">
    <div style="background-color:#e05c5c;padding:28px 32px 20px;">
        <div style="font-size:12px;color:rgba(255,255,255,0.75);letter-spacing:0.1em;text-transform:uppercase;margin-bottom:6px;">NTU Lee Kong Chian School of Medicine</div>
        <div style="font-size:22px;font-weight:700;color:#fff;margin-bottom:2px;"> Absence Application Rejected</div>
        <div style="font-size:13px;color:rgba(255,255,255,0.85);margin-top:4px;">Action required — please review and resubmit</div>
    </div>
    <div style="padding:28px 32px;">
        <p style="margin:0 0 20px;font-size:15px;color:#495057;">Hi <strong>{username}</strong>, your recent absence application has been <strong style="color:#e05c5c;">rejected</strong>:</p>
        <table style="width:100%;border-collapse:collapse;border:1px solid #e9ecef;border-radius:8px;overflow:hidden;margin-bottom:20px;">
            <tr style="background:#f9fafb;border-bottom:1px solid #e9ecef;">
                <td style="padding:10px 16px;font-size:13px;color:#868e96;width:120px;">Reference</td>
                <td style="padding:10px 16px;font-size:13px;font-weight:600;color:#1a1a2e;">#{reference}</td>
            </tr>
            <tr style="background:#fff;border-bottom:1px solid #e9ecef;">
                <td style="padding:10px 16px;font-size:13px;color:#868e96;">Date(s)</td>
                <td style="padding:10px 16px;font-size:13px;color:#1a1a2e;">{from_date}</td>
            </tr>
            <tr style="background:#f9fafb;">
                <td style="padding:10px 16px;font-size:13px;color:#868e96;">Reason submitted</td>
                <td style="padding:10px 16px;font-size:13px;color:#1a1a2e;">{reason}</td>
            </tr>
        </table>
        <div style="background:#fff5f5;border:1px solid #fecaca;border-radius:8px;padding:12px 16px;margin-bottom:20px;">
            <p style="margin:0;font-size:13px;color:#991b1b;"><strong>⚠️ Action Required:</strong> Please log in to Elentra to review the rejection reason and resubmit your application if needed.</p>
        </div>
        <a href="https://ntu.elentra.cloud/profile/absences#/dashboard" style="display:inline-block;padding:10px 20px;background:{PURPLE};color:#fff;text-decoration:none;border-radius:8px;font-size:14px;font-weight:500;">View in Elentra →</a>
        <p style="margin:24px 0 0;font-size:13px;color:#868e96;line-height:1.6;">This notification was sent automatically.<br>You can manage LOA rejection alerts in the Learning Assistant ⚙️ Settings.</p>
    </div>
    <div style="background:{DARK_FOOTER};padding:14px 32px;">
        <p style="margin:0;font-size:12px;color:rgba(255,255,255,0.5);text-align:center;">NTU Lee Kong Chian School of Medicine · Absence Application Alert</p>
    </div>
</div>
</body></html>"""
   
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = mail_address
    msg["To"]      = to_email
    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))
   
    with smtplib.SMTP(smtp_server, smtp_port) as server:
        server.ehlo()
        server.starttls()
        server.login(mail_address, mail_password)
        server.sendmail(mail_address, to_email, msg.as_string())
   
    print(f"[MAILER] LOA rejection alert sent to {to_email} (Ref: #{reference})")