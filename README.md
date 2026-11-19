# Schulportal

## Schulportal Hessen web client

A local web interface for your Schulportal Hessen timetable, substitutions, homework, message-related applications, and dashboard diagnostics. It uses the existing client in `Test.py`.

### Start

The project requires Python 3.9 or newer, `httpx`, and `beautifulsoup4`.

```sh
python -m pip install httpx beautifulsoup4
python app.py
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000) and sign in with your school ID, username, and password. The app listens only on your computer. Credentials are kept in the running process to access Schulportal and are not written to disk.

### Schedule edits

Use **Edit schedule** to add or delete lessons, or mark one as not taking place. Custom edits are saved in this browser on this device and shown in gray when cancelled. They do not change the official Schulportal timetable.