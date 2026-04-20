# Disk Analyzer Client for Multi-pod

This is for DiskAnalyzer

## Overview

Disk Analyzer is a Python-based utility that runs once per execution and performs three core tasks:

- Scans configured directories on the local machine and computes disk usage per directory.
- Sends a disk usage report to the Multi-pod backend at `http://localhost:8000/report`.
- Generates a daily summary email and sends it via Gmail to a configured recipient.

It is designed to run on the same machine where the Multi-pod backend is reachable, and is intended to be scheduled once per day using either cron or a Kubernetes CronJob. The project is containerized with Docker for easier deployment and management.

Multi-pod backend automatically ingests the report and stores it in SQLite, and the existing Streamlit frontend visualizes the data without requiring any changes.

## Features

- Single-run execution model suitable for cron or CronJob scheduling.
- Configurable scan roots and thresholds via environment variables.
- Aggregated disk usage per directory (first-level subdirectories under selected roots).
- Integration with Multi-pod backend through the existing `/report` API.
- Email notification with top directories and high-usage markers.
- Docker image for consistent runtime environment.

## Project Structure

```text
Disk_analyzer/
├── main.py          # Entry point script, performs scan, report, and email
├── requirements.txt # Python dependencies
└── Dockerfile       # Container configuration for single-run execution
```

## Prerequisites

- Python 3.10 or later (3.12 is supported)
- Pip (Python package manager)
- Access to a running Multi-pod backend (default `http://localhost:8000`)
- A Gmail account with an application-specific password for SMTP
- Optional: Docker and Docker Compose, or a Kubernetes cluster if using CronJob

## Configuration

Disk Analyzer is configured primarily through environment variables. Reasonable defaults are provided where possible.

### Core configuration

- `SCAN_ROOTS`
  - Comma-separated list of root directories to scan.
  - Example: `/Users/alice,/var/log`
  - If not set, the script defaults to the current user home directory (for example `/Users/alice` on macOS) and scans its first-level subdirectories.

- `MULTIPOD_BACKEND_URL`
  - URL of the Multi-pod backend.
  - Default: `http://localhost:8000`
  - The script sends reports to `<MULTIPOD_BACKEND_URL>/report`.

- `BIG_DIR_THRESHOLD_GB`
  - Threshold in gigabytes used to mark directories as high usage in the email.
  - Default: `10` (10 GB).

- `TOP_N_DIRS`
  - Number of largest directories to highlight in the email.
  - Default: `5`.

- `BACKEND_TIMEOUT_SECONDS`
  - Timeout in seconds for HTTP requests to the Multi-pod backend.
  - Default: `10`.

### Email configuration (Gmail)

The script uses SMTP to send an email summary after each run. It is recommended to use a Gmail application-specific password instead of a regular account password.

- `EMAIL_HOST`
  - SMTP host.
  - Default: `smtp.gmail.com`.

- `EMAIL_PORT`
  - SMTP port.
  - Default: `587`.

- `EMAIL_USER`
  - Gmail address used as the sender.
  - Example: `yourname@gmail.com`.

- `EMAIL_PASSWORD`
  - Application-specific password for the Gmail account.

- `EMAIL_TO`
  - Recipient address for the report email.
  - If not set, it defaults to the same value as `EMAIL_USER`.

## Local Usage

### Install dependencies

From the `Disk_analyzer` directory:

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

pip install -r requirements.txt
```

### Run a dry run

Dry-run mode builds the report and email content but does not send any HTTP requests or emails. This is useful for testing configuration and verifying what will be sent.

```bash
export MULTIPOD_BACKEND_URL=http://localhost:8000
export SCAN_ROOTS=/Users/your_username

python main.py --dry-run
```

Expected behavior in dry-run mode:

- The script prints which roots are scanned.
- It prints a brief summary of the report being prepared.
- It prints the email subject and body preview to stdout.

### Run a real execution

Before running a real execution, ensure:

- Multi-pod backend is running and accessible at `http://localhost:8000`.
- Gmail SMTP credentials are configured via environment variables.

Example:

```bash
export MULTIPOD_BACKEND_URL=http://localhost:8000
export SCAN_ROOTS=/Users/your_username

export EMAIL_USER=yourname@gmail.com
export EMAIL_PASSWORD=your_app_specific_password
export EMAIL_TO=yourname@gmail.com

python main.py
```

If everything is configured correctly, the script will:

- Scan the first-level subdirectories under `/Users/your_username`.
- Post a disk usage report to `http://localhost:8000/report`.
- Send a summary email to the configured Gmail address.

## Docker Usage

Disk Analyzer is packaged as a Docker image for consistent deployment.

### Build the image

From the `Disk_analyzer` directory:

```bash
docker build -t disk-analyzer:latest .
```

### Run the container once

On the same machine where Multi-pod backend is running:

```bash
docker run --rm \
  -e MULTIPOD_BACKEND_URL=http://host.docker.internal:8000 \
  -e SCAN_ROOTS=/Users/your_username \
  -e EMAIL_USER=yourname@gmail.com \
  -e EMAIL_PASSWORD=your_app_specific_password \
  -e EMAIL_TO=yourname@gmail.com \
  disk-analyzer:latest
```

Notes:

- `host.docker.internal` allows the container to access services running on the host (on macOS and Windows). If you run it in Linux or in Kubernetes, you may use a different hostname or service name.
- By default, the script performs a real run. To run in dry-run mode inside the container, append `--dry-run` at the end of the command:

```bash
docker run --rm \
  -e MULTIPOD_BACKEND_URL=http://host.docker.internal:8000 \
  -e SCAN_ROOTS=/Users/your_username \
  disk-analyzer:latest \
  python main.py --dry-run
```

## Scheduling with cron

You can configure cron on the host machine to run the Disk Analyzer container once a day. For example, to run every day at 23:00:

```cron
0 23 * * * docker run --rm \
  -e MULTIPOD_BACKEND_URL=http://host.docker.internal:8000 \
  -e SCAN_ROOTS=/Users/your_username \
  -e EMAIL_USER=yourname@gmail.com \
  -e EMAIL_PASSWORD=your_app_specific_password \
  -e EMAIL_TO=yourname@gmail.com \
  disk-analyzer:latest
```

Adjust the schedule, scan roots, and email configuration as required.

## Scheduling with Kubernetes CronJob (optional)

If Disk Analyzer is deployed in a Kubernetes cluster along with Multi-pod, it can be scheduled using a CronJob resource. The following is a simplified example:

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: disk-analyzer-job
spec:
  schedule: "0 23 * * *"
  jobTemplate:
    spec:
      template:
        spec:
          restartPolicy: Never
          containers:
            - name: disk-analyzer
              image: your-registry/disk-analyzer:latest
              env:
                - name: MULTIPOD_BACKEND_URL
                  value: "http://multi-pod-backend:8000"
                - name: SCAN_ROOTS
                  value: "/data"
                - name: EMAIL_USER
                  valueFrom:
                    secretKeyRef:
                      name: disk-analyzer-email
                      key: email_user
                - name: EMAIL_PASSWORD
                  valueFrom:
                    secretKeyRef:
                      name: disk-analyzer-email
                      key: email_password
                - name: EMAIL_TO
                  value: "yourname@gmail.com"
```

In a real deployment, sensitive values such as `EMAIL_USER` and `EMAIL_PASSWORD` should be stored in Kubernetes Secrets, as illustrated.

## Integration with Multi-pod

- Backend endpoint:
  - Disk Analyzer sends reports to the Multi-pod FastAPI backend at `POST /report`.
  - The JSON payload structure matches the `DiskReport` model used by Multi-pod:
    - `hostname`: host name of the node.
    - `timestamp`: ISO 8601 timestamp string.
    - `items`: list of directory entries, each with:
      - `folder_path`: absolute directory path.
      - `size_gb`: disk usage in gigabytes.

- Frontend dashboard:
  - Multi-pod Streamlit frontend continues to visualize the incoming reports without changes.
  - New Disk Analyzer reports appear in the dashboard, statistics, and charts as additional nodes and events.

## Development notes

- Use `--dry-run` during development to avoid sending real requests or emails.
- Verify environment variables carefully, especially email credentials and backend URL.
- Monitor Multi-pod backend logs and the Disk Analyzer container logs for troubleshooting.
