"""
Monthly Attendance Report — Rugby Club
Builds a PDF with each player's training attendance % and game attendance %
for the previous calendar month, reading from the same Google Sheet the
daily sync writes to. Coaches are excluded from the player breakdown.

Auth: Application Default Credentials (see spond_pull.py for details — in
GitHub Actions this is set up by the google-github-actions/auth step).
"""

import os
from collections import defaultdict
from datetime import datetime, timedelta

import google.auth
import gspread
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

GOOGLE_SHEET_ID = "1MLG6Xf9zGDx9orTGHG2Hk5wrynZKuZoxmdhSgeAXpVk"  # Rugby Club Attendance
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# Coaches - excluded from the player attendance breakdown. Use real names as
# they appear in Spond/the Sheet, not dashboard nicknames (e.g. "Goose" is
# Angus Guthrie).
COACHES = {"Angus Guthrie", "Lisa Newman"}


def get_sheet_client():
    creds, _ = google.auth.default(scopes=SCOPES)
    return gspread.authorize(creds)


def previous_month_range(today=None):
    today = today or datetime.utcnow()
    first_of_this_month = today.replace(day=1)
    last_day_prev_month = first_of_this_month - timedelta(days=1)
    first_day_prev_month = last_day_prev_month.replace(day=1)
    return (
        first_day_prev_month.date(),
        last_day_prev_month.date(),
        first_day_prev_month.strftime("%B %Y"),
    )


def classify_event(event_name):
    name = (event_name or "").lower()
    if "training" in name or "preseason" in name or "pre season" in name:
        return "Training"
    return "Game"


def fetch_month_attendance(start_date, end_date):
    client = get_sheet_client()
    spreadsheet = client.open_by_key(GOOGLE_SHEET_ID)
    ws = spreadsheet.worksheet("Attendance")
    rows = ws.get_all_records()

    stats = defaultdict(
        lambda: {
            "Training": {"Accepted": 0, "Total": 0},
            "Game": {"Accepted": 0, "Total": 0},
        }
    )

    for row in rows:
        try:
            event_date = datetime.strptime(str(row.get("Date", "")), "%Y-%m-%d").date()
        except ValueError:
            continue
        if not (start_date <= event_date <= end_date):
            continue

        name = row.get("Member Name", "Unknown")
        if name in COACHES:
            continue

        category = classify_event(row.get("Event Name", ""))
        response = row.get("Response", "No Response")

        stats[name][category]["Total"] += 1
        if response == "Accepted":
            stats[name][category]["Accepted"] += 1

    return stats


def pct_or_none(accepted, total):
    if total == 0:
        return None
    return round((accepted / total) * 100, 1)


def fmt_pct(pct):
    return "—" if pct is None else f"{pct}%"


def build_pdf(stats, month_label, out_path):
    rows = []
    for name, s in stats.items():
        train_pct = pct_or_none(s["Training"]["Accepted"], s["Training"]["Total"])
        game_pct = pct_or_none(s["Game"]["Accepted"], s["Game"]["Total"])
        rows.append((name, train_pct, game_pct))

    # Highest to lowest, training % as the primary sort key. Players with no
    # recorded events in a category (None) sort to the bottom of that key.
    rows.sort(key=lambda r: (r[1] if r[1] is not None else -1, r[2] if r[2] is not None else -1), reverse=True)

    rows = [(name, fmt_pct(train_pct), fmt_pct(game_pct)) for name, train_pct, game_pct in rows]

    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(out_path, pagesize=A4)
    story = [
        Paragraph(f"Rugby Attendance Report — {month_label}", styles["Title"]),
        Paragraph(f"Generated {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC", styles["Normal"]),
        Spacer(1, 16),
    ]

    table_data = [["Player", "Training Attendance %", "Game Attendance %"]]
    for r in rows:
        table_data.append(list(r))

    table = Table(table_data, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2d3d")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f5f5")]),
                ("ALIGN", (1, 0), (-1, -1), "CENTER"),
            ]
        )
    )
    story.append(table)
    doc.build(story)


def main():
    start_date, end_date, month_label = previous_month_range()
    stats = fetch_month_attendance(start_date, end_date)

    if not stats:
        print(f"No attendance data found for {month_label} — skipping report.")
        return

    os.makedirs("reports", exist_ok=True)
    filename = f"reports/attendance-{start_date.strftime('%Y-%m')}.pdf"
    build_pdf(stats, month_label, filename)
    print(f"Wrote {filename}")


if __name__ == "__main__":
    main()
