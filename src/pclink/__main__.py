import os
import subprocess
import sys
import time
import uuid
import webbrowser
from pathlib import Path

import click
import requests
import urllib3

from .core import constants
from .core.config import config_manager
from .core.utils import get_startup_manager
from .core.version import __version__
from .core.web_auth import web_auth_manager

try:
    import qrcode
    from qrcode import constants as qr_constants
except ImportError:
    qrcode = None


CONTROL_API_URL = f"http://127.0.0.1:{constants.CONTROL_PORT}"


def is_server_running():
    """Checks if the internal control API is reachable."""
    try:
        response = requests.get(f"{CONTROL_API_URL}/status", timeout=0.5)
        return response.status_code == 200
    except requests.ConnectionError:
        return False
    except Exception:
        return False


def _start_server_process():
    """Launches the main PCLink process in a fully detached state."""
    try:
        launcher_path = os.path.join(os.path.dirname(__file__), 'launcher.py')
        
        kwargs = {
            'stdin': subprocess.DEVNULL,
            'stdout': subprocess.DEVNULL,
            'stderr': subprocess.DEVNULL,
        }

        if sys.platform == "win32":
            kwargs['creationflags'] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs['start_new_session'] = True

        subprocess.Popen([sys.executable, launcher_path], **kwargs)
        
        click.echo("Waiting for PCLink to initialize...")
        for _ in range(5):
            time.sleep(1)
            if is_server_running():
                return True
        return False
    except Exception as e:
        click.echo(f"Failed to start PCLink: {e}", err=True)
        return False


def _open_browser():
    """Opens the PCLink Web UI in the default browser."""
    if not is_server_running():
        click.echo("Cannot open Web UI because PCLink is not running.", err=True)
        return

    try:
        response = requests.get(f"{CONTROL_API_URL}/web-url", timeout=1)
        response.raise_for_status()
        url = response.json().get("url")
        if url:
            click.echo(f"Opening {url} in your browser...")
            webbrowser.open(url)
        else:
            click.echo("Could not retrieve Web UI URL.", err=True)
    except requests.RequestException as e:
        click.echo(f"Failed to contact PCLink service: {e}", err=True)
    except Exception as e:
        click.echo(f"An unexpected error occurred: {e}", err=True)


@click.group(invoke_without_command=True)
@click.version_option(__version__)
@click.pass_context
def cli(ctx):
    """PCLink Server Control Interface."""
    if ctx.invoked_subcommand is None:
        start()


@cli.command()
def start():
    """Start the PCLink service in the background."""
    if is_server_running():
        click.echo("PCLink is already running.")
        return

    click.echo("Starting PCLink in the background...")
    if _start_server_process():
        click.echo("PCLink started successfully.")
    else:
        click.echo("PCLink failed to start. Check logs for details.", err=True)


@cli.command()
def stop():
    """Stop the running PCLink service."""
    if not is_server_running():
        click.echo("PCLink is not running.")
        return
        
    try:
        click.echo("Sending shutdown signal to PCLink...")
        requests.post(f"{CONTROL_API_URL}/stop", timeout=1)
    except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError):
        pass
    except Exception as e:
        click.echo(f"An error occurred while sending the stop signal: {e}", err=True)
        return

    click.echo("Waiting for PCLink to shut down...")
    shutdown_success = False
    for _ in range(5):
        if not is_server_running():
            shutdown_success = True
            break
        time.sleep(1)

    if shutdown_success:
        click.echo("PCLink stopped successfully.")
    else:
        click.echo("PCLink did not stop as expected.", err=True)


@cli.command()
def restart():
    """Restart the running PCLink service."""
    if not is_server_running():
        click.echo("PCLink is not running. Use 'start' instead.")
        return
        
    try:
        click.echo("Restarting PCLink...")
        response = requests.post(f"{CONTROL_API_URL}/restart", timeout=5)
        response.raise_for_status()
        click.echo(response.json().get("message", "PCLink is restarting."))
    except requests.RequestException as e:
        click.echo(f"Could not connect to PCLink for restart: {e}", err=True)
    except Exception as e:
        click.echo(f"An unexpected error occurred: {e}", err=True)


@cli.command()
def status():
    """Check the status of the PCLink service."""
    try:
        response = requests.get(f"{CONTROL_API_URL}/status", timeout=1)
        response.raise_for_status()
        data = response.json()
        state = data.get('status', 'unknown').title()
        port = data.get('port')
        mobile_api = "Enabled" if data.get('mobile_api_enabled') else "Disabled"
        
        click.echo(f"PCLink Status: {state}")
        click.echo(f"  - Web UI Port: {port}")
        click.echo(f"  - Mobile API: {mobile_api}")
    except requests.RequestException:
        click.echo("PCLink is not running.")
    except Exception as e:
        click.echo(f"An unexpected error occurred: {e}", err=True)


@cli.command(name='open')
def open_webui():
    """Open WebUI if PCLink is already running."""
    _open_browser()


@cli.command()
def webui():
    """Start PCLink (if needed) and open the WebUI."""
    if is_server_running():
        click.echo("PCLink is already running.")
        _open_browser()
    else:
        click.echo("PCLink is not running. Starting it now...")
        if _start_server_process():
            click.echo("PCLink started successfully.")
            _open_browser()
        else:
            click.echo("PCLink failed to start. Cannot open Web UI.", err=True)

@cli.command()
def regen_key():
    """Generate a new API key, revoking access for all paired devices."""
    click.echo("WARNING: This will generate a new API key and immediately invalidate the connection for all previously paired devices.", err=True)
    if not click.confirm("Are you sure you want to proceed?"):
        click.echo("Operation cancelled.")
        return
    try:
        new_key = str(uuid.uuid4())
        with open(constants.API_KEY_FILE, 'w') as f:
            f.write(new_key)
        click.echo("Successfully generated a new API key.")
        if is_server_running():
            click.echo("Please restart PCLink for the new key to take effect ('pclink restart').")
    except Exception as e:
        click.echo(f"Error: Could not write new API key: {e}", err=True)


@cli.command()
@click.option('--follow', '-f', is_flag=True, help="Follow log output.")
def logs(follow):
    """Display the application log file."""
    log_file = constants.APP_DATA_PATH / "pclink.log"
    if not log_file.exists():
        click.echo(f"Log file not found at: {log_file}", err=True)
        return

    try:
        with open(log_file, 'r') as f:
            if not follow:
                click.echo(f.read())
            else:
                f.seek(0, 2) 
                while True:
                    line = f.readline()
                    if not line:
                        time.sleep(0.1)
                        continue
                    click.echo(line, nl=False)
    except KeyboardInterrupt:
        pass
    except Exception as e:
        click.echo(f"Error reading log file: {e}", err=True)


@cli.command()
def qr():
    """Display the connection QR code in the terminal."""
    if qrcode is None:
        click.echo("Error: 'qrcode' library is not installed.", err=True)
        click.echo("Please run: pip install qrcode", err=True)
        return

    if not is_server_running():
        click.echo("PCLink is not running. Start it first to get a QR code.", err=True)
        return

    try:
        # Get QR payload directly from the running server via control API
        response = requests.get(f"{CONTROL_API_URL}/qr-data", timeout=5)
        response.raise_for_status()
        qr_data = response.json().get("qr_data")
        
        if not qr_data:
            click.echo("Failed to retrieve QR code data from server.", err=True)
            return
        
        click.echo("Scan the QR code below with the PCLink mobile app:")
        click.echo("")
        
        qr_obj = qrcode.QRCode(
            error_correction=qr_constants.ERROR_CORRECT_L,
            box_size=1,
            border=4,
        )
        qr_obj.add_data(qr_data)
        qr_obj.make(fit=True)
        
        try:
            qr_obj.print_tty()
        except Exception:
            # Fallback for non-TTY environments (SSH, pipes, etc.)
            click.echo("(QR code display not available in this terminal)")
            click.echo("")
            click.echo("QR Code Data (for manual entry):")
            click.echo(qr_data)

    except requests.RequestException as e:
        click.echo(f"Failed to fetch QR code data from server: {e}", err=True)
    except Exception as e:
        click.echo(f"An unexpected error occurred: {e}", err=True)


@cli.command()
def setup():
    """Complete initial password setup for web UI."""
    if web_auth_manager.is_setup_completed():
        click.echo("Setup already completed. Use the web UI to change your password.")
        return
    
    click.echo("=== PCLink Initial Setup ===")
    click.echo("")
    click.echo("Create a password for the web UI (minimum 8 characters)")
    
    password = click.prompt("Password", hide_input=True)
    confirm_password = click.prompt("Confirm password", hide_input=True)
    
    if len(password) < 8:
        click.echo("Error: Password must be at least 8 characters long.", err=True)
        return
    
    if password != confirm_password:
        click.echo("Error: Passwords do not match.", err=True)
        return
    
    if web_auth_manager.setup_password(password):
        click.echo("")
        click.echo("✓ Password setup completed successfully!")
        click.echo("")
        click.echo("You can now:")
        click.echo("  1. Start PCLink: pclink start")
        click.echo("  2. Access web UI: https://localhost:38080/ui/")
        click.echo("  3. View pairing info: pclink pair")
    else:
        click.echo("Error: Failed to setup password.", err=True)


@cli.command()
def pair():
    """Display pairing information for mobile devices."""
    if not web_auth_manager.is_setup_completed():
        click.echo("Error: Setup not completed. Run 'pclink setup' first.", err=True)
        return
    
    if not is_server_running():
        click.echo("Error: PCLink is not running. Start it with 'pclink start'.", err=True)
        return
    
    # Prompt for password to verify identity
    password = click.prompt("Enter your web UI password", hide_input=True)
    
    # Validate password
    if not web_auth_manager.verify_password(password):
        click.echo("Error: Incorrect password.", err=True)
        return
    
    try:
        # Get pairing data from server
        response = requests.get(f"{CONTROL_API_URL}/qr-data", timeout=5)
        response.raise_for_status()
        qr_data = response.json().get("qr_data")
        
        if not qr_data:
            click.echo("Failed to retrieve pairing data from server.", err=True)
            return
        
        # Display pairing information
        click.echo("")
        click.echo("=== PCLink Pairing Information ===")
        click.echo("")
        
        # Try to display QR code
        if qrcode:
            qr_obj = qrcode.QRCode(
                error_correction=qr_constants.ERROR_CORRECT_L,
                box_size=1,
                border=4,
            )
            qr_obj.add_data(qr_data)
            qr_obj.make(fit=True)
            
            try:
                qr_obj.print_tty()
                click.echo("")
            except Exception:
                click.echo("(QR code display not available in this terminal)")
                click.echo("")
        
        # Always show manual pairing data
        click.echo("Manual Pairing Data:")
        click.echo(qr_data)
        click.echo("")
        click.echo("Scan the QR code or manually enter the data above in the PCLink mobile app.")
        
    except requests.RequestException as e:
        click.echo(f"Failed to fetch pairing data: {e}", err=True)
    except Exception as e:
        click.echo(f"An unexpected error occurred: {e}", err=True)


@click.group()
def startup():
    """Manage auto-start on system login."""
    pass

@startup.command()
def enable():
    """Enable 'Start at system startup'."""
    try:
        startup_manager = get_startup_manager()
        exe = Path(sys.executable)
        app_path = f'"{exe}" -m pclink' if exe.name.lower() in ["python.exe", "pythonw.exe"] else str(exe)
        
        startup_manager.add(constants.APP_NAME, app_path)
        config_manager.set("auto_start", True)
        click.echo("PCLink will now start automatically at system startup.")
    except Exception as e:
        click.echo(f"Error: Could not enable startup: {e}", err=True)

@startup.command()
def disable():
    """Disable 'Start at system startup'."""
    try:
        startup_manager = get_startup_manager()
        startup_manager.remove(constants.APP_NAME)
        config_manager.set("auto_start", False)
        click.echo("PCLink will no longer start automatically at system startup.")
    except Exception as e:
        click.echo(f"Error: Could not disable startup: {e}", err=True)


@click.group()
def tray():
    """Enable or disable the system tray icon."""
    pass

@tray.command()
def enable():
    """Enable the system tray icon on next start."""
    config_manager.set("enable_tray_icon", True)
    click.echo("System tray icon has been enabled. Please restart PCLink for the change to take effect.")

@tray.command()
def disable():
    """Disable the system tray icon on next start."""
    config_manager.set("enable_tray_icon", False)
    click.echo("System tray icon has been disabled. PCLink will run headless on next start.")
    click.echo("Use 'pclink stop' to shut it down.")


cli.add_command(startup)
cli.add_command(tray)

if __name__ == "__main__":
    cli()