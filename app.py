
from flask import Flask, jsonify, render_template
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path

import docker
from docker.errors import APIError, DockerException, NotFound


app = Flask(__name__)

BASE_DIR = Path(__file__).resolve().parent
DATABASE = BASE_DIR / "recovery_logs.db"

CHECK_INTERVAL = 5
MAX_RESTART_ATTEMPTS = 3
RETRY_COOLDOWN_SECONDS = 60

client = None
docker_status = "Disconnected"

restart_attempts = {}
last_attempt_time = {}
monitor_started = False
monitor_lock = threading.Lock()


def now_text():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def init_db():
    """Create the log table if it does not already exist."""
    with sqlite3.connect(DATABASE) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS recovery_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                time TEXT,
                container TEXT,
                event TEXT,
                details TEXT
            )
        """)
        conn.commit()


def get_log_columns(conn):
    """Read the existing database schema without deleting old logs."""
    return {
        row[1]
        for row in conn.execute("PRAGMA table_info(recovery_logs)").fetchall()
    }


def add_log(container_name, event, details):
    """Save an event using the column names present in the existing database."""
    try:
        init_db()

        with sqlite3.connect(DATABASE) as conn:
            columns = get_log_columns(conn)

            values_by_column = {
                "time": now_text(),
                "timestamp": now_text(),
                "created_at": now_text(),
                "container": str(container_name),
                "container_name": str(container_name),
                "name": str(container_name),
                "event": str(event),
                "event_type": str(event),
                "action": str(event),
                "details": str(details),
                "message": str(details),
                "description": str(details),
            }

            insert_columns = [
                column for column in values_by_column if column in columns
            ]

            if not insert_columns:
                app.logger.error(
                    "The recovery_logs table has no compatible columns."
                )
                return

            sql_columns = ", ".join(f'"{column}"' for column in insert_columns)
            placeholders = ", ".join("?" for _ in insert_columns)
            values = [values_by_column[column] for column in insert_columns]

            conn.execute(
                f"INSERT INTO recovery_logs ({sql_columns}) "
                f"VALUES ({placeholders})",
                values,
            )
            conn.commit()

    except sqlite3.Error:
        app.logger.exception("Could not save recovery log")


def connect_docker():
    global client, docker_status

    try:
        new_client = docker.from_env()
        new_client.ping()

        client = new_client
        docker_status = "Connected"
        print("Docker connected successfully.")

    except Exception as exc:
        client = None
        docker_status = "Disconnected"
        print(f"Docker connection error: {exc}")
        print("Check that Docker Desktop is installed and running.")


def get_all_containers():
    """Return all containers, including stopped containers."""
    if client is None:
        return []

    return client.containers.list(all=True)


def monitor_loop():
    """Check every container and attempt to restart stopped containers."""
    global client, docker_status

    while True:
        try:
            if client is None:
                connect_docker()
            else:
                try:
                    client.ping()
                    docker_status = "Connected"
                except Exception:
                    print("Docker connection lost. Reconnecting...")
                    connect_docker()

            if client is not None:
                for container in get_all_containers():
                    try:
                        container.reload()
                        name = container.name

                        if container.status == "running":
                            restart_attempts[name] = 0
                            continue

                        current_time = time.time()
                        previous_time = last_attempt_time.get(name, 0)

                        if (
                            current_time - previous_time
                            < RETRY_COOLDOWN_SECONDS
                        ):
                            continue

                        attempts = restart_attempts.get(name, 0)

                        if attempts >= MAX_RESTART_ATTEMPTS:
                            continue

                        restart_attempts[name] = attempts + 1
                        last_attempt_time[name] = current_time

                        add_log(
                            name,
                            "FAILURE DETECTED",
                            f"Container status: {container.status}",
                        )

                        try:
                            container.start()
                            container.reload()

                            if container.status == "running":
                                add_log(
                                    name,
                                    "RECOVERY SUCCESS",
                                    "Container restarted successfully.",
                                )
                                restart_attempts[name] = 0
                            else:
                                add_log(
                                    name,
                                    "RECOVERY FAILED",
                                    f"Status after restart: {container.status}",
                                )

                        except (APIError, DockerException, NotFound) as exc:
                            add_log(name, "RECOVERY FAILED", str(exc))
                        except Exception as exc:
                            add_log(name, "RECOVERY FAILED", str(exc))

                    except (APIError, DockerException, NotFound) as exc:
                        add_log(
                            getattr(container, "name", "unknown"),
                            "MONITOR ERROR",
                            str(exc),
                        )
                    except Exception as exc:
                        add_log(
                            getattr(container, "name", "unknown"),
                            "MONITOR ERROR",
                            str(exc),
                        )

        except Exception as exc:
            add_log("system", "MONITOR ERROR", str(exc))

        time.sleep(CHECK_INTERVAL)


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/api/health")
def health():
    connected = False

    if client is not None:
        try:
            client.ping()
            connected = True
        except Exception:
            connected = False

    return jsonify({
        "service": "self-healing-container-management",
        "docker_status": "Connected" if connected else "Disconnected",
        "monitoring": "Active" if monitor_started else "Starting",
    })


@app.route("/api/status")
def status():
    if client is None:
        return jsonify({
            "docker_status": "Disconnected",
            "monitoring": "Unavailable",
        }), 503

    try:
        client.ping()
        containers = get_all_containers()

        return jsonify({
            "docker_status": "Connected",
            "monitoring": "Active",
            "check_interval_seconds": CHECK_INTERVAL,
            "total_containers": len(containers),
        })

    except Exception as exc:
        return jsonify({
            "docker_status": "Disconnected",
            "monitoring": "Unavailable",
            "error": str(exc),
        }), 503


@app.route("/api/containers")
def containers_api():
    if client is None:
        return jsonify({"error": "Docker is not connected"}), 503

    try:
        result = []

        for container in get_all_containers():
            container.reload()

            try:
                image_names = container.image.tags
            except Exception:
                image_names = []

            result.append({
                "id": container.short_id,
                "name": container.name,
                "status": container.status,
                "image": image_names,
                "self_healing_enabled": True,
            })

        return jsonify(result)

    except Exception as exc:
        app.logger.exception("Could not load containers")
        return jsonify({"error": str(exc)}), 500


@app.route("/api/logs")
def logs_api():
    init_db()

    try:
        with sqlite3.connect(DATABASE) as conn:
            conn.row_factory = sqlite3.Row
            columns = get_log_columns(conn)

            if not columns:
                return jsonify([])

            def choose_column(names, alias):
                for name in names:
                    if name in columns:
                        return f'"{name}" AS "{alias}"'

                return f'NULL AS "{alias}"'

            id_column = '"id"' if "id" in columns else "rowid"

            query = f"""
                SELECT
                    {id_column} AS id,
                    {choose_column(
                        ["time", "timestamp", "created_at"], "time"
                    )},
                    {choose_column(
                        ["container", "container_name", "name"], "container"
                    )},
                    {choose_column(
                        ["event", "event_type", "action"], "event"
                    )},
                    {choose_column(
                        ["details", "message", "description"], "details"
                    )}
                FROM recovery_logs
                ORDER BY {id_column} DESC
                LIMIT 100
            """

            rows = conn.execute(query).fetchall()
            return jsonify([dict(row) for row in rows])

    except sqlite3.Error as exc:
        app.logger.exception("Could not read recovery logs")
        return jsonify({"error": str(exc)}), 500


@app.route("/api/recover/<container_name>", methods=["POST"])
def recover_container(container_name):
    if client is None:
        return jsonify({"error": "Docker is not connected"}), 503

    try:
        container = client.containers.get(container_name)
        container.reload()

        if container.status == "running":
            return jsonify({
                "name": container.name,
                "status": "running",
                "message": "Container is already running.",
            })

        add_log(
            container.name,
            "MANUAL RECOVERY",
            "Manual recovery requested through the dashboard API.",
        )

        container.start()
        container.reload()

        add_log(
            container.name,
            "RECOVERY SUCCESS"
            if container.status == "running"
            else "RECOVERY FAILED",
            f"Status after restart: {container.status}",
        )

        return jsonify({
            "name": container.name,
            "status": container.status,
            "message": "Recovery attempt completed.",
        })

    except NotFound:
        return jsonify({"error": "Container not found"}), 404
    except (APIError, DockerException) as exc:
        return jsonify({"error": str(exc)}), 500
    except Exception as exc:
        app.logger.exception("Manual recovery failed")
        return jsonify({"error": str(exc)}), 500


if __name__ == "__main__":
    init_db()
    connect_docker()

    if not monitor_started:
        monitor_started = True
        threading.Thread(
            target=monitor_loop,
            daemon=True,
            name="container-monitor",
        ).start()

    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)
