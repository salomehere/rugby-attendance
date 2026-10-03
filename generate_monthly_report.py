"""
Monthly Attendance Report — Rugby Club
Builds a PDF summarizing each player's attendance % for the previous
calendar month, reading from the same Google Sheet the daily sync writes to.

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


def fetch_month_attendance(start_date, end_date):
    client = get_sheet_client()
    spreadsheet = client.open_by_key(GOOGLE_SHEET_ID)
    ws = spreadsheet.worksheet("Attendance")
    rows = ws.get_all_records()

    stats = defaultdict(
        lambda: {"Accepted": 0, "Declined": 0, "No Response": 0, "Waiting List": 0, "Total": 0}
    )

    for row in rows:
        try:
            event_date = datetime.strptime(str(row.get("Date", "")), "%Y-%m-%d").date()
        except ValueError:
            continue
        if not (start_date <= event_date <= end_date):
            continue
        name = row.get("Member Name", "Unknown")
        response = row.get("Response", "No Response")
        stats[name]["Total"] += 1
        if response in stats[name]:
            stats[name][response] += 1

    return stats


def build_pdf(stats, month_label, out_path):
    rows = []
    for name, s in stats.items():
        pct = round((s["Accepted"] / s["Total"]) * 100, 1) if s["Total"] else 0.0
        rows.append((name, s["Total"], s["Accepted"], s["Declined"], s["No Response"], s["Waiting List"], pct))

    rows.sort(key=lambda r: r[-1], reverse=True)

    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(out_path, pagesize=A4)
    story = [
        Paragraph(f"Rugby Attendance Report — {month_label}", styles["Title"]),
        Paragraph(f"Generated {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC", styles["Normal"]),
        Spacer(1, 16),
    ]

    table_data = [["Player", "Events", "Accepted", "Declined", "No Response", "Waiting List", "Attendance %"]]
    for r in rows:
        table_data.append([r[0], r[1], r[2], r[3], r[4], r[5], f"{r[6]}%"])

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
