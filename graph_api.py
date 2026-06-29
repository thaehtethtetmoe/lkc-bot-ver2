# graph_api.py
import requests
from datetime import datetime, timedelta
import pytz

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
SGT = pytz.timezone("Asia/Singapore")

def get_outlook_events(graph_token):
    """Get student's Outlook calendar events using their SSO token."""
    if not graph_token:
        return []

    headers = {"Authorization": f"Bearer {graph_token}"}
    
    start = datetime.now(SGT).strftime("%Y-%m-%dT00:00:00")
    end = (datetime.now(SGT) + timedelta(days=7)).strftime("%Y-%m-%dT23:59:59")
    
    params = {
        "$select": "subject,start,end,location",
        "$orderby": "start/dateTime",
        "$filter": f"start/dateTime ge '{start}' and end/dateTime le '{end}'",
        "$top": 50
    }
    
    try:
        resp = requests.get(
            f"{GRAPH_BASE}/me/calendar/events",
            headers=headers,
            params=params,
            timeout=10
        )
        
        if resp.status_code == 200:
            events = resp.json().get("value", [])
            formatted = []
            for e in events:
                start_dt = datetime.fromisoformat(
                    e["start"]["dateTime"].replace("Z", "+00:00")
                ).astimezone(SGT)
                end_dt = datetime.fromisoformat(
                    e["end"]["dateTime"].replace("Z", "+00:00")
                ).astimezone(SGT)
                
                formatted.append({
                    "title": e["subject"],
                    "date": start_dt.strftime("%A, %d %b %Y"),
                    "time": f"{start_dt.strftime('%H:%M')} – {end_dt.strftime('%H:%M')}",
                    "location": e.get("location", {}).get("displayName", "TBC"),
                    "source": "Outlook"
                })
            return formatted
        else:
            print(f"[GRAPH] Error: {resp.status_code}")
            return []
    except Exception as e:
        print(f"[GRAPH] Failed: {e}")
        return []


def get_user_profile(graph_token):
    """Get student's Microsoft profile info."""
    headers = {"Authorization": f"Bearer {graph_token}"}
    try:
        resp = requests.get(f"{GRAPH_BASE}/me", headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            return {
                "name": data.get("displayName"),
                "email": data.get("mail") or data.get("userPrincipalName"),
                "department": data.get("department", ""),
            }
    except:
        pass
    return None