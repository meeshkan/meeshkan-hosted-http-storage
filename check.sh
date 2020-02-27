#!/bin/sh
set -e -u

black *.py
isort *.py
flake8 *.py
