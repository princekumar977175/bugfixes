"""Generate polished visual UI screenshots/diagrams for Control-Room and Passenger Views.

Produces:
1. reports/screenshot_control_room.png
2. reports/screenshot_passenger_view.png
"""

import os
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.patches as patches
import matplotlib.pyplot as plt

ROOT_DIR = Path(__file__).resolve().parent.parent
REPORTS_DIR = ROOT_DIR / "reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)
ARTIFACTS_DIR_ENV = os.getenv("ARTIFACTS_DIR")
ARTIFACTS_DIR = Path(ARTIFACTS_DIR_ENV) if ARTIFACTS_DIR_ENV else None


def generate_control_room_screenshot():
    """Render a high-fidelity visual layout of the Control-Room UI."""
    fig = plt.figure(figsize=(14, 8.5), dpi=200, facecolor="#0f172a")
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_facecolor("#0f172a")
    ax.set_xlim(0, 1400)
    ax.set_ylim(0, 850)
    ax.axis("off")

    # 1. Header Bar
    ax.add_patch(patches.Rectangle((0, 780), 1400, 70, facecolor="#1e293b", edgecolor="#334155", linewidth=1.5))
    ax.text(25, 815, "ANTIGRAVITY", fontsize=15, fontweight="bold", color="#38bdf8", va="center")
    ax.text(145, 815, "|  DYNAMIC ETA CONTROL ROOM", fontsize=13, fontweight="bold", color="#f8fafc", va="center")

    # Mode Switcher Chips
    ax.add_patch(patches.FancyBboxPatch((480, 796), 130, 36, boxstyle="round,pad=3", facecolor="#0284c7", edgecolor="#38bdf8"))
    ax.text(545, 814, "Control Room", fontsize=10, fontweight="bold", color="#ffffff", ha="center", va="center")
    ax.add_patch(patches.FancyBboxPatch((625, 796), 130, 36, boxstyle="round,pad=3", facecolor="#1e293b", edgecolor="#475569"))
    ax.text(690, 814, "Passenger View", fontsize=10, fontweight="bold", color="#94a3b8", ha="center", va="center")

    # Simulated Data Warning Badge
    ax.add_patch(patches.FancyBboxPatch((1180, 796), 195, 36, boxstyle="round,pad=3", facecolor="#7f1d1d", edgecolor="#ef4444"))
    ax.text(1277, 814, "[!] SIMULATED DATA", fontsize=10, fontweight="bold", color="#fecaca", ha="center", va="center")

    # 2. Replay Toolbar
    ax.add_patch(patches.Rectangle((25, 715), 1350, 52, facecolor="#1e293b", edgecolor="#334155", linewidth=1))
    ax.text(45, 741, "SIMULATOR REPLAY:", fontsize=11, fontweight="bold", color="#94a3b8", va="center")
    ax.add_patch(patches.FancyBboxPatch((185, 725), 80, 32, boxstyle="round,pad=2", facecolor="#15803d", edgecolor="#22c55e"))
    ax.text(225, 741, "> RUNNING", fontsize=9.5, fontweight="bold", color="#ffffff", ha="center", va="center")

    ax.text(290, 741, "Clock: 2026-01-20 07:35:00 IST", fontsize=11, fontweight="bold", color="#38bdf8", va="center")

    # Speed Multipliers
    speeds = ["1x", "2x", "5x", "10x", "20x"]
    for i, s in enumerate(speeds):
        bg = "#0284c7" if s == "5x" else "#334155"
        ax.add_patch(patches.FancyBboxPatch((620 + i * 45, 727), 38, 28, boxstyle="round,pad=2", facecolor=bg, edgecolor="#475569"))
        ax.text(639 + i * 45, 741, s, fontsize=9, fontweight="bold", color="#ffffff", ha="center", va="center")

    ax.text(880, 741, "Active Fleet: 10 Trains | Corridor: NDLS -> MKA (1,088 km)", fontsize=10.5, color="#cbd5e1", va="center")

    # 3. Main Map Panel (Left / Center)
    ax.add_patch(patches.Rectangle((25, 25), 840, 675, facecolor="#090d16", edgecolor="#334155", linewidth=1.5))
    ax.text(45, 675, "CORRIDOR INFRASTRUCTURE & ACTIVE FLEET MAP", fontsize=11.5, fontweight="bold", color="#f8fafc")

    # Track Backbone (Trunk Line with gradient/segmented status)
    track_coords = [
        (60, 550, "NDLS", "On Time", "#22c55e"),
        (160, 540, "GZB", "TSR 60", "#eab308"),
        (260, 500, "ALJN", "Fog Reg", "#eab308"),
        (370, 460, "TDL", "Normal", "#22c55e"),
        (460, 410, "ETW", "TSR 30", "#ef4444"),
        (560, 350, "CNB", "Contention", "#ef4444"),
        (640, 290, "FTP", "Normal", "#22c55e"),
        (720, 220, "PRYJ", "Overrun", "#eab308"),
        (780, 150, "DDU", "Normal", "#22c55e"),
        (820, 90, "PNBE", "Normal", "#22c55e"),
    ]

    for i in range(len(track_coords) - 1):
        x1, y1, code1, _, c1 = track_coords[i]
        x2, y2, code2, _, _ = track_coords[i + 1]
        line_color = "#ef4444" if (track_coords[i][4] == "#ef4444" or track_coords[i + 1][4] == "#ef4444") else (
            "#eab308" if (track_coords[i][4] == "#eab308" or track_coords[i + 1][4] == "#eab308") else "#22c55e"
        )
        ax.plot([x1, x2], [y1, y2], color=line_color, linewidth=5, zorder=2)
        ax.plot([x1, x2], [y1, y2], color=line_color, linewidth=10, alpha=0.2, zorder=1)

    for x, y, code, _status, dot_c in track_coords:
        ax.plot(x, y, "o", color="#f8fafc", markersize=9, zorder=4)
        ax.plot(x, y, "o", color=dot_c, markersize=6, zorder=5)
        ax.text(x, y + 14, code, fontsize=9.5, fontweight="bold", color="#ffffff", ha="center", zorder=6)

    # Disruption Callout Boxes on Map
    ax.add_patch(patches.FancyBboxPatch((130, 470), 160, 45, boxstyle="round,pad=3", facecolor="#451a03", edgecolor="#f59e0b", linewidth=1.2))
    ax.text(210, 492, "[FOG] DENSE FOG WINDOW\nGZB-ALJN (Speed: 60 km/h)", fontsize=8, fontweight="bold", color="#fde68a", ha="center", va="center")

    ax.add_patch(patches.FancyBboxPatch((420, 450), 160, 45, boxstyle="round,pad=3", facecolor="#450a0a", edgecolor="#ef4444", linewidth=1.2))
    ax.text(500, 472, "[TSR] TSR BLOCK 30 km/h\nETW-CNB Track Repair", fontsize=8, fontweight="bold", color="#fecaca", ha="center", va="center")

    # Moving Trains on Map
    # Train 12002
    ax.plot(210, 520, "D", color="#38bdf8", markersize=11, zorder=7)
    ax.add_patch(patches.FancyBboxPatch((165, 545), 100, 24, boxstyle="round,pad=2", facecolor="#0369a1", edgecolor="#38bdf8"))
    ax.text(215, 557, "12002 (+21m)", fontsize=8.5, fontweight="bold", color="#ffffff", ha="center", va="center")

    # Train 12302
    ax.plot(510, 380, "D", color="#a855f7", markersize=11, zorder=7)
    ax.add_patch(patches.FancyBboxPatch((465, 330), 100, 24, boxstyle="round,pad=2", facecolor="#6b21a8", edgecolor="#c084fc"))
    ax.text(515, 342, "12302 (+37m)", fontsize=8.5, fontweight="bold", color="#ffffff", ha="center", va="center")

    # Heatmap Legend
    ax.add_patch(patches.FancyBboxPatch((45, 45), 320, 70, boxstyle="round,pad=3", facecolor="#1e293b", edgecolor="#334155"))
    ax.text(60, 95, "SECTION CONGESTION HEATMAP:", fontsize=8.5, fontweight="bold", color="#cbd5e1")
    ax.plot([60, 80], [70, 70], color="#22c55e", linewidth=4)
    ax.text(88, 70, "<10m Free", fontsize=8, color="#94a3b8", va="center")
    ax.plot([145, 165], [70, 70], color="#eab308", linewidth=4)
    ax.text(173, 70, "10-20m / TSR", fontsize=8, color="#94a3b8", va="center")
    ax.plot([250, 270], [70, 70], color="#ef4444", linewidth=4)
    ax.text(278, 70, ">20m Heavy", fontsize=8, color="#94a3b8", va="center")

    # 4. Right Fleet Table & Knock-on Risk Panel
    ax.add_patch(patches.Rectangle((885, 25), 490, 675, facecolor="#1e293b", edgecolor="#334155", linewidth=1.5))
    ax.text(905, 675, "FLEET DELAY & KNOCK-ON RISK MONITOR", fontsize=11.5, fontweight="bold", color="#f8fafc")

    # Table Headers
    ax.add_patch(patches.Rectangle((900, 630), 460, 30, facecolor="#334155"))
    headers = ["Train #", "Type", "Current", "Delay", "Knock-on Risk"]
    cols_x = [915, 990, 1070, 1175, 1260]
    for h, x_pos in zip(headers, cols_x, strict=False):
        ax.text(x_pos, 645, h, fontsize=9, fontweight="bold", color="#cbd5e1", va="center")

    # Rows
    fleet_rows = [
        ("12002", "Vande Bharat", "GZB-ALJN", "+21m", "HIGH (18m)", "#ef4444", "#7f1d1d"),
        ("12302", "Rajdhani Exp", "ETW-CNB", "+37m", "HIGH (24m)", "#ef4444", "#7f1d1d"),
        ("13008", "Toofan Exp", "FTP-PRYJ", "+14m", "MEDIUM (7m)", "#eab308", "#78350f"),
        ("12394", "Sampark Kranti", "TDL", "+6m", "LOW (Safe)", "#22c55e", "#14532d"),
        ("54302", "Passenger", "NDLS", "On Time", "LOW (Safe)", "#22c55e", "#14532d"),
    ]

    for idx, (t_no, t_name, loc, delay, risk, tag_c, tag_bg) in enumerate(fleet_rows):
        y_r = 590 - idx * 58
        ax.add_patch(patches.Rectangle((900, y_r - 18), 460, 48, facecolor="#1e293b" if idx % 2 == 0 else "#0f172a", edgecolor="#334155", linewidth=0.5))
        ax.text(915, y_r + 5, t_no, fontsize=10, fontweight="bold", color="#38bdf8")
        ax.text(990, y_r + 5, t_name, fontsize=8.5, color="#cbd5e1")
        ax.text(1070, y_r + 5, loc, fontsize=8.5, color="#94a3b8")
        ax.text(1175, y_r + 5, delay, fontsize=9.5, fontweight="bold", color="#f87171" if "+" in delay else "#4ade80")

        # Risk badge
        ax.add_patch(patches.FancyBboxPatch((1245, y_r - 6), 105, 24, boxstyle="round,pad=2", facecolor=tag_bg, edgecolor=tag_c))
        ax.text(1297, y_r + 6, risk, fontsize=8, fontweight="bold", color=tag_c, ha="center", va="center")

    # Dispatcher Notice Box
    ax.add_patch(patches.FancyBboxPatch((900, 50), 460, 160, boxstyle="round,pad=4", facecolor="#090d16", edgecolor="#0284c7", linewidth=1.5))
    ax.text(915, 185, "AUTOMATED DISPATCH ADVISORY", fontsize=10, fontweight="bold", color="#38bdf8")
    advice_text = (
        "• Train 12002 entering fog zone GZB-ALJN; predicted delay +21m.\n"
        "• High Knock-On Risk: Trailing 12394 will encounter headway hold at ALJN.\n"
        "• Recommended Action: Hold 54302 on loop line at Tundla to prioritize\n"
        "  12002 recovery path into Kanpur Central."
    )
    ax.text(915, 115, advice_text, fontsize=8.5, color="#e2e8f0", va="center")

    out_file = REPORTS_DIR / "screenshot_control_room.png"
    plt.savefig(out_file, dpi=200)
    plt.close(fig)
    print(f"[+] Saved Control Room Screenshot: {out_file}")

    if ARTIFACTS_DIR and ARTIFACTS_DIR.exists():
        import shutil
        shutil.copy2(out_file, ARTIFACTS_DIR / out_file.name)


def generate_passenger_view_screenshot():
    """Render a high-fidelity visual layout of the Passenger View UI."""
    fig = plt.figure(figsize=(14, 8.5), dpi=200, facecolor="#f8fafc")
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_facecolor("#f8fafc")
    ax.set_xlim(0, 1400)
    ax.set_ylim(0, 850)
    ax.axis("off")

    # 1. Header Bar
    ax.add_patch(patches.Rectangle((0, 780), 1400, 70, facecolor="#0284c7", edgecolor="#0369a1", linewidth=1.5))
    ax.text(35, 815, "ANTIGRAVITY RAIL PASSENGER PORTAL", fontsize=15, fontweight="bold", color="#ffffff", va="center")
    ax.text(430, 815, "|  LIVE DYNAMIC ETA & EXPLANATION", fontsize=12, color="#e0f2fe", va="center")

    # Simulated Data Warning Badge
    ax.add_patch(patches.FancyBboxPatch((1180, 796), 185, 36, boxstyle="round,pad=3", facecolor="#b91c1c", edgecolor="#ef4444"))
    ax.text(1272, 814, "[!] SIMULATED DATA", fontsize=10, fontweight="bold", color="#ffffff", ha="center", va="center")

    # 2. Search & Filter Bar
    ax.add_patch(patches.Rectangle((35, 710), 1330, 55, facecolor="#ffffff", edgecolor="#cbd5e1", linewidth=1.2))
    ax.text(55, 737, "SEARCH TRAIN:", fontsize=11, fontweight="bold", color="#334155", va="center")
    ax.add_patch(patches.FancyBboxPatch((170, 720), 280, 35, boxstyle="round,pad=2", facecolor="#f1f5f9", edgecolor="#94a3b8"))
    ax.text(185, 737, "12002 - Vande Bharat Express", fontsize=10, fontweight="bold", color="#0f172a", va="center")

    chips = ["12002 (Vande Bharat)", "12302 (Rajdhani)", "12394 (Sampark Kranti)", "13008 (Toofan)"]
    for i, ch in enumerate(chips):
        bg = "#e0f2fe" if "12002" in ch else "#f8fafc"
        bd = "#0284c7" if "12002" in ch else "#cbd5e1"
        ax.add_patch(patches.FancyBboxPatch((480 + i * 180, 720), 170, 35, boxstyle="round,pad=2", facecolor=bg, edgecolor=bd))
        ax.text(565 + i * 180, 737, ch, fontsize=8.5, fontweight="bold", color="#0369a1" if "12002" in ch else "#64748b", ha="center", va="center")

    # 3. Main Hero Card (Left Panel)
    ax.add_patch(patches.FancyBboxPatch((35, 290), 680, 400, boxstyle="round,pad=4", facecolor="#ffffff", edgecolor="#cbd5e1", linewidth=1.5))
    ax.text(60, 660, "12002  VANDE BHARAT EXPRESS", fontsize=14, fontweight="bold", color="#0f172a")
    ax.text(60, 638, "New Delhi (NDLS)  ->  Mokama Jn (MKA)  •  Direction: DN", fontsize=9.5, color="#64748b")

    # Big ETA Display
    ax.add_patch(patches.FancyBboxPatch((60, 490), 630, 130, boxstyle="round,pad=3", facecolor="#f0f9ff", edgecolor="#bae6fd", linewidth=1.5))
    ax.text(85, 590, "NEXT DESTINATION: KANPUR CENTRAL (CNB)", fontsize=10, fontweight="bold", color="#0369a1")
    ax.text(85, 535, "10:38 AM", fontsize=38, fontweight="bold", color="#0284c7")
    ax.text(310, 545, "+36 min Delayed", fontsize=14, fontweight="bold", color="#dc2626")

    # Best-Case / Worst-Case Bounds
    ax.add_patch(patches.FancyBboxPatch((60, 380), 630, 90, boxstyle="round,pad=3", facecolor="#f8fafc", edgecolor="#e2e8f0"))
    ax.text(85, 445, "UNCONFIRMED WINDOW (10th – 90th PERCENTILE):", fontsize=9, fontweight="bold", color="#475569")
    ax.text(85, 405, "10:30 AM  (Best Case / p10)", fontsize=11, fontweight="bold", color="#16a34a")
    ax.text(340, 405, "->", fontsize=13, color="#94a3b8")
    ax.text(380, 405, "10:56 AM  (Worst Case / p90)", fontsize=11, fontweight="bold", color="#d97706")
    ax.text(585, 405, "±13 min spread", fontsize=9, color="#64748b")

    # Alert Toggle
    ax.add_patch(patches.FancyBboxPatch((60, 310), 630, 50, boxstyle="round,pad=3", facecolor="#f1f5f9", edgecolor="#cbd5e1"))
    ax.text(85, 335, "[ALERT]  Alert me 15 minutes before arrival at destination", fontsize=10, fontweight="bold", color="#334155", va="center")
    ax.add_patch(patches.FancyBboxPatch((600, 320), 70, 30, boxstyle="round,pad=2", facecolor="#16a34a", edgecolor="#15803d"))
    ax.text(635, 335, "ACTIVE", fontsize=8.5, fontweight="bold", color="#ffffff", ha="center", va="center")

    # 4. "Why Did This Change?" Panel (Right Upper)
    ax.add_patch(patches.FancyBboxPatch((740, 470), 625, 220, boxstyle="round,pad=4", facecolor="#ffffff", edgecolor="#f59e0b", linewidth=1.5))
    ax.text(765, 665, "WHY DID THIS ETA CHANGE?", fontsize=12, fontweight="bold", color="#b45309")
    ax.text(765, 640, "Plain-Language Root Cause Attribution (TreeSHAP Driver Engine):", fontsize=9, color="#64748b")

    reason_quote = (
        "\"+36 min: fog visibility regulation on section GZB-ALJN-DN, "
        "speed restriction in section ETW-CNB-DN, "
        "historical section bottleneck on section GZB-ALJN-DN\""
    )
    ax.add_patch(patches.FancyBboxPatch((765, 560), 575, 65, boxstyle="round,pad=3", facecolor="#fef3c7", edgecolor="#fde68a"))
    ax.text(780, 592, reason_quote, fontsize=9.5, fontweight="bold", color="#92400e", wrap=True, va="center")

    # Attribution Driver Pills
    drivers = [
        ("Dense Fog Window (+21m)", "#ef4444", "#fee2e2"),
        ("TSR Speed Cap 30 km/h (+12m)", "#f97316", "#ffedd5"),
        ("Track Headway Caution (+3m)", "#eab308", "#fef9c3"),
    ]
    for idx, (drv_text, border, fill) in enumerate(drivers):
        ax.add_patch(patches.FancyBboxPatch((765 + idx * 190, 490), 180, 34, boxstyle="round,pad=2", facecolor=fill, edgecolor=border))
        ax.text(855 + idx * 190, 507, drv_text, fontsize=8, fontweight="bold", color="#1e293b", ha="center", va="center")

    # 5. Upcoming Stations Timeline (Right Lower)
    ax.add_patch(patches.FancyBboxPatch((740, 40), 625, 410, boxstyle="round,pad=4", facecolor="#ffffff", edgecolor="#cbd5e1", linewidth=1.5))
    ax.text(765, 420, "UPCOMING STATIONS & CONFIDENCE TIMELINE", fontsize=11, fontweight="bold", color="#0f172a")

    timeline_data = [
        ("Aligarh Jn (ALJN)", "07:09", "07:13", "07:30", "07:25 – 07:37", "Arrived (07:30)", "#16a34a"),
        ("Kanpur Central (CNB)", "10:02", "10:06", "10:38", "10:30 – 10:56", "In Transit (+36m)", "#0284c7"),
        ("Prayagraj Jn (PRYJ)", "11:57", "12:01", "12:27", "12:18 – 12:52", "Scheduled (+30m)", "#64748b"),
        ("Pt. DD Upadhyaya (DDU)", "13:26", "13:30", "13:52", "13:42 – 14:22", "Scheduled (+26m)", "#64748b"),
        ("Patna Jn (PNBE)", "15:22", "15:26", "15:48", "15:35 – 16:25", "Scheduled (+26m)", "#64748b"),
        ("Mokama Jn (MKA)", "16:12", "16:16", "16:38", "16:20 – 17:15", "Scheduled (+26m)", "#64748b"),
    ]

    # Timeline header
    ax.text(770, 385, "Station", fontsize=8.5, fontweight="bold", color="#64748b")
    ax.text(930, 385, "Timetable", fontsize=8.5, fontweight="bold", color="#64748b")
    ax.text(1005, 385, "Base A", fontsize=8.5, fontweight="bold", color="#64748b")
    ax.text(1070, 385, "Model Median", fontsize=8.5, fontweight="bold", color="#0284c7")
    ax.text(1185, 385, "10-90 Range", fontsize=8.5, fontweight="bold", color="#64748b")

    for i, (stn, sch, b_a, med, rng, _status, st_c) in enumerate(timeline_data):
        y_pos = 350 - i * 50
        ax.plot([755, 755], [y_pos - 10, y_pos + 15], color="#cbd5e1", linewidth=2)
        ax.plot(755, y_pos, "o", color=st_c, markersize=7)

        ax.text(770, y_pos, stn, fontsize=8.5, fontweight="bold", color="#0f172a")
        ax.text(930, y_pos, sch, fontsize=8.5, color="#64748b")
        ax.text(1005, y_pos, b_a, fontsize=8.5, color="#ef4444")
        ax.text(1070, y_pos, med, fontsize=9, fontweight="bold", color="#0284c7")
        ax.text(1185, y_pos, rng, fontsize=8, color="#64748b")

    out_file = REPORTS_DIR / "screenshot_passenger_view.png"
    plt.savefig(out_file, dpi=200)
    plt.close(fig)
    print(f"[+] Saved Passenger View Screenshot: {out_file}")

    if ARTIFACTS_DIR and ARTIFACTS_DIR.exists():
        import shutil
        shutil.copy2(out_file, ARTIFACTS_DIR / out_file.name)


if __name__ == "__main__":
    generate_control_room_screenshot()
    generate_passenger_view_screenshot()
