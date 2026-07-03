"""
Spond Attendance Pull — Rugby Club
Fetches attendance, responses, and comments from Spond
and writes them to Google Sheets using OAuth.

Requirements: pip install -r requirements.txt
Setup: See SETUP.md
"""

import asyncio
import os
from datetime import datetime, timedelta

import gspread
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from spond import spond

# ─── CONFIG ───────────────────────────────────────────────────────────────────

SPOND_USERNAME = os.environ.get("SPOND_USERNAME", "ash.salome@gmail.com")
SPOND_PASSWORD = os.environ.get("SPOND_PASSWORD", "Iloves2.")

GOOGLE_CLIENT_SECRET_FILE = "client_secret.json"   # downloaded from Google Cloud
GOOGLE_TOKEN_FILE = "token.json"                    # auto-created after first login
GOOGLE_SHEET_NAME = "Rugby Club Attendance"         # exact name of your Google Sheet

# How far back and forward to pull events (days)
DAYS_BACK = 365
DAYS_FORWARD = 90

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# ─── GOOGLE SHEETS AUTH ───────────────────────────────────────────────────────

def get_sheet_client():
    creds = None

    if os.path.exists(GOOGLE_TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(GOOGLE_TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            print("Opening browser for Google login — please sign in and click Allow...")
            flow = InstalledAppFlow.from_client_secrets_file(GOOGLE_CLIENT_SECRET_FILE, SCOPES)
            creds = flow.run_local_server(port=0)

        with open(GOOGLE_TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
        print("Google login saved — won't need to log in again.")

    return gspread.authorize(creds)

# ─── WORKSHEET HELPER ─────────────────────────────────────────────────────────

def get_or_create_worksheet(spreadsheet, title, headers):
    try:
        ws = spreadsheet.worksheet(title)
    except gspread.exceptions.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=title, rows=1000, cols=len(headers))
        ws.append_row(headers)
    return ws

# ─── SPOND FETCH ──────────────────────────────────────────────────────────────

async def fetch_spond_data():
    s = spond.Spond(username=SPOND_USERNAME, password=SPOND_PASSWORD)

    now = datetime.utcnow()
    min_dt = now - timedelta(days=DAYS_BACK)
    max_dt = now + timedelta(days=DAYS_FORWARD)

    print("Fetching groups...")
    groups = await s.get_groups()
    group = groups[0]
    group_id = group["id"]

    # Build member lookup: id -> full name
    members = {}
    for member in group.get("members", []):
        uid = member.get("id", "")
        first = member.get("firstName", "")
        last = member.get("lastName", "")
        members[uid] = f"{first} {last}".strip()

    print(f"Found {len(members)} members in group: {group.get('name', 'Unknown')}")

    print("Fetching events...")
    events = await s.get_events(
        min_end=min_dt,
        max_end=max_dt,
        group_id=group_id,
        max_events=200,
        include_scheduled=True,
    )

    print(f"Found {len(events)} events")

    attendance_rows = []
    event_summary_rows = []

    for event in events:
        event_id = event.get("id", "")
        heading = event.get("heading", "Unnamed Event")
        start_raw = event.get("startTimestamp", "")
        event_type = event.get("type", "")
        location = event.get("location", {})
        location_str = location.get("feature", "") if isinstance(location, dict) else ""

        # Parse start time
        try:
            start_dt = datetime.fromisoformat(start_raw.replace("Z", "+00:00"))
            start_str = start_dt.strftime("%Y-%m-%d %H:%M")
            start_date = start_dt.strftime("%Y-%m-%d")
        except Exception:
            start_str = start_raw
            start_date = ""

        # Responses
        responses = event.get("responses", {})
        accepted_ids = set(responses.get("acceptedIds", []))
        declined_ids = set(responses.get("declinedIds", []))
        unresponded_ids = set(responses.get("unrespondedIds", []))
        waiting_ids = set(responses.get("waitinglistIds", []))

        # Comments
        comments = event.get("comments", [])
        comment_texts = []
        for c in comments:
            author_id = c.get("author", {}).get("id", "")
            author_name = members.get(author_id, author_id)
            text = c.get("text", "")
            comment_texts.append(f"{author_name}: {text}")
        comments_str = " | ".join(comment_texts)

        spond_known_ids = accepted_ids | declined_ids | unresponded_ids | waiting_ids
        total_invited = len(spond_known_ids)
        attendance_pct = round((len(accepted_ids) / total_invited * 100), 1) if total_invited > 0 else 0

        event_summary_rows.append([
            event_id, heading, start_str, start_date, event_type, location_str,
            len(accepted_ids), len(declined_ids), len(unresponded_ids), len(waiting_ids),
            total_invited, attendance_pct, comments_str,
            datetime.utcnow().strftime("%Y-%m-%d %H:%M"),
        ])

        # Write a row for EVERY group member for EVERY event.
        # If Spond has no response recorded, treat as "No Response".
        for uid, name in members.items():
            if uid in accepted_ids:
                status = "Accepted"
            elif uid in declined_ids:
                status = "Declined"
            elif uid in waiting_ids:
                status = "Waiting List"
            else:
                # Covers both unrespondedIds and members Spond has no record of
                status = "No Response"

            attendance_rows.append([event_id, heading, start_str, start_date, name, status])

    await s.clientsession.close()
    return event_summary_rows, attendance_rows, members

# ─── WRITE TO GOOGLE SHEETS ───────────────────────────────────────────────────

def write_to_sheets(event_summary_rows, attendance_rows, members):
    print("Connecting to Google Sheets...")
    client = get_sheet_client()
    spreadsheet = client.open(GOOGLE_SHEET_NAME)

    event_headers = [
        "Event ID", "Event Name", "Date & Time", "Date",
        "Type", "Location",
        "Accepted", "Declined", "No Response", "Waiting List",
        "Total Invited", "Attendance %", "Comments", "Last Updated"
    ]
    ws_events = get_or_create_worksheet(spreadsheet, "Events", event_headers)
    ws_events.clear()
    ws_events.append_row(event_headers)
    if event_summary_rows:
        ws_events.append_rows(event_summary_rows)
    print(f"Written {len(event_summary_rows)} events to 'Events' sheet")

    att_headers = ["Event ID", "Event Name", "Date & Time", "Date", "Member Name", "Response"]
    ws_att = get_or_create_worksheet(spreadsheet, "Attendance", att_headers)
    ws_att.clear()
    ws_att.append_row(att_headers)
    if attendance_rows:
        ws_att.append_rows(attendance_rows)
    print(f"Written {len(attendance_rows)} attendance rows to 'Attendance' sheet")

    member_headers = ["Member ID", "Member Name"]
    ws_members = get_or_create_worksheet(spreadsheet, "Members", member_headers)
    ws_members.clear()
    ws_members.append_row(member_headers)
    member_rows = [[uid, name] for uid, name in sorted(members.items(), key=lambda x: x[1])]
    if member_rows:
        ws_members.append_rows(member_rows)
    print(f"Written {len(member_rows)} members to 'Members' sheet")

    print("✅ All done! Google Sheet updated.")

# ─── MAIN ─────────────────────────────────────────────────────────────────────

async def main():
    print(f"Starting Spond pull — {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC")
    event_summary_rows, attendance_rows, members = await fetch_spond_data()
    write_to_sheets(event_summary_rows, attendance_rows, members)

if __name__ == "__main__":
    asyncio.run(main())
