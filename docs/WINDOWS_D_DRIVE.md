# Windows setup: D: drive

The repository is portable. No absolute `C:\\` or `D:\\` path is built into the code.

## Prerequisites

- Windows 10 or 11, PowerShell 5.1+, and Python 3.12 (3.11+ should also work).
- Internet access for Python packages during initial installation.
- Enough disk space for the virtual environment and optional document uploads.

## Example location

Extract or clone the repository to **`D:\\Projects\\Aadharshila`**. Paths with spaces are supported by quoted paths in the scripts.

1. Open that folder in File Explorer and double-click **`setup.bat`**. This creates `.venv` on the **same drive**, installs dependencies, and initializes/migrates the local SQLite database.
2. Double-click **`run.bat`**. Leave the terminal window open.
3. Open **http://127.0.0.1:8000** and log in as `analyst` / `Demo@12345` (synthetic demo only).
4. Optionally run **`worker.bat`** in a second terminal for queued background reassessments.
5. Run **`test.bat`** to execute the automated test suite.

The local database is `D:\\Projects\\Aadharshila\\aadharshila.db`; documents are under `var\\documents`. Both paths follow the actual extraction folder, not a hard-coded location. The `.venv`, `.db`, uploads, secrets, and caches are ignored by Git.

### PowerShell alternative

```powershell
Set-Location 'D:\Projects\Aadharshila'
.\setup.bat
.\run.bat
```

Avoid using a bare SQLite Windows drive URL such as `sqlite:///D:\\...` in `DATABASE_URL`. The scripts use `sqlite:///./aadharshila.db` from the project root. For a custom absolute SQLite location, use a proper forward-slash URL such as `sqlite:///D:/Data/aadharshila.db` and create the parent folder first.

### Docker Desktop

From a PowerShell terminal in the repository root, copy `.env.example` to `.env`, replace `SESSION_SECRET` with a sufficiently random secret, then run `docker compose up --build -d`. Named volumes are portable across drives and managed by Docker Desktop; they do **not** automatically store the database in `D:\\Projects`.

Docker requires Docker Desktop with Linux containers/WSL2. Docker mode was not exercised in the authoring environment and should be tested on the target Windows machine.

### Troubleshooting

- **Python is missing**: Install Python 3.12 and run `setup.bat` again.
- **Port 8000 is occupied**: End the conflicting local process or change `--port 8000` in `scripts/windows/run.ps1`.
- **Scripts blocked by execution policy**: Use the `.bat` wrappers, which set execution policy only for that launched process.
- **Moved the folder after setup**: Delete `.venv` and run `setup.bat` again. Windows virtual environments embed interpreter paths.
- **SQLite locked**: Do not launch concurrent API servers against the same SQLite database. Use PostgreSQL for multi-process deployments.
- **Need to preserve your data**: Copy the `.db` file and `var\\documents` together only when the app and worker are stopped. These are development backup instructions, not production recovery assurances.
