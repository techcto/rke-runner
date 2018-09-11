#!/bin/bash

init() {
    pip3 install boto3 paramiko python-dotenv
}

run() {
    python3 run.py
}

$*