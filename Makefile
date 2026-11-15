.PHONY: run test compile check install uninstall clean

PYTHON ?= python3

run:
	$(PYTHON) app.py

test:
	$(PYTHON) -m unittest discover -s tests -t . -v

compile:
	$(PYTHON) -m compileall -q .

check: compile test

install:
	./install.sh

uninstall:
	./uninstall.sh

clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf build dist *.egg-info
