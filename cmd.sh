#!/bin/bash

rkeClean() {
    python-lambda-local -l ~/.local/lib/ -e env.clean.json -f run -t 1500 app.py event.json
}

rkeUpdate() {
    python-lambda-local -l ~/.local/lib/ -e env.json -f run -t 1500 app.py event.json
}

$*