#!/usr/bin/env python3
"""Deploy Cortex AI Platform to VPS via SSH + paramiko"""
import paramiko
import os
import tarfile
import io
import sys

HOST = "31.97.242.246"
USER = "root"
PASSWORD=os.environ.get("VPS_PASS", "")
PROJECT_DIR = "/opt/data/cortex"
REMOTE_DIR = "/opt/data/cortex"

def main():
    if not PASSWORD:
        print("ERROR: Set VPS_PASS env var")
        sys.exit(1)

    # Create tar of project
    print("Creating tar of project...")
    tar_buffer = io.BytesIO()
    with tarfile.open(fileobj=tar_buffer, mode='w:gz') as tar:
        for root, dirs, files in os.walk(PROJECT_DIR):
            if '__pycache__' in root or '.git' in root or '.venv' in root:
                continue
            for f in files:
                full_path = os.path.join(root, f)
                arcname = os.path.relpath(full_path, PROJECT_DIR)
                tar.add(full_path, arcname=arcname)
                print(f"  Added: {arcname}")

    tar_buffer.seek(0)
    print(f"Tar size: {tar_buffer.getbuffer().nbytes / 1024:.1f} KB")

    # Connect via SSH
    print(f"\nConnecting to {HOST}...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, password=PASSWORD, timeout=15)
    print("Connected!")

    # Create remote directory
    print(f"Creating {REMOTE_DIR}...")
    stdin, stdout, stderr = ssh.exec_command(f"mkdir -p {REMOTE_DIR} && ls {REMOTE_DIR}")
    out = stdout.read().decode()
    err = stderr.read().decode()
    print(f"Remote: {out}{err}")

    # Upload tar file
    print("Uploading project...")
    sftp = ssh.open_sftp()
    sftp.putfo(tar_buffer, "/tmp/cortex.tar.gz")
    sftp.close()
    print("Upload complete!")

    # Extract on remote
    print("Extracting on remote...")
    stdin, stdout, stderr = ssh.exec_command(
        f"cd {REMOTE_DIR} && tar xzf /tmp/cortex.tar.gz && rm /tmp/cortex.tar.gz && ls -la"
    )
    out = stdout.read().decode()
    err = stderr.read().decode()
    print(f"Extract: {out[:500]}")
    if err:
        print(f"Extract errors: {err[:500]}")

    # Check docker
    print("\nChecking Docker...")
    stdin, stdout, stderr = ssh.exec_command("docker info 2>&1 | head -5")
    print(stdout.read().decode())

    # Run docker compose
    print("Running docker compose up --build...")
    stdin, stdout, stderr = ssh.exec_command(
        f"cd {REMOTE_DIR} && docker compose up -d --build 2>&1",
        timeout=600
    )
    out = stdout.read().decode()
    err = stderr.read().decode()
    print(f"STDOUT:\n{out[-2000:]}")
    if err:
        print(f"STDERR:\n{err[-2000:]}")

    # Check status
    print("\nContainer status:")
    stdin, stdout, stderr = ssh.exec_command(f"cd {REMOTE_DIR} && docker compose ps 2>&1")
    print(stdout.read().decode())

    ssh.close()
    print("\n✅ Deploy complete!")


if __name__ == "__main__":
    main()
