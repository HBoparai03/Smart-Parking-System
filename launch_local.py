import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
import psycopg2
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parent
DATABASE_DIR = ROOT / "database"
FRONTEND_DIR = ROOT / "frontend"
DEFAULT_DB_SERVICE_URL = "http://localhost:8001"
DEFAULT_SYNC_DB_URL = "postgresql://parkinguser:parkingpass@localhost:5433/smartparking"


def load_env() -> None:
    load_dotenv(ROOT / ".env", override=False)
    load_dotenv(DATABASE_DIR / ".env", override=False)


def normalize_sync_db_url() -> str:
    value = os.getenv("SYNC_DATABASE_URL") or os.getenv("DATABASE_URL") or DEFAULT_SYNC_DB_URL
    return value.replace("+psycopg2", "").replace("+asyncpg", "")


def run_checked(command: list[str], cwd: Path) -> None:
    print(f"> {' '.join(command)}")
    subprocess.run(command, cwd=str(cwd), check=True)


def wait_for_postgres(timeout_seconds: int = 60) -> None:
    dsn = normalize_sync_db_url()
    deadline = time.time() + timeout_seconds

    while time.time() < deadline:
        try:
            with psycopg2.connect(dsn) as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT 1")
                return
        except psycopg2.Error:
            time.sleep(1)

    raise RuntimeError("PostgreSQL did not become ready in time")


def wait_for_backend(url: str, timeout_seconds: int = 60) -> None:
    deadline = time.time() + timeout_seconds

    while time.time() < deadline:
        try:
            response = httpx.get(f"{url}/health", timeout=5.0)
            if response.status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(1)

    raise RuntimeError("Backend API did not become ready in time")


def spawn_console(title: str, command: list[str], cwd: Path, env: dict[str, str] | None = None) -> None:
    command_line = subprocess.list2cmdline(command)
    subprocess.Popen(
        ["cmd", "/k", f"title {title} && {command_line}"],
        cwd=str(cwd),
        env=env,
        creationflags=subprocess.CREATE_NEW_CONSOLE,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Launch the Smart Parking local stack")
    parser.add_argument(
        "--random-rate",
        type=float,
        default=None,
        help="Optional random traffic rate passed to sensor_service.py",
    )
    parser.add_argument(
        "--skip-seed",
        action="store_true",
        help="Skip running seed.py after the backend starts",
    )
    args = parser.parse_args()

    if os.name != "nt":
        raise SystemExit("launch_local.py is intended for Windows cmd/PowerShell environments")

    load_env()
    db_service_url = DEFAULT_DB_SERVICE_URL
    local_env = os.environ.copy()
    local_env["DB_SERVICE_URL"] = DEFAULT_DB_SERVICE_URL

    print("Starting PostgreSQL...")
    run_checked(["docker", "compose", "up", "-d"], DATABASE_DIR)

    print("Waiting for PostgreSQL...")
    wait_for_postgres()

    print("Running migrations...")
    run_checked([sys.executable, "-m", "alembic", "upgrade", "head"], DATABASE_DIR)

    print("Launching backend...")
    spawn_console(
        "Smart Parking Backend",
        [sys.executable, "-m", "uvicorn", "app.main:app", "--reload", "--port", "8001"],
        DATABASE_DIR,
        env=local_env,
    )

    print("Waiting for backend API...")
    wait_for_backend(db_service_url)

    if not args.skip_seed:
        print("Seeding sample data...")
        print(f"> {sys.executable} seed.py")
        subprocess.run([sys.executable, "seed.py"], cwd=str(DATABASE_DIR), env=local_env, check=True)

    print("Launching frontend...")
    spawn_console(
        "Smart Parking Frontend",
        [sys.executable, "-m", "uvicorn", "app.main:app", "--reload", "--port", "8000"],
        FRONTEND_DIR,
        env=local_env,
    )

    sensor_command = [sys.executable, "sensor_service.py"]
    if args.random_rate is not None:
        sensor_command.extend(["--random-rate", str(args.random_rate)])

    print("Launching sensor service...")
    spawn_console("Smart Parking Sensor", sensor_command, DATABASE_DIR, env=local_env)

    print()
    print("Smart Parking is launching.")
    print("Frontend: http://localhost:8000")
    print("Backend docs: http://localhost:8001/docs")
    print()
    print("Close the opened service windows to stop the backend, frontend, and sensor loop.")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        raise SystemExit(exc.returncode)
    except Exception as exc:
        raise SystemExit(f"Launch failed: {exc}")
