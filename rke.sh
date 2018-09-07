#!/bin/bash

clean() {
    python-lambda-local -l ~/.local/lib/ -e env.clean.json -f run -t 3500 app.py event.json
}

update() {
    python-lambda-local -l ~/.local/lib/ -e env.json -f run -t 3500 app.py event.json
}

$*
