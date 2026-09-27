#!/usr/bin/env python3
"""Project 1 - Infrastructure Validation Script."""

import os
import sys
import boto3
import paramiko

REGION = "ap-south-1"
KEY_PATH = os.path.expanduser("~/.ssh/project1-key")
ec2 = boto3.client("ec2", region_name=REGION)
results = []


def check(desc, passed):
    print(f"[{'PASS' if passed else 'FAIL'}] {desc}")
    results.append(passed)


def get_instance(name):
    """Look up a running EC2 instance by its Name tag."""
    r = ec2.describe_instances(Filters=[
        {"Name": "tag:Name", "Values": [name]},
        {"Name": "instance-state-name", "Values": ["running"]},
    ])
    resv = r.get("Reservations", [])
    return resv[0]["Instances"][0] if resv else None


def sg_ports(group_name):
    """Return the set of inbound ports a security group allows."""
    r = ec2.describe_security_groups(Filters=[{"Name": "group-name", "Values": [group_name]}])
    if not r["SecurityGroups"]:
        return None
    rules = r["SecurityGroups"][0]["IpPermissions"]
    return {rule["FromPort"] for rule in rules if rule.get("FromPort") is not None}


def ssh_via_bastion(bastion_ip, private_ip):
    """Full end-to-end SSH test: bastion -> tunnel -> private server -> run a command."""
    key = paramiko.Ed25519Key.from_private_key_file(KEY_PATH)
    bastion = paramiko.SSHClient()
    bastion.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    bastion.connect(bastion_ip, username="ec2-user", pkey=key, timeout=10)

    channel = bastion.get_transport().open_channel(
        "direct-tcpip", (private_ip, 22), (bastion_ip, 22)
    )
    server = paramiko.SSHClient()
    server.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    server.connect(private_ip, username="ec2-user", pkey=key, sock=channel, timeout=10)

    _, stdout, _ = server.exec_command("hostname")
    hostname = stdout.read().decode().strip()
    server.close()
    bastion.close()
    return hostname


def main():
    print("=== Project 1 Infrastructure Validation ===\n")

    bastion = get_instance("project1-bastion")
    rhel = get_instance("project1-rhel-server")

    check("Bastion is running", bastion is not None)
    check("Bastion has a public IP", bool(bastion and bastion.get("PublicIpAddress")))
    check("RHEL server is running", rhel is not None)
    check("RHEL server has NO public IP", bool(rhel) and rhel.get("PublicIpAddress") is None)

    # Security group checks: (name, expected ports)
    expected_sgs = {
        "project1-bastion-sg": {22},
        "project1-public-sg": {22, 80},
        "project1-private-sg": {22},
    }
    for sg_name, expected in expected_sgs.items():
        actual = sg_ports(sg_name)
        check(f"{sg_name} allows exactly {expected} (found {actual})", actual == expected)

    # End-to-end SSH test
    if bastion and rhel and bastion.get("PublicIpAddress"):
        try:
            hostname = ssh_via_bastion(bastion["PublicIpAddress"], rhel["PrivateIpAddress"])
            check(f"SSH via bastion works (hostname: {hostname})", True)
        except Exception as e:
            check(f"SSH via bastion failed: {e}", False)
    else:
        check("SSH via bastion - SKIPPED (missing instance data)", False)

    print(f"\n=== {sum(results)}/{len(results)} checks passed ===")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()