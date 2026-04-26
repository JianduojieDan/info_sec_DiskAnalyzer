import argparse
import os
import socket
import sys
from datetime import datetime
from email.message import EmailMessage
from typing import Dict, List, Tuple

import requests
import smtplib


def get_scan_roots() -> List[str]:
    roots_env = os.getenv("SCAN_ROOTS")
    if roots_env:
        roots = [p.strip() for p in roots_env.split(",") if p.strip()]
        if roots:
            return roots
    home = os.path.expanduser("~")
    return [home]


def iter_first_level_dirs(root: str) -> List[str]:
    dirs: List[str] = []
    try:
        with os.scandir(root) as it:
            for entry in it:
                if entry.is_dir(follow_symlinks=False):
                    dirs.append(entry.path)
    except OSError:
        return []
    return dirs


def dir_size_bytes(path: str) -> int:
    total = 0
    for current_root, dirs, files in os.walk(path, onerror=lambda e: None, followlinks=False):
        for name in files:
            fp = os.path.join(current_root, name)
            try:
                st = os.stat(fp)
            except OSError:
                continue
            total += st.st_size
    return total


def bytes_to_gb(size_bytes: int) -> float:
    if size_bytes <= 0:
        return 0.0
    return round(size_bytes / (1024 ** 3), 3)


def build_items_for_roots(roots: List[str]) -> List[Dict[str, float]]:
    items: List[Dict[str, float]] = []
    for root in roots:
        first_level = iter_first_level_dirs(root)
        targets = first_level if first_level else [root]
        for path in targets:
            size_bytes = dir_size_bytes(path)
            size_gb = bytes_to_gb(size_bytes)
            items.append({"folder_path": path, "size_gb": size_gb})
    return items


def build_report(roots: List[str]) -> Dict:
    hostname = socket.gethostname()
    timestamp = datetime.now().isoformat()
    items = build_items_for_roots(roots)
    if not items:
        raise RuntimeError("No directories found to report.")
    report = {
        "hostname": hostname,
        "timestamp": timestamp,
        "items": items,
    }
    return report


def send_report_to_backend(report: Dict, backend_url: str, timeout: int, dry_run: bool) -> bool:
    url = backend_url.rstrip("/") + "/report"
    if dry_run:
        print("Dry run enabled. Skipping HTTP POST to backend.")
        print(f"Backend URL: {url}")
        print(f"Report summary: hostname={report['hostname']}, items={len(report['items'])}")
        return True
    try:
        response = requests.post(url, json=report, timeout=timeout)
        if response.status_code != 200:
            print(f"Backend responded with status {response.status_code}: {response.text}", file=sys.stderr)
            return False
        print(f"Report sent to backend {url}. Response: {response.json()}")
        return True
    except requests.RequestException as exc:
        print(f"Failed to send report to backend: {exc}", file=sys.stderr)
        return False


def summarize_items(items: List[Dict[str, float]], big_threshold_gb: float, top_n: int) -> Tuple[float, List[Dict]]:
    total_gb = sum(item["size_gb"] for item in items)
    sorted_items = sorted(items, key=lambda x: x["size_gb"], reverse=True)
    top_items = sorted_items[:top_n]
    for item in top_items:
        item["is_big"] = item["size_gb"] >= big_threshold_gb
    return total_gb, top_items


def build_email_content(report: Dict, big_threshold_gb: float, top_n: int) -> Tuple[str, str]:
    hostname = report["hostname"]
    timestamp = report["timestamp"]
    items = report["items"]
    total_gb, top_items = summarize_items(items, big_threshold_gb, top_n)

    subject = f"Disk Analyzer Daily Report - {hostname} - {timestamp}"

    lines: List[str] = []
    lines.append("Disk Analyzer Daily Report")
    lines.append("")
    lines.append(f"Host: {hostname}")
    lines.append(f"Timestamp: {timestamp}")
    lines.append("")
    lines.append(f"Total directories scanned: {len(items)}")
    lines.append(f"Total size (GB): {total_gb:.3f}")
    lines.append("")
    lines.append(f"Top {len(top_items)} directories by size:")
    for index, item in enumerate(top_items, start=1):
        marker = " HIGH USAGE" if item.get("is_big") else ""
        lines.append(f"{index}. {item['folder_path']}: {item['size_gb']:.3f} GB{marker}")
    lines.append("")
    lines.append(f"High usage threshold: {big_threshold_gb:.3f} GB")

    body = "\n".join(lines)
    return subject, body


def send_email(subject: str, body: str, dry_run: bool) -> bool:
    host = os.getenv("EMAIL_HOST", "smtp.gmail.com")
    port_str = os.getenv("EMAIL_PORT", "587")
    user = os.getenv("EMAIL_USER")
    password = os.getenv("EMAIL_PASSWORD")
    to_addr = os.getenv("EMAIL_TO", user)

    try:
        port = int(port_str)
    except ValueError:
        print(f"Invalid EMAIL_PORT value: {port_str}", file=sys.stderr)
        return False

    if not user or not password or not to_addr:
        print("Email configuration is incomplete. Skipping email sending.", file=sys.stderr)
        print(f"EMAIL_USER set: {bool(user)}; EMAIL_TO set: {bool(to_addr)}")
        return False

    if dry_run:
        print("Dry run enabled. Skipping email send.")
        print(f"Email subject: {subject}")
        print("Email body preview:")
        print(body)
        return True

    message = EmailMessage()
    message["From"] = user
    message["To"] = to_addr
    message["Subject"] = subject
    message.set_content(body, charset="utf-8")

    try:
        with smtplib.SMTP(host, port) as server:
            server.starttls()
            server.login(user, password)
            server.send_message(message)
        print(f"Email sent to {to_addr}")
        return True
    except Exception as exc:
        print(f"Failed to send email: {exc}", file=sys.stderr)
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Disk Analyzer single-run client for Multi_pod.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build report and email content but do not send HTTP requests or emails.",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=int(os.getenv("TOP_N_DIRS", "5")),
        help="Number of top directories by size to highlight in the email.",
    )
    parser.add_argument(
        "--big-threshold-gb",
        type=float,
        default=float(os.getenv("BIG_DIR_THRESHOLD_GB", "5")),
        help="Threshold in GB for marking a directory as high usage in the email.",
    )
    parser.add_argument(
        "--backend-timeout",
        type=int,
        default=int(os.getenv("BACKEND_TIMEOUT_SECONDS", "10")),
        help="Timeout in seconds for backend HTTP requests.",
    )
    args = parser.parse_args()

    roots = get_scan_roots()
    print(f"Scanning roots: {', '.join(roots)}")

    try:
        report = build_report(roots)
    except Exception as exc:
        print(f"Failed to build report: {exc}", file=sys.stderr)
        return 1

    backend_url = os.getenv("MULTIPOD_BACKEND_URL", "http://localhost:8000")

    backend_ok = send_report_to_backend(report, backend_url, args.backend_timeout, args.dry_run)
    subject, body = build_email_content(report, args.big_threshold_gb, args.top_n)
    email_ok = send_email(subject, body, args.dry_run)

    if backend_ok and email_ok:
        return 0
    if not backend_ok:
        print("Backend reporting failed.", file=sys.stderr)
    if not email_ok:
        print("Email sending failed.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

